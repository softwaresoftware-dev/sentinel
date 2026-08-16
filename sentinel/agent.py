"""Inbound SMS → headless Claude (with all MCP tools) → SMS reply."""
from __future__ import annotations
import json, logging, os, re, subprocess, time
from datetime import datetime
from zoneinfo import ZoneInfo
from .config import DATA_DIR
log = logging.getLogger("sentinel.agent")

SYSTEM_TMPL = """You are {name}'s personal operator, reached by message from their own phone. You run headless on their machine with their tools: whatever MCP servers and CLIs are configured for Claude Code here (calendar, mail, chat, code hosting, the phone bridge if present), plus the sentinel CLIs `calwatch agenda|conflicts`, `mailwatch recent`, `ghwatch brief`, `slackwatch brief` for what the watchers have seen.{context}

Rules:
- Replies go back as a short message on a phone: plain text, no markdown, ≤ {max_chars} characters, lead with the outcome. If a task is long, do the work first, then reply once.
- Reads/lookups: just do them. Internal actions (labeling mail, RSVPing their own calendar, snoozing, creating their own events, notes): do them.
- Anything that reaches ANOTHER PERSON — sending email/chat/SMS to someone else, calendar invites, code-review comments, issues — DRAFT it, show the exact text and recipient, and ask them to reply "yes" (or "send"). Only send after an explicit yes in this conversation. Exception: if their message itself says "send it", "just do it", "go ahead", "no need to confirm", act immediately.
- This conversation persists for the day, so a bare "yes"/"no"/"send" refers to your last proposal.
- Never invent facts about their schedule or mail — read them. If a tool is unavailable, say so briefly.
- Sign nothing; keep it terse."""


def system_prompt(cfg: dict) -> str:
    o = cfg.get("owner", {})
    ctx = (" About them: " + o["context"]) if o.get("context") else ""
    s = SYSTEM_TMPL.format(name=o.get("name") or "the owner", context=ctx, max_chars=cfg.get("reply_max_chars", 900))
    if cfg.get("agent_extra_tools"):
        s += "\nAdditional watcher CLIs available: " + "; ".join(cfg["agent_extra_tools"]) + "."
    return s


def _sessions_path():
    DATA_DIR.mkdir(parents=True, exist_ok=True); return DATA_DIR / "sessions.json"


def session_id_for(cfg: dict) -> str | None:
    p = _sessions_path()
    d = json.loads(p.read_text()) if p.exists() else {}
    key = datetime.now(ZoneInfo(cfg["owner"]["timezone"])).date().isoformat() if cfg.get("session_scope", "day") == "day" else "global"
    return d.get(key)


def save_session(cfg: dict, sid: str):
    p = _sessions_path(); d = json.loads(p.read_text()) if p.exists() else {}
    key = datetime.now(ZoneInfo(cfg["owner"]["timezone"])).date().isoformat() if cfg.get("session_scope", "day") == "day" else "global"
    d[key] = sid; p.write_text(json.dumps(d))


def run(cfg: dict, text: str) -> str:
    sid = session_id_for(cfg)
    system = system_prompt(cfg)
    args = ["claude", "-p", "--output-format", "json", "--model", cfg.get("agent_model", "opus"),
            "--dangerously-skip-permissions", "--append-system-prompt", system]
    if sid:
        args += ["--resume", sid]
    args += [text]
    env = dict(os.environ); env.setdefault("HOME", os.path.expanduser("~"))
    t0 = time.time()
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=int(cfg.get("agent_timeout_seconds", 600)), cwd=cfg.get("agent_cwd") or None, env=env)
    except subprocess.TimeoutExpired:
        return "⏱ I ran out of time on that one (10 min). Try narrowing it, or ask me to continue."
    out = (r.stdout or "").strip()
    reply, new_sid = "", None
    try:
        j = json.loads(out)
        reply = j.get("result") or ""; new_sid = j.get("session_id")
        if j.get("is_error"): reply = reply or f"error: {j.get('error') or 'unknown'}"
    except Exception:
        # resume of a dead session, or non-JSON output → retry fresh once
        if sid and ("No conversation found" in (r.stderr or "") or r.returncode != 0):
            log.warning("resume failed (%s); starting a fresh session", (r.stderr or "")[:120])
            args = [a for a in args if a not in ("--resume", sid)]
            r = subprocess.run(args, capture_output=True, text=True, timeout=int(cfg.get("agent_timeout_seconds", 600)), cwd=cfg.get("agent_cwd") or None, env=env)
            try:
                j = json.loads((r.stdout or "").strip()); reply = j.get("result") or ""; new_sid = j.get("session_id")
            except Exception:
                reply = out or (r.stderr or "").strip()[-400:] or "no output"
        else:
            reply = out or (r.stderr or "").strip()[-400:] or "no output"
    if new_sid:
        save_session(cfg, new_sid)
    log.info("agent took %.0fs rc=%s sid=%s", time.time() - t0, r.returncode, new_sid)
    reply = re.sub(r"\*\*|__|`", "", reply).strip()
    mx = int(cfg.get("reply_max_chars", 900))
    return reply if len(reply) <= mx else reply[: mx - 1] + "…"
