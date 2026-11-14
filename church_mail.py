"""church_mail.py — every leader gets their own @churchdomain address.

Kevin, 2026-11-11: "I want to make sure chief knows how to get people there
email with the @domain name for each church. so that way the admin sor leader
etc will have there own email setup"; "prayer would go to the leader of
prayer so assign that to that role so once someone get the role, it goes with
it"; "do a setup for all roles to be done that way so if a person is removed
automatically the emails etc is as well". 2026-11-13: "can we build what is
needed so this can go live right away?" Plan: artifact WYc8oLMAerrqDkCBa5Dq2t.

Way A: the church's MX points at Resend receiving, so every message to
anyone@lovecityc.com reaches /email/inbound. This module sorts it by CHURCH
FIRST (the domain), then by address. Church mail never reaches another
business's contact match or the platform's Mission Control inbox.

    a box (church_mailboxes) .. one address and who it reaches:
        person  ........ a login (user_id) or one of the church's people
                         (contact_id, a leader without a login)
        role    ........ whoever holds a role on Leaders & roles (youth@)
        prayer  ........ the prayer list: a new care request, shared with the
                         prayer team, handed out by church_prayer like any
                         other (danger words stay with the pastor)
        office  ........ the logins it's shared with (share_with), else the
                         owner; one office box a church is the catch-all
        forward ........ an outside address (a forward brought over from
                         the church's old mail)

    who, every time ........ looked up live from the seat, the person's roles
                             and the role, never copied onto the box. A login
                             taken off the team or a leader out of every role:
                             their mail goes to the catch-all that moment. A
                             role nobody holds: the role it answers to.
    where it goes .......... into the Email room (church_mail_room), for
                             whoever the box reaches now, and a COPY at each
                             person's own email: sent from the box's address,
                             its Reply-To a relay that answers as the box,
                             marked with which box it came to. A person who
                             turned copies off (church_mail_people) reads it
                             in the room only. Prayer mail is never copied
                             or shown: its words stay on the prayer list.
    what's held ............ mail that fails its sender checks (no SPF or
                             DKIM pass, DMARC fail, the spam or virus verdict)
                             and our own copies looping back are kept, never
                             copied: a church's domain and the platform's
                             sending name are never spent on spam
    kept ................... every message, in church_mail, also when its box
                             is turned off (the history stays with the
                             address). Never shown to Chief.

A read that fails raises Unavailable, and /email/inbound answers 503 so
Resend retries: church mail waits rather than going to the wrong place.
"""
from __future__ import annotations

import asyncio
import html as _html
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

import httpx

import sb_clients

logger = logging.getLogger(__name__)

KINDS = ("person", "role", "prayer", "office", "forward")
LOCAL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,38}[a-z0-9])?$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
COPY_HEADER = "X-Solutionist-Copy"
MAX_ATTACH_BYTES = 25 * 1024 * 1024
MAX_PRAYER_CHARS = 4000
CACHE_SECONDS = 60.0
# Resend receiving's MX hosts (Email Setup shows the one for each domain).
RECEIVING_MX = ("inbound-smtp.", ".forge.rmta.net", "resend")

_BOX_SELECT = ("id,business_id,domain,local,kind,user_id,contact_id,role_key,share_with,forward_to,catch_all,"
               "status,told_at,created_at")


class Unavailable(Exception):
    """A read or write that decides where mail goes failed. Never 'nobody'."""


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rows(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise Unavailable(path.split("?")[0])
    return rows


def _plain(v: Any, n: int = 200) -> str:
    return " ".join("".join(ch for ch in str(v or "") if ch.isprintable()).split())[:n]


def platform_domain() -> str:
    return (os.environ.get("INBOUND_EMAIL_DOMAIN") or "").strip().lower()


def clean_local(v: Any) -> str:
    """'Tia', 'tia@lovecityc.com', ' TIA ' → 'tia'. '' when it can't be an address."""
    s = str(v or "").strip().lower()
    if "@" in s:
        s = s.split("@", 1)[0]
    s = s.strip(" .")
    return s if LOCAL_RE.match(s) else ""


def church_domain(biz: Dict[str, Any]) -> str:
    """The church's own sending domain once it's verified, else ''."""
    try:
        import email_sender
        cfg = email_sender.email_domain_settings((biz or {}).get("settings"))
    except Exception:
        return ""
    if cfg.get("status") != "verified":
        return ""
    return str(cfg.get("domain") or "").strip().lower().rstrip(".")


# ─── Which church a domain is ─────────────────────────────────────────

_DOMAIN_CACHE: Dict[str, Tuple[float, Optional[Dict[str, Any]]]] = {}
_BIZ_SELECT = "id,name,type,owner_id,settings"


def church_for_domain(domain: str) -> Optional[Dict[str, Any]]:
    """The business whose mail this domain is: the one with live boxes at
    it, else the one whose verified sending domain it is. None for the
    platform's own domain and for a domain nobody here owns. Raises
    Unavailable when it couldn't be read."""
    d = str(domain or "").strip().lower().rstrip(".")
    if not d or d == platform_domain():
        return None
    hit = _DOMAIN_CACHE.get(d)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    found: Optional[Dict[str, Any]] = None
    boxes = _rows(f"/church_mailboxes?domain=eq.{_q(d)}&status=eq.active&select=business_id&limit=1")
    if boxes:
        biz = _rows(f"/businesses?id=eq.{_q(boxes[0]['business_id'])}&select={_BIZ_SELECT}&limit=1")
        found = biz[0] if biz else None
    else:
        rows = _rows(f"/businesses?settings->email_domain->>domain=eq.{_q(d)}&select={_BIZ_SELECT}&limit=5")
        mine = [b for b in rows if church_domain(b) == d]
        found = mine[0] if len(mine) == 1 else None
        if len(mine) > 1:
            logger.warning("church mail: %d businesses verified %s; none chosen", len(mine), d)
    _DOMAIN_CACHE[d] = (time.monotonic(), found)
    return found


def forget_domain(domain: str) -> None:
    _DOMAIN_CACHE.pop(str(domain or "").strip().lower(), None)


# ─── Who a box reaches, right now ─────────────────────────────────────

class Church:
    """One church's reads for one message (or one Chief turn), each read once."""

    def __init__(self, biz: Dict[str, Any]):
        self.biz = biz
        self.id = str(biz["id"])
        self.owner_id = str(biz.get("owner_id") or "")
        self.domain = church_domain(biz)
        self._boxes: Optional[List[Dict[str, Any]]] = None
        self._roles: Optional[List[Dict[str, Any]]] = None
        self._defs: Optional[List[Dict[str, Any]]] = None
        self._seats: Optional[Dict[str, Dict[str, Any]]] = None
        self._emails: Dict[str, str] = {}
        self._copies_off: Optional[set] = None

    def boxes(self) -> List[Dict[str, Any]]:
        if self._boxes is None:
            self._boxes = _rows(f"/church_mailboxes?business_id=eq.{_q(self.id)}&status=eq.active"
                                f"&select={_BOX_SELECT}&order=created_at.asc&limit=500")
        return self._boxes

    def box(self, local: str) -> Optional[Dict[str, Any]]:
        return next((b for b in self.boxes() if b.get("local") == local), None)

    def catch_all(self) -> Optional[Dict[str, Any]]:
        return next((b for b in self.boxes() if b.get("catch_all")), None)

    def roles(self) -> List[Dict[str, Any]]:
        if self._roles is None:
            import church_follow_up as cfu
            got = cfu.roles(self.id)
            if got is None:
                raise Unavailable("church_leader_roles")
            self._roles = [r for r in got if r.get("status") == "active"]
        return self._roles

    def defs(self) -> List[Dict[str, Any]]:
        if self._defs is None:
            import church_roles as cr
            got = cr.defs(self.id)
            if got is None:
                raise Unavailable("church_role_defs")
            self._defs = got
        return self._defs

    def seats(self) -> Dict[str, Dict[str, Any]]:
        """Active office logins, by user id: {role, name, contact_id, invited_email}."""
        if self._seats is None:
            rows = _rows(f"/business_users?business_id=eq.{_q(self.id)}&status=eq.active"
                         "&select=user_id,role,name,contact_id,invited_email&limit=500")
            self._seats = {str(r["user_id"]): r for r in rows if r.get("user_id")}
        return self._seats

    def is_on_team(self, uid: str) -> bool:
        return bool(uid) and (uid == self.owner_id or uid in self.seats())

    def login_email(self, uid: str) -> str:
        """A login's sign-in email. Raises Unavailable when Auth can't be read."""
        if uid in self._emails:
            return self._emails[uid]
        import messaging_router
        got = messaging_router.owner_email_read(uid)
        if got is None:
            raise Unavailable("auth users")
        if not got:
            got = str((self.seats().get(uid) or {}).get("invited_email") or "").strip().lower()
        self._emails[uid] = got
        return got

    def login_name(self, uid: str) -> str:
        if uid == self.owner_id:
            settings = self.biz.get("settings") or {}
            return _plain(settings.get("practitioner_name")) or "the pastor"
        seat = self.seats().get(uid) or {}
        name = _plain(seat.get("name"))
        if not name and seat.get("contact_id"):
            name = self.contact_name(str(seat["contact_id"]))
        return name or "an office login"

    def contact(self, cid: str) -> Optional[Dict[str, Any]]:
        rows = _rows(f"/contacts?business_id=eq.{_q(self.id)}&id=eq.{_q(cid)}&select=id,name,email&limit=1")
        return rows[0] if rows else None

    def contact_name(self, cid: str) -> str:
        c = self.contact(cid)
        return _plain((c or {}).get("name")) if c else ""

    def role_title(self, key: str) -> str:
        import church_roles as cr
        try:
            return cr.title_of(key, self.defs())
        except Exception:
            return key.replace("_", " ")

    def holders(self, key: str) -> List[Dict[str, Any]]:
        return [h for h in self.roles() if h.get("role") == key]

    def owner_target(self, why: str) -> List[Dict[str, str]]:
        return [{"email": self.login_email(self.owner_id), "name": self.login_name(self.owner_id), "why": why,
                 "user_id": self.owner_id}]

    def uid_for_contact(self, cid: str, email: str = "") -> str:
        """The login that is this person, if any: the seat tied to them, else
        the login whose email is theirs. '' when they have no login."""
        if cid:
            for uid, s in self.seats().items():
                if str(s.get("contact_id") or "") == str(cid):
                    return uid
        email = (email or "").strip().lower()
        if not email:
            return ""
        for uid, s in self.seats().items():
            if str(s.get("invited_email") or "").strip().lower() == email:
                return uid
        try:
            if self.owner_id and self.login_email(self.owner_id) == email:
                return self.owner_id
        except Unavailable:
            pass
        return ""

    def copies_off(self) -> set:
        """The logins that read their church mail in the Email room only (no
        copy at their own email). A read that fails is nobody: a copy too
        many, never mail that reaches no one."""
        if self._copies_off is None:
            rows = sb_clients.sb_get_as_service(f"/church_mail_people?business_id=eq.{_q(self.id)}"
                                                "&copies=eq.false&select=user_id&limit=500")
            self._copies_off = {str(r["user_id"]) for r in rows if r.get("user_id")} if isinstance(rows, list) else set()
        return self._copies_off


def _first(name: str) -> str:
    return (name.split(" ")[0] if name else "") or name


def reach(church: Church, box: Optional[Dict[str, Any]], *, _depth: int = 0) -> Dict[str, Any]:
    """Where mail to this box goes now: {"prayer": bool, "to": [{email, name,
    why}], "path": plain words}. `box` None is an address with no box (the
    catch-all's). Never empty unless the owner has no email."""
    if box is None:
        ca = church.catch_all()
        if ca and _depth == 0:
            got = reach(church, ca, _depth=1)
            return {**got, "path": "no box of its own, so the office box: " + got["path"]}
        return {"prayer": False, "to": church.owner_target("no box, so the pastor"),
                "path": "no box of its own, so the pastor"}
    kind = box.get("kind")
    if kind == "prayer":
        return {"prayer": True, "to": [], "path": "the prayer list"}
    if kind == "forward":
        return {"prayer": False, "path": "an outside address",
                "to": [{"email": str(box.get("forward_to") or "").lower(), "name": "", "why": "forwarded"}]}
    if kind == "person":
        uid, cid = str(box.get("user_id") or ""), str(box.get("contact_id") or "")
        if uid and church.is_on_team(uid):
            name = church.login_name(uid)
            return {"prayer": False, "path": f"{name}'s own box",
                    "to": [{"email": church.login_email(uid), "name": name, "why": "their own box", "user_id": uid}]}
        if cid and not uid:
            leads = [h for h in church.roles() if h.get("contact_id") == cid]
            seat = next((s for s in church.seats().values() if str(s.get("contact_id") or "") == cid), None)
            c = church.contact(cid) if (leads or seat) else None
            email = str((c or {}).get("email") or "").strip().lower()
            if not email and seat:
                email = church.login_email(str(seat["user_id"]))
            if c and email:
                name = _plain(c.get("name"))
                return {"prayer": False, "path": f"{name}'s own box",
                        "to": [{"email": email, "name": name, "why": "their own box",
                                "user_id": str(seat["user_id"]) if seat else church.uid_for_contact(cid, email)}]}
        return _to_office(church, box, "the person it was for isn't on the team now", _depth)
    if kind == "role":
        key = str(box.get("role_key") or "")
        title = church.role_title(key)
        people = church.holders(key)
        if people:
            return {"prayer": False, "path": f"the {title} ({', '.join(_plain(h.get('name')) for h in people)})",
                    "to": [{"email": str(h.get("email") or "").lower(), "name": _plain(h.get("name")),
                            "why": f"holds {title}",
                            "user_id": church.uid_for_contact(str(h.get("contact_id") or ""), str(h.get("email") or ""))}
                           for h in people if h.get("email")]}
        import church_roles as cr
        d = cr.by_key(church.defs()).get(key)
        for up, ups in cr.chain_above(d, church.defs(), cr.active_holders(church.roles())) if d else []:
            got = [{"email": str(h.get("email") or "").lower(), "name": _plain(h.get("name")),
                    "why": f"nobody holds {title}, so {up['title']}",
                    "user_id": church.uid_for_contact(str(h.get("contact_id") or ""), str(h.get("email") or ""))}
                   for h in ups if h.get("email")]
            if got:
                return {"prayer": False, "to": got,
                        "path": f"nobody holds {title}, so who it answers to: the {up['title']}"}
        return {"prayer": False, "to": church.owner_target(f"nobody holds {title}"),
                "path": f"nobody holds {title}, so the pastor"}
    if kind == "office":
        shared = [str(u) for u in (box.get("share_with") or []) if church.is_on_team(str(u))]
        if shared:
            names = [church.login_name(u) for u in shared]
            return {"prayer": False, "path": "the office: " + ", ".join(names),
                    "to": [{"email": church.login_email(u), "name": n, "why": "shares the office box", "user_id": u}
                           for u, n in zip(shared, names)]}
        return {"prayer": False, "to": church.owner_target("the office box"), "path": "the office (the pastor)"}
    return _to_office(church, box, "it has no one", _depth)


def _to_office(church: Church, box: Dict[str, Any], why: str, depth: int) -> Dict[str, Any]:
    ca = church.catch_all()
    if ca and depth == 0 and ca.get("id") != box.get("id"):
        got = reach(church, ca, _depth=1)
        return {**got, "path": f"{why}, so the office box: {got['path']}"}
    return {"prayer": False, "to": church.owner_target(why), "path": f"{why}, so the pastor"}


def _ours(email: str) -> bool:
    """An address whose mail comes back here: a copy sent to it would loop."""
    dom = email.rsplit("@", 1)[-1].lower() if "@" in email else ""
    if not dom:
        return True
    if dom == platform_domain():
        return True
    try:
        return church_for_domain(dom) is not None
    except Unavailable:
        return True


# ─── Mail coming in ───────────────────────────────────────────────────

def _addresses(val: Any) -> List[str]:
    out: List[str] = []
    for item in val if isinstance(val, list) else ([val] if val else []):
        s = (item.get("email") or item.get("address")) if isinstance(item, dict) else item
        for part in str(s or "").split(","):
            p = part.strip()
            if "<" in p and ">" in p:
                p = p.split("<", 1)[1].split(">", 1)[0]
            p = p.strip().strip('"').lower()
            if EMAIL_RE.match(p) and p not in out:
                out.append(p)
    return out


def recipients(payload: Dict[str, Any]) -> List[str]:
    """Every address a message was for: To, Cc, Bcc and the envelope's
    (received_for), so a Bcc'd box still gets it."""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    out: List[str] = []
    for k in ("to", "cc", "bcc", "received_for"):
        for a in _addresses(data.get(k)):
            if a not in out:
                out.append(a)
    return out


_LIVE_CACHE: Dict[str, Tuple[float, bool]] = {}


def mail_comes_here(domain: str) -> bool:
    """Does mail to this domain come to us (its MX is the mail service's
    receiving)? A church's address that is only named on a message, a Cc
    on mail to someone here, is not ours to deliver: its own mail service
    already did. Raises Unavailable when it can't be looked up."""
    d = str(domain or "").strip().lower()
    hit = _LIVE_CACHE.get(d)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    live = receiving_live(d)
    if live is None:
        raise Unavailable("mx lookup")
    _LIVE_CACHE[d] = (time.monotonic(), bool(live))
    return bool(live)


def church_recipients(addrs: Iterable[str]) -> List[Tuple[Dict[str, Any], str, str]]:
    """[(church, local, address)] for the addresses at a church's domain
    whose mail comes here."""
    out = []
    for a in addrs:
        local, _, dom = a.partition("@")
        biz = church_for_domain(dom)
        if biz and mail_comes_here(dom):
            out.append((biz, local, a))
    return out


async def _send_refusal(business_id: Any, to: Any) -> Optional[str]:
    """Why a copy or a reply must not go (sample_church.py, BE-3): the church
    is a sample, or the address is at a domain reserved for examples. None
    when it may."""
    import sample_church
    try:
        await sample_church.refuse_send_async("email", business_id, email=to)
    except sample_church.SendRefused as e:
        return e.why
    return None


async def _resend(client: httpx.AsyncClient, method: str, path: str, **kw) -> Optional[Dict[str, Any]]:
    if method.upper() == "POST" and path.split("?")[0].rstrip("/") == "/emails":
        # The last wall before a send: never to a reserved address
        # (sample_church.py). The callers check the church itself.
        import sample_church
        to = (kw.get("json") or {}).get("to")
        if sample_church.send_refusal(None, email=to):
            logger.info("church mail: a send to a reserved address was refused")
            return None
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        raise Unavailable("RESEND_API_KEY")
    try:
        r = await client.request(method, f"https://api.resend.com{path}", timeout=30.0,
                                 headers={"Authorization": f"Bearer {key}", **kw.pop("headers", {})}, **kw)
    except httpx.HTTPError as e:
        raise Unavailable(f"resend {path.split('/')[1]}: {type(e).__name__}")
    if r.status_code >= 500 or r.status_code == 429:
        raise Unavailable(f"resend {r.status_code}")
    if r.status_code >= 400:
        logger.warning("church mail: resend %s %s -> %s %s", method, path.split("?")[0][:60], r.status_code, r.text[:200])
        return None
    try:
        return r.json()
    except ValueError:
        return {}


async def fetch_received(client: httpx.AsyncClient, email_id: str) -> Dict[str, Any]:
    """The whole message (headers, text, html, authentication, attachments
    with download links). Raises Unavailable when it can't be fetched."""
    msg = await _resend(client, "GET", f"/emails/receiving/{_q(email_id)}")
    if msg is None:
        raise Unavailable("received email")
    atts: List[Dict[str, Any]] = []
    if msg.get("attachments"):
        listed = await _resend(client, "GET", f"/emails/receiving/{_q(email_id)}/attachments")
        atts = list((listed or {}).get("data") or [])
    msg["attachment_links"] = atts
    return msg


def _header(msg: Dict[str, Any], name: str) -> str:
    h = msg.get("headers") or {}
    if isinstance(h, dict):
        for k, v in h.items():
            if str(k).lower() == name.lower():
                return str(v[0] if isinstance(v, list) and v else v or "")
    elif isinstance(h, list):
        for item in h:
            if isinstance(item, dict) and str(item.get("name") or "").lower() == name.lower():
                return str(item.get("value") or "")
    return ""


def held_because(msg: Dict[str, Any]) -> Optional[str]:
    """Why a message is kept but never copied, or None to copy it."""
    if _header(msg, COPY_HEADER):
        return "one of our own copies came back"
    for h in ("x-ses-virus-verdict", "x-ses-spam-verdict"):
        if _header(msg, h).strip().upper() == "FAIL":
            return "the mail service marked it as spam or a virus"
    if _header(msg, "x-spam-flag").strip().upper() == "YES":
        return "the mail service marked it as spam"
    auth = msg.get("authentication")
    if isinstance(auth, dict) and auth:
        val = {k: str(auth.get(k) or "").lower() for k in ("spf", "dkim", "dmarc")}
        if val["dmarc"] == "fail":
            return "the sender's domain says it didn't send it"
        if val["spf"] != "pass" and val["dkim"] != "pass":
            return "its sender couldn't be checked"
    return None


def sender_name(msg: Dict[str, Any], fallback: str = "") -> str:
    raw = _header(msg, "from") or str(msg.get("from") or "")
    if "<" in raw:
        name = raw.split("<", 1)[0].strip().strip('"').strip()
        if name:
            return _plain(name, 120)
    return _plain(fallback, 120)


def _strip_html(s: str) -> str:
    s = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", s or "", flags=re.I)
    s = re.sub(r"<br\s*/?>|</p>|</div>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return _html.unescape(s).strip()


def _claim(church: Church, box: Optional[Dict[str, Any]], address: str, email_id: str, msg: Dict[str, Any],
           from_email: str, from_name: str) -> Optional[Dict[str, Any]]:
    """Write the message's row first. None when it's already here (Resend
    sent the webhook twice); raises Unavailable when it couldn't be saved."""
    have = _rows(f"/church_mail?email_id=eq.{_q(email_id)}&to_address=eq.{_q(address)}&select=id&limit=1")
    if have:
        return None
    text = str(msg.get("text") or "")
    html_body = str(msg.get("html") or "")
    row = {
        "business_id": church.id, "mailbox_id": (box or {}).get("id"), "to_address": address,
        "from_email": from_email[:254], "from_name": from_name[:200] or None,
        "subject": _plain(msg.get("subject"), 1000) or None,
        "body_text": (text or _strip_html(html_body))[:100000] or None,
        "body_html": html_body[:1000000] or None,
        "attachments": [{"filename": _plain(a.get("filename"), 200), "size": a.get("size"),
                         "content_type": _plain(a.get("content_type"), 100)}
                        for a in (msg.get("attachment_links") or msg.get("attachments") or [])],
        "email_id": email_id, "message_id": _plain(msg.get("message_id"), 1000) or None,
        "outcome": "stored", "received_at": _now_iso(),
    }
    out = sb_clients.sb_post_as_service("/church_mail", row)
    if isinstance(out, list) and out:
        return out[0]
    if _rows(f"/church_mail?email_id=eq.{_q(email_id)}&to_address=eq.{_q(address)}&select=id&limit=1"):
        return None
    raise Unavailable("church_mail write")


def _settle(row: Dict[str, Any], outcome: str, why: str, delivered: List[Dict[str, Any]]) -> None:
    out = sb_clients.sb_patch_as_service(f"/church_mail?id=eq.{_q(row['id'])}",
                                         {"outcome": outcome, "why": why[:300] or None, "delivered": delivered})
    if not isinstance(out, list):
        logger.warning("church mail: couldn't record where message %s went", str(row["id"])[:8])


def to_prayer_list(church: Church, address: str, email_id: str, msg: Dict[str, Any],
                   from_email: str, from_name: str) -> Dict[str, Any]:
    """Mail to prayer@ joins the prayer list as a request the person shared
    with the prayer team (they wrote to it), handed out like every other.
    Words about danger stay with the pastor (consent_columns)."""
    have = _rows(f"/ministry_care_requests?business_id=eq.{_q(church.id)}"
                 f"&submission->>email_id=eq.{_q(email_id)}&select=id,needs_pastor&limit=1")
    if have:
        return {"id": str(have[0]["id"]), "needs_pastor": bool(have[0].get("needs_pastor")), "already": True}
    import business_users_router
    import church_prayer
    person = business_users_router.match_contact(church.id, from_email, from_name)
    subject = _plain(msg.get("subject"), 300)
    body = str(msg.get("text") or "") or _strip_html(str(msg.get("html") or ""))
    try:
        import email_sender
        body = email_sender._strip_quoted_reply(body)
    except Exception:
        pass
    words = (f"{subject}\n\n{body}" if subject else body).strip()[:MAX_PRAYER_CHARS]
    submission = {"name": from_name, "email": from_email, "prayer_request": words, "confidential": "no",
                  "source": "Email", "email_id": email_id, "to": address}
    rows = sb_clients.sb_post_as_service("/ministry_care_requests", {
        "business_id": church.id, "form_id": None, "contact_id": (person or {}).get("id"), "status": "new",
        "submission": submission, **church_prayer.consent_columns(submission, share=True),
    })
    if not isinstance(rows, list) or not rows:
        raise Unavailable("ministry_care_requests write")
    church_prayer.on_new(church.id, rows[0])
    return {"id": str(rows[0]["id"]), "needs_pastor": bool(rows[0].get("needs_pastor")), "already": False}


def _copy_attachments(links: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """Resend attachments from the received links, largest dropped first
    past the size cap. (attachments, how many were too big)."""
    usable = [a for a in links if a.get("download_url") and a.get("filename")]
    usable.sort(key=lambda a: int(a.get("size") or 0))
    out, total, dropped = [], 0, 0
    for a in usable:
        size = int(a.get("size") or 0)
        if total + size > MAX_ATTACH_BYTES:
            dropped += 1
            continue
        total += size
        item = {"filename": _plain(a["filename"], 200), "path": a["download_url"]}
        if a.get("content_type"):
            item["content_type"] = a["content_type"]
        if a.get("content_id") and str(a.get("content_disposition") or "").lower() == "inline":
            item["content_id"] = str(a["content_id"]).strip("<>")
        out.append(item)
    return out, dropped + (len(links) - len(usable))


def _banner(address: str, from_name: str, from_email: str, dropped: int, relayed: bool = False) -> Tuple[str, str]:
    who = f"{from_name} <{from_email}>" if from_name else from_email
    reply = _first(from_name) or from_email
    extra = ""
    if dropped:
        extra = (f" {dropped} attachments too large to copy are" if dropped != 1
                 else " 1 attachment too large to copy is") + " kept in the system."
    as_box = f" from {address}" if relayed else ""
    text = f"Sent to {address} by {who}. Reply and it goes to {reply}{as_box}.{extra}"
    h = ('<div style="font:13px/1.45 -apple-system,Segoe UI,Arial,sans-serif;color:#555;border-bottom:1px solid '
         f'#ddd;padding:0 0 8px;margin:0 0 12px">{_html.escape(text)}</div>')
    return text, h


# ─── Replying as the box ─────────────────────────────────────────────
#
# A copy's Reply-To is a one-message relay address at the church's own
# domain: r<the message's id><a signature over the id and the person the
# copy went to>@domain. Their reply from their own email comes back here and
# goes on to the sender FROM THE BOX'S ADDRESS, threaded on the original.
# Only from that person (the From the copy went to, proved by DMARC), only
# that message, only to its sender: a leaked relay address can't send as the
# church to anyone else, and one without a valid signature does nothing.

RELAY_RE = re.compile(r"^r([0-9a-f]{32})([a-z2-7]{16})$")


def _relay_secret() -> str:
    return (os.environ.get("CHURCH_MAIL_SECRET") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()


def _relay_sig(row_id: str, email: str) -> str:
    import base64
    import hashlib
    import hmac
    sec = _relay_secret()
    if not sec:
        return ""
    d = hmac.new(sec.encode(), f"church-mail-relay|{row_id}|{(email or '').strip().lower()}".encode(),
                 hashlib.sha256).digest()
    return base64.b32encode(d).decode().lower()[:16]


def relay_address(row_id: Any, email: str, domain: str) -> Optional[str]:
    sig = _relay_sig(str(row_id), email)
    hexid = str(row_id or "").replace("-", "").lower()
    if not sig or not domain or not re.fullmatch(r"[0-9a-f]{32}", hexid):
        return None
    return f"r{hexid}{sig}@{domain}"


def _relay_find(church: Church, hexid: str, sig: str) -> Optional[Tuple[Dict[str, Any], str]]:
    """(the original message's row, the person whose copy this relay was)."""
    rid = f"{hexid[:8]}-{hexid[8:12]}-{hexid[12:16]}-{hexid[16:20]}-{hexid[20:]}"
    rows = _rows(f"/church_mail?id=eq.{_q(rid)}&business_id=eq.{_q(church.id)}"
                 "&select=id,mailbox_id,to_address,from_email,from_name,subject,message_id,delivered&limit=1")
    if not rows:
        return None
    import hmac
    for d in rows[0].get("delivered") or []:
        email = str((d or {}).get("email") or "").lower()
        if email and hmac.compare_digest(_relay_sig(rid, email), sig):
            return rows[0], email
    return None


def _relay_refusal(msg: Dict[str, Any], from_email: str, holder: str) -> Optional[str]:
    if (from_email or "").lower() != holder:
        return "it didn't come from the person the copy went to"
    auth = msg.get("authentication") if isinstance(msg.get("authentication"), dict) else {}
    if str(auth.get("dmarc") or "").lower() != "pass":
        return "their email provider couldn't prove it was them"
    return None


async def relay_reply(client: httpx.AsyncClient, church: Church, address: str, hexid: str, sig: str,
                      email_id: str, msg: Dict[str, Any], held: Optional[str]) -> Dict[str, Any]:
    """A person's reply to a copy goes to the sender from the box's address."""
    import email_sender
    from_email = (_addresses(msg.get("from")) or [""])[0]
    row = await asyncio.to_thread(_claim, church, None, address, email_id, msg, from_email, sender_name(msg))
    if row is None:
        return {"address": address, "outcome": "already"}
    found = await asyncio.to_thread(_relay_find, church, hexid, sig)
    if not found:
        await asyncio.to_thread(_settle, row, "held", "a reply address that matches nothing sent", [])
        return {"address": address, "outcome": "held"}
    orig, holder = found
    auto = _header(msg, "auto-submitted").strip().lower()
    if auto and auto != "no":
        # An out-of-office answering a copy never goes on as the church: two
        # responders would answer each other.
        await asyncio.to_thread(_settle, row, "held", "an automatic reply, not sent on", [])
        return {"address": address, "outcome": "held", "why": "automatic reply"}
    why = held or _relay_refusal(msg, from_email, holder)
    box_addr = str(orig.get("to_address") or "").lower()
    to = str(orig.get("from_email") or "").lower()
    if not why and (not EMAIL_RE.match(to) or to == holder):
        why = "there's no one to send it to"
    if not why:
        why = await _send_refusal(church.id, to)
    if why:
        await asyncio.to_thread(_settle, row, "held", f"reply not sent as {box_addr}: {why}", [])
        if not held and from_email.lower() == holder:
            await _tell_relay_failed(church, holder, box_addr, to, why)
        return {"address": address, "outcome": "held", "why": why}
    name = next((str(d.get("name") or "") for d in orig.get("delivered") or []
                 if str((d or {}).get("email") or "").lower() == holder), "")
    church_name = _plain(church.biz.get("name"), 80) or ""
    sender = box_addr if church.domain and box_addr.endswith("@" + church.domain) else email_sender.DEFAULT_FROM_EMAIL
    subject = _plain(msg.get("subject"), 900) or ("Re: " + _plain(orig.get("subject"), 880)).strip()
    atts, _dropped = _copy_attachments(msg.get("attachment_links") or [])
    headers: Dict[str, str] = {}
    if orig.get("message_id"):
        headers = {"In-Reply-To": orig["message_id"], "References": orig["message_id"]}
    payload: Dict[str, Any] = {
        "from": email_sender._format_address(sender, name or church_name or None),
        "to": [to], "reply_to": [box_addr], "subject": subject,
        "text": str(msg.get("text") or "") or _strip_html(str(msg.get("html") or "")),
    }
    if msg.get("html"):
        payload["html"] = str(msg["html"])
    if headers:
        payload["headers"] = headers
    if atts:
        payload["attachments"] = atts
    out = await _resend(client, "POST", "/emails", json=payload,
                        headers={"Idempotency-Key": f"church-relay-{email_id}"[:256]})
    if out is None:
        await asyncio.to_thread(_settle, row, "failed", f"reply as {box_addr} refused by the mail service", [])
        await _tell_relay_failed(church, holder, box_addr, to, "the mail service refused it")
        return {"address": address, "outcome": "failed"}
    await asyncio.to_thread(_settle, row, "copied", f"reply sent as {box_addr}",
                            [{"email": to, "name": _plain(orig.get("from_name")), "why": f"the reply, as {box_addr}"}])
    await asyncio.to_thread(_answered, church, orig, row, name or holder)
    return {"address": address, "outcome": "replied"}


def _answered(church: Church, orig: Dict[str, Any], row: Dict[str, Any], who: str) -> None:
    """A reply from someone's own email shows in the Email room: the message
    is marked answered (so nobody on a shared box answers it twice) and the
    reply sits in the box's Sent. Best effort: the reply already went."""
    now = _now_iso()
    a = sb_clients.sb_patch_as_service(f"/church_mail?id=eq.{_q(orig['id'])}&business_id=eq.{_q(church.id)}",
                                       {"answered_at": now, "answered_name": _plain(who, 200) or None})
    b = sb_clients.sb_patch_as_service(f"/church_mail?id=eq.{_q(row['id'])}&business_id=eq.{_q(church.id)}",
                                       {"direction": "out", "mailbox_id": orig.get("mailbox_id"),
                                        "from_name": _plain(who, 200) or None})
    if not isinstance(a, list) or not isinstance(b, list):
        logger.warning("church mail: a reply by email wasn't marked in the Email room")


async def _tell_relay_failed(church: Church, holder: str, box_addr: str, to: str, why: str) -> None:
    """The person whose reply didn't go out hears so, with who to write."""
    import email_sender
    church_name = _plain(church.biz.get("name"), 80) or "your church"
    body = (f"Your reply couldn't go out from {box_addr} because {why}.\n\n"
            f"It hasn't been sent. You can write to {to} directly from your own email.\n\n{church_name}")
    try:
        await email_sender.send_via_resend(
            to_email=holder, to_name=None, from_email=email_sender.DEFAULT_FROM_EMAIL, from_name=church_name,
            subject=f"Your reply from {box_addr} wasn't sent", body=body, reply_to=None, business_id=church.id)
    except Exception as e:
        logger.warning("church mail: couldn't tell a person their reply failed: %s", type(e).__name__)


async def send_copy(client: httpx.AsyncClient, church: Church, address: str, target: Dict[str, str],
                    msg: Dict[str, Any], from_email: str, from_name: str, email_id: str,
                    row_id: Optional[str] = None) -> Optional[str]:
    """A copy of the message at the person's own email. None when sent,
    else why not. Never carries the platform's unsubscribe (it's their
    mail, not a mailing). Its Reply-To is the relay address, so their
    reply goes out from the box; with no relay, the sender."""
    import email_sender
    to = target["email"]
    if not EMAIL_RE.match(to or ""):
        return "no email on record"
    if _ours(to):
        return "their email is at the church's own domain"
    refused = await _send_refusal(church.id, to)
    if refused:
        return refused
    try:
        if await email_sender.is_suppressed(to):
            return "their email bounced before"
    except Exception:
        pass
    atts, dropped = _copy_attachments(msg.get("attachment_links") or [])
    on_domain = bool(church.domain) and address.endswith("@" + church.domain)
    relay = relay_address(row_id, to, church.domain) if row_id and on_domain else None
    banner_text, banner_html = _banner(address, from_name, from_email, dropped, relayed=bool(relay))
    sender = address if on_domain else email_sender.DEFAULT_FROM_EMAIL
    reply_to = [relay] if relay else (_addresses(msg.get("reply_to")) or [from_email])
    church_name = _plain(church.biz.get("name"), 80) or "your church"
    payload: Dict[str, Any] = {
        "from": email_sender._format_address(sender, f"{from_name or from_email} via {church_name}"),
        "to": [email_sender._format_address(to, target.get("name") or None)],
        "subject": _plain(msg.get("subject"), 900) or "(no subject)",
        "reply_to": reply_to[:5],
        "text": banner_text + "\n\n" + (str(msg.get("text") or "") or _strip_html(str(msg.get("html") or ""))),
        "headers": {COPY_HEADER: address},
    }
    if msg.get("html"):
        payload["html"] = banner_html + str(msg["html"])
    if atts:
        payload["attachments"] = atts
    out = await _resend(client, "POST", "/emails", json=payload,
                        headers={"Idempotency-Key": f"church-copy-{email_id}-{address}-{to}"[:256]})
    return None if out is not None else "the mail service refused the copy"


async def deliver(client: httpx.AsyncClient, biz: Dict[str, Any], local: str, address: str, email_id: str,
                  msg: Dict[str, Any], held: Optional[str]) -> Dict[str, Any]:
    """One church address on one message: claim it, then copy it, put it on
    the prayer list, or hold it."""
    church = Church(biz)
    relay = RELAY_RE.match(local)
    if relay:
        return await relay_reply(client, church, address, relay.group(1), relay.group(2), email_id, msg, held)
    box = await asyncio.to_thread(church.box, local)
    from_email = (_addresses(msg.get("from")) or [""])[0]
    from_name = sender_name(msg)
    row = await asyncio.to_thread(_claim, church, box, address, email_id, msg, from_email, from_name)
    if row is None:
        return {"address": address, "outcome": "already"}
    if held:
        await asyncio.to_thread(_settle, row, "held", held, [])
        return {"address": address, "outcome": "held", "why": held}
    where = await asyncio.to_thread(reach, church, box)
    if where["prayer"]:
        got = await asyncio.to_thread(to_prayer_list, church, address, email_id, msg, from_email, from_name)
        why = "words about danger: with the pastor only" if got["needs_pastor"] else "on the prayer list"
        await asyncio.to_thread(_settle, row, "prayer", why, [{"care_request_id": got["id"]}])
        return {"address": address, "outcome": "prayer"}
    delivered, failed, skipped = [], [], []
    seen = set()
    # An out-of-office reply to a copy comes back to the box it came from:
    # never copy a person's own automatic reply back to them.
    auto_reply = _header(msg, "auto-submitted").strip().lower().startswith("auto-replied")
    room_only = await asyncio.to_thread(church.copies_off) if any(t.get("user_id") for t in where["to"]) else set()
    for t in where["to"]:
        if not t.get("email") or t["email"] in seen:
            continue
        seen.add(t["email"])
        if auto_reply and t["email"] == from_email:
            skipped.append({"email": t["email"], "name": t.get("name") or "", "why": "their own automatic reply"})
            continue
        if t.get("user_id") and str(t["user_id"]) in room_only:
            # They read church mail in the Email room only (Kevin, 2026-11-13,
            # the approved Email room: "Copies to your own email" is theirs).
            skipped.append({"email": t["email"], "name": t.get("name") or "", "why": "reads it in the Email room"})
            continue
        why_not = await send_copy(client, church, address, t, msg, from_email, from_name, email_id,
                                  row_id=str(row["id"]))
        (failed if why_not else delivered).append({"email": t["email"], "name": t.get("name") or "",
                                                   "why": why_not or t.get("why") or ""})
    outcome = "copied" if delivered else ("failed" if failed else "stored")
    await asyncio.to_thread(_settle, row, outcome, where["path"], delivered + failed + skipped)
    _alert_soon(church, str(row["id"]))
    return {"address": address, "outcome": outcome, "copies": len(delivered), "failed": len(failed)}


def _alert_soon(church: "Church", row_id: str) -> None:
    """Tell whoever the box reaches that mail came (church_mail_alerts), off
    the webhook's back: Resend gets its answer at once, and the worker's
    sweep sends anything this misses."""
    def run() -> None:
        try:
            import church_mail_alerts
            church_mail_alerts.on_new(church, row_id)
        except Exception as e:  # noqa: BLE001 — the mail is in Email either way
            logger.warning("church mail: alert for %s not sent now: %s", row_id[:8], e)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        run()  # in tests, in step, so what it does can be checked
        return
    import threading
    threading.Thread(target=run, name="church-mail-alert", daemon=True).start()


async def handle_inbound(client: httpx.AsyncClient, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """/email/inbound's first step. None when no recipient is at a church's
    domain (the platform's own sorting carries on as before). Else
    {"status", "results", "church"}: `church` is the church addresses it
    handled, which the platform's sorting must leave alone. Raises
    Unavailable."""
    addrs = recipients(payload)
    found = await asyncio.to_thread(church_recipients, addrs)
    if not found:
        return None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    email_id = str(data.get("email_id") or data.get("id") or "")
    if not email_id:
        logger.warning("church mail: a message for %d church address(es) had no id", len(found))
        return {"status": "church_mail", "results": [], "church": [f[2] for f in found]}
    msg = await fetch_received(client, email_id)
    if not msg.get("from"):
        msg["from"] = data.get("from")
    held = held_because(msg)
    results = []
    for biz, local, address in found:
        results.append(await deliver(client, biz, local, address, email_id, msg, held))
    logger.info("church mail: %s", ", ".join(f"{r['address'].split('@')[0]}@…={r['outcome']}" for r in results))
    return {"status": "church_mail", "results": results, "church": [f[2] for f in found]}


# ─── Is mail switched on? ─────────────────────────────────────────────

def receiving_live(domain: str) -> Optional[bool]:
    """True when the domain's MX points at the mail service's receiving,
    False when it points elsewhere, None when it couldn't be looked up."""
    if not domain:
        return False
    try:
        import email_domain_dns
        mx = email_domain_dns._mx_sync(domain, strict=True)
    except Exception:
        return None
    hosts = [h.lower() for _p, h in mx]
    if not hosts:
        return False
    lowest = min(p for p, _h in mx)
    best = [h.lower() for p, h in mx if p == lowest]
    return all(any(m in h for m in RECEIVING_MX) for h in best)


def receiving_record(domain_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The MX record Resend gives a domain for receiving (at the domain's
    root, never the `send` sending record): {host, priority, status}."""
    for rec in (domain_payload or {}).get("records") or []:
        if not isinstance(rec, dict) or str(rec.get("type") or "").upper() != "MX":
            continue
        name = str(rec.get("name") or "").strip().lower()
        kind = str(rec.get("record") or "").strip().lower()
        if kind in ("receiving", "inbound") or not name.startswith("send"):
            return {"host": str(rec.get("value") or "").strip().rstrip("."),
                    "priority": rec.get("priority") if rec.get("priority") is not None else 10,
                    "status": str(rec.get("status") or "").lower()}
    return None


def apex_cname(domain: str) -> str:
    """Where the domain's own name points when it's a CNAME ('' when it
    isn't). Mail records can't sit beside a CNAME: a church whose website
    was connected with "CNAME @" gets no mail until it becomes an ALIAS."""
    try:
        import email_domain_dns
        got = email_domain_dns._cname_sync(domain)
    except Exception:
        return ""
    return got[0] if got else ""


def apex_mx(domain: str) -> Optional[List[Tuple[int, str]]]:
    """The domain's MX records now, lowest first; None when the lookup failed."""
    try:
        import email_domain_dns
        return sorted(email_domain_dns._mx_sync(domain, strict=True))
    except Exception:
        return None


# ─── The directory, and giving out addresses (Chief) ──────────────────

def describe(church: Church, box: Dict[str, Any], *, full: bool) -> Dict[str, Any]:
    where = reach(church, box)
    kind = box.get("kind")
    label = {"person": "own box", "role": "role", "prayer": "prayer list", "office": "office box",
             "forward": "forwarded"}.get(kind, kind)
    if kind == "forward" and full:
        path = f"forwarded to {box.get('forward_to')}"
    else:
        path = where["path"]
    return {"address": f"{box['local']}@{box['domain']}", "kind": kind, "label": label,
            "catch_all": bool(box.get("catch_all")), "goes_to": path,
            "people": [t.get("name") for t in where["to"] if t.get("name")]}


def _suggest_local(name: str, taken: set) -> str:
    parts = [re.sub(r"[^a-z0-9]", "", p.lower()) for p in _plain(name).split(" ")]
    parts = [p for p in parts if p]
    if not parts:
        return ""
    for cand in (parts[0], ".".join(parts[:1] + parts[-1:]) if len(parts) > 1 else "", "".join(parts)):
        if cand and LOCAL_RE.match(cand) and cand not in taken:
            return cand
    return ""


def directory(biz: Dict[str, Any], *, full: bool) -> Dict[str, Any]:
    """Every live box and where it goes now, and who still has none (with a
    suggested address and the `to` Chief passes to give it)."""
    church = Church(biz)
    boxes = church.boxes()
    taken = {b["local"] for b in boxes}
    out = {"domain": church.domain, "boxes": [describe(church, b, full=full) for b in boxes], "suggest": []}
    if not full:
        return out
    has_login = {str(b.get("user_id")) for b in boxes if b.get("kind") == "person" and b.get("user_id")}
    has_person = {str(b.get("contact_id")) for b in boxes if b.get("kind") == "person" and b.get("contact_id")}
    seat_people = {str(s.get("contact_id")) for s in church.seats().values() if s.get("contact_id")}
    for uid in [church.owner_id, *church.seats().keys()]:
        if not uid or uid in has_login:
            continue
        name = church.login_name(uid)
        local = _suggest_local(name, taken) if name not in ("the pastor", "an office login") else ""
        if local:
            taken.add(local)
        out["suggest"].append({"name": name, "who": "office login" if uid != church.owner_id else "owner",
                               "address": local, "to": f"login:{uid}"})
    import church_follow_up as cfu
    if cfu.is_church(biz):
        # A login's own record (the pastor's, which no seat ties) isn't a second person.
        login_names = {church.login_name(u).casefold() for u in [church.owner_id, *church.seats().keys()] if u}
        seen = set()
        for h in church.roles():
            cid = str(h.get("contact_id") or "")
            if (not cid or cid in seen or cid in has_person or cid in seat_people
                    or _plain(h.get("name")).casefold() in login_names):
                continue
            seen.add(cid)
            local = _suggest_local(_plain(h.get("name")), taken)
            if local:
                taken.add(local)
            out["suggest"].append({"name": _plain(h.get("name")), "who": church.role_title(str(h.get("role"))),
                                   "address": local, "to": f"person:{cid}", "has_email": bool(h.get("email"))})
        if not any(b.get("kind") == "prayer" for b in boxes) and "prayer" not in taken:
            out["suggest"].append({"name": "the prayer list", "who": "whoever leads prayer", "address": "prayer",
                                   "to": "prayer"})
    if not church.catch_all():
        local = next((x for x in ("office", "info", "hello") if x not in taken), "")
        if local:
            out["suggest"].append({"name": "the office box (gets anything sent to an address with no box)",
                                   "who": "the logins you pick, else the pastor", "address": local,
                                   "to": "office", "catch_all": True})
    return out


def _who(church: Church, to: str) -> Dict[str, Any]:
    """Chief's `to` → the box's columns. 'login:<uid>', 'person:<contact>',
    'role:<key or title>', 'prayer', 'office', 'email:<address>', or a name
    (an office login's or a leader's, matched exactly)."""
    s = " ".join(str(to or "").split())
    low = s.lower()
    if low.startswith("login:"):
        uid = s.split(":", 1)[1].strip()
        if not church.is_on_team(uid):
            raise ValueError("that login isn't on this church's team")
        return {"kind": "person", "user_id": uid, "name": church.login_name(uid)}
    if low.startswith("person:"):
        cid = s.split(":", 1)[1].strip()
        c = church.contact(cid)
        if not c:
            raise ValueError("that person isn't in this church")
        seat = next((u for u, st in church.seats().items() if str(st.get("contact_id") or "") == cid), None)
        if seat:
            return {"kind": "person", "user_id": seat, "name": church.login_name(seat)}
        if not any(h.get("contact_id") == cid for h in church.roles()):
            raise ValueError(f"{_plain(c.get('name'))} has no login and leads nothing, so a box would go "
                             "straight to the office; give them a role or an office login first")
        if not str(c.get("email") or "").strip():
            raise ValueError(f"{_plain(c.get('name'))} has no email on record to copy their mail to")
        return {"kind": "person", "contact_id": cid, "name": _plain(c.get("name"))}
    if low.startswith("role:"):
        want = s.split(":", 1)[1].strip()
        d = next((x for x in church.defs() if x["key"] == want or x["title"].casefold() == want.casefold()), None)
        if not d:
            raise ValueError(f"there's no role called {want} on Leaders & roles")
        if "prayer_shared" in (d.get("handles") or []):
            return {"kind": "prayer", "name": "the prayer list"}
        return {"kind": "role", "role_key": d["key"], "name": f"the {d['title']}"}
    if low == "prayer":
        return {"kind": "prayer", "name": "the prayer list"}
    if low == "office":
        return {"kind": "office", "name": "the office"}
    if low.startswith("email:"):
        addr = s.split(":", 1)[1].strip().lower()
        if not EMAIL_RE.match(addr) or len(addr) > 254:
            raise ValueError("that isn't an email address")
        if _ours(addr) or addr.endswith("@" + church.domain):
            raise ValueError("that address is at a domain whose mail comes here; it would loop")
        return {"kind": "forward", "forward_to": addr, "name": addr}
    if not s:
        raise ValueError("say who it's for")
    key = s.casefold()
    hits = []
    for uid in [church.owner_id, *church.seats().keys()]:
        n = church.login_name(uid)
        if n.casefold() == key or (_first(n).casefold() == key):
            hits.append(("login", uid, n))
    for h in church.roles():
        n = _plain(h.get("name"))
        if n.casefold() == key or _first(n).casefold() == key:
            if not any(x[1] == h["contact_id"] for x in hits):
                hits.append(("person", h["contact_id"], n))
    uniq = {(k, i) for k, i, _n in hits}
    if len(uniq) == 1:
        k, i, _n = hits[0]
        return _who(church, f"{k}:{i}")
    if len(uniq) > 1:
        raise ValueError(f"more than one person is called {s}: " + ", ".join(sorted({n for _k, _i, n in hits})))
    raise ValueError(f"no office login or leader is called {s}")


def give(biz: Dict[str, Any], caller: str, address: str, to: str, *, share_with: Iterable[str] = (),
         catch_all: bool = False) -> Dict[str, Any]:
    """Make an address, or point an existing one somewhere new. ValueError
    is a refusal to say; Unavailable a failed read or write."""
    church = Church(biz)
    if not church.domain:
        raise ValueError("the church's email domain isn't verified yet (Build → Email Setup)")
    local = clean_local(address)
    if not local:
        raise ValueError("an address is letters, numbers, dots or dashes, like tia or tia.brown")
    if "@" in str(address) and str(address).strip().lower().split("@", 1)[1] != church.domain:
        raise ValueError(f"church addresses are @{church.domain}")
    who = _who(church, to)
    import church_follow_up as cfu
    if who["kind"] == "prayer" and not cfu.is_church(biz):
        raise ValueError("the prayer list is for churches")
    shared = [str(u) for u in share_with or [] if str(u)]
    if who["kind"] == "office":
        bad = [u for u in shared if not church.is_on_team(u)]
        if bad:
            raise ValueError("an office box is shared with the church's own logins only")
    elif shared:
        raise ValueError("only the office box is shared with logins")
    if catch_all and who["kind"] != "office":
        raise ValueError("only the office box can get mail for addresses with no box")
    cols = {"kind": who["kind"], "user_id": who.get("user_id"), "contact_id": who.get("contact_id"),
            "role_key": who.get("role_key"), "forward_to": who.get("forward_to"), "share_with": shared,
            "catch_all": bool(catch_all)}
    other = _rows(f"/church_mailboxes?domain=eq.{_q(church.domain)}&local=eq.{_q(local)}&status=eq.active"
                  f"&select={_BOX_SELECT}&limit=1")
    if other and str(other[0]["business_id"]) != church.id:
        raise ValueError("that address belongs to another account")
    if catch_all:
        ca = church.catch_all()
        if ca and ca.get("local") != local:
            patched = sb_clients.sb_patch_as_service(
                f"/church_mailboxes?id=eq.{_q(ca['id'])}&business_id=eq.{_q(church.id)}",
                {"catch_all": False, "updated_at": _now_iso()})
            if not isinstance(patched, list):
                raise Unavailable("church_mailboxes write")
    if other:
        before = other[0]
        same = all((before.get(k) or None) == (v or None) for k, v in cols.items() if k != "share_with") and \
            sorted(map(str, before.get("share_with") or [])) == sorted(shared)
        if same:
            row, changed = before, False
        else:
            out = sb_clients.sb_patch_as_service(
                f"/church_mailboxes?id=eq.{_q(before['id'])}&business_id=eq.{_q(church.id)}",
                {**cols, "told_at": None if before.get("kind") != cols["kind"] or
                 before.get("user_id") != cols["user_id"] or before.get("contact_id") != cols["contact_id"]
                 else before.get("told_at"), "updated_at": _now_iso()})
            if not isinstance(out, list) or not out:
                raise Unavailable("church_mailboxes write")
            row, changed = out[0], True
        moved_from = describe(church, before, full=True)["goes_to"] if changed else ""
    else:
        out = sb_clients.sb_post_as_service("/church_mailboxes", {
            "business_id": church.id, "domain": church.domain, "local": local, **cols,
            "status": "active", "created_by": caller or None})
        if not isinstance(out, list) or not out:
            raise Unavailable("church_mailboxes write")
        row, changed, moved_from = out[0], True, ""
    forget_domain(church.domain)
    church._boxes = None
    return {"box": row, "address": f"{local}@{church.domain}", "changed": changed, "moved_from": moved_from,
            "goes_to": describe(church, row, full=True)["goes_to"], "name": who.get("name") or ""}


def take_back(biz: Dict[str, Any], address: str) -> Dict[str, Any]:
    church = Church(biz)
    local = clean_local(address)
    box = church.box(local) if local else None
    if not box:
        raise ValueError(f"{address} isn't one of the church's addresses")
    out = sb_clients.sb_patch_as_service(
        f"/church_mailboxes?id=eq.{_q(box['id'])}&business_id=eq.{_q(church.id)}&status=eq.active",
        {"status": "off", "catch_all": False, "updated_at": _now_iso()})
    if not isinstance(out, list) or not out:
        raise Unavailable("church_mailboxes write")
    church._boxes = None
    forget_domain(church.domain)
    ca = church.catch_all()
    now = reach(church, ca)["path"] if ca else "the pastor"
    return {"address": f"{box['local']}@{box['domain']}", "now": now, "was_catch_all": bool(box.get("catch_all"))}


def sender_box(biz: Dict[str, Any], uid: str) -> Optional[Dict[str, str]]:
    """The church address a login sends from: its own live box at the
    church's verified domain, while that domain's mail comes here (so the
    replies do too). None means the church's usual address, as before;
    a read that fails is None too, never a held send (Kevin, 2026-11-13:
    "I want everyone to send out emails today")."""
    if not uid or not biz:
        return None
    try:
        church = Church(biz)
        if not church.domain or not church.is_on_team(str(uid)):
            return None
        box = next((b for b in church.boxes() if b.get("kind") == "person"
                    and str(b.get("user_id") or "") == str(uid)), None)
        if not box or box.get("domain") != church.domain or not mail_comes_here(church.domain):
            return None
        return {"address": f"{box['local']}@{box['domain']}", "name": church.login_name(str(uid))}
    except Exception:  # noqa: BLE001 — never hold a send over this
        logger.warning("church mail: couldn't read a login's own address; sending as the church")
        return None


# ─── A new office login gets its address (Kevin, 2026-11-13) ──────────
#
# A church whose mail comes here gives every office login its own address
# the moment the login is accepted: the invite says which one, and the
# person gets the welcome note naming it. The pastor, an Admin or the church
# email duty can change or take it back in Email → Addresses.

def _live_church(biz: Dict[str, Any]) -> Optional["Church"]:
    """The church, when it is a church whose own domain's mail comes here."""
    import church_follow_up as cfu
    if not biz or not cfu.is_church(biz):
        return None
    church = Church(biz)
    if not church.domain:
        return None
    try:
        return church if mail_comes_here(church.domain) else None
    except Unavailable:
        return None


def new_login_address(biz: Dict[str, Any], name: str) -> Optional[str]:
    """The address an invited login will get when it accepts (from the name
    the church knows them by), or None: not a church whose mail comes here,
    no name to make one from, or a read failed. Never raises."""
    try:
        church = _live_church(biz)
        if not church or not _plain(name):
            return None
        local = _suggest_local(name, {b["local"] for b in church.boxes()})
        return f"{local}@{church.domain}" if local else None
    except Exception:  # noqa: BLE001 — an invite never fails over this
        logger.warning("church mail: couldn't plan a new login's address")
        return None


def give_new_login(biz: Dict[str, Any], uid: str, *, caller: str = "", name: str = "") -> Optional[Dict[str, Any]]:
    """Give a login that just joined its own address, once. None when it
    isn't a church whose mail comes here, the login already has a box (its
    own, or one for the person it is), there's no name to make one from, or
    anything failed: a login's joining never waits on its address."""
    try:
        church = _live_church(biz)
        uid = str(uid or "")
        if not church or not church.is_on_team(uid):
            return None
        seat = church.seats().get(uid) or {}
        cid = str(seat.get("contact_id") or "")
        if any(b.get("kind") == "person" and (str(b.get("user_id") or "") == uid
                                             or (cid and str(b.get("contact_id") or "") == cid))
               for b in church.boxes()):
            return None
        known = church.login_name(uid)
        who = known if known not in ("the pastor", "an office login") else _plain(name)
        local = _suggest_local(who, {b["local"] for b in church.boxes()})
        if not local:
            return None
        return give(biz, caller or church.owner_id, local, f"login:{uid}")
    except Exception as e:  # noqa: BLE001 — never hold a joining login
        logger.warning("church mail: a new login's address wasn't made: %s", type(e).__name__)
        return None


def held_count(business_id: str, days: int = 7) -> Optional[int]:
    from datetime import timedelta
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        rows = _rows(f"/church_mail?business_id=eq.{_q(business_id)}&outcome=eq.held"
                     f"&received_at=gte.{_q(since)}&select=id&limit=500")
    except Unavailable:
        return None
    return len(rows)


async def welcome(biz: Dict[str, Any], box: Dict[str, Any]) -> Optional[str]:
    """The note naming a person's address, sent once. None when sent, else
    why not."""
    church = Church(biz)
    try:
        where = await asyncio.to_thread(reach, church, box)
    except Unavailable:
        return "their email couldn't be read"
    if box.get("kind") != "person" or not where["to"] or "own box" not in where["path"]:
        return "it isn't one person's box"
    t = where["to"][0]
    if not EMAIL_RE.match(t.get("email") or "") or _ours(t["email"]):
        return "no outside email to send it to"
    address = f"{box['local']}@{box['domain']}"
    church_name = _plain(biz.get("name"), 80) or "your church"
    body = (f"Hi {_first(t.get('name') or '') or 'there'},\n\n"
            f"Your church email is {address}.\n\n"
            f"Mail sent to {address} comes to this inbox as a copy, marked with who sent it. "
            f"Hit reply as you normally would and your answer goes straight back to them.\n\n"
            f"You can also read, answer and write church mail in the app, under Email. Once you do, you can "
            f"turn these copies off there.\n\n"
            f"{church_name}")
    import email_sender
    try:
        await email_sender.send_via_resend(
            to_email=t["email"], to_name=t.get("name") or None, from_email=email_sender.DEFAULT_FROM_EMAIL,
            from_name=church_name, subject=f"Your church email: {address}", body=body, reply_to=None,
            business_id=church.id, idempotency_key=f"church-mail-welcome-{box['id']}")
    except Exception as e:
        logger.warning("church mail: welcome for box %s not sent: %s", str(box["id"])[:8], type(e).__name__)
        return "the note couldn't be sent"
    sb_clients.sb_patch_as_service(f"/church_mailboxes?id=eq.{_q(box['id'])}", {"told_at": _now_iso()})
    return None
