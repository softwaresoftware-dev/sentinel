"""Triage new mail with claude -p. Returns {uid: {"tier": urgent|reply|fyi|noise, "why": str, "due": str}}."""
from __future__ import annotations
import json, logging, re, shutil, subprocess
from .model import Mail

log = logging.getLogger("mailwatch.classify")
NOISE_SENDER = re.compile(r"(no-?reply|donotreply|do-not-reply|notifications?@|mailer-daemon|newsletter|marketing|noreply)", re.I)


def prefilter(m: Mail, cfg: dict) -> str | None:
    """Cheap rules. Returns a tier to short-circuit, or None to ask the model."""
    labs = set(m.labels)
    if labs & {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "SPAM", "TRASH"}:
        return "noise"
    from sentinel import core
    me = [x.lower() for x in (cfg.get("me") or core.owner().get("emails", []))]
    if m.sender_addr in me:
        return "noise"                       # my own sent mail landing in inbox (self-cc)
    if any(v.lower() in (m.sender or "").lower() for v in cfg.get("vip", [])):
        return None                          # always let the model rank VIPs (at least reply)
    if m.has_unsubscribe and NOISE_SENDER.search(m.sender_addr or ""):
        return "noise"
    return None


def classify(mails: list[Mail], cfg: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    ask: list[Mail] = []
    for m in mails:
        t = prefilter(m, cfg)
        if t:
            out[m.uid] = {"tier": t, "why": "rule", "due": ""}
        else:
            ask.append(m)
    if not ask:
        return out
    if not shutil.which("claude"):
        for m in ask:
            out[m.uid] = {"tier": "fyi", "why": "no classifier", "due": ""}
        return out
    payload = [{"uid": m.uid, "account": m.account, "from": m.sender, "to": m.to[:3], "subject": m.subject,
                "received": m.received.isoformat(), "unsubscribe_header": m.has_unsubscribe, "labels": m.labels[:6], "body": m.snippet[:600]} for m in ask]
    vip = cfg.get("vip", [])
    from sentinel import core
    o = core.owner(); who = o.get("name") or "the owner"; ctx = (" Context: " + o["context"]) if o.get("context") else ""
    prompt = f"""You triage {who}'s inbox across several accounts (the "account" field is a label the owner chose).{ctx} Classify EACH message into exactly one tier:
- "urgent": needs the owner within hours — a real person waiting on them, a deadline/meeting today or tomorrow, money movement, security/account alerts that need action, travel changes, anything from a VIP that asks a question. They will get paged.
- "reply": a real human wrote to the owner and expects a response, but not time-critical. Goes in the morning brief.
- "fyi": legit but no action (receipts, confirmations, CI/deploy notices, statements, calendar acceptances, threads they're cc'd on).
- "noise": marketing, newsletters, cold outreach, digests, social notifications.
VIP senders (never below "reply"): {json.dumps(vip)}
Be strict about "urgent" — false alarms are costly; false "noise" is worse than "fyi".
Reply with ONLY a JSON array: [{{"uid": "...", "tier": "...", "why": "<=12 words", "due": "<deadline if any, else empty>"}}]

Messages: {json.dumps(payload, ensure_ascii=False)}"""
    try:
        r = subprocess.run(["claude", "-p", "--model", cfg.get("classify_model", "sonnet"), "--output-format", "text", prompt],
                           capture_output=True, text=True, timeout=240)
        txt = (r.stdout or "").strip()
        mjs = re.search(r"\[.*\]", txt, re.S)
        arr = json.loads(mjs.group(0)) if mjs else []
        for it in arr:
            if it.get("uid") and it.get("tier") in ("urgent", "reply", "fyi", "noise"):
                out[it["uid"]] = {"tier": it["tier"], "why": str(it.get("why", ""))[:80], "due": str(it.get("due", ""))[:40]}
    except Exception as e:
        log.warning("classifier failed: %s", e)
    for m in ask:
        out.setdefault(m.uid, {"tier": "fyi", "why": "classifier miss", "due": ""})
    return out
