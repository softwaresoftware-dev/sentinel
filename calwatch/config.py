from __future__ import annotations
import json, os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("CALWATCH_CONFIG_DIR", Path.home() / ".config" / "calwatch"))
CONFIG_PATH = CONFIG_DIR / "config.json"
DATA_DIR = Path(os.environ.get("CALWATCH_DATA_DIR", Path.home() / ".local" / "share" / "calwatch"))

DEFAULTS = {
    "timezone": None,   # None → owner timezone from sentinel core config
    "poll_interval_seconds": 300,
    "lookahead_days": 14,
    "daily_brief_time": "07:00",
    "daily_brief_latest": "13:00",   # if daemon was down at brief time, still send before this
    "brief_model": "sonnet",
    "brief_use_claude": True,
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


def bridge_token(cfg: dict) -> str:
    p = Path(cfg["bridge_token_file"]).expanduser()
    return p.read_text().strip() if p.exists() else ""
