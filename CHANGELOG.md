# Changelog

## 1.0.0 — 2026-08-15
- Initial release: `calwatch` (Google / Microsoft / ICS calendars → conflict alerts + prep notes), `mailwatch` (Gmail / Microsoft Graph → Claude-triaged urgent mail), `ghwatch` (GitHub notifications), `slackwatch` (multi-workspace DMs + mentions), `sentinel` hub (one combined morning brief, alert outbox, reply-to-act agent), `sentinel new` scaffolder for custom watchers.
- Delivery channels: ntfy, phone SMS via session-bridge, Pushover, Slack, email, desktop. Inbound (reply-to-act): ntfy topic or phone SMS.
