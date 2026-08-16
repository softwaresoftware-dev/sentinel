---
name: ask
description: Run one message through the sentinel reply-to-act agent from this session (no phone round-trip) — the same headless Claude that answers the owner's texts/pushes. Use when asked to "test the sentinel agent", "ask sentinel …", or to debug why a reply was wrong.
---
`uv run --directory "${CLAUDE_PLUGIN_ROOT}" sentinel ask "<message>"`. It resumes today's session (so follow-ups like "yes" work) and prints the reply that would have been delivered. Sessions: `~/.local/share/sentinel/sessions.json`; system prompt: `sentinel/agent.py` (`system_prompt()`), owner name/context from `~/.config/sentinel/config.json`.
