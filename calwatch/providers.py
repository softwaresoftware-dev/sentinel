"""Calendar providers → normalized Event lists."""
from __future__ import annotations
import html, json, logging
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dateutil import parser as dtparse

from .model import Event

log = logging.getLogger("calwatch.providers")

GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
MS_SCOPES = ["Calendars.ReadWrite", "User.Read"]  # must match what the token was consented for


def _utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- Google
class GoogleAccount:
    def __init__(self, acct: dict, tz: str):
        self.label = acct["label"]
        self.tz = ZoneInfo(tz)
        self.token_path = Path(acct["token_path"]).expanduser()
        self.credentials_path = Path(acct["credentials_path"]).expanduser()
        self.include = acct.get("calendars", "all")     # "all" | [ids]
        self.exclude = set(acct.get("exclude_calendars", []))
        self.nonblocking = set(acct.get("nonblocking_calendars", []))
        self.include_shared = bool(acct.get("include_shared_people", False))
        self._creds = None

    def creds(self):
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        if self._creds is None:
            tok = json.loads(self.token_path.read_text())
            cj = json.loads(self.credentials_path.read_text())
            client = cj.get("installed") or cj.get("web")
            self._creds = Credentials(
                token=tok.get("access_token") or tok.get("token"),
                refresh_token=tok.get("refresh_token"),
                token_uri="https://oauth2.googleapis.com/token",
                client_id=client["client_id"],
                client_secret=client["client_secret"],
                scopes=(tok.get("scope") or "").split() or None,
            )
            self._creds.refresh(Request())  # stored access token may be stale; refresh sets a real expiry
        if not self._creds.valid:
            self._creds.refresh(Request())
        return self._creds

    def _get(self, url, **params):
        r = requests.get(url, headers={"Authorization": f"Bearer {self.creds().token}"}, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def calendars(self) -> list[dict]:
        items = self._get("https://www.googleapis.com/calendar/v3/users/me/calendarList").get("items", [])
        out = []
        for c in items:
            if c["id"] in self.exclude:
                continue
            if self.include != "all" and c["id"] not in self.include:
                continue
            if c.get("accessRole") == "freeBusyReader":
                continue
            # another person's calendar shared into this account (id is their email) — not my time
            cid = c["id"]
            is_person = "@" in cid and not cid.endswith("calendar.google.com") and not c.get("primary")
            if is_person and not self.include_shared and cid not in (self.include if isinstance(self.include, list) else []):
                continue
            out.append(c)
        return out

    def events(self, start: datetime, end: datetime) -> list[Event]:
        out = []
        for cal in self.calendars():
            page = None
            while True:
                data = self._get(
                    f"https://www.googleapis.com/calendar/v3/calendars/{requests.utils.quote(cal['id'], safe='')}/events",
                    timeMin=_utc(start).isoformat().replace("+00:00", "Z"),
                    timeMax=_utc(end).isoformat().replace("+00:00", "Z"),
                    singleEvents="true", orderBy="startTime", maxResults=250,
                    showDeleted="false", pageToken=page,
                )
                for e in data.get("items", []):
                    ev = self._norm(cal, e)
                    if ev:
                        out.append(ev)
                page = data.get("nextPageToken")
                if not page:
                    break
        return out

    def _norm(self, cal: dict, e: dict) -> Event | None:
        s, en = e.get("start", {}), e.get("end", {})
        all_day = "date" in s
        if all_day:
            st = datetime.combine(date.fromisoformat(s["date"]), datetime.min.time(), self.tz)
            et = datetime.combine(date.fromisoformat(en["date"]), datetime.min.time(), self.tz)
        else:
            st, et = dtparse.isoparse(s["dateTime"]), dtparse.isoparse(en["dateTime"])
        my = "organizer"
        for a in e.get("attendees", []):
            if a.get("self"):
                my = a.get("responseStatus", "needsAction")
        attendees = [a.get("email", "") for a in e.get("attendees", []) if not a.get("self")]
        online = ""
        cd = e.get("conferenceData", {})
        for ep in cd.get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                online = ep.get("uri", "")
        return Event(
            uid=f"{self.label}/{cal['id']}/{e['id']}", account=self.label,
            calendar=cal.get("summaryOverride") or cal.get("summary", cal["id"]), calendar_id=cal["id"], id=e["id"],
            title=html.unescape(e.get("summary") or "(no title)"), start=_utc(st), end=_utc(et), all_day=all_day,
            busy=e.get("transparency", "opaque") != "transparent" and not ({cal["id"], cal.get("summary")} & self.nonblocking),
            status=e.get("status", "confirmed"),
            my_response=my, location=e.get("location", ""), description=(e.get("description") or "")[:2000],
            attendees=attendees[:20], organizer=(e.get("organizer") or {}).get("email", ""),
            link=e.get("htmlLink", ""), online_meeting=online or e.get("hangoutLink", ""),
            updated=e.get("updated", ""), recurring=bool(e.get("recurringEventId")),
        )


def google_authorize(label: str, credentials_path: str, token_out: str) -> str:
    """Interactive loopback OAuth (needs a browser). Writes token JSON; returns the email."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, scopes=GOOGLE_SCOPES + ["https://www.googleapis.com/auth/userinfo.email", "openid"])
    creds = flow.run_local_server(port=0, open_browser=False, prompt="consent", access_type="offline")
    tok = {"token": creds.token, "refresh_token": creds.refresh_token, "scope": " ".join(creds.scopes or []),
           "token_uri": creds.token_uri, "client_id": creds.client_id, "client_secret": creds.client_secret}
    p = Path(token_out).expanduser(); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(tok, indent=2)); p.chmod(0o600)
    email = requests.get("https://www.googleapis.com/oauth2/v3/userinfo", headers={"Authorization": f"Bearer {creds.token}"}, timeout=20).json().get("email", "?")
    return email


# ---------------------------------------------------------------- Microsoft
class MicrosoftAccount:
    def __init__(self, acct: dict, tz: str):
        self.label = acct["label"]
        self.tz = ZoneInfo(tz)
        self.cache_path = Path(acct["cache_path"]).expanduser()
        self.client_id = acct["client_id"]
        self.authority = acct.get("authority", "https://login.microsoftonline.com/common")
        self.scopes = acct.get("scopes", MS_SCOPES)
        self.username = acct.get("username")
        self.include = acct.get("calendars", "all")
        self.exclude = set(acct.get("exclude_calendars", []))
        self.nonblocking = set(acct.get("nonblocking_calendars", []))
        self._app = None
        self._cache = None

    def app(self):
        import msal
        if self._app is None:
            self._cache = msal.SerializableTokenCache()
            if self.cache_path.exists():
                self._cache.deserialize(self.cache_path.read_text())
            self._app = msal.PublicClientApplication(self.client_id, authority=self.authority, token_cache=self._cache)
        return self._app

    def _persist(self):
        if self._cache is not None and self._cache.has_state_changed:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(self._cache.serialize())
            self.cache_path.chmod(0o600)

    def token(self) -> str:
        app = self.app()
        accts = app.get_accounts(username=self.username) or app.get_accounts()
        if not accts:
            raise RuntimeError(f"[{self.label}] no MS account in cache — run: calwatch auth ms {self.label}")
        r = app.acquire_token_silent_with_error(self.scopes, account=accts[0])
        self._persist()
        if not r or "access_token" not in r:
            raise RuntimeError(f"[{self.label}] MS token refresh failed: {r}")
        return r["access_token"]

    def _get(self, url, **params):
        r = requests.get(url, headers={"Authorization": f"Bearer {self.token()}", "Prefer": 'outlook.timezone="UTC"'}, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def calendars(self) -> list[dict]:
        cals = self._get("https://graph.microsoft.com/v1.0/me/calendars", **{"$top": 50}).get("value", [])
        out = []
        for c in cals:
            if c["id"] in self.exclude or c.get("name") in self.exclude:
                continue
            if self.include != "all" and c["id"] not in self.include and c.get("name") not in self.include:
                continue
            out.append(c)
        return out

    def events(self, start: datetime, end: datetime) -> list[Event]:
        out = []
        for cal in self.calendars():
            url = f"https://graph.microsoft.com/v1.0/me/calendars/{cal['id']}/calendarView"
            params = {"startDateTime": _utc(start).isoformat(), "endDateTime": _utc(end).isoformat(), "$top": 100,
                      "$select": "id,subject,start,end,isAllDay,showAs,isCancelled,responseStatus,location,bodyPreview,attendees,organizer,webLink,onlineMeeting,onlineMeetingUrl,lastModifiedDateTime,type,seriesMasterId"}
            while url:
                data = self._get(url, **params)
                params = {}
                for e in data.get("value", []):
                    out.append(self._norm(cal, e))
                url = data.get("@odata.nextLink")
        return out

    def _norm(self, cal: dict, e: dict) -> Event:
        st = dtparse.isoparse(e["start"]["dateTime"]).replace(tzinfo=timezone.utc)
        et = dtparse.isoparse(e["end"]["dateTime"]).replace(tzinfo=timezone.utc)
        if e.get("isAllDay"):
            # Graph gives all-day as UTC midnight of the date; re-anchor to local midnight
            st = datetime.combine(st.date(), datetime.min.time(), self.tz)
            et = datetime.combine(et.date(), datetime.min.time(), self.tz)
        show = (e.get("showAs") or "busy").lower()
        resp = ((e.get("responseStatus") or {}).get("response") or "none").lower()
        my = {"accepted": "accepted", "tentativelyaccepted": "tentative", "declined": "declined",
              "organizer": "organizer", "notresponded": "needsAction", "none": "organizer"}.get(resp, resp)
        status = "cancelled" if e.get("isCancelled") else ("tentative" if show == "tentative" else "confirmed")
        om = (e.get("onlineMeeting") or {}).get("joinUrl") or e.get("onlineMeetingUrl") or ""
        return Event(
            uid=f"{self.label}/{cal['id']}/{e['id']}", account=self.label,
            calendar=cal.get("name", "Calendar"), calendar_id=cal["id"], id=e["id"],
            title=html.unescape(e.get("subject") or "(no title)"), start=_utc(st), end=_utc(et), all_day=bool(e.get("isAllDay")),
            busy=show not in ("free", "workingelsewhere") and not ({cal["id"], cal.get("name")} & self.nonblocking),
            status=status, my_response=my,
            location=((e.get("location") or {}).get("displayName") or ""), description=(e.get("bodyPreview") or "")[:2000],
            attendees=[(a.get("emailAddress") or {}).get("address", "") for a in e.get("attendees", [])][:20],
            organizer=((e.get("organizer") or {}).get("emailAddress") or {}).get("address", ""),
            link=e.get("webLink", ""), online_meeting=om, updated=e.get("lastModifiedDateTime", ""),
            recurring=e.get("type") in ("occurrence", "exception"),
        )


def ms_authorize(acct: dict) -> str:
    """Device-code flow: prints a URL + code; returns username on success."""
    import msal
    cache = msal.SerializableTokenCache()
    p = Path(acct["cache_path"]).expanduser()
    if p.exists():
        cache.deserialize(p.read_text())
    app = msal.PublicClientApplication(acct["client_id"], authority=acct.get("authority", "https://login.microsoftonline.com/common"), token_cache=cache)
    flow = app.initiate_device_flow(scopes=acct.get("scopes", MS_SCOPES))
    if "user_code" not in flow:
        raise RuntimeError(f"device flow failed: {flow}")
    print(flow["message"], flush=True)
    r = app.acquire_token_by_device_flow(flow)
    if "access_token" not in r:
        raise RuntimeError(f"auth failed: {r.get('error_description') or r}")
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(cache.serialize()); p.chmod(0o600)
    return (r.get("id_token_claims") or {}).get("preferred_username", "?")


# ---------------------------------------------------------------- ICS feed (Outlook "publish calendar", Google secret address, any .ics URL)
class IcsAccount:
    def __init__(self, acct: dict, tz: str):
        self.label = acct["label"]
        self.tz = ZoneInfo(tz)
        self.url = acct["url"]
        self.name = acct.get("calendar_name", acct["label"])
        self.nonblocking = bool(acct.get("nonblocking", False))

    def events(self, start: datetime, end: datetime) -> list[Event]:
        import icalendar, recurring_ical_events
        r = requests.get(self.url, timeout=45, headers={"User-Agent": "calwatch/0.1"})
        r.raise_for_status()
        cal = icalendar.Calendar.from_ical(r.content)
        out = []
        for e in recurring_ical_events.of(cal).between(_utc(start), _utc(end)):
            ds, de = e.get("DTSTART").dt, (e.get("DTEND").dt if e.get("DTEND") else None)
            all_day = not isinstance(ds, datetime)
            if all_day:
                st = datetime.combine(ds, datetime.min.time(), self.tz)
                et = datetime.combine(de or (ds + timedelta(days=1)), datetime.min.time(), self.tz)
            else:
                st = ds if ds.tzinfo else ds.replace(tzinfo=self.tz)
                et = de if de is not None else st + timedelta(hours=1)
                et = et if et.tzinfo else et.replace(tzinfo=self.tz)
            uid = str(e.get("UID", "")) + "@" + _utc(st).isoformat()
            transp = str(e.get("TRANSP", "OPAQUE")).upper()
            busy = "TRANSPARENT" not in transp and str(e.get("X-MICROSOFT-CDO-BUSYSTATUS", "BUSY")).upper() not in ("FREE",) and not self.nonblocking
            status = str(e.get("STATUS", "CONFIRMED")).lower()
            out.append(Event(
                uid=f"{self.label}/ics/{uid}", account=self.label, calendar=self.name, calendar_id=self.url, id=uid,
                title=html.unescape(str(e.get("SUMMARY", "(no title)"))), start=_utc(st), end=_utc(et), all_day=all_day,
                busy=busy, status="cancelled" if status == "cancelled" else "tentative" if status == "tentative" else "confirmed",
                my_response="organizer", location=str(e.get("LOCATION", "") or ""), description=str(e.get("DESCRIPTION", "") or "")[:2000],
                attendees=[], organizer=str(e.get("ORGANIZER", "") or "").replace("mailto:", ""), link="",
                online_meeting=str(e.get("X-MICROSOFT-SKYPETEAMSMEETINGURL", "") or ""), updated=str(e.get("LAST-MODIFIED", "") or ""),
                recurring=bool(e.get("RRULE") or e.get("RECURRENCE-ID")),
            ))
        return out


def build(acct: dict, tz: str):
    t = acct["type"]
    if t == "google":
        return GoogleAccount(acct, tz)
    if t == "microsoft":
        return MicrosoftAccount(acct, tz)
    if t == "ics":
        return IcsAccount(acct, tz)
    raise ValueError(f"unknown account type {t}")
