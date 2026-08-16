# sentinel — launch drafts (not posted; Thatcher approves/edits first)

## Show HN
**Title:** Show HN: Sentinel – background watchers for Claude Code that page you, one morning brief, reply to act
**Text:** I have three Google accounts, two Microsoft tenants, five Slack workspaces and six GitHub orgs, and no single view of my day. sentinel is a small stack of watchers: each polls a source, remembers what it's seen (sqlite), and only pages you on things that need you — a calendar conflict across accounts, an email a person is actually waiting on (one `claude -p` triage call after cheap rules drop the noise), a GitHub mention, a Slack DM. One combined morning message. Alerts land on your phone (ntfy by default, or real SMS via your own phone), and you can message back: a headless Claude session with your MCP tools does the work and answers in the thread. It runs with permissions bypassed — the guardrail is one rule: anything that reaches another person is drafted and needs an explicit "yes". `sentinel new x` scaffolds a new watcher where you write fetch/alert/brief and nothing else. MIT, Python, runs locally. https://sentinel.softwaresoftware.dev · https://github.com/softwaresoftware-dev/sentinel

## r/ClaudeAI (or r/ClaudeCode)
**Title:** I made Claude Code page me only when something needs me, then let me text it back — plugin + writeup
**Body:** (same as HN, plus:) The bit that surprised me: the first thing the reply agent did unprompted was notice I had two flights to Austin two days apart; when I said "yes look at that" it went into Gmail, found the airline change email, explained the stale event, and asked before deleting it. Setup is `/softwaresoftware:install sentinel` → `/sentinel:setup`. Blog: https://blog.softwaresoftware.dev/posts/sentinel/

## X / Bluesky thread
1/ five inboxes, one calendar app that shows one account at a time. built the alerting layer I actually wanted and shipped it as a Claude Code plugin: sentinel. watchers that page you. one morning brief. reply to act. sentinel.softwaresoftware.dev
2/ every watcher = poll → remember (sqlite) → page only on new. silent baseline on first run. quiet hours hold, don't drop. phone unreachable? outbox, retried, marked (delayed).
3/ calwatch: conflicts across ALL your accounts (knows mirrored invites and 3-day trips aren't conflicts). mailwatch: rules kill noise, one claude -p call triages the rest. ghwatch: mentions/assigns/new issues. slackwatch: DMs + @you across workspaces.
4/ 07:00: one message. calendar w/ Claude prep notes ("you land 10:15, lunch at 11 — tight"), what needs a reply, what's assigned, who DM'd.
5/ text it back. "what do I have tuesday, anything conflicting?" → it also flagged two flights to Austin. "yes look at that" → found the airline change email, explained the stale event, ASKED before deleting.
6/ the agent runs with permissions bypassed. the guardrail is one sentence: anything that reaches another person is drafted and waits for your yes. it's held up.
7/ your own watcher = one file, three functions. `sentinel new draftwatch`. "set up a sentinel for my fantasy league" works in a fresh Claude session.
8/ MIT, local, python. /softwaresoftware:install sentinel → /sentinel:setup. writeup: blog.softwaresoftware.dev/posts/sentinel

## LinkedIn (short)
Shipped sentinel today — a Claude Code plugin that watches your calendars, inboxes, GitHub and Slack in the background, pages you only when something needs you, sends one morning brief, and lets you text back to have Claude act (with a hard rule: anything that reaches another person is drafted and confirmed first). Built it for myself across 3 Google accounts, 2 Microsoft tenants and 5 Slack workspaces; the pattern generalizes to any source in three functions. Writeup + install: sentinel.softwaresoftware.dev

## Where to submit (needs Thatcher's account/approval)
- Anthropic plugin marketplace submission: https://claude.ai/settings/plugins/submit
- awesome-claude-code style lists (PR)
- ntfy community showcase (they list integrations)
