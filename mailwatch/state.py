from __future__ import annotations
import json, sqlite3, time
from .config import DATA_DIR


class State:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(DATA_DIR / "state.db"))
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS mail (uid TEXT PRIMARY KEY, account TEXT, received REAL, tier TEXT, why TEXT, due TEXT,
            data TEXT, seen_at REAL, alerted_at REAL);
        CREATE TABLE IF NOT EXISTS briefs (day TEXT PRIMARY KEY, sent_at REAL, text TEXT);
        CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE IF NOT EXISTS log (ts REAL, kind TEXT, msg TEXT);
        """)

    def get(self, k, d=None):
        r = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone(); return json.loads(r[0]) if r else d
    def set(self, k, v):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, json.dumps(v))); self.db.commit()
    def log(self, kind, msg):
        self.db.execute("INSERT INTO log VALUES (?,?,?)", (time.time(), kind, msg)); self.db.commit()
    def known(self, uid) -> bool:
        return self.db.execute("SELECT 1 FROM mail WHERE uid=?", (uid,)).fetchone() is not None
    def add(self, m, tier, why, due, alerted: bool):
        self.db.execute("INSERT OR REPLACE INTO mail VALUES (?,?,?,?,?,?,?,?,?)",
                        (m.uid, m.account, m.received.timestamp(), tier, why, due, json.dumps(m.to_json()), time.time(), time.time() if alerted else None))
    def commit(self): self.db.commit()
    def since(self, ts: float, tiers=("urgent", "reply")):
        q = f"SELECT data, tier, why, due, alerted_at FROM mail WHERE received>=? AND tier IN ({','.join('?'*len(tiers))}) ORDER BY received DESC"
        return [(json.loads(d), t, w, du, a) for d, t, w, du, a in self.db.execute(q, (ts, *tiers))]
    def brief_sent(self, day): return self.db.execute("SELECT 1 FROM briefs WHERE day=?", (day,)).fetchone() is not None
    def record_brief(self, day, text): self.db.execute("INSERT OR REPLACE INTO briefs VALUES (?,?,?)", (day, time.time(), text)); self.db.commit()
    def prune(self, days=45):
        self.db.execute("DELETE FROM mail WHERE received < ?", (time.time() - days * 86400,)); self.db.commit()
