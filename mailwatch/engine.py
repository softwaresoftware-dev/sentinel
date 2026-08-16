from __future__ import annotations
import logging, re, time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sentinel import notify
from .classify import classify
from .providers import build
from .state import State

log = logging.getLogger("mailwatch.engine")


def _hm(s): h, m = s.split(":"); return int(h) * 60 + int(m)


def in_quiet_hours(cfg: dict, now_local: datetime) -> bool:
    qh = cfg.get("quiet_hours")
    if not qh: return False
    a, b = _hm(qh[0]), _hm(qh[1]); t = now_local.hour * 60 + now_local.minute
    return (a <= t or t < b) if a > b else (a <= t < b)


def fetch_new(cfg: dict, st: State) -> tuple[list, dict]:
    new, errs = [], {}
    for acct in cfg["accounts"]:
        if acct.get("disabled"): continue
        label = acct["label"]
        last = st.get(f"last:{label}")
        since = datetime.fromtimestamp(last, tz=timezone.utc) - timedelta(minutes=10) if last else datetime.now(timezone.utc) - timedelta(hours=6)
        try:
            mails = build(acct).recent(since)
        except Exception as e:
            errs[label] = f"{type(e).__name__}: {e}"; log.error("fetch %s failed: %s", label, e); continue
        fresh = [m for m in mails if not st.known(m.uid)]
        new.extend(fresh)
        st.set(f"last:{label}", max([m.received.timestamp() for m in mails] + [last or 0, time.time() - 3600]))
    return new, errs


def poll(cfg: dict, st: State, send=True) -> dict:
    tz = ZoneInfo(cfg["timezone"])
    new, errs = fetch_new(cfg, st)
    baseline = not st.get("baseline_done", False)
    verdicts = classify(new, cfg) if (new and not baseline) else {m.uid: {"tier": "fyi", "why": "baseline", "due": ""} for m in new}
    urgent = []
    for m in new:
        v = verdicts.get(m.uid, {"tier": "fyi", "why": "", "due": ""})
        if v["tier"] == "urgent" and not baseline:
            urgent.append((m, v))
        st.add(m, v["tier"], v["why"], v["due"], alerted=False)
    st.commit()
    if baseline:
        st.set("baseline_done", True)
    # held-over urgent from quiet hours
    held = st.get("held", [])
    now_local = datetime.now(tz)
    to_send = [(m, v) for m, v in urgent]
    if in_quiet_hours(cfg, now_local):
        for m, v in to_send:
            held.append({"uid": m.uid, "sender": m.sender, "subject": m.subject, "account": m.account, "why": v["why"], "due": v["due"]})
        st.set("held", held); to_send = []
    msg, sent = None, None
    lines = []
    if held and not in_quiet_hours(cfg, now_local):
        for h in held: lines.append(f"• [{h['account']}] {_short(h['sender'])}: {h['subject'][:60]} — {h['why']}" + (f" (due {h['due']})" if h['due'] else ""))
        st.set("held", [])
    for m, v in to_send[: int(cfg.get("max_alerts_per_poll", 3))]:
        lines.append(f"• [{m.account}] {_short(m.sender)}: {m.subject[:60]} — {v['why']}" + (f" (due {v['due']})" if v['due'] else ""))
    if len(to_send) > int(cfg.get("max_alerts_per_poll", 3)):
        lines.append(f"…+{len(to_send) - int(cfg.get('max_alerts_per_poll', 3))} more urgent")
    if lines:
        msg = "📧 Urgent mail\n" + "\n".join(lines)
        st.log("urgent", msg)
        if send:
            ok, txt = notify.deliver(cfg, msg, title="Urgent mail"); sent = {"ok": ok, "detail": txt}
            for m, v in to_send:
                st.db.execute("UPDATE mail SET alerted_at=? WHERE uid=?", (time.time(), m.uid))
            st.commit()
        log.warning("URGENT MAIL ALERT:\n%s", msg)
    if errs: st.log("error", "; ".join(f"{k}: {v}" for k, v in errs.items()))
    counts = {}
    for m in new: counts[m.account] = counts.get(m.account, 0) + 1
    tiers = {}
    for v in verdicts.values(): tiers[v["tier"]] = tiers.get(v["tier"], 0) + 1
    st.set("last_poll", {"at": time.time(), "new": counts, "tiers": tiers, "errors": errs})
    st.prune()
    return {"new": counts, "tiers": tiers, "errors": errs, "message": msg, "sent": sent, "baseline": baseline}


def _short(sender: str) -> str:
    from email.utils import parseaddr
    n, a = parseaddr(sender or "")
    return (n or a or "?").strip('"')[:28]


def build_brief(cfg: dict, st: State) -> str:
    tz = ZoneInfo(cfg["timezone"])
    now = datetime.now(tz)
    since = (now - timedelta(hours=24)).timestamp()
    items = st.since(since)
    lp = st.get("last_poll") or {}
    head = f"📧 Inbox {now.strftime('%a %b %-d')}"
    if not items:
        return head + "\nNothing needs a reply from the last 24h."
    urg = [i for i in items if i[1] == "urgent"]; rep = [i for i in items if i[1] == "reply"]
    parts = [head + f" — {len(urg)} urgent, {len(rep)} need reply (24h)"]
    # collapse threads: same sender + same subject stem (e.g. a burst of Google Docs comments)
    groups: dict[tuple, list] = {}
    for d, t, why, due, a in (urg + rep):
        stem = re.sub(r"^(re|fwd?):\s*", "", d["subject"], flags=re.I)[:40].lower()
        groups.setdefault((t, _short(d["sender"]), stem), []).append((d, due))
    shown = 0
    for (t, who, stem), items in groups.items():
        if shown >= 10: break
        d, due = items[0]
        flag = "‼" if t == "urgent" else "•"
        n = f" (×{len(items)})" if len(items) > 1 else ""
        parts.append(f"{flag} [{d['account']}] {who}: {d['subject'][:55]}{n}" + (f" (due {due})" if due else "") + ("" if d.get("unread", True) else " ✓read"))
        shown += 1
    if len(groups) > shown:
        parts.append(f"…+{len(groups)-shown} more")
    return "\n".join(parts)
