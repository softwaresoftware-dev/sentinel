"""One-shot reminders: fire a message at a time, N minutes from now, or N minutes before a calendar event.
Stored in the sentinel state DB; the sentinel loop fires anything due each cycle (idempotent)."""
from __future__ import annotations
import json, logging, re, sqlite3, time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from .core import DATA_DIR

log = logging.getLogger("sentinel.remind")


def _db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DATA_DIR / "state.db"))
    db.execute("""CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, due REAL, message TEXT,
                  created REAL, fired REAL, source TEXT, event TEXT)""")
    db.commit(); return db


def parse_duration(s: str) -> timedelta:
    """'90m', '1h30m', '2h', '45 min', '1 hour', '2d'"""
    s = s.strip().lower().replace(" ", "")
    total = 0
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)(d|h|m|min|mins|minutes?|hours?|hr|hrs|days?)", s):
        n = float(num)
        total += n * (86400 if unit.startswith("d") else 3600 if unit.startswith("h") else 60)
    if total == 0: raise ValueError(f"can't parse duration {s!r}")
    return timedelta(seconds=total)


def parse_when(s: str, tz: ZoneInfo) -> datetime:
    """Absolute local time: '2026-08-16 11:00', '11:00' (today or tomorrow if past), 'tomorrow 11:00', 'aug 16 11:00'."""
    from dateutil import parser as dp
    now = datetime.now(tz); s = s.strip()
    low = s.lower()
    base = now
    if low.startswith("tomorrow"):
        base = now + timedelta(days=1); s = s[len("tomorrow"):].strip() or "09:00"
    elif low.startswith("today"):
        s = s[len("today"):].strip() or "09:00"
    dt = dp.parse(s, default=base.replace(hour=9, minute=0, second=0, microsecond=0))
    if dt.tzinfo is None: dt = dt.replace(tzinfo=tz)
    if dt <= now and re.fullmatch(r"\d{1,2}(:\d{2})?\s*(am|pm)?", low): dt += timedelta(days=1)   # bare time already passed → tomorrow
    return dt


def find_event(query: str, tz: ZoneInfo):
    """Search configured calendars (calwatch) for the next event whose title contains query. Returns (title, start) or None."""
    try:
        from calwatch import config as C; from calwatch.engine import fetch_all
        got, _ = fetch_all(C.load())
    except Exception as e:
        log.warning("calendar lookup failed: %s", e); return None
    now = datetime.now(tz); q = query.lower()
    cands = sorted([e for l in got for e in got[l] if q in e.title.lower() and e.end > now], key=lambda e: e.start)
    return (cands[0].title, cands[0].start.astimezone(tz)) if cands else None


def add(message: str, due: datetime, source="cli", event: str | None = None) -> int:
    db = _db()
    cur = db.execute("INSERT INTO reminders (due, message, created, fired, source, event) VALUES (?,?,?,?,?,?)",
                     (due.timestamp(), message, time.time(), None, source, event))
    db.commit(); return cur.lastrowid


def pending(include_fired=False) -> list[dict]:
    db = _db()
    q = "SELECT id, due, message, created, fired, source, event FROM reminders" + ("" if include_fired else " WHERE fired IS NULL") + " ORDER BY due"
    return [dict(zip(("id", "due", "message", "created", "fired", "source", "event"), r)) for r in db.execute(q)]


def cancel(rid: int) -> bool:
    db = _db(); n = db.execute("DELETE FROM reminders WHERE id=? AND fired IS NULL", (rid,)).rowcount; db.commit(); return n > 0


def fire_due(cfg: dict) -> int:
    """Deliver everything due. Called by the loop each cycle."""
    from . import notify
    db = _db(); now = time.time(); n = 0
    for rid, due, msg, event in db.execute("SELECT id, due, message, event FROM reminders WHERE fired IS NULL AND due <= ?", (now,)).fetchall():
        late = now - due
        text = "⏰ " + msg + (f"\n({event})" if event else "") + (f"\n(late by {int(late//60)} min)" if late > 300 else "")
        ok, detail = notify.deliver(cfg, text, title="Reminder")
        db.execute("UPDATE reminders SET fired=? WHERE id=?", (now, rid)); db.commit()   # deliver() queued to outbox on failure
        log.info("reminder %s %s: %s", rid, "sent" if ok else detail, msg[:80]); n += 1
    return n


def brief_lines(cfg: dict) -> str | None:
    tz = ZoneInfo(cfg["owner"]["timezone"]); now = datetime.now(tz)
    today = [r for r in pending() if datetime.fromtimestamp(r["due"], tz).date() == now.date()]
    if not today: return None
    return "⏰ Reminders today\n" + "\n".join(f"• {datetime.fromtimestamp(r['due'], tz).strftime('%-I:%M%p').lower()} {r['message'][:70]}" for r in today)


def schedule(cfg: dict, message: str, at: str | None = None, in_: str | None = None, before: str | None = None, offsets: str | None = None, source="cli") -> list[tuple[int, datetime]]:
    """Returns [(id, due)] created. `before` = event title query; `offsets` = '60m,30m'."""
    tz = ZoneInfo(cfg["owner"]["timezone"]); out = []
    if before:
        ev = find_event(before, tz)
        if not ev: raise ValueError(f"no upcoming calendar event matching {before!r}")
        title, start = ev
        for off in (offsets or "30m").split(","):
            d = parse_duration(off); due = start - d
            if due <= datetime.now(tz): continue
            out.append((add(f"{message} — {title} at {start.strftime('%-I:%M%p').lower()} (in {off.strip()})", due, source, title), due))
        if not out: raise ValueError("all requested offsets are already in the past")
    elif in_:
        due = datetime.now(tz) + parse_duration(in_); out.append((add(message, due, source), due))
    elif at:
        for a in at.split(","):
            due = parse_when(a, tz)
            if due <= datetime.now(tz): raise ValueError(f"{a!r} is in the past")
            out.append((add(message, due, source), due))
    else:
        raise ValueError("need --at, --in, or --before")
    return out
