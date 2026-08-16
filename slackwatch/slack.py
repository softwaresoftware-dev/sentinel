from __future__ import annotations
import json, logging, time
from pathlib import Path
import requests
from .config import CONFIG_DIR

log = logging.getLogger("slackwatch.slack")


def app_creds() -> dict:
    return json.loads((CONFIG_DIR / "app.json").read_text())


class Workspace:
    def __init__(self, ws: dict):
        self.label = ws["label"]; self.team_id = ws["team_id"]; self.user_id = ws["user_id"]
        self.token = Path(ws["token_path"]).expanduser().read_text().strip()
        self._users: dict[str, str] = {}

    def api(self, method: str, **params):
        for attempt in range(3):
            r = requests.get(f"https://slack.com/api/{method}", headers={"Authorization": f"Bearer {self.token}"}, params=params, timeout=30)
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", "5"))); continue
            j = r.json()
            if not j.get("ok"):
                raise RuntimeError(f"{self.label}/{method}: {j.get('error')}")
            return j
        raise RuntimeError(f"{self.label}/{method}: rate limited")

    def user_name(self, uid: str) -> str:
        if not uid: return "?"
        if uid not in self._users:
            try:
                u = self.api("users.info", user=uid)["user"]
                self._users[uid] = u.get("real_name") or u.get("name") or uid
            except Exception:
                self._users[uid] = uid
        return self._users[uid]

    def dms(self) -> list[dict]:
        out, cursor = [], None
        while True:
            j = self.api("conversations.list", types="im,mpim", exclude_archived="true", limit=200, **({"cursor": cursor} if cursor else {}))
            out += j.get("channels", [])
            cursor = (j.get("response_metadata") or {}).get("next_cursor")
            if not cursor: break
        return out

    def history(self, channel: str, oldest: str, limit=20) -> list[dict]:
        return self.api("conversations.history", channel=channel, oldest=oldest, limit=limit, inclusive="false").get("messages", [])

    def search_mentions(self, since_date: str, count=50) -> list[dict]:
        j = self.api("search.messages", query=f"<@{self.user_id}> after:{since_date}", sort="timestamp", sort_dir="desc", count=count)
        return (j.get("messages") or {}).get("matches", [])

    def search(self, query: str, count=30) -> list[dict]:
        j = self.api("search.messages", query=query, sort="timestamp", sort_dir="desc", count=count)
        return (j.get("messages") or {}).get("matches", [])

    def permalink(self, channel: str, ts: str) -> str:
        try:
            return self.api("chat.getPermalink", channel=channel, message_ts=ts).get("permalink", "")
        except Exception:
            return ""


def authorize(label: str, cfg: dict) -> dict:
    """Loopback OAuth: prints URL, waits for redirect on :8765, exchanges code, writes token. Returns workspace entry."""
    import http.server, urllib.parse, threading, webbrowser
    app = app_creds()
    state = f"{label}-{int(time.time())}"
    url = ("https://slack.com/oauth/v2/authorize?" + urllib.parse.urlencode({"client_id": app["client_id"], "user_scope": app["user_scopes"], "redirect_uri": app["redirect_uri"], "state": state}))
    got = {}
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200); self.end_headers(); self.wfile.write(b"slackwatch: authorized, you can close this tab.")
        def log_message(self, *a): pass
    srv = http.server.HTTPServer(("127.0.0.1", 8765), H)
    if app["redirect_uri"].startswith("https://"):
        import ssl
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(str(CONFIG_DIR / "localhost.crt"), str(CONFIG_DIR / "localhost.key"))
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    print("Open this URL in a browser signed into the target workspace:\n" + url, flush=True)
    while "code" not in got and "error" not in got:
        srv.handle_request()
    srv.server_close()
    if "error" in got:
        raise RuntimeError(f"oauth error: {got['error']}")
    r = requests.post("https://slack.com/api/oauth.v2.access", data={"client_id": app["client_id"], "client_secret": app["client_secret"], "code": got["code"], "redirect_uri": app["redirect_uri"]}, timeout=30).json()
    if not r.get("ok"):
        raise RuntimeError(f"oauth.v2.access failed: {r}")
    au = r["authed_user"]; team = r.get("team") or {}
    tp = CONFIG_DIR / f"token-{label}.txt"; tp.write_text(au["access_token"]); tp.chmod(0o600)
    entry = {"label": label, "team_id": team.get("id"), "team_name": team.get("name"), "user_id": au["id"], "token_path": str(tp)}
    cfg["workspaces"] = [w for w in cfg.get("workspaces", []) if w["label"] != label] + [entry]
    from . import config as C; C.save(cfg)
    return entry
