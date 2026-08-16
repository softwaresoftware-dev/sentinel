from __future__ import annotations
import json, logging, re, sqlite3, time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sentinel import notify
from .config import DATA_DIR
from .slack import Workspace

log = logging.getLogger("slackwatch.engine")


class State:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(DATA_DIR / "state.db"))
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS seen (key TEXT PRIMARY KEY, ts REAL, ws TEXT, kind TEXT, who TEXT, text TEXT, link TEXT, alerted INTEGER);
        CREATE TABLE IF NOT EXISTS briefs (day TEXT PRIMARY KEY, sent_at REAL, text TEXT);
        CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE IF NOT EXISTS log (ts REAL, kind TEXT, msg TEXT);""")
    def get(self, k, d=None):
        r = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone(); return json.loads(r[0]) if r else d
    def set(self, k, v): self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, json.dumps(v))); self.db.commit()
    def log(self, kind, msg): self.db.execute("INSERT INTO log VALUES (?,?,?)", (time.time(), kind, msg)); self.db.commit()
    def known(self, key): return self.db.execute("SELECT 1 FROM seen WHERE key=?", (key,)).fetchone() is not None
    def add(self, key, ws, kind, who, text, link, alerted):
        self.db.execute("INSERT OR REPLACE INTO seen VALUES (?,?,?,?,?,?,?,?)", (key, time.time(), ws, kind, who, text, link, int(alerted)))
    def commit(self): self.db.commit()
    def brief_sent(self, d): return self.db.execute("SELECT 1 FROM briefs WHERE day=?", (d,)).fetchone() is not None
    def record_brief(self, d, t): self.db.execute("INSERT OR REPLACE INTO briefs VALUES (?,?,?)", (d, time.time(), t)); self.db.commit()


def _hm(s): h, m = s.split(":"); return int(h) * 60 + int(m)
def in_quiet(cfg, now):
    qh = cfg.get("quiet_hours")
    if not qh: return False
    a, b, t = _hm(qh[0]), _hm(qh[1]), now.hour * 60 + now.minute
    return (a <= t or t < b) if a > b else (a <= t < b)


def clean(text: str, ws: Workspace) -> str:
    text = re.sub(r"<@(U[A-Z0-9]+)(\|[^>]*)?>", lambda m: "@" + ws.user_name(m.group(1)), text or "")
    text = re.sub(r"<#[A-Z0-9]+\|([^>]*)>", r"#\1", text); text = re.sub(r"<(https?://[^|>]+)(\|[^>]*)?>", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def poll_workspace(ws: Workspace, cfg: dict, st: State, baseline: bool) -> list[dict]:
    """Returns list of alert dicts for this workspace."""
    alerts = []
    now = time.time()
    # --- DMs / group DMs
    if "dm" in cfg["alert_on"]:
        last_dm = st.get(f"dm_ts:{ws.label}") or f"{now - 6*3600:.6f}"
        newest = float(last_dm)
        for ch in ws.dms():
            if ch.get("is_user_deleted"): continue
            # skip DMs with no activity since last check (updated is ms epoch when present)
            upd = ch.get("updated")
            if upd and upd / 1000 < float(last_dm) - 60: continue
            try:
                msgs = ws.history(ch["id"], oldest=last_dm)
            except Exception as e:
                log.warning("%s history %s: %s", ws.label, ch["id"], e); continue
            for m in msgs:
                if m.get("user") == ws.user_id or m.get("subtype") in ("channel_join", "bot_message") or m.get("bot_id"): continue
                key = f"{ws.label}:{ch['id']}:{m['ts']}"
                if st.known(key): continue
                who = ws.user_name(m.get("user", "")); text = clean(m.get("text", ""), ws)
                kind = "group dm" if ch.get("is_mpim") else "dm"
                st.add(key, ws.label, kind, who, text, "", not baseline)
                newest = max(newest, float(m["ts"]))
                if not baseline: alerts.append({"ws": ws.label, "kind": kind, "who": who, "text": text, "channel": ch["id"], "ts": m["ts"]})
        st.set(f"dm_ts:{ws.label}", f"{newest:.6f}")
    # --- mentions (channels) via search
    if "mention" in cfg["alert_on"] or "keyword" in cfg["alert_on"]:
        since_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        queries = []
        if "mention" in cfg["alert_on"]: queries.append(("mention", f"<@{ws.user_id}> after:{since_date}"))
        if cfg.get("channel_mentions"): queries += [("@channel", f"<!channel> after:{since_date}"), ("@here", f"<!here> after:{since_date}")]
        from sentinel import core
        kws = list(cfg.get("keywords", []))
        first = (core.owner().get("name") or "").split(" ")[0].lower()
        if first and first not in [k.lower() for k in kws]: kws.append(first)
        for kw in (kws if "keyword" in cfg["alert_on"] else []):
            queries.append((f"kw:{kw}", f"{kw} after:{since_date}"))
        for kind, q in queries:
            try:
                matches = ws.search(q)
            except Exception as e:
                log.warning("%s search %s: %s", ws.label, kind, e); continue
            for m in matches:
                if m.get("user") == ws.user_id: continue
                if kind.startswith("kw:") and not re.search(re.escape(kind[3:]), m.get("text", ""), re.I): continue
                chid = (m.get("channel") or {}).get("id", ""); chname = (m.get("channel") or {}).get("name", "")
                if (m.get("channel") or {}).get("is_im") or (m.get("channel") or {}).get("is_mpim"): continue  # DMs handled above
                key = f"{ws.label}:{chid}:{m['ts']}"
                if st.known(key): continue
                if float(m["ts"]) < now - 6 * 3600 and not baseline: 
                    st.add(key, ws.label, kind, m.get("username", ""), clean(m.get("text", ""), ws), m.get("permalink", ""), False); continue
                who = m.get("username") or ws.user_name(m.get("user", "")); text = clean(m.get("text", ""), ws)
                st.add(key, ws.label, kind, who, text, m.get("permalink", ""), not baseline)
                if not baseline: alerts.append({"ws": ws.label, "kind": f"{kind} in #{chname}", "who": who, "text": text, "link": m.get("permalink", "")})
    st.commit()
    return alerts


def poll(cfg: dict, st: State, send=True) -> dict:
    tz = ZoneInfo(cfg["timezone"]); now = datetime.now(tz)
    all_alerts, errs = [], {}
    for w in cfg.get("workspaces", []):
        if w.get("disabled"): continue
        base_key = f"baseline:{w['label']}"; baseline = not st.get(base_key, False)
        try:
            all_alerts += poll_workspace(Workspace(w), cfg, st, baseline)
            if baseline: st.set(base_key, True)
        except Exception as e:
            errs[w["label"]] = f"{type(e).__name__}: {e}"; log.error("poll %s failed: %s", w["label"], e)
    held = st.get("held", [])
    if in_quiet(cfg, now):
        held += all_alerts; st.set("held", held); all_alerts = []
    elif held:
        all_alerts = held + all_alerts; st.set("held", [])
    msg = sent = None
    if all_alerts:
        cap = int(cfg.get("max_alerts_per_poll", 4))
        lines = [f"• [{a['ws']}] {a['who']} ({a['kind']}): {a['text'][:90]}" for a in all_alerts[:cap]]
        if len(all_alerts) > cap: lines.append(f"…+{len(all_alerts)-cap} more")
        msg = "💬 Slack\n" + "\n".join(lines); st.log("alert", msg)
        if send:
            ok, txt = notify.deliver(cfg, msg, title="Slack"); sent = {"ok": ok, "detail": txt}
        log.warning("SLACK ALERT:\n%s", msg)
    if errs: st.log("error", json.dumps(errs))
    st.set("last_poll", {"at": time.time(), "alerts": len(all_alerts), "errors": errs})
    return {"alerts": len(all_alerts), "errors": errs, "message": msg, "sent": sent}


def build_brief(cfg: dict, st: State) -> str:
    tz = ZoneInfo(cfg["timezone"]); now = datetime.now(tz)
    day = (now - timedelta(hours=24)).timestamp()
    rows = st.db.execute("SELECT ws, kind, who, text FROM seen WHERE ts>=? AND alerted=1 ORDER BY ts DESC", (day,)).fetchall()
    head = f"💬 Slack {now.strftime('%a %b %-d')} — {len(rows)} DMs/mentions in 24h"
    if not rows: return head + "\nQuiet day on Slack."
    by = {}
    for ws, kind, who, text in rows: by.setdefault(ws, []).append((kind, who, text))
    parts = [head]
    for ws, items in by.items():
        parts.append(f"[{ws}] " + "; ".join(f"{who}: {text[:40]}" for _, who, text in items[:4]) + (f" …+{len(items)-4}" if len(items) > 4 else ""))
    return "\n".join(parts)
