---
name: status
description: Show what sentinel is watching, when each watcher last polled, delivery/inbound channels, outbox backlog, and recent alerts. Use when asked "is sentinel running", "sentinel status", "what's being watched", "did my alerts go out", "why didn't I get paged".
---
Run `uv run --directory "${CLAUDE_PLUGIN_ROOT}" sentinel status`, then for any watcher the user asks about, `<watcher> status` (recent log lines) and, if it's a daemon question, list managed daemons through the daemon capability (use an available tool). If `last poll` is `never` for a configured watcher, its daemon isn't registered — point to `/sentinel:setup` step 5. If the outbox is non-empty, delivery is failing: `sentinel test` and check `~/.config/sentinel/config.json` → `delivery`.
