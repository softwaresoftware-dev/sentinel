"""Outbound delivery (pluggable) + outbox retry + sent-log. Every watcher calls deliver(); nothing else touches a channel."""
from __future__ import annotations
import json, logging, os, platform, shutil, subprocess, time
from pathlib import Path
import requests
from . import core

log = logging.getLogger("sentinel.notify")
OUTBOX = core.DATA_DIR / "outbox.jsonl"
SENT_LOG = core.DATA_DIR / "sent.jsonl"


# ---------------------------------------------------------------- channels
def _ntfy(d: dict, message: str, title: str) -> tuple[bool, str]:
    n = d.get("ntfy", {}); url = f"{n.get('server', 'https://ntfy.sh').rstrip('/')}/{n['topic']}"
    h = {"Title": title, "Priority": str(n.get("priority", "default")), "Markdown": "no"}
    if n.get("token"): h["Authorization"] = f"Bearer {n['token']}"
    r = requests.post(url, data=message.encode(), headers=h, timeout=20)
    return r.ok, r.text[:200]


def _sms_bridge(d: dict, message: str, title: str) -> tuple[bool, str]:
    b = d.get("sms_bridge", {})
    url = f"{b.get('url', 'http://127.0.0.1:8940')}/devices/{b['device']}/tools/sms_send"
    h = {"Content-Type": "application/json"}
    tokf = b.get("token_file") or str(Path.home() / ".config" / "session-bridge" / "token")
    if Path(tokf).expanduser().exists(): h["Authorization"] = "Bearer " + Path(tokf).expanduser().read_text().strip()
    r = requests.post(url, json={"arguments": {"number": b["number"], "message": message}}, headers=h, timeout=60)
    if not r.ok: return False, f"HTTP {r.status_code}: {r.text[:200]}"
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    return (not j.get("isError", False)), " ".join(c.get("text", "") for c in j.get("content", []) if isinstance(c, dict))[:200]


def _pushover(d: dict, message: str, title: str) -> tuple[bool, str]:
    p = d["pushover"]
    r = requests.post("https://api.pushover.net/1/messages.json", data={"token": p["app_token"], "user": p["user_key"], "title": title, "message": message}, timeout=20)
    return r.ok, r.text[:200]


def _slack(d: dict, message: str, title: str) -> tuple[bool, str]:
    s = d["slack"]
    if s.get("webhook"):
        r = requests.post(s["webhook"], json={"text": f"*{title}*\n{message}"}, timeout=20); return r.ok, r.text[:200]
    r = requests.post("https://slack.com/api/chat.postMessage", headers={"Authorization": f"Bearer {s['token']}"}, json={"channel": s["channel"], "text": f"*{title}*\n{message}"}, timeout=20)
    j = r.json(); return bool(j.get("ok")), j.get("error", "")


def _email(d: dict, message: str, title: str) -> tuple[bool, str]:
    import smtplib, ssl
    from email.message import EmailMessage
    e = d["email"]; m = EmailMessage(); m["From"] = e["from"]; m["To"] = e["to"]; m["Subject"] = title; m.set_content(message)
    with smtplib.SMTP(e.get("host", "smtp.gmail.com"), int(e.get("port", 587)), timeout=30) as s:
        s.starttls(context=ssl.create_default_context()); s.login(e["user"], e["password"]); s.send_message(m)
    return True, "sent"


def _desktop(d: dict, message: str, title: str) -> tuple[bool, str]:
    sysname = platform.system()
    try:
        if sysname == "Linux" and shutil.which("notify-send"):
            subprocess.run(["notify-send", title, message[:400]], check=True, timeout=10); return True, "notify-send"
        if sysname == "Darwin":
            subprocess.run(["osascript", "-e", f'display notification {json.dumps(message[:200])} with title {json.dumps(title)}'], check=True, timeout=10); return True, "osascript"
        if sysname == "Windows":
            ps = f"[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms')|Out-Null;$n=New-Object System.Windows.Forms.NotifyIcon;$n.Icon=[System.Drawing.SystemIcons]::Information;$n.Visible=$true;$n.ShowBalloonTip(10000,{json.dumps(title)},{json.dumps(message[:200])},[System.Windows.Forms.ToolTipIcon]::None)"
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, timeout=15); return True, "balloon"
    except Exception as e:
        return False, str(e)
    return False, "no desktop notifier"


CHANNELS = {"ntfy": _ntfy, "sms-bridge": _sms_bridge, "pushover": _pushover, "slack": _slack, "email": _email, "desktop": _desktop}


# ---------------------------------------------------------------- public API
def deliver(cfg: dict | None, message: str, title: str = "sentinel", queue_on_fail: bool = True) -> tuple[bool, str]:
    """Send via the configured channel (cfg arg is ignored except for tests; core config is the source of truth).
    Falls back to desktop; if all fail, queue to the outbox for retry."""
    d = core.load()["delivery"]
    chan = d.get("channel", "desktop")
    fn = CHANNELS.get(chan)
    ok, txt = (False, f"unknown channel {chan}") if fn is None else _try(fn, d, message, title)
    if ok:
        remember_sent(message); return True, txt
    if chan != "desktop":
        ok2, txt2 = _try(_desktop, d, message, title)
        if ok2: return True, f"{chan} failed ({txt}); shown on desktop"
    if queue_on_fail:
        OUTBOX.parent.mkdir(parents=True, exist_ok=True)
        with OUTBOX.open("a") as f: f.write(json.dumps({"ts": time.time(), "title": title, "message": message}) + "\n")
        log.warning("delivery failed (%s) — queued to outbox", txt)
        return False, f"queued to outbox; {chan} failed ({txt})"
    return False, f"{chan} failed ({txt})"


def _try(fn, d, message, title):
    try: return fn(d, message, title)
    except Exception as e: return False, f"{type(e).__name__}: {e}"


def sms(cfg: dict, message: str) -> tuple[bool, str]:   # backwards-compat name
    return deliver(cfg, message)


def remember_sent(message: str) -> None:
    try:
        SENT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with SENT_LOG.open("a") as f: f.write(json.dumps({"ts": time.time(), "body": message}) + "\n")
    except Exception as e: log.warning("sent log: %s", e)


def flush_outbox(cfg: dict | None = None) -> int:
    if not OUTBOX.exists(): return 0
    items = [json.loads(l) for l in OUTBOX.read_text().splitlines() if l.strip()]
    if not items: return 0
    left, n = [], 0
    for it in items:
        if time.time() - it["ts"] > 2 * 86400: continue
        ok, _ = deliver(None, "(delayed) " + it["message"], it.get("title", "sentinel"), queue_on_fail=False)
        if ok: n += 1
        else: left.append(it)
    OUTBOX.write_text("".join(json.dumps(i) + "\n" for i in left))
    return n
