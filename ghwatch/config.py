from __future__ import annotations
import json, os
from pathlib import Path
CONFIG_DIR = Path(os.environ.get("GHWATCH_CONFIG_DIR", Path.home() / ".config" / "ghwatch"))
CONFIG_PATH = CONFIG_DIR / "config.json"
DATA_DIR = Path(os.environ.get("GHWATCH_DATA_DIR", Path.home() / ".local" / "share" / "ghwatch"))
DEFAULTS = {
    "timezone": None,   # None → owner timezone from sentinel core config
    "poll_interval_seconds": 300,
    "daily_brief_time": "07:10",
    "daily_brief_latest": "13:00",
    "max_alerts_per_poll": 4,
    "quiet_hours": ["22:30", "06:30"],
    # notification reasons that always page
    "alert_reasons": ["mention", "team_mention", "assign", "review_requested", "author", "comment", "security_alert"],
    # repos (fnmatch patterns) where a *newly opened* issue pages even if I'm only 'subscribed'
    "new_issue_repos": ["*"],      # fnmatch patterns of owner/repo; "*" = every repo you're subscribed to
    "include_prs": True,
    "ignore_reasons": ["ci_activity"],
    "ignore_title_patterns": ["Weekly digest", "workflow run succeeded"],
}
def load():
    c = dict(DEFAULTS)
    if CONFIG_PATH.exists(): c.update(json.loads(CONFIG_PATH.read_text()))
    if not c.get("timezone"):
        from sentinel import core; c["timezone"] = core.timezone()
    return c
def save(c):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700); CONFIG_PATH.write_text(json.dumps(c, indent=2) + "\n"); os.chmod(CONFIG_PATH, 0o600)
