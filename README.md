# sentinel

**Watchers that page you. One morning brief. Reply to act.**

sentinel is a small stack of background watchers for Claude Code users who don't want to live in five inboxes. Each watcher polls a source every few minutes, remembers what it has seen, and only interrupts you when something actually needs you — a new calendar conflict across *all* your accounts, an email a real person is waiting on, a GitHub mention, a Slack DM. Every morning you get **one** text/push with the day laid out. And because the alerts arrive on your phone, you can **message back**: "decline the 11:30", "what's the deal with the two flights?", "draft a reply to Hunter" — a headless Claude with your MCP tools does the work and answers in the same thread, asking before anything reaches another person.

```
07:00  🧭 Tuesday Aug 18
       📅 3 events, 1 all-day · 11:00 lunch overlaps Arctype Sync 11:30 · you land 10:15, lunch at 11 — tight
       📧 0 urgent, 2 need reply · Tim Sims: Re: Four Two
       🐙 12 assigned, 1 review waiting
       💬 quiet
11:42  📧 Urgent mail — Nicole Abel: flight change for Thursday — needs a yes by 3pm
11:44  you: "tell her yes to the 8am, and add it to my calendar"
11:45  Claude: Drafted to Nicole: "Yes to the 8am on Thursday, thanks!" — reply yes to send. Calendar hold added.
11:45  you: "yes"
11:46  Claude: Sent. Hold is now a confirmed event 8:00–10:15 Thu.
```

## What's in the box

| Watcher | Sources | Pages you when | Brief section |
|---|---|---|---|
| `calwatch` | Google (any number of accounts), Microsoft 365, any ICS feed | a new/changed event **conflicts** with another — across accounts; mirrored invites, all-day, multi-day spans and reminder calendars don't count | today's agenda + Claude prep notes (unanswered invites, in-person locations, back-to-back, deadlines in descriptions) |
| `mailwatch` | Gmail (multi-account), Microsoft Graph | Claude triages new mail as **urgent** (a person waiting, deadline, money, security). Rules drop promo/social/newsletter noise first, so it's cheap | what needs a reply from the last 24 h, threads collapsed |
| `ghwatch` | GitHub notifications (`gh` CLI) | mention · assigned · review requested · comment on your thread · **new issue/PR** in repos you care about (CI noise ignored) | open issues assigned to you (freshest first, age), reviews waiting, mentions |
| `slackwatch` | any number of Slack workspaces (user token, read-only) | DMs, group DMs, @you, keywords | DMs/mentions per workspace |
| `sentinel` (hub) | — | — | merges everything into **one** message at your brief time; retries alerts from an outbox when your phone is unreachable; runs the **reply-to-act agent** |
| `sentinel new …` | anything | you decide, in ~30 lines of Python | auto-added |

Delivery: **ntfy** (free push, no account, works everywhere), or real SMS through your own phone on the session mesh, Pushover, Slack, email, desktop. Inbound (reply-to-act): an ntfy topic or texts to your own number.

## Install

In Claude Code:
```
/softwaresoftware:install sentinel
/sentinel:setup
```
The setup skill asks who you are and how to reach you, sends a test, walks through only the sources you want (GitHub is zero-config; ICS feeds need a URL; Google/Microsoft/Slack need a one-time OAuth — see `docs/accounts.md`), and registers the daemons through the daemon capability so it survives reboots on Linux, macOS, and Windows.

Manual: `uv sync` in the plugin root; CLIs are `uv run sentinel …`, `uv run calwatch …` etc.

## Make your own watcher

```
/sentinel:new     →  "set up a sentinel for my fantasy football league"
```
or by hand: `sentinel new draftwatch --title "Draft" --emoji "🏈"` scaffolds a package where you edit one file:

```python
def fetch(cfg):            # current window of items, each with a stable "key"
def alert(item, cfg):      # one-line reason to page NOW, or None
def brief(items, cfg):     # a few lines for the morning text
```
Baseline, dedupe, batching, quiet hours, outbox, CLI, brief and agent registration are already handled.

## Reminders
`sentinel remind "stretch" --in 45m` · `sentinel remind "call mom" --at "tomorrow 11:00"` · `sentinel remind "draft starts" --before "fantasy draft" --offsets 60m,30m` (looks the event up on your calendars). Delivered through the same channel; today's pending reminders show in the brief. Texting the agent "remind me 30 minutes before the draft" does the same thing.

## The reply-to-act agent

Runs `claude -p` (default model opus, one session per day) with your MCP servers and the watcher CLIs, `--dangerously-skip-permissions` because that's what acting on your behalf needs. Guardrail baked into the system prompt: reads and self-only actions are free; **anything that reaches another person is drafted and needs your explicit "yes"** (or "just do it" in your original message). Test from a terminal: `sentinel ask "…"`.

## Files
`~/.config/sentinel/config.json` (owner, delivery, inbound, brief time, agent), `~/.config/<watcher>/config.json` (sources, thresholds, quiet hours — live-reloaded), state in `~/.local/share/<watcher>/state.db`, outbox at `~/.local/share/sentinel/outbox.jsonl`.

## Requirements
Python ≥ 3.11 with `uv`; `claude` CLI; optional `gh`. Cross-platform (daemons via daemon-manager: systemd / launchd / Task Scheduler).

MIT · NOV LLC · https://sentinel.softwaresoftware.dev
