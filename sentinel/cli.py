from __future__ import annotations
import argparse, json, logging, sys
from . import notify, inbound, brief, agent, loop
from . import core as C
def main(argv=None):
    ap = argparse.ArgumentParser(prog="sentinel"); ap.add_argument("-v", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="SMS agent loop + morning brief + outbox retry").set_defaults(f=lambda a, c: loop.run(c))
    p = sub.add_parser("brief"); p.add_argument("--send", action="store_true")
    def do_brief(a, c):
        t = brief.build(c); print(t)
        if a.send: print(notify.deliver(c, t, title="Morning brief"), file=sys.stderr)
    p.set_defaults(f=do_brief)
    p = sub.add_parser("ask", help="run one command through the agent (no SMS)"); p.add_argument("text", nargs="+"); p.set_defaults(f=lambda a, c: print(agent.run(c, " ".join(a.text))))
    p = sub.add_parser("inbox", help="show inbound owner messages as the loop sees them"); p.set_defaults(f=lambda a, c: print(*[f"{m['id']} {m['body'][:80]}" for m in inbound.fetch(c)], sep="\n"))
    p = sub.add_parser("test", help="send a test message through the configured delivery channel"); p.add_argument("message", nargs="?", default="sentinel test — delivery works"); p.set_defaults(f=lambda a, c: print(notify.deliver(c, a.message, title="sentinel")))
    p = sub.add_parser("setup", help="write the core config (owner + delivery + inbound)")
    p.add_argument("--name"); p.add_argument("--timezone"); p.add_argument("--context"); p.add_argument("--email", action="append"); p.add_argument("--phone")
    p.add_argument("--delivery", choices=["ntfy", "sms-bridge", "pushover", "slack", "email", "desktop"]); p.add_argument("--inbound", action="append", choices=["ntfy", "sms-bridge", "none"], help="repeatable: several inbound channels are polled together")
    p.add_argument("--ntfy-topic"); p.add_argument("--ntfy-server"); p.add_argument("--ntfy-inbound-topic")
    p.add_argument("--sms-device"); p.add_argument("--sms-number"); p.add_argument("--pushover-user"); p.add_argument("--pushover-token")
    p.add_argument("--slack-webhook"); p.add_argument("--slack-token"); p.add_argument("--slack-channel")
    p.add_argument("--brief-time"); p.add_argument("--agent-model"); p.add_argument("--show", action="store_true")
    def setup(a, c):
        raw = json.loads(C.CONFIG_PATH.read_text()) if C.CONFIG_PATH.exists() else {}
        o = raw.setdefault("owner", {}); d = raw.setdefault("delivery", {}); i = raw.setdefault("inbound", {})
        if a.name: o["name"] = a.name
        if a.timezone: o["timezone"] = a.timezone
        if a.context: o["context"] = a.context
        if a.email: o["emails"] = a.email
        if a.phone: o["phone"] = a.phone
        if a.delivery: d["channel"] = a.delivery
        if a.inbound:
            i["channels"] = a.inbound; i["channel"] = a.inbound[0]
        if a.ntfy_topic or a.ntfy_server:
            n = d.setdefault("ntfy", {}); n["topic"] = a.ntfy_topic or n.get("topic"); n["server"] = a.ntfy_server or n.get("server", "https://ntfy.sh")
        if a.ntfy_inbound_topic:
            n = i.setdefault("ntfy", {}); n["topic"] = a.ntfy_inbound_topic; n["server"] = a.ntfy_server or d.get("ntfy", {}).get("server", "https://ntfy.sh")
        if a.sms_device or a.sms_number:
            b = d.setdefault("sms_bridge", {}); b["device"] = a.sms_device or b.get("device"); b["number"] = a.sms_number or b.get("number") or o.get("phone")
            i.setdefault("sms_bridge", b)
        if a.pushover_user or a.pushover_token:
            pv = d.setdefault("pushover", {}); pv["user_key"] = a.pushover_user or pv.get("user_key"); pv["app_token"] = a.pushover_token or pv.get("app_token")
        if a.slack_webhook or a.slack_token or a.slack_channel:
            sl = d.setdefault("slack", {})
            if a.slack_webhook: sl["webhook"] = a.slack_webhook
            if a.slack_token: sl["token"] = a.slack_token
            if a.slack_channel: sl["channel"] = a.slack_channel
        if a.brief_time: raw["brief_time"] = a.brief_time
        if a.agent_model: raw["agent_model"] = a.agent_model
        C.save(raw)
        shown = json.loads(C.CONFIG_PATH.read_text())
        for k in ("pushover", "slack", "email"):
            if k in shown.get("delivery", {}): shown["delivery"][k] = {kk: ("***" if "token" in kk or "password" in kk or "key" in kk else vv) for kk, vv in shown["delivery"][k].items()}
        print(json.dumps(shown, indent=2)); print(f"→ {C.CONFIG_PATH}", file=sys.stderr)
    p.set_defaults(f=setup)
    sub.add_parser("flush", help="retry queued alerts").set_defaults(f=lambda a, c: print("delivered", notify.flush_outbox(c)))
    p = sub.add_parser("new", help="scaffold a new watcher package"); p.add_argument("name"); p.add_argument("--title"); p.add_argument("--emoji", default="🔔"); p.add_argument("--no-enable", action="store_true")
    p.set_defaults(f=lambda a, c: __import__("sentinel.scaffold", fromlist=["new"]).new(a.name, a.title, a.emoji, not a.no_enable))
    p = sub.add_parser("rm", help="remove a scaffolded watcher"); p.add_argument("name"); p.add_argument("--purge", action="store_true")
    p.set_defaults(f=lambda a, c: __import__("sentinel.scaffold", fromlist=["remove"]).remove(a.name, a.purge))
    def daemons(a, c):
        import shutil, os
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        uv = shutil.which("uv") or "uv"
        names = ["sentinel", "calwatch", "mailwatch", "ghwatch", "slackwatch"] + [b.split(".")[0] for b in c.get("extra_briefs", [])]
        print("Register each as a boot-persistent daemon through the daemon capability (daemon-manager):")
        for n in names:
            print(f"  name={n}  cmd={uv}  args=['run','--directory','{root}','{n}','run']  cwd={root}")
        print("Only enable the watchers you configured (a watcher with no accounts just logs an error every cycle).")
    sub.add_parser("daemons", help="print daemon registration lines for the daemon capability").set_defaults(f=daemons)
    def status(a, c):
        import importlib
        print(f"owner={c['owner'].get('name')!r} tz={c['owner'].get('timezone')} delivery={c['delivery'].get('channel')} inbound={c['inbound'].get('channel')} brief={c.get('brief_time')} model={c.get('agent_model')}")
        for n in ["calwatch", "mailwatch", "ghwatch", "slackwatch"] + [b.split(".")[0] for b in c.get("extra_briefs", [])]:
            try:
                st = importlib.import_module(f"{n}.state").State() if n in ("calwatch", "mailwatch") else importlib.import_module(f"{n}.engine").State()
                lp = st.get("last_poll"); print(f"  {n:12} last poll: {lp if lp else 'never'}")
            except Exception as e:
                print(f"  {n:12} {type(e).__name__}: {e}")
        st = loop.State(); lp = st.get("started_at")
        print(f"  {'sentinel':12} loop started: {lp}  outbox: {notify.OUTBOX if notify.OUTBOX.exists() else 'empty'}")
    sub.add_parser("status").set_defaults(f=status)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.v else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    a.f(a, C.load())
if __name__ == "__main__": main()
