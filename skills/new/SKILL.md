---
name: new
description: Scaffold a new sentinel watcher for any source (a league, a feed, a website, an API, a queue…) — it polls, pages the owner when something needs them, and adds a section to their morning brief. Use when asked to "set up a sentinel for X", "watch X and alert me", "monitor my <league/feed/site> like the calendar one", "add X to my morning brief", or to tune an existing watcher.
---

# sentinel new — poll → alert → brief → (reply to act)

`ROOT="${CLAUDE_PLUGIN_ROOT}"`. Read `$ROOT/README.md` once if you haven't. The engine already provides: 5-min poll, silent first-run baseline, per-key dedupe (sqlite), batching (`max_alerts_per_poll`), quiet hours hold-not-drop, outbox retry when delivery fails, `run|once|items|brief|status` CLI, registration into the combined brief and into the reply agent's tool list. **You write one file.**

## Steps
1. `uv run --directory "$ROOT" sentinel new <name>watch --title "<Title>" --emoji "🏈"` (lowercase identifier ending in `watch`). Creates `$ROOT/<name>watch/{config,source,engine,cli}.py` and `~/.config/<name>watch/config.json`.
2. Edit **only** `$ROOT/<name>watch/source.py`:
   - `fetch(cfg) -> list[dict]` — return the *current window* of items (not just new). Each has a stable `"key"` and `"title"`; add `when`, `who`, `url`, `mine`, … freely. Credentials/URLs come from `cfg` (`~/.config/<name>watch/config.json`, 0600); add defaults to `DEFAULTS` in `config.py`.
   - `alert(item, cfg) -> str|None` — the one-line reason to page **now**, or None. Be strict; attention is expensive. New keys only; implement `changed(old,new)` if a known item's change should re-alert.
   - `brief(items, cfg) -> str` — a few plain-text lines for the morning text. No markdown.
   Time-critical sources (draft clock, auction ending): set `poll_interval_seconds` low (60 is fine) and alert on the *state that matters* (`item["on_the_clock"] and item["mine"]`), not on every change.
3. Auth: prefer an official API + token in the config file. OAuth → mirror calwatch/slackwatch (loopback flow, token file under `~/.config/<name>watch/`); the browser-automation capability may click consent screens, but never type the owner's passwords. No API → `requests` + parse or the browser-automation capability inside `fetch()` at a polite interval.
4. Verify: `<name>watch items` → `<name>watch once --dry-run` twice (first is baseline) → `<name>watch brief` → `sentinel brief` (combined; the section appears automatically).
5. Daemon: `sentinel daemons` prints the registration line for `<name>watch`; register + autostart it through the daemon capability (use an available tool), and restart the `sentinel` daemon so the agent learns the new CLI.
6. Tell the owner in one paragraph what will page them and when. Don't create a separate morning message — the combined brief carries it (`daily_brief_time` stays `null`).

If the reply agent should *act* on the source (e.g. make a pick), expose a CLI subcommand in `<name>watch/cli.py` and mention it in `agent_extra_tools` in `~/.config/sentinel/config.json` (the scaffolder adds `items|status|brief` already).

Remove: `sentinel rm <name>watch [--purge]` (then remove its daemon autostart via the daemon capability).
