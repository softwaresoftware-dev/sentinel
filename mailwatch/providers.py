from __future__ import annotations
import base64, html, json, logging, re
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

import requests

from .model import Mail

log = logging.getLogger("mailwatch.providers")
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
MS_SCOPES = ["Calendars.ReadWrite", "User.Read", "Mail.ReadWrite"]   # subset of what the token was consented for


def _strip_html(s: str) -> str:
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


# ---------------------------------------------------------------- Gmail
class GmailAccount:
    def __init__(self, acct: dict):
        self.label = acct["label"]
        self.token_path = Path(acct["token_path"]).expanduser()
        self.credentials_path = Path(acct["credentials_path"]).expanduser()
        self.query = acct.get("query", "in:inbox -category:promotions -category:social")
        self._creds = None

    def creds(self):
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        if self._creds is None:
            tok = json.loads(self.token_path.read_text())
            cj = json.loads(self.credentials_path.read_text()); client = cj.get("installed") or cj.get("web")
            self._creds = Credentials(token=None, refresh_token=tok.get("refresh_token"), token_uri="https://oauth2.googleapis.com/token",
                                      client_id=client["client_id"], client_secret=client["client_secret"])
            self._creds.refresh(Request())
        if not self._creds.valid:
            self._creds.refresh(Request())
        return self._creds

    def _get(self, path, **params):
        r = requests.get(f"https://gmail.googleapis.com/gmail/v1/users/me/{path}", headers={"Authorization": f"Bearer {self.creds().token}"}, params=params, timeout=30)
        r.raise_for_status(); return r.json()

    def recent(self, since: datetime, limit=50) -> list[Mail]:
        q = f"{self.query} after:{int(since.timestamp())}"
        ids = self._get("messages", q=q, maxResults=limit).get("messages", []) or []
        out = []
        for m in ids:
            try:
                out.append(self._fetch(m["id"]))
            except Exception as e:
                log.warning("gmail %s fetch %s failed: %s", self.label, m["id"], e)
        return out

    def _fetch(self, mid: str) -> Mail:
        d = self._get(f"messages/{mid}", format="full")
        hdrs = {h["name"].lower(): h["value"] for h in d.get("payload", {}).get("headers", [])}
        body = self._body(d.get("payload", {})) or d.get("snippet", "")
        name, addr = parseaddr(hdrs.get("from", ""))
        received = datetime.fromtimestamp(int(d.get("internalDate", "0")) / 1000, tz=timezone.utc)
        labels = d.get("labelIds", [])
        return Mail(uid=f"{self.label}/{mid}", account=self.label, id=mid, thread_id=d.get("threadId", ""),
                    sender=hdrs.get("from", ""), sender_addr=addr.lower(), to=[a.strip() for a in hdrs.get("to", "").split(",") if a.strip()][:10],
                    subject=hdrs.get("subject", "(no subject)"), snippet=body[:700], received=received,
                    unread="UNREAD" in labels, labels=labels, has_unsubscribe="list-unsubscribe" in hdrs,
                    link=f"https://mail.google.com/mail/u/0/#inbox/{d.get('threadId','')}")

    def _body(self, p) -> str:
        if p.get("mimeType", "").startswith("text/plain") and p.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(p["body"]["data"] + "==").decode("utf-8", "ignore")
        for part in p.get("parts", []) or []:
            t = self._body(part)
            if t:
                return t
        if p.get("mimeType", "").startswith("text/html") and p.get("body", {}).get("data"):
            return _strip_html(base64.urlsafe_b64decode(p["body"]["data"] + "==").decode("utf-8", "ignore"))
        return ""


def gmail_authorize(label: str, credentials_path: str, token_out: str) -> str:
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, scopes=GMAIL_SCOPES + ["https://www.googleapis.com/auth/userinfo.email", "openid"])
    creds = flow.run_local_server(port=0, open_browser=False, prompt="consent", access_type="offline")
    p = Path(token_out).expanduser(); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"refresh_token": creds.refresh_token, "scope": " ".join(creds.scopes or [])}, indent=2)); p.chmod(0o600)
    return requests.get("https://www.googleapis.com/oauth2/v3/userinfo", headers={"Authorization": f"Bearer {creds.token}"}, timeout=20).json().get("email", "?")


# ---------------------------------------------------------------- Microsoft Graph
class GraphMailAccount:
    def __init__(self, acct: dict):
        self.label = acct["label"]
        self.cache_path = Path(acct["cache_path"]).expanduser()
        self.client_id = acct["client_id"]; self.authority = acct.get("authority")
        self.scopes = acct.get("scopes", MS_SCOPES); self.username = acct.get("username")
        self._app = None; self._cache = None

    def token(self) -> str:
        import msal
        if self._app is None:
            self._cache = msal.SerializableTokenCache()
            if self.cache_path.exists():
                self._cache.deserialize(self.cache_path.read_text())
            self._app = msal.PublicClientApplication(self.client_id, authority=self.authority, token_cache=self._cache)
        accts = self._app.get_accounts(username=self.username) or self._app.get_accounts()
        if not accts:
            raise RuntimeError(f"[{self.label}] no MS account in cache")
        r = self._app.acquire_token_silent_with_error(self.scopes, account=accts[0])
        if self._cache.has_state_changed:
            self.cache_path.write_text(self._cache.serialize()); self.cache_path.chmod(0o600)
        if not r or "access_token" not in r:
            raise RuntimeError(f"[{self.label}] token failed: {r}")
        return r["access_token"]

    def recent(self, since: datetime, limit=50) -> list[Mail]:
        params = {"$filter": f"receivedDateTime ge {since.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
                  "$orderby": "receivedDateTime desc", "$top": limit,
                  "$select": "id,conversationId,subject,from,toRecipients,receivedDateTime,isRead,bodyPreview,body,webLink,categories,inferenceClassification,internetMessageHeaders"}
        r = requests.get("https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages", headers={"Authorization": f"Bearer {self.token()}", "Prefer": 'outlook.body-content-type="text"'}, params=params, timeout=45)
        r.raise_for_status()
        out = []
        for m in r.json().get("value", []):
            fr = (m.get("from") or {}).get("emailAddress") or {}
            hdrs = {h["name"].lower(): h["value"] for h in (m.get("internetMessageHeaders") or [])}
            body = (m.get("body") or {}).get("content") or m.get("bodyPreview") or ""
            if (m.get("body") or {}).get("contentType") == "html":
                body = _strip_html(body)
            out.append(Mail(uid=f"{self.label}/{m['id']}", account=self.label, id=m["id"], thread_id=m.get("conversationId", ""),
                            sender=f"{fr.get('name','')} <{fr.get('address','')}>", sender_addr=(fr.get("address") or "").lower(),
                            to=[(x.get("emailAddress") or {}).get("address", "") for x in m.get("toRecipients", [])][:10],
                            subject=m.get("subject") or "(no subject)", snippet=re.sub(r"\s+", " ", body)[:700],
                            received=datetime.fromisoformat(m["receivedDateTime"].replace("Z", "+00:00")), unread=not m.get("isRead", False),
                            labels=(m.get("categories") or []) + [m.get("inferenceClassification", "")], has_unsubscribe="list-unsubscribe" in hdrs,
                            link=m.get("webLink", "")))
        return out


def build(acct: dict):
    return {"gmail": GmailAccount, "microsoft": GraphMailAccount}[acct["type"]](acct)
