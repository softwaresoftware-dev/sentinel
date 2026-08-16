"""The hub loop: flush outbox → send the combined brief at brief_time → poll inbound owner messages → agent → reply."""
from __future__ import annotations
import hashlib, json, logging, sqlite3, time
from datetime import datetime
from zoneinfo import ZoneInfo
from . import notify, inbound, agent, brief as briefmod
from .core import DATA_DIR

log = logging.getLogger("sentinel.loop")


class State:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(DATA_DIR / "state.db"))
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS handled (key TEXT PRIMARY KEY, ts REAL, body TEXT, reply TEXT);
        CREATE TABLE IF NOT EXISTS briefs (day TEXT PRIMARY KEY, sent_at REAL, text TEXT);
        CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);""")
    def get(self, k, d=None):
        r = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone(); return json.loads(r[0]) if r else d
    def set(self, k, v): self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, json.dumps(v))); self.db.commit()
    def handled(self, key): return self.db.execute("SELECT 1 FROM handled WHERE key=?", (key,)).fetchone() is not None
    def mark(self, key, body, reply): self.db.execute("INSERT OR REPLACE INTO handled VALUES (?,?,?,?)", (key, time.time(), body, reply)); self.db.commit()
    def brief_sent(self, d): return self.db.execute("SELECT 1 FROM briefs WHERE day=?", (d,)).fetchone() is not None
    def record_brief(self, d, t): self.db.execute("INSERT OR REPLACE INTO briefs VALUES (?,?,?)", (d, time.time(), t)); self.db.commit()


def new_commands(cfg: dict, st: State) -> list[dict]:
    """Owner messages not yet handled, oldest first. Ignores our own outbound bodies (self-text echo), alert echoes, and anything predating the loop."""
    sent = inbound.recent_sent_hashes()
    started = st.get("started_at")
    if not started:
        started = time.time(); st.set("started_at", started)
    out = []
    for m in inbound.fetch(cfg):
        body = m["body"]
        if not body: continue
        key = f"{m['id']}:{hashlib.sha1(body.encode()).hexdigest()[:10]}"
        if st.handled(key): continue
        if hashlib.sha1(body.encode()).hexdigest() in sent: st.mark(key, body, "(own outbound)"); continue
        if any(body.startswith(p) for p in cfg.get("ignore_prefixes", [])) or body[:1] in "📅📧🐙💬⚠🧭🔔": st.mark(key, body, "(alert echo)"); continue
        if m["ts"] < started - 300 or time.time() - m["ts"] > 12 * 3600: st.mark(key, body, "(stale)"); continue
        out.append({"key": key, "body": body, "ts": m["ts"]})
    out.sort(key=lambda x: x["ts"])
    return out


def handle(cfg: dict, st: State, cmd: dict) -> None:
    log.info("command: %s", cmd["body"][:120])
    st.mark(cmd["key"], cmd["body"], "(in progress)")
    reply = agent.run(cfg, cmd["body"])
    ok, detail = notify.deliver(cfg, reply, title="Claude")
    st.mark(cmd["key"], cmd["body"], reply)
    log.info("reply (%s): %s", "sent" if ok else detail, reply[:200])


def _hm(s): h, m = s.split(":"); return int(h) * 60 + int(m)


def maybe_brief(cfg: dict, st: State) -> None:
    tz = ZoneInfo(cfg["owner"]["timezone"]); now = datetime.now(tz); day = now.date().isoformat()
    if not cfg.get("brief_time") or st.brief_sent(day): return
    t = now.hour * 60 + now.minute
    if not (_hm(cfg["brief_time"]) <= t < _hm(cfg["brief_latest"])): return
    text = briefmod.build(cfg)
    ok, detail = notify.deliver(cfg, text, title="Morning brief")
    log.info("brief %s: %s", "sent" if ok else detail, text[:200])
    st.record_brief(day, text)   # deliver() queues to the outbox on failure, so don't retry-spam


def run(cfg: dict) -> None:
    st = State()
    iv = int(cfg.get("poll_seconds", 45))
    log.info("sentinel loop: inbound=%s delivery=%s poll %ds, brief at %s", cfg["inbound"].get("channel"), cfg["delivery"].get("channel"), iv, cfg.get("brief_time"))
    while True:
        t0 = time.time()
        try:
            n = notify.flush_outbox(cfg)
            if n: log.info("flushed %d queued alerts", n)
        except Exception as e:
            log.warning("outbox flush: %s", e)
        try:
            maybe_brief(cfg, st)
        except Exception as e:
            log.exception("brief: %s", e)
        try:
            for cmd in new_commands(cfg, st):
                handle(cfg, st, cmd)
        except Exception as e:
            log.warning("inbound poll: %s", str(e)[:200])
        from . import core
        cfg = core.load()
        time.sleep(max(10, iv - (time.time() - t0)))
