from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class Mail:
    uid: str            # "<account>/<id>"
    account: str
    id: str
    thread_id: str
    sender: str         # "Name <addr>"
    sender_addr: str
    to: list[str]
    subject: str
    snippet: str        # first ~600 chars of body/preview
    received: datetime  # aware UTC
    unread: bool = True
    labels: list[str] = field(default_factory=list)   # gmail labels / graph categories+folder
    has_unsubscribe: bool = False
    is_reply_to_me: bool = False   # thread has my message before this one
    link: str = ""

    def to_json(self):
        d = asdict(self); d["received"] = self.received.isoformat(); return d
