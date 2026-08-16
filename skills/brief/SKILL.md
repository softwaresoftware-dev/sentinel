---
name: brief
description: Print or send the combined sentinel morning brief now (calendar, inbox, GitHub, Slack, custom watchers). Use when asked "what's my brief", "send my morning brief now", "show me today's brief", "what would sentinel text me".
---
`uv run --directory "${CLAUDE_PLUGIN_ROOT}" sentinel brief` prints it; add `--send` to deliver through the configured channel. Individual sections: `calwatch brief [--date YYYY-MM-DD]`, `mailwatch brief`, `ghwatch brief`, `slackwatch brief`, `<custom>watch brief`.
