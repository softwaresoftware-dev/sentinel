from __future__ import annotations
import json, sqlite3, time
from pathlib import Path
from .config import DATA_DIR
from .model import Event


class State:
    def __init__(self, path: Path | None = None):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path or DATA_DIR / "state.db"))
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS events (uid TEXT PRIMARY KEY, account TEXT, data TEXT, signature TEXT,
            first_seen REAL, last_seen REAL, gone_since REAL);
        CREATE TABLE IF NOT EXISTS conflicts (pair TEXT PRIMARY KEY, signature TEXT, notified_at REAL, detail TEXT);
        CREATE TABLE IF NOT EXISTS briefs (day TEXT PRIMARY KEY, sent_at REAL, text TEXT);
        CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE IF NOT EXISTS log (ts REAL, kind TEXT, msg TEXT);
        """)

    # -- meta
    def get(self, k, default=None):
        r = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return json.loads(r[0]) if r else default

    def set(self, k, v):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, json.dumps(v))); self.db.commit()

    def log(self, kind, msg):
        self.db.execute("INSERT INTO log VALUES (?,?,?)", (time.time(), kind, msg)); self.db.commit()

    # -- events
    def known(self, account: str | None = None) -> dict[str, dict]:
        q, a = "SELECT uid, data, signature, first_seen, gone_since FROM events", ()
        if account:
            q += " WHERE account=?"; a = (account,)
        return {u: {"data": json.loads(d), "signature": s, "first_seen": f, "gone_since": g} for u, d, s, f, g in self.db.execute(q, a)}

    def upsert(self, ev: Event, now: float) -> str:
        """Returns 'new' | 'changed' | 'same'."""
        r = self.db.execute("SELECT signature FROM events WHERE uid=?", (ev.uid,)).fetchone()
        sig = ev.signature()
        if r is None:
            self.db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,NULL)", (ev.uid, ev.account, json.dumps(ev.to_json()), sig, now, now))
            return "new"
        self.db.execute("UPDATE events SET data=?, signature=?, last_seen=?, gone_since=NULL WHERE uid=?", (json.dumps(ev.to_json()), sig, now, ev.uid))
        return "changed" if r[0] != sig else "same"

    def mark_gone(self, account: str, seen_uids: set[str], now: float):
        for (uid,) in self.db.execute("SELECT uid FROM events WHERE account=? AND gone_since IS NULL", (account,)).fetchall():
            if uid not in seen_uids:
                self.db.execute("UPDATE events SET gone_since=? WHERE uid=?", (now, uid))
        # forget events gone > 30 days
        self.db.execute("DELETE FROM events WHERE gone_since IS NOT NULL AND gone_since < ?", (now - 30 * 86400,))

    def commit(self):
        self.db.commit()

    # -- conflicts
    def conflict_notified(self, pair: str) -> str | None:
        r = self.db.execute("SELECT signature FROM conflicts WHERE pair=?", (pair,)).fetchone()
        return r[0] if r else None

    def record_conflict(self, pair: str, signature: str, detail: str, notified: bool):
        self.db.execute("INSERT OR REPLACE INTO conflicts VALUES (?,?,?,?)", (pair, signature, time.time() if notified else 0, detail)); self.db.commit()

    # -- briefs
    def brief_sent(self, day: str) -> bool:
        return self.db.execute("SELECT 1 FROM briefs WHERE day=?", (day,)).fetchone() is not None

    def record_brief(self, day: str, text: str):
        self.db.execute("INSERT OR REPLACE INTO briefs VALUES (?,?,?)", (day, time.time(), text)); self.db.commit()
