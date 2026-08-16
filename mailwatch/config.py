from __future__ import annotations
import json, os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("MAILWATCH_CONFIG_DIR", Path.home() / ".config" / "mailwatch"))
CONFIG_PATH = CONFIG_DIR / "config.json"
DATA_DIR = Path(os.environ.get("MAILWATCH_DATA_DIR", Path.home() / ".local" / "share" / "mailwatch"))

DEFAULTS = {
    "timezone": None,   # None → owner timezone from sentinel core config
    "poll_interval_seconds": 300,
    "daily_brief_time": "07:05",
    "daily_brief_latest": "13:00",
    "classify_model": "sonnet",
    "max_alerts_per_poll": 3,
    "quiet_hours": ["22:30", "06:30"],   # urgent alerts held (not dropped) during this window
    "me": [],            # your own addresses (defaults to owner.emails from the sentinel core config)
    "vip": [],           # senders (substrings) that are always at least "reply"
    "accounts": [],
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text()))
    if not cfg.get("timezone"):
        from sentinel import core; cfg["timezone"] = core.timezone()
    return cfg


def save(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")
    os.chmod(CONFIG_PATH, 0o600)
