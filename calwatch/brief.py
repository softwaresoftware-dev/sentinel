"""Daily prep brief."""
from __future__ import annotations
import json, logging, shutil, subprocess
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo

from .model import Event
from .engine import fetch_all, find_conflicts, is_duplicate, fmt_range

log = logging.getLogger("calwatch.brief")


def _t(d: datetime, tz) -> str:
    d = d.astimezone(tz)
    s = d.strftime("%I:%M%p").lstrip("0").lower()
    return s.replace(":00", "")


def day_events(cfg: dict, day: date, prefetched: dict[str, list[Event]] | None = None) -> tuple[list[Event], dict]:
    tz = ZoneInfo(cfg["timezone"])
    if prefetched is not None:
        got, errs = prefetched, {}
    else:
        got, errs = fetch_all(cfg)
    d0 = datetime.combine(day, datetime.min.time(), tz)
    d1 = d0 + timedelta(days=1)
    evs = []
    for label, lst in got.items():
        for e in lst:
            if e.status == "cancelled" or e.my_response == "declined":
                continue
            if e.start < d1 and e.end > d0:
                evs.append(e)
    # de-dupe mirrored invites
    uniq: list[Event] = []
    for e in sorted(evs, key=lambda x: (not x.all_day, x.start, x.title)):
        if any(is_duplicate(e, u) for u in uniq):
            continue
        uniq.append(e)
    return uniq, errs


def plain_lines(evs: list[Event], tz) -> list[str]:
    lines = []
    for e in evs:
        if e.all_day:
            lines.append(f"• All day: {e.title} [{e.account}]")
            continue
        extra = []
        if e.location:
            extra.append(e.location.split("\n")[0][:40])
        if e.online_meeting:
            extra.append("Teams" if "teams" in e.online_meeting else "Meet" if "meet.google" in e.online_meeting else "Zoom" if "zoom" in e.online_meeting else "video")
        if e.my_response == "needsAction":
            extra.append("RSVP?")
        if e.status == "tentative":
            extra.append("tentative")
        tail = f" ({'; '.join(extra)})" if extra else ""
        lines.append(f"• {_t(e.start, tz)}–{_t(e.end, tz)} {e.title} [{e.account}]{tail}")
    return lines


def rule_notes(evs: list[Event], conflicts, tz) -> list[str]:
    notes = []
    for a, b, s, e in conflicts:
        notes.append(f"Conflict: {a.title} vs {b.title} ({_t(s, tz)}–{_t(e, tz)})")
    rsvp = [e.title for e in evs if e.my_response == "needsAction" and not e.all_day]
    if rsvp:
        notes.append("Unanswered invites: " + ", ".join(rsvp[:3]))
    inperson = [e for e in evs if e.location and not e.online_meeting and not e.all_day and "http" not in e.location]
    for e in inperson[:2]:
        notes.append(f"In person: {e.title} @ {e.location.split(chr(10))[0][:50]}")
    first = next((e for e in evs if not e.all_day), None)
    if first and first.start.astimezone(tz).hour < 8:
        notes.append(f"Early start: {first.title} at {_t(first.start, tz)}")
    return notes


def claude_notes(cfg: dict, day: date, evs: list[Event], conflicts, tz) -> str | None:
    if not cfg.get("brief_use_claude", True) or not shutil.which("claude"):
        return None
    payload = []
    for e in evs:
        payload.append({
            "title": e.title, "account": e.account, "calendar": e.calendar,
            "when": "all day" if e.all_day else f"{_t(e.start, tz)}–{_t(e.end, tz)}",
            "location": e.location[:200], "online": bool(e.online_meeting), "my_response": e.my_response,
            "status": e.status, "organizer": e.organizer, "attendees": e.attendees[:10],
            "description": (e.description or "")[:600], "recurring": e.recurring,
        })
    conf = [f"{a.title} vs {b.title} {_t(s,tz)}–{_t(e,tz)}" for a, b, s, e in conflicts]
    from sentinel import core
    o = core.owner(); who = o.get("name") or "the owner"; ctx = (" Context about them: " + o["context"]) if o.get("context") else ""
    prompt = f"""You are prepping {who} for the day ({day.strftime('%A %B %-d')}).{ctx} Below are today's calendar events (all accounts merged) and any conflicts.
Write the "prep notes" section of a short morning TEXT MESSAGE. Rules:
- Plain text only, no markdown, no headers, no emoji. Max 4 short lines, each starting with "- ". Total under 350 characters.
- Only mention things worth acting on or noticing: unanswered invites, conflicts, in-person locations / travel time, materials or agenda items mentioned in descriptions, first-time meetings with external people, unusual timing (early/late/back-to-back with no gap), deadlines.
- Do NOT restate the schedule — they already get the list. No filler like "have a great day".
- If nothing is notable, reply with exactly: Nothing special today.

Conflicts: {json.dumps(conf)}
Events: {json.dumps(payload, ensure_ascii=False)}"""
    try:
        r = subprocess.run(["claude", "-p", "--model", cfg.get("brief_model", "sonnet"), "--output-format", "text", prompt],
                           capture_output=True, text=True, timeout=180)
        out = (r.stdout or "").strip()
        if r.returncode != 0 or not out:
            log.warning("claude -p failed rc=%s: %s", r.returncode, (r.stderr or "")[:300])
            return None
        # keep it text-message sized
        return out[:600]
    except Exception as e:
        log.warning("claude -p error: %s", e)
        return None


def build_brief(cfg: dict, day: date | None = None, prefetched=None) -> tuple[str, dict]:
    tz = ZoneInfo(cfg["timezone"])
    day = day or datetime.now(tz).date()
    evs, errs = day_events(cfg, day, prefetched)
    conflicts = find_conflicts(evs)
    header = f"📅 {day.strftime('%a %b %-d')}"
    timed = [e for e in evs if not e.all_day]
    if not evs:
        body = ["No events today."]
    else:
        body = plain_lines(evs, tz)
        header += f" — {len(timed)} event{'s' if len(timed)!=1 else ''}" + (f", {len(evs)-len(timed)} all-day" if len(evs) != len(timed) else "")
    notes = claude_notes(cfg, day, evs, conflicts, tz) if evs else None
    if notes is None:
        rn = rule_notes(evs, conflicts, tz)
        notes = "\n".join(f"- {n}" for n in rn) if rn else ("Nothing special today." if evs else "")
    parts = [header] + body
    if notes:
        parts += ["Prep:", notes]
    if errs:
        parts.append("(⚠ couldn't read: " + ", ".join(errs) + ")")
    return "\n".join(parts), {"events": len(evs), "conflicts": len(conflicts), "errors": errs}
