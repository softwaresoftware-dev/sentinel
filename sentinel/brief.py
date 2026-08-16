"""One morning text that merges calendar, inbox, GitHub, Slack."""
from __future__ import annotations
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
log = logging.getLogger("sentinel.brief")


def _safe(name, fn):
    try:
        return fn()
    except Exception as e:
        log.exception("%s brief failed: %s", name, e)
        return f"({name}: unavailable — {type(e).__name__})"


def build(cfg: dict) -> str:
    tz = ZoneInfo(cfg["owner"]["timezone"]); now = datetime.now(tz)
    parts = [f"🧭 {now.strftime('%A %b %-d')}"]
    import shutil
    def cal():
        from calwatch import config as C; from calwatch.brief import build_brief
        c = C.load()
        if not c.get("accounts"): return None
        text, _ = build_brief(c); return text
    def mail():
        from mailwatch import config as C; from mailwatch.engine import build_brief; from mailwatch.state import State
        c = C.load()
        if not c.get("accounts"): return None
        return build_brief(c, State())
    def gh():
        from ghwatch import config as C; from ghwatch.engine import build_brief, State
        if not shutil.which("gh") or C.load().get("disabled"): return None
        return build_brief(C.load(), State())
    def slack():
        from slackwatch import config as C; from slackwatch.engine import build_brief, State
        c = C.load()
        if not c.get("workspaces"): return None
        return build_brief(c, State())
    for name, fn in (("calendar", cal), ("inbox", mail), ("github", gh), ("slack", slack)):
        r = _safe(name, fn)
        if r: parts.append(r)          # None = watcher not configured → no section
    import importlib
    for spec in cfg.get("extra_briefs", []):        # "pkg.module:function" added by `sentinel new`
        mod, _, fn = spec.partition(":")
        parts.append(_safe(spec, lambda mod=mod, fn=fn: getattr(importlib.import_module(mod), fn)()))
    if cfg.get("inbound", {}).get("channel", "none") != "none":
        parts.append("Reply here to have me act on anything.")
    return "\n\n".join(parts)
