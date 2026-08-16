from __future__ import annotations
import fnmatch, json, logging, re, sqlite3, subprocess, time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sentinel import notify
from .config import DATA_DIR

log = logging.getLogger("ghwatch.engine")


def gh(path: str, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    r = subprocess.run(["gh", "api", f"{path}{'?' + q if q else ''}"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"gh api {path}: {r.stderr.strip()[:200]}")
    return json.loads(r.stdout or "null")


class State:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(DATA_DIR / "state.db"))
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS seen (key TEXT PRIMARY KEY, ts REAL, kind TEXT, repo TEXT, title TEXT, url TEXT, alerted INTEGER);
        CREATE TABLE IF NOT EXISTS briefs (day TEXT PRIMARY KEY, sent_at REAL, text TEXT);
        CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE IF NOT EXISTS log (ts REAL, kind TEXT, msg TEXT);""")
    def get(self, k, d=None):
        r = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone(); return json.loads(r[0]) if r else d
    def set(self, k, v): self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, json.dumps(v))); self.db.commit()
    def log(self, kind, msg): self.db.execute("INSERT INTO log VALUES (?,?,?)", (time.time(), kind, msg)); self.db.commit()
    def known(self, key): return self.db.execute("SELECT 1 FROM seen WHERE key=?", (key,)).fetchone() is not None
    def add(self, key, kind, repo, title, url, alerted):
        self.db.execute("INSERT OR REPLACE INTO seen VALUES (?,?,?,?,?,?,?)", (key, time.time(), kind, repo, title, url, int(alerted))); self.db.commit()
    def brief_sent(self, d): return self.db.execute("SELECT 1 FROM briefs WHERE day=?", (d,)).fetchone() is not None
    def record_brief(self, d, t): self.db.execute("INSERT OR REPLACE INTO briefs VALUES (?,?,?)", (d, time.time(), t)); self.db.commit()


def _hm(s): h, m = s.split(":"); return int(h) * 60 + int(m)
def in_quiet(cfg, now):
    qh = cfg.get("quiet_hours");
    if not qh: return False
    a, b, t = _hm(qh[0]), _hm(qh[1]), now.hour * 60 + now.minute
    return (a <= t or t < b) if a > b else (a <= t < b)


def html_url(subj_url: str) -> str:
    # https://api.github.com/repos/o/r/issues/12 → https://github.com/o/r/issues/12
    return re.sub(r"^https://api\.github\.com/repos/", "https://github.com/", subj_url or "").replace("/pulls/", "/pull/")


def poll(cfg: dict, st: State, send=True) -> dict:
    tz = ZoneInfo(cfg["timezone"]); now = datetime.now(tz)
    baseline = not st.get("baseline_done", False)
    since = st.get("since") or (datetime.now(timezone.utc) - timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
    notes = gh("/notifications", all="false", per_page=50, since=since) or []
    me = st.get("me") or gh("/user")["login"]; st.set("me", me)
    alerts, seen_new = [], 0
    for n in notes:
        subj = n.get("subject") or {}; typ = subj.get("type"); reason = n.get("reason")
        repo = (n.get("repository") or {}).get("full_name", "?"); title = subj.get("title", "")
        key = f"{n.get('id')}:{n.get('updated_at')}"
        if st.known(key): continue
        seen_new += 1
        if typ not in ("Issue", "PullRequest") or (typ == "PullRequest" and not cfg.get("include_prs", True)):
            st.add(key, typ or "?", repo, title, "", False); continue
        if reason in cfg.get("ignore_reasons", []) or any(p.lower() in title.lower() for p in cfg.get("ignore_title_patterns", [])):
            st.add(key, reason, repo, title, "", False); continue
        page = reason in cfg["alert_reasons"]
        detail = ""
        if not page and reason == "subscribed":
            # newly opened issue/PR in a repo I care about?
            if any(fnmatch.fnmatch(repo, pat) for pat in cfg.get("new_issue_repos", [])):
                try:
                    it = gh(subj["url"].replace("https://api.github.com", ""))
                    created = datetime.fromisoformat(it["created_at"].replace("Z", "+00:00"))
                    if it.get("user", {}).get("login") != me and datetime.now(timezone.utc) - created < timedelta(hours=6) and n.get("updated_at", "")[:16] == it["created_at"][:16]:
                        page = True; detail = f"new {typ.lower()} by {it['user']['login']}"
                except Exception as e:
                    log.warning("lookup %s failed: %s", subj.get("url"), e)
        url = html_url(subj.get("url", ""))
        st.add(key, reason, repo, title, url, page and not baseline)
        if page and not baseline:
            alerts.append({"repo": repo, "title": title, "reason": detail or reason.replace("_", " "), "url": url, "type": typ})
    if notes:
        st.set("since", max(n.get("updated_at", "") for n in notes))
    else:
        st.set("since", (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    if baseline: st.set("baseline_done", True)
    held = st.get("held", [])
    if in_quiet(cfg, now):
        held += alerts; st.set("held", held); alerts = []
    elif held:
        alerts = held + alerts; st.set("held", [])
    msg, sent = None, None
    if alerts:
        cap = int(cfg.get("max_alerts_per_poll", 4))
        lines = [f"• {a['repo'].split('/')[-1]}#{a['url'].rsplit('/',1)[-1]} {a['title'][:55]} — {a['reason']}" for a in alerts[:cap]]
        if len(alerts) > cap: lines.append(f"…+{len(alerts)-cap} more")
        msg = "🐙 GitHub\n" + "\n".join(lines)
        st.log("alert", msg)
        if send:
            ok, txt = notify.deliver(cfg, msg, title="GitHub"); sent = {"ok": ok, "detail": txt}
        log.warning("GH ALERT:\n%s", msg)
    st.set("last_poll", {"at": time.time(), "notifications": len(notes), "new": seen_new, "alerts": len(alerts)})
    return {"notifications": len(notes), "new": seen_new, "alerts": len(alerts), "message": msg, "sent": sent, "baseline": baseline}


def build_brief(cfg: dict, st: State) -> str:
    tz = ZoneInfo(cfg["timezone"]); now = datetime.now(tz)
    me = st.get("me") or gh("/user")["login"]
    assigned = sorted(gh("/issues", filter="assigned", state="open", per_page=50) or [], key=lambda i: i.get("updated_at", ""), reverse=True)
    mentioned = gh("/issues", filter="mentioned", state="open", per_page=30) or []
    reviews = gh("/search/issues", q=f"is:pr+is:open+review-requested:{me}", per_page=20).get("items", [])
    unread = gh("/notifications", all="false", per_page=50) or []
    unread = [n for n in unread if (n.get("subject") or {}).get("type") in ("Issue", "PullRequest") and n.get("reason") not in cfg.get("ignore_reasons", [])]
    day = (now - timedelta(hours=24)).timestamp()
    recent = st.db.execute("SELECT repo,title,url FROM seen WHERE ts>=? AND alerted=1 ORDER BY ts DESC", (day,)).fetchall()
    head = f"🐙 GitHub {now.strftime('%a %b %-d')} — {len(assigned)} assigned, {len(reviews)} reviews, {len(unread)} unread"
    parts = [head]
    def line(it, tag=""):
        repo = it["repository_url"].rsplit("/", 1)[-1] if "repository_url" in it else it.get("repo", "")
        stale = ""
        if it.get("updated_at"):
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(it["updated_at"].replace("Z", "+00:00"))).days
            stale = f" ({age}d)" if age >= 3 else ""
        return f"• {repo}#{it['number']} {it['title'][:50]}{stale}{tag}"
    for it in [i for i in assigned if "pull_request" not in i][:6]: parts.append(line(it))
    for it in [i for i in assigned if "pull_request" in i][:3]: parts.append(line(it, " [PR]"))
    for it in reviews[:4]: parts.append(line(it, " [review]"))
    seen_urls = {i.get("html_url") for i in assigned + reviews}
    for it in [i for i in mentioned if i.get("html_url") not in seen_urls][:4]: parts.append(line(it, " [mentioned]"))
    if recent: parts.append(f"Alerted last 24h: {len(recent)}")
    if len(parts) == 1: parts.append("Nothing assigned or waiting on you.")
    return "\n".join(parts)
