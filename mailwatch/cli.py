from __future__ import annotations
import argparse, json, logging, sys, time
from datetime import datetime
from zoneinfo import ZoneInfo

from sentinel import notify
from . import config as C
from .engine import poll, build_brief
from .state import State

log = logging.getLogger("mailwatch")


def _hm(s): h, m = s.split(":"); return int(h) * 60 + int(m)


def brief_due(cfg, st, now_local):
    if not cfg.get('daily_brief_time'): return False
    day = now_local.date().isoformat()
    if st.brief_sent(day): return False
    t = now_local.hour * 60 + now_local.minute
    return _hm(cfg["daily_brief_time"]) <= t < _hm(cfg["daily_brief_latest"])


def send_brief(cfg, st, send):
    text = build_brief(cfg, st)
    if send:
        ok, detail = notify.deliver(cfg, text, title="Inbox brief")
        st.log("brief", f"{'ok' if ok else 'FAIL'} {detail}")
        if ok: st.record_brief(datetime.now(ZoneInfo(cfg["timezone"])).date().isoformat(), text)
    return text


def cmd_run(a, cfg):
    st = State(); tz = ZoneInfo(cfg["timezone"]); iv = int(cfg["poll_interval_seconds"])
    log.info("mailwatch daemon: %d accounts, poll %ds, brief %s", len(cfg["accounts"]), iv, cfg["daily_brief_time"])
    while True:
        t0 = time.time()
        try:
            r = poll(cfg, st, send=True); log.info("poll: new=%s tiers=%s errors=%s", r["new"], r["tiers"], r["errors"] or "-")
        except Exception as e:
            log.exception("poll crashed: %s", e)
        try:
            cfg = C.load()
            if brief_due(cfg, st, datetime.now(tz)):
                log.info("brief:\n%s", send_brief(cfg, st, True))
        except Exception as e:
            log.exception("brief crashed: %s", e)
        time.sleep(max(15, iv - (time.time() - t0)))


def cmd_once(a, cfg):
    print(json.dumps(poll(cfg, State(), send=not a.dry_run), indent=2, default=str))


def cmd_brief(a, cfg):
    print(send_brief(cfg, State(), a.send))


def cmd_status(a, cfg):
    st = State(); lp = st.get("last_poll")
    for x in cfg["accounts"]: print(f"  - {x['label']} ({x['type']})")
    print("last poll:", json.dumps(lp, default=str) if lp else "never")
    for ts, k, m in st.db.execute("SELECT ts,kind,msg FROM log ORDER BY ts DESC LIMIT 8"):
        print(f"  {datetime.fromtimestamp(ts).isoformat(timespec='seconds')} {k}: {m.splitlines()[0][:110]}")


def cmd_recent(a, cfg):
    st = State()
    for d, t, why, due, al in st.since(time.time() - 86400 * float(a.days), tiers=("urgent", "reply", "fyi", "noise")):
        print(f"{t:6} [{d['account']:10}] {d['sender'][:32]:32} | {d['subject'][:50]:50} | {why}")


def cmd_auth(a, cfg):
    from . import providers
    acct = next((x for x in cfg["accounts"] if x["label"] == a.label), None)
    if a.kind == "gmail":
        cred = a.credentials or (acct or {}).get("credentials_path")
        tok = (acct or {}).get("token_path") or str(C.CONFIG_DIR / f"gmail-{a.label}.json")
        email = providers.gmail_authorize(a.label, cred, tok)
        if not acct: cfg["accounts"].append({"type": "gmail", "label": a.label, "credentials_path": cred, "token_path": tok})
        C.save(cfg); print("authorized", email)
    else:
        sys.exit("for microsoft, reuse calwatch's MSAL cache: add {type: microsoft, cache_path, client_id, authority, username} to config")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mailwatch"); ap.add_argument("-v", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run").set_defaults(f=cmd_run)
    p = sub.add_parser("once"); p.add_argument("--dry-run", action="store_true"); p.set_defaults(f=cmd_once)
    p = sub.add_parser("brief"); p.add_argument("--send", action="store_true"); p.set_defaults(f=cmd_brief)
    sub.add_parser("status").set_defaults(f=cmd_status)
    p = sub.add_parser("recent"); p.add_argument("--days", default=1); p.set_defaults(f=cmd_recent)
    p = sub.add_parser("auth"); p.add_argument("kind", choices=["gmail", "ms"]); p.add_argument("label"); p.add_argument("--credentials"); p.set_defaults(f=cmd_auth)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.v else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    logging.getLogger("urllib3").setLevel(logging.WARNING); logging.getLogger("msal").setLevel(logging.WARNING)
    a.f(a, C.load())


if __name__ == "__main__":
    main()
