from __future__ import annotations
import logging, time, traceback
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .model import Event, overlap
from .providers import build
from .state import State
from sentinel import notify

log = logging.getLogger("calwatch.engine")


def fmt_range(a: datetime, b: datetime, tz: ZoneInfo, with_day=True) -> str:
    a, b = a.astimezone(tz), b.astimezone(tz)
    def t(d):
        s = d.strftime("%I:%M%p").lstrip("0").lower()
        return s.replace(":00", "")
    day = a.strftime("%a %-m/%-d ") if with_day else ""
    if a.date() != b.date():
        return f"{day}{t(a)}–{b.strftime('%a %-m/%-d')} {t(b)}"
    return f"{day}{t(a)}–{t(b)}"


def is_duplicate(a: Event, b: Event) -> bool:
    """Same meeting mirrored on two calendars/accounts (invite in both inboxes)."""
    if a.uid == b.uid:
        return True
    return a.title.strip().lower() == b.title.strip().lower() and a.start == b.start and a.end == b.end


def find_conflicts(events: list[Event]) -> list[tuple[Event, Event, datetime, datetime]]:
    evs = []
    for e in sorted([e for e in events if e.blocks()], key=lambda e: e.start):
        if any(is_duplicate(e, u) for u in evs):   # collapse the same meeting mirrored across accounts
            continue
        evs.append(e)
    out = []
    for i, a in enumerate(evs):
        for b in evs[i + 1:]:
            if b.start >= a.end:
                break
            ov = overlap(a, b)
            if ov and not is_duplicate(a, b):
                out.append((a, b, ov[0], ov[1]))
    return out


def pair_key(a: Event, b: Event) -> str:
    return "||".join(sorted([a.uid, b.uid]))


def fetch_all(cfg: dict) -> tuple[dict[str, list[Event]], dict[str, str]]:
    """Returns {account_label: events}, {account_label: error}"""
    tz = cfg["timezone"]
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=1)
    end = now + timedelta(days=int(cfg["lookahead_days"]))
    got, errs = {}, {}
    for acct in cfg["accounts"]:
        if acct.get("disabled"):
            continue
        try:
            prov = build(acct, tz)
            got[acct["label"]] = prov.events(start, end)
        except Exception as e:
            errs[acct["label"]] = f"{type(e).__name__}: {e}"
            log.error("fetch %s failed: %s", acct["label"], e)
    return got, errs


def poll(cfg: dict, st: State, send: bool = True) -> dict:
    """One polling cycle. Returns a summary dict."""
    tz = ZoneInfo(cfg["timezone"])
    now = time.time()
    got, errs = fetch_all(cfg)
    changed_uids: set[str] = set()
    counts = {}
    for label, evs in got.items():
        baseline = st.get(f"baseline_done:{label}", False)
        seen = set()
        n_new = n_chg = 0
        for ev in evs:
            seen.add(ev.uid)
            r = st.upsert(ev, now)
            if r == "new":
                n_new += 1
                if baseline:
                    changed_uids.add(ev.uid)
            elif r == "changed":
                n_chg += 1
                changed_uids.add(ev.uid)
        st.mark_gone(label, seen, now)
        if not baseline:
            st.set(f"baseline_done:{label}", True)
        counts[label] = {"events": len(evs), "new": n_new, "changed": n_chg, "baseline": not baseline}
    st.commit()

    # Conflicts across everything currently known & not gone
    all_events = [e for label in got for e in got[label]]
    conflicts = find_conflicts(all_events)
    to_notify = []
    for a, b, s, e in conflicts:
        pk = pair_key(a, b)
        sig = a.signature() + "##" + b.signature()
        prev = st.conflict_notified(pk)
        if prev == sig:
            continue
        involves_change = (a.uid in changed_uids or b.uid in changed_uids)
        detail = f"{a.title} ({a.account}, {fmt_range(a.start, a.end, tz)}) ⟷ {b.title} ({b.account}, {fmt_range(b.start, b.end, tz)})"
        # First sighting of an account = baseline; record silently. Otherwise notify only if a member changed.
        will_notify = involves_change and prev != sig
        st.record_conflict(pk, sig, detail, notified=will_notify)
        if will_notify:
            to_notify.append((a, b, s, e))
        else:
            log.info("conflict recorded (baseline/unchanged): %s", detail)

    sent = None
    if to_notify:
        msg = format_conflict_sms(to_notify, tz)
        st.log("conflict", msg)
        if send:
            ok, txt = notify.deliver(cfg, msg, title="Calendar conflict")
            sent = {"ok": ok, "detail": txt}
            st.log("sms", f"{'ok' if ok else 'FAIL'} {txt}")
        else:
            sent = {"ok": None, "detail": "dry-run"}
        log.warning("CONFLICT ALERT:\n%s", msg)

    if errs:
        st.log("error", "; ".join(f"{k}: {v}" for k, v in errs.items()))
    st.set("last_poll", {"at": now, "counts": counts, "errors": errs, "conflicts_total": len(conflicts)})
    return {"counts": counts, "errors": errs, "conflicts_total": len(conflicts), "alerted": len(to_notify), "message": format_conflict_sms(to_notify, tz) if to_notify else None, "sent": sent}


def format_conflict_sms(pairs, tz: ZoneInfo) -> str:
    lines = ["⚠️ Calendar conflict" + ("s" if len(pairs) > 1 else "")]
    for a, b, s, e in pairs[:6]:
        lines.append(f"• {a.title} [{a.account}] {fmt_range(a.start, a.end, tz)}")
        lines.append(f"  vs {b.title} [{b.account}] {fmt_range(b.start, b.end, tz, with_day=b.start.astimezone(tz).date()!=a.start.astimezone(tz).date())}")
    if len(pairs) > 6:
        lines.append(f"…and {len(pairs)-6} more")
    return "\n".join(lines)
