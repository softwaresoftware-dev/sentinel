"""Shared sentinel core config: who the owner is, how to reach them, how they reach back.

~/.config/sentinel/config.json (created by `sentinel setup`), example:
{
  "owner": {"name": "Ada", "timezone": "America/Denver", "context": "runs Acme (cofounder Bob); day job at Globex",
            "emails": ["ada@acme.com"], "phone": "5551234567"},
  "delivery": {"channel": "ntfy", "ntfy": {"server": "https://ntfy.sh", "topic": "ada-sentinel-x9k2"}},
  "inbound":  {"channel": "ntfy", "ntfy": {"server": "https://ntfy.sh", "topic": "ada-sentinel-x9k2-in"}},
  "brief_time": "07:00", "agent_model": "opus"
}
Channels: delivery = ntfy | sms-bridge | pushover | slack | email | desktop ; inbound = ntfy | sms-bridge | none
"""
from __future__ import annotations
import json, os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("SENTINEL_CONFIG_DIR", Path.home() / ".config" / "sentinel"))
CONFIG_PATH = CONFIG_DIR / "config.json"
DATA_DIR = Path(os.environ.get("SENTINEL_DATA_DIR", Path.home() / ".local" / "share" / "sentinel"))

DEFAULTS = {
    "owner": {"name": "", "timezone": "UTC", "context": "", "emails": [], "phone": ""},
    "delivery": {"channel": "desktop"},
    "inbound": {"channel": "none"},
    "brief_time": "07:00", "brief_latest": "13:00",
    "quiet_hours": ["22:30", "06:30"],
    "poll_seconds": 45,
    "agent_model": "opus", "agent_timeout_seconds": 600, "agent_cwd": str(Path.home()),
    "reply_max_chars": 900, "session_scope": "day",
    "extra_briefs": [], "agent_extra_tools": [],
    "ignore_prefixes": ["(delayed) "],
}


def _merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = _merge(a[k], v) if isinstance(v, dict) and isinstance(a.get(k), dict) else v
    return out


def load() -> dict:
    cfg = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
    return _merge(DEFAULTS, cfg)


def save(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")
    try: os.chmod(CONFIG_PATH, 0o600)
    except Exception: pass


def owner() -> dict: return load()["owner"]
def timezone() -> str: return load()["owner"].get("timezone") or "UTC"
