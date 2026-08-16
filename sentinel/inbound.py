"""Inbound messages from the owner (commands for the agent). Channels: sms-bridge (phone via session-bridge), ntfy (owner posts to an inbound topic from the ntfy app), none."""
from __future__ import annotations
import hashlib, json, logging, re, time
from datetime import datetime
from pathlib import Path
import requests
from . import core, notify

log = logging.getLogger("sentinel.inbound")


def _digits(s): return re.sub(r"\D", "", s or "")[-10:]


def _sms_bridge(cfg: dict) -> list[dict]:
    b = cfg["inbound"].get("sms_bridge") or cfg["delivery"].get("sms_bridge") or {}
    url = f"{b.get('url', 'http://127.0.0.1:8940')}/devices/{b['device']}/tools/sms_list"
    h = {"Content-Type": "application/json"}
    tokf = b.get("token_file") or str(Path.home() / ".config" / "session-bridge" / "token")
    if Path(tokf).expanduser().exists(): h["Authorization"] = "Bearer " + Path(tokf).expanduser().read_text().strip()
    r = requests.post(url, json={"arguments": {"limit": 25, "type": "inbox"}}, headers=h, timeout=45)
    if not r.ok: raise RuntimeError(f"sms_list HTTP {r.status_code}: {r.text[:160]}")
    j = r.json()
    if j.get("isError"): raise RuntimeError("sms_list: " + " ".join(c.get("text", "") for c in j.get("content", [])))
    txt = " ".join(c.get("text", "") for c in j.get("content", []) if isinstance(c, dict))
    m = re.search(r"\[.*\]", txt, re.S); msgs = json.loads(m.group(0)) if m else []
    mine = _digits(b.get("number") or cfg["owner"].get("phone", ""))
    out = []
    for m in msgs:
        if _digits(m.get("number", "")) != mine: continue         # only the owner's own texts are commands
        try: ts = datetime.strptime(m.get("received", ""), "%Y-%m-%d %H:%M").timestamp()
        except Exception: ts = time.time()
        out.append({"id": f"sms:{m.get('_id') or m.get('id')}:{m.get('received','')}", "ts": ts, "body": (m.get("body") or "").strip()})
    return out


def _ntfy(cfg: dict) -> list[dict]:
    n = cfg["inbound"]["ntfy"]; server = n.get("server", "https://ntfy.sh").rstrip("/")
    h = {}
    if n.get("token"): h["Authorization"] = f"Bearer {n['token']}"
    r = requests.get(f"{server}/{n['topic']}/json", params={"poll": "1", "since": n.get("since", "6h")}, headers=h, timeout=30)
    r.raise_for_status()
    out = []
    for line in r.text.splitlines():
        try: m = json.loads(line)
        except Exception: continue
        if m.get("event") != "message": continue
        out.append({"id": f"ntfy:{m['id']}", "ts": float(m.get("time", time.time())), "body": (m.get("message") or "").strip()})
    return out


def fetch(cfg: dict) -> list[dict]:
    chan = cfg["inbound"].get("channel", "none")
    if chan == "none": return []
    if chan == "sms-bridge": return _sms_bridge(cfg)
    if chan == "ntfy": return _ntfy(cfg)
    raise RuntimeError(f"unknown inbound channel {chan}")


def recent_sent_hashes(hours=48) -> set[str]:
    p = notify.SENT_LOG; out = set()
    if not p.exists(): return out
    cutoff = time.time() - hours * 3600
    for l in p.read_text().splitlines():
        try:
            d = json.loads(l)
            if d["ts"] >= cutoff: out.add(hashlib.sha1(d["body"].encode()).hexdigest())
        except Exception: pass
    return out
