from __future__ import annotations
import json, os
from pathlib import Path
CONFIG_DIR = Path(os.environ.get("SLACKWATCH_CONFIG_DIR", Path.home() / ".config" / "slackwatch"))
CONFIG_PATH = CONFIG_DIR / "config.json"
DATA_DIR = Path(os.environ.get("SLACKWATCH_DATA_DIR", Path.home() / ".local" / "share" / "slackwatch"))
DEFAULTS = {
    "timezone": None,   # None → owner timezone from sentinel core config "poll_interval_seconds": 300,
    "daily_brief_time": "07:15", "daily_brief_latest": "13:00",
    "max_alerts_per_poll": 4, "quiet_hours": ["22:30", "06:30"],
    "alert_on": ["dm", "mention", "keyword"],       # dm = any DM/group DM to me; mention = @me / @channel/@here in my channels; keyword
    "keywords": ["urgent", "asap"],   # your first name is added automatically from the core config
    "channel_mentions": False,                        # treat @channel/@here as mention
    "workspaces": [],                                # [{label, team_id, team_name, user_id, token_path}]
}
def load():
    c = dict(DEFAULTS)
    if CONFIG_PATH.exists(): c.update(json.loads(CONFIG_PATH.read_text()))
    if not c.get("timezone"):
        from sentinel import core; c["timezone"] = core.timezone()
    return c
def save(c):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700); CONFIG_PATH.write_text(json.dumps(c, indent=2) + "\n"); os.chmod(CONFIG_PATH, 0o600)
