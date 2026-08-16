# Connecting sources

Everything is optional — configure only the watchers you want. Config files live in `~/.config/<watcher>/config.json` (0600) and are re-read every poll cycle.

## GitHub (`ghwatch`) — zero setup
Uses the `gh` CLI's existing login (`gh auth status`). Pages on mention / assign / review-requested / comments on your threads / newly opened issues in repos matching `new_issue_repos` (default `["*"]`). Tune in `~/.config/ghwatch/config.json`.

## Calendars (`calwatch`)
Accounts are entries in `~/.config/calwatch/config.json` → `accounts`:
- **ICS feed** (any calendar; Outlook "publish calendar", Google "secret address"): `{"type":"ics","label":"work","url":"https://…/calendar.ics"}` — no auth.
- **Google**: create a Desktop OAuth client in Google Cloud (APIs & Services → Credentials), download `credentials.json`, then `calwatch auth google <label> --credentials /path/credentials.json` (loopback flow; open the printed URL in a browser signed into that account, tick the calendar scope). Repeat per Google account.
- **Microsoft 365**: an Entra app registration (public client, "Allow public client flows" on, delegated `Calendars.ReadWrite` + `User.Read` (+ `Mail.ReadWrite` for mailwatch); multi-tenant if you have several tenants). Then `calwatch auth ms <label> --client-id <APP_ID> --authority https://login.microsoftonline.com/<tenant-or-organizations>` (device-code flow). Some tenants require admin consent — you'll see it in the browser.
Per-account knobs: `calendars` (all | list), `exclude_calendars`, `nonblocking_calendars` (never conflict, e.g. reminders), `include_shared_people` (default false: other people's calendars shared into your account are skipped).

## Mail (`mailwatch`)
- **Gmail**: `mailwatch auth gmail <label> --credentials /path/credentials.json` (readonly scope; same OAuth client as above).
- **Microsoft**: add `{"type":"microsoft","label":"work","client_id":…,"authority":…,"cache_path":"~/.config/mailwatch/ms-work.json","username":"you@corp.com"}` and run the calwatch MS auth once with `Mail.ReadWrite` in scopes (the MSAL cache file is shared format).
Triage uses `claude -p` (model `classify_model`, default sonnet) after cheap rules drop promotions/social/noreply. `vip` = sender substrings that are never below "reply".

## Slack (`slackwatch`)
1. https://api.slack.com/apps → Create New App → From a manifest → paste `docs/slack-app-manifest.json` (a workspace you admin). Copy the client id/secret from Basic Information into `~/.config/slackwatch/app.json`:
   `{"client_id":"…","client_secret":"…","app_id":"…","redirect_uri":"https://localhost:8765/","user_scopes":"channels:history,channels:read,groups:history,groups:read,im:history,im:read,mpim:history,mpim:read,users:read,search:read,team:read"}`
   For more than one workspace: Manage Distribution → activate public distribution (needs the https redirect; the CLI serves a self-signed cert — if the browser blocks the redirect, `curl -k` the redirected URL).
2. `slackwatch auth <label>` per workspace, open the printed URL signed into that workspace, Allow.
Free-plan workspaces cap at 10 apps.

## Delivery / inbound
`sentinel setup --delivery ntfy --ntfy-topic <random-string> --inbound ntfy --ntfy-inbound-topic <random-string>-in` is the zero-account default: install the ntfy app, subscribe to both topics; alerts arrive as push, and anything you post to the `-in` topic is a command for the agent. Several inbound channels can be polled together (`--inbound ntfy --inbound sms-bridge`) — useful when a phone routes self-texts over RCS, which `termux-sms-list` cannot see. Alternatives: `sms-bridge` (your phone on the session mesh: `--sms-device <host> --sms-number <you>` — alerts arrive as texts and your self-texts are commands), `pushover`, `slack`, `email`, `desktop`. Test with `sentinel test`.
