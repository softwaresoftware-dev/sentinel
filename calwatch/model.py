from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, date, timedelta, timezone
from typing import Optional


@dataclass
class Event:
    uid: str                 # globally unique: "<account>/<calendar_id>/<event_id>"
    account: str
    calendar: str            # human calendar name
    calendar_id: str
    id: str
    title: str
    start: datetime          # tz-aware UTC (for all-day: local midnight → converted)
    end: datetime
    all_day: bool = False
    busy: bool = True        # False when transparency=free / showAs=free
    status: str = "confirmed"      # confirmed | tentative | cancelled
    my_response: str = "accepted"  # accepted | tentative | declined | needsAction | organizer
    location: str = ""
    description: str = ""
    attendees: list[str] = field(default_factory=list)
    organizer: str = ""
    link: str = ""
    online_meeting: str = ""
    updated: str = ""
    recurring: bool = False

    def to_json(self) -> dict:
        d = asdict(self)
        d["start"] = self.start.isoformat()
        d["end"] = self.end.isoformat()
        return d

    @staticmethod
    def from_json(d: dict) -> "Event":
        d = dict(d)
        d["start"] = datetime.fromisoformat(d["start"])
        d["end"] = datetime.fromisoformat(d["end"])
        return Event(**d)

    # Does this event occupy my time (for conflict purposes)?
    def blocks(self) -> bool:
        if self.all_day:
            return False
        if self.status == "cancelled":
            return False
        if self.my_response == "declined":
            return False
        if not self.busy:
            return False
        if (self.end - self.start) > timedelta(hours=20):   # multi-day spans (trips) aren't meetings
            return False
        return self.end > self.start

    def signature(self) -> str:
        return f"{self.start.isoformat()}|{self.end.isoformat()}|{self.status}|{self.my_response}|{int(self.busy)}"


def overlap(a: Event, b: Event) -> Optional[tuple[datetime, datetime]]:
    s = max(a.start, b.start)
    e = min(a.end, b.end)
    return (s, e) if s < e else None
