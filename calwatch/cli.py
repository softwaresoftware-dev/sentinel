from __future__ import annotations
import argparse, json, logging, sys, time
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config as C
from .state import State
from .engine import poll, fetch_all, find_conflicts, fmt_range
from .brief import build_brief
from sentinel import notify

log = logging.getLogger("calwatch")


def _setup_logging(verbose: bool):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("msal").setLevel(logging.WARNING)


def _hm(s: str) -> tuple[int, int]:
    h, m = s.split(":"); return int(h), int(m)


def brief_due(cfg: dict, st: State, now_local: datetime) -> bool:
    if not cfg.get('daily_brief_time'): return False
    day = now_local.date().isoformat()
    if st.brief_sent(day):
        return False
    h, m = _hm(cfg["daily_brief_time"]); lh, lm = _hm(cfg["daily_brief_latest"])
    t = now_local.hour * 60 + now_local.minute
    return h * 60 + m <= t < lh * 60 + lm


def send_brief(cfg: dict, st: State, day: date | None, send: bool) -> tuple[str, dict]:
    text, meta = build_brief(cfg, day)
    tz = ZoneInfo(cfg["timezone"])
    d = (day or datetime.now(tz).date()).isoformat()
    if send:
        ok, detail = notify.deliver(cfg, text, title="Daily brief")
        st.log("brief", f"{'ok' if ok else 'FAIL'} {detail}")
        if ok:
            st.record_brief(d, text)
        meta["sent"] = ok; meta["detail"] = detail
    return text, meta


def cmd_run(args, cfg):
    st = State()
    tz = ZoneInfo(cfg["timezone"])
    interval = int(cfg["poll_interval_seconds"])
    log.info("calwatch daemon: %d accounts, poll every %ds, brief at %s %s", len(cfg["accounts"]), interval, cfg["daily_brief_time"], cfg["timezone"])
    while True:
        t0 = time.time()
        try:
            r = poll(cfg, st, send=True)
            log.info("poll: %s conflicts=%d alerted=%d errors=%s", {k: (v['events'], v['new'], v['changed']) for k, v in r["counts"].items()}, r["conflicts_total"], r["alerted"], r["errors"] or "-")
        except Exception as e:
            log.exception("poll crashed: %s", e)
        try:
            cfg = C.load()  # pick up config edits live
            if brief_due(cfg, st, datetime.now(tz)):
                text, meta = send_brief(cfg, st, None, send=True)
                log.info("daily brief sent=%s\n%s", meta.get("sent"), text)
        except Exception as e:
            log.exception("brief crashed: %s", e)
        time.sleep(max(15, interval - (time.time() - t0)))


def cmd_once(args, cfg):
    st = State()
    r = poll(cfg, st, send=not args.dry_run)
    print(json.dumps(r, indent=2, default=str))


def cmd_brief(args, cfg):
    st = State()
    day = date.fromisoformat(args.date) if args.date else None
    text, meta = send_brief(cfg, st, day, send=args.send)
    print(text); print("---", json.dumps(meta, default=str), file=sys.stderr)


def cmd_agenda(args, cfg):
    tz = ZoneInfo(cfg["timezone"])
    got, errs = fetch_all(cfg)
    days = int(args.days)
    end = datetime.now(tz) + timedelta(days=days)
    evs = sorted((e for l in got for e in got[l]), key=lambda e: e.start)
    for e in evs:
        if e.start > end or e.status == "cancelled":
            continue
        flag = "" if e.blocks() else " (free/declined/all-day)"
        print(f"{fmt_range(e.start, e.end, tz):28} {e.title[:50]:50} [{e.account}/{e.calendar}] {e.my_response}{flag}")
    if errs:
        print("errors:", errs, file=sys.stderr)


def cmd_conflicts(args, cfg):
    tz = ZoneInfo(cfg["timezone"])
    got, errs = fetch_all(cfg)
    conf = find_conflicts([e for l in got for e in got[l]])
    if not conf:
        print("No conflicts in the next", cfg["lookahead_days"], "days.")
    for a, b, s, e in conf:
        print(f"⚠ {fmt_range(s, e, tz)}: {a.title} [{a.account}]  vs  {b.title} [{b.account}]")
    if errs:
        print("errors:", errs, file=sys.stderr)


def cmd_status(args, cfg):
    st = State()
    lp = st.get("last_poll")
    print("accounts:")
    for a in cfg["accounts"]:
        print(f"  - {a['label']} ({a['type']}){' DISABLED' if a.get('disabled') else ''}")
    if lp:
        print(f"last poll: {datetime.fromtimestamp(lp['at']).isoformat(timespec='seconds')} counts={lp['counts']} conflicts={lp['conflicts_total']} errors={lp['errors'] or '-'}")
    else:
        print("last poll: never")
    for ts, kind, msg in st.db.execute("SELECT ts,kind,msg FROM log ORDER BY ts DESC LIMIT 10"):
        print(f"  {datetime.fromtimestamp(ts).isoformat(timespec='seconds')} {kind}: {msg.splitlines()[0][:120]}")


def cmd_test_sms(args, cfg):
    ok, txt = notify.sms(cfg, args.message)
    print("ok" if ok else "FAILED", txt)


def cmd_auth(args, cfg):
    from . import providers
    acct = next((a for a in cfg["accounts"] if a["label"] == args.label), None)
    if args.kind == "google":
        cred = args.credentials or (acct or {}).get("credentials_path")
        if not cred:
            sys.exit("need --credentials <client json> for a new google account")
        tok = (acct or {}).get("token_path") or str(C.CONFIG_DIR / f"google-{args.label}.json")
        print(f"Starting Google OAuth for '{args.label}'. Open the printed URL in a browser signed into the right account.")
        email = providers.google_authorize(args.label, cred, tok)
        if not acct:
            cfg["accounts"].append({"type": "google", "label": args.label, "credentials_path": cred, "token_path": tok, "calendars": "all"})
        else:
            acct.update({"credentials_path": cred, "token_path": tok})
        C.save(cfg); print(f"authorized {email} → {tok}")
    else:
        if not acct:
            acct = {"type": "microsoft", "label": args.label, "client_id": args.client_id or "db61edcd-9d68-46c7-8278-c71f3952ca20",
                    "authority": args.authority or "https://login.microsoftonline.com/common",
                    "cache_path": str(C.CONFIG_DIR / f"ms-{args.label}.json"), "calendars": "all"}
            cfg["accounts"].append(acct)
        user = providers.ms_authorize(acct)
        acct["username"] = user
        C.save(cfg); print(f"authorized {user} → {acct['cache_path']}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="calwatch", description="Multi-account calendar sentinel")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="run the daemon loop").set_defaults(f=cmd_run)
    p = sub.add_parser("once", help="one poll cycle"); p.add_argument("--dry-run", action="store_true"); p.set_defaults(f=cmd_once)
    p = sub.add_parser("brief", help="build (and optionally send) the daily brief"); p.add_argument("--send", action="store_true"); p.add_argument("--date"); p.set_defaults(f=cmd_brief)
    p = sub.add_parser("agenda", help="print merged agenda"); p.add_argument("--days", default=3); p.set_defaults(f=cmd_agenda)
    sub.add_parser("conflicts", help="list current conflicts").set_defaults(f=cmd_conflicts)
    sub.add_parser("status", help="daemon status").set_defaults(f=cmd_status)
    p = sub.add_parser("test-sms"); p.add_argument("message", nargs="?", default="calwatch test"); p.set_defaults(f=cmd_test_sms)
    p = sub.add_parser("auth", help="authorize an account"); p.add_argument("kind", choices=["google", "ms"]); p.add_argument("label")
    p.add_argument("--credentials"); p.add_argument("--client-id"); p.add_argument("--authority"); p.set_defaults(f=cmd_auth)
    args = ap.parse_args(argv)
    _setup_logging(args.verbose)
    cfg = C.load()
    args.f(args, cfg)


if __name__ == "__main__":
    main()
