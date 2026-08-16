---
name: setup
description: Install and configure sentinel — the alerting stack (calendar conflicts, urgent mail, GitHub, Slack, custom watchers), the combined morning brief, and the reply-to-act agent — and register its daemons so it survives reboot. Use when asked to "set up sentinel", "install sentinel", "get my morning brief working", "make sentinel page me", or when a sentinel CLI reports missing config.
---

# sentinel setup

Goal: after this, the user gets paged (phone push/SMS/etc.) when something needs them, one morning brief, and can message back to have Claude act. Everything runs locally as boot-persistent daemons via the **daemon capability**.

Set `ROOT="${CLAUDE_PLUGIN_ROOT}"` for every command below. All CLIs are `uv run --directory "$ROOT" <cli> …` (or `$ROOT/.venv/bin/<cli>` after step 1). Never hardcode the user's paths, names, or numbers into files that ship with the plugin — everything personal goes in `~/.config/sentinel/config.json` and `~/.config/<watcher>/config.json`.

## 1. Dependencies
- `uv` on PATH (`uv --version`); Python ≥ 3.11. Then `uv sync --directory "$ROOT"` (creates `$ROOT/.venv`).
- `claude` on PATH (used headless for mail triage, prep notes and the reply agent).
- Optional per source: `gh` (GitHub), a Google OAuth client, an Entra app, a Slack app — see `$ROOT/docs/accounts.md`. Do not block on these; the core works with zero sources.

## 2. Owner + delivery (ask, then run `sentinel setup …`)
Ask for: name, IANA timezone, one line of context ("runs Acme with cofounder Bob; day job at Globex" — used by the triage/brief prompts), their email addresses (so their own mail isn't flagged), and how they want to be reached.

Recommend in this order and explain trade-offs in one line each:
1. **ntfy** (default, zero accounts): pick two random topics (e.g. `<name>-sentinel-<8 random chars>` and the same + `-in`), tell them to install the ntfy app and subscribe to both. Alerts arrive as push; anything they post to the `-in` topic is a command for the agent.
   `sentinel setup --name "…" --timezone … --context "…" --email a@b.com --delivery ntfy --ntfy-topic <t> --inbound ntfy --ntfy-inbound-topic <t>-in`
2. **sms-bridge**: if the send-sms / session-mesh capability with a phone device is available (use an available tool to check devices), alerts arrive as real texts and their self-texts are commands: `--delivery sms-bridge --sms-device <host> --sms-number <their number> --inbound sms-bridge`.
3. pushover / slack / email / desktop as fallbacks (`--pushover-user/--pushover-token`, `--slack-webhook` or `--slack-token --slack-channel`, email needs `delivery.email` block in the config file).
Then `sentinel test` — confirm they received it before continuing.

## 3. Sources (only what they want; each is optional)
Follow `$ROOT/docs/accounts.md`. Order of least friction: GitHub (`gh auth status` → done) → ICS calendar feeds → Slack (manifest provided) → Google (OAuth client) → Microsoft (Entra app). For OAuth flows: run the auth command, open the printed URL — the browser-automation capability may click through consent screens if available, but **never type the user's passwords or 2FA; hand the tab to them**. After each source: `<watcher> once --dry-run` twice (first = silent baseline) and `<watcher> brief`.

## 4. Verify the brief
`sentinel brief` prints the combined morning text (unconfigured watchers are omitted). `sentinel brief --send` delivers it once now so they see the real thing.

## 5. Daemons (boot-persistent, cross-platform)
Run `sentinel daemons` — it prints one line per daemon: name, command (`uv`), args, cwd. Register **only** `sentinel` plus the watchers they configured, through the daemon capability: start each daemon and install its autostart (use an available daemon-capability tool). Confirm each is `started`/`installed`. On Linux you can then watch with `journalctl --user -u <name> -f`; on macOS the daemon capability's log path; on Windows Task Scheduler.

## 6. Reply-to-act agent (already part of the `sentinel` daemon)
Explain: message the inbound channel (ntfy `-in` topic or a text to their own number) and Claude answers using their MCP tools; anything that reaches other people is drafted and needs a "yes". Test without the phone: `sentinel ask "what's on my calendar tomorrow"`. Model/timeout: `agent_model`, `agent_timeout_seconds` in `~/.config/sentinel/config.json`. Note plainly that the agent runs `claude -p --dangerously-skip-permissions` — that is what "act on my behalf" requires; the confirm-before-contacting-others rule in the system prompt is the safeguard.

## 7. Wrap up
Report: delivery channel, which watchers are live, brief time, how to add a custom watcher (`/sentinel:new`), and where config lives. Offer to tune quiet hours (`quiet_hours` in each watcher config, default 22:30–06:30 hold-not-drop).
