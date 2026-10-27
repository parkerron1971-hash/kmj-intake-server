"""
member_portal.py — a church member's own page, at <church site>/my.

WHAT IT IS (Kevin, 2026-09-29: "passwordless, permanent address, long
device session"). A member signs in with a 6-digit code sent to the email
the church already has for them — no password, no account in the
practitioner's user pool — and sees their own giving and their year-end
statement. Nothing else about anyone else, except the member directory
(member_directory.py, 2026-10-27): off until the church turns it on, and
only the adult members who said yes, showing only what each one chose.

WHO CAN SIGN IN. Only an email the church has on a contact. Asking for a
code NEVER says whether an address is on the list — the same page comes
back either way, and only a known address is mailed. One person per
email: an address on more than one record is never mailed a code.

THE CODE. 6 digits from `secrets`, stored only as an HMAC under a key
derived for this business (customer_token.derive_key, purpose
"member-code"), 10 minutes, 5 tries, single use; a new code retires every
earlier one. At most MAX_FAILED_PER_DAY wrong codes per address per day,
across all its codes. Asking is limited per network and, per address, to
one a minute and a dozen a day (rate_limit.allow_strict — fail closed).
NOTHING SAYS WHO IS ON THE LIST (review, 2026-09-29): the code page is the
same for any address, the lookup, stored code and email all run after the
reply is sent (so timing is the same too), and every failed verify shows
one message.

THE SESSION. A __Host- cookie on the church's own address (Secure, no
Domain, Path=/, httponly, SameSite=Lax), 180 days: {biz, em, cid, iat,
exp}. Signed with a second derived key (purpose "member-session"), so a
session for one church can never open another's. Re-checked on every
request against the contact rows: change or remove the email on the
person's record and it stops working. The owner can also sign everyone
out (settings.member_portal.epoch), and switching the page back on does
the same.

SHARED EMAILS (Kevin, 2026-09-29: "1 person per email is right"). An
address on more than MAX_HOUSEHOLD (= 1) record never signs in, and the
page tells them to ask the church office for their own. The chooser and
/my/person remain for a session minted before this rule (it re-checks,
and with one person per email it can only ever pick that one person).

WHERE IT RUNS. GET /my and /my/statement are served from
public_site.subdomain_catch_all (the church's host decides the church);
the POST routes below are registered at the root like /learn/*/mark and
refuse the API host. Every POST also refuses a cross-site Origin.

GATE. A nonprofit-family business (the portal's first page is giving)
whose owner switched it on (settings.member_portal.enabled), on a vertical
allowed a client surface at all. Everyone else gets a plain "not
available" page with a 404 status.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html as _html
import json
import logging
import os
import re
import secrets
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("member_portal")

router = APIRouter(tags=["member-portal"])

CODE_TTL_SECONDS = 10 * 60
MAX_CODE_ATTEMPTS = 5
# Wrong codes allowed per church + address per day, across every code
# asked for. Without it the budget was 5 codes × 5 tries every hour.
MAX_FAILED_PER_DAY = 15
# ONE PERSON PER EMAIL (Kevin, 2026-09-29). An email on more than one
# record signs nobody in: whoever reads a shared inbox (a couple's, the
# church office's, a placeholder) must never see another person's giving.
# Each person needs their own address on their own record.
MAX_HOUSEHOLD = 1
SESSION_TTL_SECONDS = 180 * 24 * 60 * 60
# __Host-: Secure, no Domain, Path=/ — so another church's subdomain can
# never plant a cookie this page would read.
SESSION_COOKIE = "__Host-sol_member"
COOKIE_PATH = "/"
SESSION_VERSION = 1

GENERIC_CODE_ERROR = ("That code didn't work. It may be mistyped, expired or already used — "
                      "check it, or send a new one below.")

_SECURE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
    # same-origin, not no-referrer: under no-referrer a browser sends a
    # same-origin form post with Origin: null, which _same_origin refuses,
    # so "Send my code" answered {"detail":"Not allowed"} (Kevin,
    # 2026-10-15). Other sites still get no referrer at all.
    "Referrer-Policy": "same-origin",
}

UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")


# ─── Pure helpers (unit-tested) ──────────────────────────────────────


def norm_email(value: Any) -> str:
    return str(value or "").strip().lower()


def valid_email(value: str) -> bool:
    return bool(_EMAIL_RE.match(value or "")) and len(value) <= 254


_PHONE_RE = re.compile(r"^\+\d{8,15}$")


def norm_ident(value: Any) -> str:
    """What a member signs in with: an email (lower-cased) or a mobile
    number (E.164, "+15550102030"). "" when it is neither."""
    raw = str(value or "").strip()
    if "@" in raw:
        return norm_email(raw)
    import sms_service
    # Spaces, dots, dashes and brackets out first: the shared normaliser
    # passes anything starting with "+" through as typed.
    phone = sms_service.normalize_phone(re.sub(r"[^\d+]", "", raw))
    return phone if _PHONE_RE.match(phone or "") else ""


def is_phone(ident: str) -> bool:
    return str(ident or "").startswith("+")


def valid_ident(value: str) -> bool:
    return valid_email(value) or bool(_PHONE_RE.match(value or ""))


def show_ident(ident: str) -> str:
    """How to show it back: a US/Canada number as (555) 010-2030."""
    if is_phone(ident) and len(ident) == 12 and ident.startswith("+1"):
        d = ident[2:]
        return f"({d[:3]}) {d[3:6]}-{d[6:]}"
    return ident


def _last10(phone: Any) -> str:
    """The number itself, however it was typed: digits only, an extension
    ("x2", "ext. 12") dropped, the last ten kept."""
    raw = re.split(r"(?i)\s*(?:x|ext)", str(phone or ""), maxsplit=1)[0]
    return re.sub(r"\D", "", raw)[-10:]


def portal_settings(settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    raw = (settings or {}).get("member_portal") or {}
    return raw if isinstance(raw, dict) else {}


def portal_eligible(biz: Dict[str, Any]) -> bool:
    """A church (or nonprofit) that COULD switch the page on."""
    import vertical_family
    import vertical_scope
    t = biz.get("type")
    return vertical_family.is_nonprofit_like(t) and vertical_scope.client_surface_allowed(t)


def portal_active(biz: Dict[str, Any]) -> bool:
    """The ONE activation rubric: page, POSTs and the owner panel."""
    return portal_eligible(biz) and bool(portal_settings(biz.get("settings")).get("enabled"))


def sign_in_open(biz: Dict[str, Any]) -> bool:
    """The owner's sign-in switch (Settings → Member page; Kevin 10/04: "a
    turn on and off switch for member sign in"). On unless the owner paused
    it. While paused no code is sent and no code is accepted; anyone already
    signed in stays in ("sign everyone out" is the separate control)."""
    return portal_settings(biz.get("settings")).get("sign_in") is not False


def codes_can_go_out() -> bool:
    """A member signs in with a code sent by email (Resend) or text
    (Twilio): False while neither is set up."""
    if (os.environ.get("RESEND_API_KEY") or "").strip():
        return True
    try:
        import sms_service
        return bool(sms_service._twilio_configured())
    except Exception:
        return False


def _previewing(request: Request, biz: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The owner's live preview claims on this church, or None
    (member_portal_preview.py)."""
    import member_portal_preview as pv
    if not portal_eligible(biz):
        return None
    return pv.read_session(request.cookies.get(pv.PREVIEW_COOKIE) or "", biz["id"], epoch=_epoch(biz))


def _key(purpose: str, business_id: str) -> bytes:
    from customer_token import derive_key
    return derive_key(purpose, str(business_id))


def code_hash(business_id: str, email: str, code: str) -> str:
    return hmac.new(_key("member-code", business_id),
                    f"{norm_ident(email)}|{code}".encode("utf-8"),
                    hashlib.sha256).hexdigest()


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def mint_session(business_id: str, email: str, contact_id: str = "",
                 now: Optional[int] = None) -> str:
    now = int(now if now is not None else time.time())
    payload = _b64(json.dumps({
        "biz": str(business_id), "em": norm_ident(email), "cid": str(contact_id or ""),
        "iat": now, "exp": now + SESSION_TTL_SECONDS, "v": SESSION_VERSION,
    }, separators=(",", ":")).encode("utf-8"))
    sig = _b64(hmac.new(_key("member-session", business_id),
                        payload.encode("ascii"), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_session(value: str, business_id: str, now: Optional[int] = None,
                 epoch: int = 0) -> Optional[Dict[str, Any]]:
    """Claims for THIS business, or None. Never raises. A session issued
    before the church's epoch (it signed everyone out, or switched the
    page back on) is over."""
    try:
        payload, sig = (value or "").split(".", 1)
        want = _b64(hmac.new(_key("member-session", business_id),
                             payload.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(want, sig):
            return None
        claims = json.loads(_unb64(payload))
        if claims.get("v") != SESSION_VERSION or str(claims.get("biz")) != str(business_id):
            return None
        if int(claims.get("exp") or 0) <= int(now if now is not None else time.time()):
            return None
        if int(claims.get("iat") or 0) < int(epoch or 0):
            return None
        if not valid_ident(str(claims.get("em") or "")):
            return None
        return claims
    except Exception:
        return None


def first_name(name: str) -> str:
    return (str(name or "").strip().split() or [""])[0]


def money(amount: float) -> str:
    return f"${amount:,.2f}"


def _e(s: Any) -> str:
    return _html.escape(str(s if s is not None else ""), quote=True)


# ─── Data (service role; every read is scoped to one business) ──────


def contacts_for_email(business_id: str, email: str) -> Optional[List[Dict[str, Any]]]:
    """Everyone at this church with exactly this address (a household can
    share one). An exact, case-insensitive match — wildcards escaped.
    None when the read FAILED: that is "try again", never "not on the
    list". Reads one past MAX_HOUSEHOLD so an over-shared address shows."""
    em = norm_email(email)
    if not valid_email(em):
        return []
    pattern = re.sub(r"([\\%_*])", r"\\\1", em)
    rows = sb_clients.sb_get_as_service(
        f"/contacts?business_id=eq.{quote(str(business_id), safe='')}"
        f"&email=ilike.{quote(pattern, safe='')}"
        f"&select=id,name,email,birthdate,photo:metadata->member_photo&order=created_at.asc&limit={MAX_HOUSEHOLD + 1}")
    if not isinstance(rows, list):
        return None
    return [r for r in rows if isinstance(r, dict) and norm_email(r.get("email")) == em]


def contacts_for_phone(business_id: str, phone: str) -> Optional[List[Dict[str, Any]]]:
    """Everyone at this church whose phone is this number, however the
    office typed it ("(555) 010-2030", "555.010.2030 x2"). The database
    narrows by the digits in order; the exact last-ten match is made here.
    None when the read failed."""
    digits = _last10(phone)
    if len(digits) < 10:
        return []
    rows = sb_clients.sb_get_as_service(
        f"/contacts?business_id=eq.{quote(str(business_id), safe='')}"
        f"&phone=like.{quote('*' + '*'.join(digits) + '*', safe='')}"
        f"&select=id,name,email,phone,birthdate,photo:metadata->member_photo&order=created_at.asc&limit=20")
    if not isinstance(rows, list):
        return None
    return [r for r in rows if isinstance(r, dict) and _last10(r.get("phone")) == digits]


def contacts_for_ident(business_id: str, ident: str) -> Optional[List[Dict[str, Any]]]:
    """The people an email or a mobile number belongs to at this church.
    A child under 13 is never one of them: kids come in through a parent's
    Kids space (member_spaces; Kevin, 2026-10-15), so a child's record gets
    no code and no session, and a parent who shares an address with their
    child can still sign in."""
    import member_spaces as msp
    ident = norm_ident(ident)
    rows = contacts_for_phone(business_id, ident) if is_phone(ident) else contacts_for_email(business_id, ident)
    return None if rows is None else [r for r in rows if not msp.is_child(r)]


def failures_today(business_id: str, email: str) -> Optional[int]:
    """Wrong codes for this address in the last day, across every code.
    None when the read failed (the caller refuses rather than guesses)."""
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    rows = sb_clients.sb_get_as_service(
        f"/member_login_codes?business_id=eq.{quote(str(business_id), safe='')}"
        f"&email=eq.{quote(norm_ident(email), safe='')}&created_at=gt.{quote(since, safe='')}"
        f"&select=attempts,succeeded&limit=200")
    if not isinstance(rows, list):
        return None
    return sum(max(0, int(r.get("attempts") or 0) - (1 if r.get("succeeded") else 0)) for r in rows)


def _latest_code(business_id: str, email: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/member_login_codes?business_id=eq.{quote(str(business_id), safe='')}"
        f"&email=eq.{quote(norm_ident(email), safe='')}&consumed_at=is.null"
        f"&select=id,code_hash,expires_at,attempts&order=created_at.desc&limit=1") or []
    return rows[0] if rows else None


def issue_code(business_id: str, email: str) -> str:
    code = new_code()
    expires = datetime.now(timezone.utc) + timedelta(seconds=CODE_TTL_SECONDS)
    # Old rows are not needed for anything: the latest unused code is the
    # only one that counts. A day of history is kept for support.
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        sb_clients.sb_delete_as_service(
            f"/member_login_codes?business_id=eq.{quote(str(business_id), safe='')}"
            f"&created_at=lt.{quote(cutoff, safe='')}")
    except Exception:
        pass
    # A new code retires every earlier one, so a code that was sent before
    # cannot come back to life (with fresh tries) once this one is used.
    sb_clients.sb_patch_as_service(
        f"/member_login_codes?business_id=eq.{quote(str(business_id), safe='')}"
        f"&email=eq.{quote(norm_ident(email), safe='')}&consumed_at=is.null",
        {"consumed_at": datetime.now(timezone.utc).isoformat()})
    saved = sb_clients.sb_post_as_service("/member_login_codes", {
        "business_id": str(business_id), "email": norm_ident(email),
        "code_hash": code_hash(business_id, email, code),
        "expires_at": expires.isoformat(),
    })
    # sb_clients answers None for a failed write; a code that was never
    # stored must not be mailed (it could never work).
    if not saved:
        raise RuntimeError("member code was not stored")
    return code


def check_code(business_id: str, email: str, code: str) -> str:
    """'ok', 'wrong', 'expired' or 'locked'. Each try is counted BEFORE the
    comparison, with a revision guard on the count, so parallel guesses
    cannot share one attempt. The page shows ONE message for every
    failure: a different word for "no code was ever sent" would tell a
    stranger who is on the church's list."""
    code = re.sub(r"\D", "", str(code or ""))
    failed = failures_today(business_id, email)
    if failed is None or failed >= MAX_FAILED_PER_DAY:
        if failed is not None:
            logger.warning("member sign-in: daily wrong-code cap reached for business %s", business_id)
        return "locked"
    row = _latest_code(business_id, email)
    if not row:
        return "expired"
    try:
        exp = datetime.fromisoformat(str(row.get("expires_at")).replace("Z", "+00:00"))
    except ValueError:
        return "expired"
    if exp <= datetime.now(timezone.utc):
        return "expired"
    tries = int(row.get("attempts") or 0)
    if tries >= MAX_CODE_ATTEMPTS:
        return "locked"
    counted = sb_clients.sb_patch_as_service(
        f"/member_login_codes?id=eq.{row['id']}&attempts=eq.{tries}&consumed_at=is.null",
        {"attempts": tries + 1})
    if not counted:
        return "wrong"
    if len(code) != 6 or not hmac.compare_digest(
            code_hash(business_id, email, code), str(row.get("code_hash") or "")):
        return "locked" if tries + 1 >= MAX_CODE_ATTEMPTS else "wrong"
    used = sb_clients.sb_patch_as_service(
        f"/member_login_codes?id=eq.{row['id']}&consumed_at=is.null",
        {"consumed_at": datetime.now(timezone.utc).isoformat(), "succeeded": True})
    return "ok" if used else "expired"


def gifts_for(business_id: str, contact_id: str, year: int) -> List[Dict[str, Any]]:
    """One person's gifts in one year, newest first. Raises (HTTP 503) on
    a failed read — a failed read must never render as $0."""
    import giving_records
    from giving_statements import _net_amount
    rows = giving_records.read_gifts(business_id, f"{year}-01-01", f"{year + 1}-01-01",
                                     contact_id)
    out = [{
        "date": str(r.get("paid_at") or "")[:10],
        "fund": (r.get("gift_fund") or r.get("category") or "").strip() or "General",
        "amount": _net_amount(r),
        "refunded": bool(r.get("refund_amount_cents")),
        "method": str(r.get("payment_method") or ""),
    } for r in rows]
    out.sort(key=lambda g: g["date"], reverse=True)
    return out


# ─── Host → church ───────────────────────────────────────────────────


def _church_for_request(request: Request) -> Optional[Dict[str, Any]]:
    """The church whose address this request arrived on, or None (the API
    host, an unknown host, a site taken offline)."""
    import public_site
    host = public_site.public_host(request)
    if public_site._is_api_host(host):
        return None
    slug = public_site.extract_slug_from_host(request)
    if slug:
        q = f"slug=eq.{quote(slug, safe='')}"
    else:
        domain = (host or "").split(":")[0].lower()
        if domain.startswith("www."):
            domain = domain[4:]
        if "." not in domain:
            return None
        q = f"site_config->>custom_domain=eq.{quote(domain, safe='')}"
    # The site and its church in one read (every member page, its icons and
    # its service worker start here; two reads in a row were two waits).
    sites = sb_clients.sb_get_as_service(
        f"/business_sites?{q}&order=updated_at.desc&limit=1"
        f"&select=slug,business_id,site_config,"
        f"business:businesses(id,name,type,settings,stripe_account_id)") or []
    if not sites or (sites[0].get("site_config") or {}).get("offline"):
        return None
    site = dict(sites[0])
    biz = site.pop("business", None)
    if not isinstance(biz, dict) or not biz.get("id"):
        return None
    return {"business": biz, "site": site}


def _same_origin(request: Request) -> bool:
    """A POST from another site is refused. Browsers send Origin on POST;
    a missing one (old clients, some privacy modes) falls back to Referer,
    and neither present is allowed — SameSite=Lax already keeps the
    session cookie off cross-site POSTs."""
    import public_site
    host = (public_site.public_host(request) or "").split(":")[0].lower()
    origin = request.headers.get("origin")
    if origin == "null":
        # A page still open from before the referrer fix posts with Origin:
        # null; the browser's own Sec-Fetch-Site (which a page can't set)
        # says whether it came from this very address. Another church's
        # address is "same-site", never "same-origin".
        return (request.headers.get("sec-fetch-site") or "").lower() == "same-origin"
    if origin is not None:
        return (urlparse(origin).hostname or "").lower() == host
    referer = request.headers.get("referer")
    if referer:
        return (urlparse(referer).hostname or "").lower() == host
    return True


def _epoch(biz: Dict[str, Any]) -> int:
    try:
        return int(portal_settings(biz.get("settings")).get("epoch") or 0)
    except (TypeError, ValueError):
        return 0


def _session_for(request: Request, church: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The signed-in member, re-checked against today's records.
    {"unavailable": True} when the records could not be read — the page
    says "try again" rather than signing the member out."""
    biz = church["business"]
    preview = _previewing(request, biz)
    if preview:
        import member_portal_preview as pv
        who = pv.load_contact(biz["id"], preview["cid"])
        if who is None:
            return {"unavailable": True}
        if who:
            return {"claims": preview, "people": [who], "me": who, "preview": True}
    claims = read_session(request.cookies.get(SESSION_COOKIE) or "", biz["id"],
                          epoch=_epoch(biz))
    if not claims:
        return None
    people = contacts_for_ident(biz["id"], claims["em"])
    if people is None:
        return {"unavailable": True}
    if not people or len(people) > MAX_HOUSEHOLD:
        return None
    me = next((p for p in people if str(p["id"]) == str(claims.get("cid") or "")), None)
    return {"claims": claims, "people": people, "me": me}


def _set_session(resp, value: str) -> None:
    resp.set_cookie(SESSION_COOKIE, value, max_age=SESSION_TTL_SECONDS, path=COOKIE_PATH,
                    httponly=True, secure=True, samesite="lax")


# ─── Pages (pure renderers) ─────────────────────────────────────────


def palette_for(biz: Dict[str, Any], site: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """The member app's colours for this church (member_app_ui.palette)."""
    import member_app_ui as ui
    from public_form_theme import resolve_theme
    return ui.palette(biz, resolve_theme(biz, site))


def _body_class(door: bool, space: str, tab: Optional[str]) -> str:
    """The sign-in pages' class, a Youth or Kids space's, and the colour the
    page's tab wears (member_app_ui.TAB_HUE: Watch violet, Bible gold,
    Connect teal)."""
    import member_app_ui as ui
    if door:
        return ' class="si"'
    names = [f"sp-{space}"] if space != "church" else []
    place = ui.TAB_OF.get(tab or "", "")
    if place in ui.TAB_HUE:
        names.append(f"pg-{place}")
    return f' class="{" ".join(names)}"' if names else ""


def _shell(biz: Dict[str, Any], site: Optional[Dict[str, Any]], title: str,
           body: str, *, script: str = "", tab: Optional[str] = None,
           who: Optional[Dict[str, Any]] = None, bare: bool = False, bar: bool = True,
           door: bool = False, back: Optional[Tuple[str, str]] = None, news_n: Optional[int] = None) -> str:
    """Every member page. Signed-in pages pass `tab` (the page's place in
    the tab bar: home, watch, bible, give, connect — the older names map
    over) and `who` (their picture, top right, which opens Me); the
    sign-in pages pass neither and get no bar. `back` = (href, label) puts
    a back link at the top left (else Home shows the church's logo there).
    The page's title moves into the bar as its large title scrolls away.
    `bare` leaves the bar at the top out; `bar=False` keeps it but drops the
    tab bar (a chat, whose box sits at the foot of the screen). `door` is a
    page before sign-in (member_app_signin), which draws its own top and
    foot. `news_n` (Home, when the church has news) puts the bell at the top
    right, with how many posts are new (member_portal_news). The look is
    member_app_ui's."""
    import member_app_ui as ui
    import member_app_install as mai
    import member_app_photos as photos
    import member_app_signin as sg
    from public_form_theme import resolve_theme, css_vars
    theme = resolve_theme(biz, site)
    name = (biz.get("name") or "").strip() or "Your church"
    logo = theme.get("logo_url") or ""
    mark = f'<img src="{_e(logo)}" alt="">' if logo else _e(ui.initials(name))
    word = "" if logo else photos.wordmark(site, light=ui.palette(biz, theme)["dark"])
    brand = (f'<img class="mb-wordmark" src="{_e(word)}" alt="{_e(name)}">' if word else
             f'<span class="mb-mark" aria-hidden="true">{mark}</span><p class="mp-church">{_e(name)}</p>')
    # Me lives on the profile picture (Kevin, 10/02: the Bible took a tab).
    here = ' aria-current="page"' if tab == "me" else ""
    import member_photos as ph
    mine = ph.src(who) if who else ""
    avatar = ((f'<a class="mb-avatar has-photo mp-noprint" href="/my/me" aria-label="Me"{here}>'
               f'<img src="{_e(mine)}" alt=""></a>') if mine else
              (f'<a class="mb-avatar mp-noprint" href="/my/me" aria-label="Me"{here}>{_e(ui.initials(who.get("name")))}</a>')
              ) if who else ""
    signed_in = tab is not None
    if back is None and not (bare or door):
        # A page's own back link moves up into the bar.
        m = re.search(r'<a class="mb-back" href="([^"]*)"[^>]*>(.*?)</a>', body, re.S)
        if m:
            import html as _html
            back = (_html.unescape(m.group(1)), _html.unescape(re.sub(r"<[^>]+>", "", m.group(2)).strip()))
            body = body[:m.start()] + body[m.end():]
    import member_spaces as msp
    ctx = (msp.CURRENT.get() or {}) if signed_in else {}
    space = ctx.get("space") or "church"
    # A page the church made a tab of its own (Events, Prayer, News,
    # Messages: member_app_ui.church_tabs) is a tab like Watch: no way back
    # to Home at the top, and Messages has no second way in up there.
    own_bar = signed_in and space == "church"
    if own_bar and back and back[0] == "/my" and ui.in_church_bar(biz, tab):
        back = None
    import member_portal_messaging as mpm
    chat = (f'<a class="mb-chat-link mp-noprint" href="/my/messages" aria-label="Messages">{ui.icon("chat", 19)}</a>'
            if signed_in and mpm.turned_on(biz) and tab not in ("messages", "connect", "groups")
            and not (own_bar and ui.in_church_bar(biz, "messages")) else "")
    if signed_in and news_n is not None:
        badge = f'<span class="mb-unread">{news_n}</span>' if news_n else ""
        label = f"News, {news_n} new" if news_n else "News"
        chat = (f'<a class="mb-chat-link mp-noprint" href="/my/news" aria-label="{label}">{ui.icon("bell", 19)}{badge}</a>'
                + chat)
    if back:
        left = f'<a class="mb-back" href="{_e(back[0])}">{ui.icon("back", 24)}{_e(back[1])}</a>'
    elif tab == "home":
        left = msp.switcher(ctx, name) or (
            f'<a class="mb-brand" href="/my"><span class="y-mark"><b>{_e(ui.initials(name))}</b>Youth</span></a>'
            if space == "youth" else f'<a class="mb-brand" href="/my">{brand}</a>')
    else:
        left = ""
    top = "" if bare or door else (
        f'<header class="mb-top"><div class="mb-top-l">{left}</div>'
        f'<span class="mb-top-t" aria-hidden="true">{_e(title)}</span>'
        f'<span class="mb-top-right">{chat}{avatar}</span></header>')
    pal = ui.palette(biz, theme, space)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow">
<meta name="theme-color" content="{pal['bg']}">
{mai.head_tags(biz)}
<title>{_e(title)} — {_e(name)}</title>
{ui.FONTS}
<style>{css_vars(theme)}</style>
<style>{ui.css(biz, theme, space)}</style>
{f'<style>{sg.css(biz, theme)}</style>' if door else ''}
</head>
<body{_body_class(door, space, tab)}>
{top}
<main class="mp-shell{' mb-has-nav' if signed_in and bar else ''}{' mb-bare' if bare or door else ''}">
  {body}
  {'' if door else f'<footer class="mp-foot mp-noprint">Your page at {_e(name)} · Powered by Solutionist</footer>'}
</main>
{ui.nav(tab, space=space, kids_parent=bool(ctx.get("kids_parent")), lead=bool(ctx.get("lead")), biz=biz) if signed_in and bar else ''}
{'' if bare or door else ui.SCROLL_JS}
{script}
{mai.REGISTER_JS}
</body>
</html>"""


GIVE_CSS = """
.gv-shell{max-width:600px;padding:calc(8px + env(safe-area-inset-top,0px)) 20px calc(118px + env(safe-area-inset-bottom,0px));}
.gv-card{border:0;background:transparent;border-radius:0;padding:0;box-shadow:none;}
.gv-label{display:block;color:var(--fg3);font-size:12.5px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;margin:24px 0 10px;}
.gv-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(68px,1fr));gap:8px;}
.gv-amt{border:0;background:var(--s1);border-radius:14px;font-family:var(--mb-ui);font-size:20px;font-weight:700;letter-spacing:-.03em;
  min-height:58px;color:var(--fg);font-variant-numeric:tabular-nums;}
.gv-amt.on{background:var(--fg);color:var(--bg);}
.gv-input{border:1px solid transparent;background:var(--s1);border-radius:14px;min-height:54px;color:var(--fg);font-family:var(--mb-ui);font-size:16px;margin-top:8px;}
.gv-input:focus{outline:none;border-color:var(--acc);box-shadow:0 0 0 4px var(--mb-soft);}
.gv-input option{background:var(--s1);color:var(--fg);}
.gv-freq{border:0;border-radius:12px;background:var(--s1);padding:3px;gap:3px;}
.gv-freq button{border-radius:9px;color:var(--fg2);font-family:var(--mb-ui);min-height:38px;padding:0;font-size:13.5px;}
.gv-freq button.on{background:var(--s3);color:var(--fg);}
.gv-cover{margin-top:16px;color:var(--fg2);font-size:14.5px;}
.gv-cover input{accent-color:var(--acc-fill);}
.gv-give{background:var(--acc-fill);color:var(--on-acc);border-radius:16px;min-height:56px;font-family:var(--mb-ui);font-size:16.5px;font-weight:650;
  letter-spacing:-.01em;margin-top:22px;}
.gv-error{color:var(--error);}
.gv-banner{border:0;background:var(--s1);color:var(--fg);border-radius:14px;}
.gv-msg{color:var(--fg2);}
.gv-note{color:var(--fg3);}
.gv-back{color:var(--acc);font-family:var(--mb-ui);}
.gv-footer{display:none;}
"""


def render_give(biz: Dict[str, Any], site, me: Dict[str, Any], *, preview: bool = False) -> str:
    """Give, a tab of the member app: the give page's own form and
    payment (giving_router.render_give_page), in the app's look, with the
    member's name and email filled in and the tab bar under it. In the
    owner's preview, Give is refused (nothing is charged)."""
    import member_app_ui as ui
    import public_site
    from business_sites_helpers import PUBLIC_DOMAIN
    from giving_router import render_give_page
    from public_form_theme import css_vars, resolve_theme
    theme = resolve_theme(biz, site)
    slug = str((site or {}).get("slug") or "")
    name = (biz.get("name") or "").strip() or "the church"
    top = (f'<div class="mb-lt"><h1>Give</h1></div>'
           f'<p class="mb-sub" style="margin:0 0 4px">To {_e(name)}. Thank you for your generosity.</p>'
           f'<a class="mb-row" href="/my/me#mp-giving" style="margin:16px 0 0"><span class="mb-row-ic">{ui.icon("doc", 20)}</span>'
           f'<span class="mb-row-t"><strong>Your giving</strong><span>This year, each gift and your statement</span></span>'
           f'{ui.icon("chevron", 18)}</a>')
    if preview:
        top += '<p class="mp-flash mp-ok" role="status">This is a preview, so Give won\'t charge anything.</p>'
    head = (ui.FONTS + f"<style>{css_vars(theme)}</style><style>{ui.css(biz, theme)}</style><style>{GIVE_CSS}</style>")
    return render_give_page(biz, f"https://{slug}.{PUBLIC_DOMAIN}/give", slug, api_origin=public_site._EMBED_ORIGIN,
                            app={"head": head, "top": top, "name": me.get("name") or "",
                                 "email": me.get("email") or "", "preview": preview,
                                 "foot": ui.nav("give", biz=biz)})


def _door_page(biz: Dict[str, Any], site, title: str, *, icon: str, heading: str, body: str,
               actions: str = "") -> str:
    """A page before sign-in with one thing to say, in the front door's
    look (member_app_signin.status_body)."""
    import member_app_signin as sg
    from public_form_theme import resolve_theme
    return _shell(biz, site, title, sg.status_body(biz, site, resolve_theme(biz, site), icon=icon, title=heading,
                                                   body=body, actions=actions), door=True)


def render_unavailable(biz: Dict[str, Any], site=None) -> str:
    return _door_page(biz, site, "Not available", icon="lock", heading="This page isn't open yet", body="""
<p>Member sign-in isn't turned on for this church. If you were expecting it, ask the church office.</p>""")


def render_signin_paused(biz: Dict[str, Any], site=None) -> str:
    return _door_page(biz, site, "Sign-in paused", icon="clock", heading="Sign-in is paused for now", body=f"""
<p>{_e(biz.get('name') or 'The church')} has paused new sign-ins to this page, so no code will be sent.
If you're already signed in on another phone or computer, you're still in there.</p>
<p>Ask the church office when it's back on.</p>""")


def render_signin(biz: Dict[str, Any], site=None, *, error: str = "", email: str = "") -> str:
    """The front door (member_app_signin): the church's photo in an open
    doorway, "Welcome home.", and the form in a sheet below."""
    import member_app_signin as sg
    from public_form_theme import resolve_theme
    return _shell(biz, site, "Sign in", sg.signin_body(biz, site, resolve_theme(biz, site), error=error, email=email),
                  script=sg.SIGNIN_JS, door=True)


def render_code(biz: Dict[str, Any], site=None, *, email: str, error: str = "") -> str:
    import member_app_signin as sg
    return _shell(biz, site, "Enter your code",
                  sg.code_body(biz, site, email=email, shown=show_ident(email), texted=is_phone(email), error=error),
                  script=sg.CODE_JS, door=True)


def render_try_again(biz: Dict[str, Any], site=None) -> str:
    return _door_page(biz, site, "Try again", icon="refresh", heading="We couldn't open your page just now", body="""
<p>Nothing is wrong with your account. Please try again in a moment.</p>""",
                      actions='<a class="mp-go si-go" href="/my">Try again</a>')


def render_shared_address(biz: Dict[str, Any], site=None) -> str:
    return _door_page(biz, site, "Ask the church office", icon="users",
                      heading="This email is on more than one person's record", body=f"""
<p>To keep everyone's giving private, each person signs in with their own email, so this one can't be used.
Ask {_e(biz.get('name') or 'the church office')} to put your own email on your record, then sign in with that.</p>""",
                      actions='<a class="mp-go mp-go-2" href="/my">Back</a>')


def render_choose(biz: Dict[str, Any], site, people: List[Dict[str, Any]]) -> str:
    import member_app_signin as sg
    return _door_page(biz, site, "Who's signing in?", icon="users", heading="Who's signing in?", body=f"""
<p>This email is on more than one person's record at {_e(biz.get('name') or 'the church')}, so
anyone who reads it can see each of these people's giving. Choose yourself.</p>""", actions=sg.people_list(people))


def render_give_off(biz: Dict[str, Any], site, me: Dict[str, Any], *, preview: bool = False) -> str:
    """The Give tab before the church takes gifts in the app: the church's
    own giving page when its site has one (a hand-built site's give.html —
    Love City's still holds its Subsplash form), giving in person, and the
    member's own giving so far (gifts imported or recorded by the office).
    The owner's preview says where online giving is switched on."""
    import member_app_ui as ui
    import member_app_photos as photos
    church = (biz.get("name") or "").strip() or "the church"
    pool = photos.photos(biz, site)
    pic, look = photos.choose(biz, "give", pool, words=("giv", "basket", "offering"))
    art = ui.picture(pic, look, "giving", eager=True, night=True)
    online = photos.has_site_page(site, "give")
    action = (f'<div class="mb-hero-row"><a class="mp-go" href="/give">{ui.icon("give", 18)}Give online</a></div>'
              if online else "")
    lead = ("Give online on our website, or in person at any service." if online
            else "Give in person at any service. Giving in the app is on its way.")
    hint = (ui.sample_hint("Online giving isn't on yet. Turn it on in Operate, Payments, and this tab takes gifts "
                           "right in the app, with the member's name and email filled in.") if preview else "")
    body = f"""<div class="mb-lt"><h1>Give</h1></div>
<p class="mb-sub" style="margin:0 0 16px">To {_e(church)}. Thank you for your generosity.</p>
{hint}
<section class="mb-hero" aria-labelledby="mb-give-h">{art}<div class="mb-hero-in">
<span class="mb-when">Ways to give</span><h2 id="mb-give-h">Every gift matters</h2><p>{_e(lead)}</p>{action}</div></section>
<a class="mb-row" href="/my/me#mp-giving"><span class="mb-row-ic">{ui.icon("doc", 20)}</span>
<span class="mb-row-t"><strong>Your giving</strong><span>This year, each gift and your statement</span></span>{ui.icon("chevron", 18)}</a>
<div class="mb-row" style="cursor:default"><span class="mb-row-ic">{ui.icon("heart", 20)}</span>
<span class="mb-row-t"><strong>In person</strong><span>During any service at {_e(church)}</span></span></div>"""
    return _shell(biz, site, "Give", body, tab="give", who=me)


def prayer_card() -> str:
    import member_app_ui as ui
    return (f'<a class="mb-pray" href="/my/prayer"><span class="mb-pray-ic">{ui.icon("pray", 22)}</span>'
            f'<span><strong>How can we pray for you?</strong><span>It goes privately to the pastors.</span></span>'
            f'{ui.icon("chevron", 18)}</a>')


def render_home(biz: Dict[str, Any], site, *, me: Dict[str, Any], occasions, groups, library,
                give_url: str, flash: str = "", live: Optional[Dict[str, Any]] = None,
                reading: str = "", bible: str = "kjv", where: Optional[Tuple[str, int]] = None,
                checkin: str = "", serving: str = "", edit: bool = False, devotional: str = "", news: str = "",
                news_n: Optional[int] = None, celebrate: str = "", ask: str = "") -> str:
    """Home ("Member App, Top Tier", Kevin approved 2026-10-15; round three
    2026-10-19): the greeting, the next gathering on the church's own photo
    (a Live now card while the church is live; the church itself when
    nothing is on the calendar), shorter now, four quick ways in, each in its
    colour, Today (the verse of the day with today's reading, or where they
    left off, in one card), the latest message (its art, the title under it,
    as members know from Subsplash), the church's own tiles, this week, and
    prayer.

    Nothing here ever says "nothing yet": a block with nothing in it is
    left out, and the verse, the Bible and prayer always have something.
    The greeting and date are set by the phone's own clock (the server
    can't know the member's time of day); without script it reads
    "Hi, Ana.". `reading` is today's reading row (member_portal_reading
    .today_row), '' when no plan is running; `devotional` today's
    devotional row (member_portal_devotionals.today_row). `edit` (the owner in a
    preview, or someone the owner named, at /my?edit=pictures) puts a
    Change button on each picture (member_app_pictures)."""
    import member_app_ui as ui
    import member_app_photos as photos
    import member_portal_bible as mpb
    import member_portal_church as mpc
    import member_portal_sermons as mps
    import member_app_install as mai
    import member_push
    import member_portal_news as mpn
    import member_portal_celebrations as mcl
    if news or celebrate:
        news = f"<style>{mpn.NEWS_CSS}{mcl.CEL_CSS if celebrate else ''}</style>{news}"
    pal = palette_for(biz, site)
    pool = photos.photos(biz, site)
    used: set = set()
    hero_pic, hero_look = photos.choose(biz, "home", pool, fallback=photos.hero(pool), look="church", used=used)
    hello = first_name(me.get("name") or "") or "there"
    church = (biz.get("name") or "").strip() or "Your church"
    hero = (mpc.live_hero(live, hero_pic, church, look=hero_look) if live else
            mpc.next_card(occasions, pic=hero_pic, church=church, look=hero_look)
            or mpc.church_hero(hero_pic, church, look=hero_look))
    quick = "".join(f'<a class="h-{hue}" href="{href}"><i class="mb-qd">{ui.icon(ic, 20)}</i>{label}</a>'
                    for hue, href, ic, label in (("brand", "/my/prayer", "pray", "Prayer"),
                                                 ("coral", "/my/events", "calendar", "Events"),
                                                 ("teal", "/my/groups", "users", "Groups"),
                                                 ("violet", "/my/live", "live", "Live")))
    script = """<script>(function(){var d=new Date(),h=d.getHours();
var g=h<12?'Good morning':(h<17?'Good afternoon':'Good evening');
var t=document.querySelector('.mb-date');if(t){t.textContent=d.toLocaleDateString(undefined,{weekday:'long',month:'long',day:'numeric'});}
var e=document.querySelector('[data-first]');if(e){var em=document.createElement('em');em.textContent=e.getAttribute('data-first')+'.';
e.textContent='';e.append(g+', ',em);}
})();</script>"""
    first = str(((occasions or [{}])[0] or {}).get("entry_id") or "") if hero and not live and occasions else ""
    editbar = ""
    if edit:
        editbar = (f'<div class="mb-editbar" role="status"><span class="mb-editbar-ic">{ui.icon("camera", 18)}</span>'
                   f'<span class="mb-editbar-t"><strong>Changing pictures</strong><span>Only you see these buttons.</span></span>'
                   f'<a class="mb-editbar-a" href="/my/pictures">All</a><a class="mp-go mb-editbar-done" href="/my">Done</a></div>')
        if hero.startswith("<section"):
            hero = hero.replace('<div class="mb-hero-in">', ui.pin("/my/pictures/spot?key=home&amp;back=home")
                                + '<div class="mb-hero-in">', 1)
    today = (f'<section class="h-gold" aria-labelledby="mb-today-h">{ui.section("Today", "/my/bible/plans", "Plans", hid="mb-today-h")}'
             f'<div class="mb-today">{mpb.verse_card(bible)}{devotional}{reading or mpb.continue_row(where, bible)}</div></section>')
    return _shell(biz, site, "Home", f"""
{editbar}
<div class="mb-hello-wrap"><p class="mb-date" aria-hidden="true"></p>
<h1 class="mb-hello" data-first="{_e(hello)}">Hi, <em>{_e(hello)}.</em></h1></div>
{checkin}
{serving}
{f'<div style="display:flex;flex-direction:column;gap:12px;margin:6px 0 16px">{celebrate}</div>' if celebrate else ''}
{hero}
<nav class="mb-quick" aria-label="Quick ways in">{quick}</nav>
{flash}
{news}
{today}
{mps.latest_card(library, pal, pool=pool, used=used, site=site)}
{mpc.home_tiles(biz, site, pool, used, edit=edit)}
{mpc.week_cards(occasions, groups, pal=pal, pool=pool, used=used, skip=first, biz=biz, edit=edit)}
{mai.install_card(church)}
{member_push.home_card(biz)}
{prayer_card()}
{ask}""", tab="home", who=me, script=script + (mpn.RX_JS if news else "") + (mcl.STRIP_JS if celebrate else ""),
                  news_n=news_n)


def _month_bars(gifts: List[Dict[str, Any]], year: int, this_year: int) -> str:
    """Twelve bars, one per month of the year shown; the current month
    (or, for a past year, the biggest) is the bright one."""
    totals = [0.0] * 12
    for g in gifts:
        try:
            m = int(str(g.get("date") or "")[5:7]) - 1
        except ValueError:
            continue
        if 0 <= m < 12:
            totals[m] += max(0.0, float(g.get("amount") or 0))
    top = max(totals) or 1.0
    hi = date.today().month - 1 if year == this_year else totals.index(max(totals))
    bars = "".join(f'<i{" class=\"mb-on\"" if i == hi else ""} style="height:{max(6, round(v / top * 100))}%"></i>'
                   for i, v in enumerate(totals))
    months = "".join(f"<span>{m}</span>" for m in "JFMAMJJASOND")
    return f'<div class="mb-bars" aria-hidden="true">{bars}</div><div class="mb-months" aria-hidden="true">{months}</div>'


def render_me(biz: Dict[str, Any], site, *, me: Dict[str, Any], people: List[Dict[str, Any]],
              year: int, gifts: Optional[List[Dict[str, Any]]], give_url: str,
              this_year: int, flash: str = "", pictures: bool = False, serving: bool = False,
              asks: Optional[List[str]] = None) -> str:
    """Me: who's signed in, their giving (a year's total, month by month,
    each gift and the statement), then the ways to look after their own
    record, and sign out. `pictures` (the owner in a preview, or someone
    the owner named) adds the app's pictures; `asks` (member_asks.entry)
    adds Ask the church."""
    import member_asks
    import member_portal_messaging as mpm
    import member_push
    msgs_on = mpm.turned_on(biz)
    notes_on = bool(member_push.church_kinds(biz.get("settings")) - set(member_push.OWN_PAGE_KINDS)) and member_push.ready()
    import church_follow_up as cfu
    celebrations = cfu.is_church(biz)
    import member_app_ui as ui
    years = "".join(
        f'<a href="/my/me?year={y}#mp-giving"{" aria-current=\"page\"" if y == year else ""}>{y}</a>'
        for y in range(this_year, this_year - 4, -1))
    statement = ""
    bars = ""
    if gifts is None:
        giving = ('<p class="mp-err" role="alert">Your giving couldn\'t load just now. Your gifts are safe — '
                  'please try again in a moment.</p>')
    elif not gifts:
        giving = f'<p class="mp-muted" style="margin:0">No gifts recorded for {year}.</p>'
    else:
        total = sum(g["amount"] for g in gifts)
        items = "".join(
            f'<li><span>{_e(_day(g["date"]))} · {_e(g["fund"])}{" (refunded)" if g["refunded"] else ""}</span>'
            f'<span>{money(g["amount"])}</span></li>' for g in gifts)
        bars = _month_bars(gifts, year, this_year)
        giving = (f'<details class="mb-each"><summary>See each gift ({len(gifts)})</summary><ul class="mp-gifts">{items}</ul></details>')
        statement = (f'<a class="mp-go mp-go-2" href="/my/statement?year={year}" aria-label="{year} statement">'
                     f'{ui.icon("doc", 16)}Statement</a>')
    total_html = (f'<p class="mp-total">{money(sum(g["amount"] for g in gifts))}</p>' if gifts else "")
    give = f'<a class="mp-go" href="{_e(give_url)}">{ui.icon("give", 17)}Give</a>' if give_url else ""
    buttons = (f'<div class="mb-give-row">{give}{statement}</div>' if give and statement else
               (f'<div style="margin-top:14px">{give or statement}</div>' if (give or statement) else ""))
    switch = ('<form method="post" action="/my/person"><input type="hidden" name="cid" value="">'
              '<button class="mp-link" type="submit">Not you? Choose someone else in your household</button></form>'
              if len(people) > 1 else "")
    link = lambda href, ic, title, sub: (
        f'<li><a href="{href}"><span class="mb-list-ic">{ui.icon(ic, 17)}</span><span class="mb-list-text"><strong>{title}</strong>'
        f'<span>{sub}</span></span>{ui.icon("chevron", 16)}</a></li>')
    recurring = link('/my/gifts', 'give', 'Recurring gifts', 'Change, pause or stop one') if give_url else ''
    import member_photos as ph
    import member_messaging_rules as rules
    has = bool(ph.of(me))
    age = rules.age(me.get("birthdate"))
    seen = ("Only your parents and the church staff see it." if age is not None and age < 18 else
            "Members you message and the church staff see it." if age is not None else
            "The church staff see it, so they know who you are.")
    remove = ('<form method="post" action="/my/photo/remove" class="mp-noprint"><button class="mp-link" type="submit" '
              'style="padding:0;min-height:32px">Remove photo</button></form>' if has else "")
    photo = f"""<form class="mb-photo" method="post" action="/my/photo" enctype="multipart/form-data">
  <label class="mb-photo-pick" for="mb-photo-in">{ph.avatar(me, show=True)}<span class="mb-photo-badge" aria-hidden="true">{ui.icon('camera', 15)}</span>
  <span class="mp-sr">{'Change your photo' if has else 'Add a photo of you'}</span></label>
  <input class="mp-sr" id="mb-photo-in" type="file" name="photo" accept="image/jpeg,image/png,image/webp,image/*">
  <noscript><button class="mp-link" type="submit">Save photo</button></noscript>
</form>"""
    script = """<script>(function(){var i=document.getElementById('mb-photo-in');if(!i)return;
i.addEventListener('change',function(){if(!i.files||!i.files.length)return;var n=document.getElementById('mb-photo-note');
if(n){n.textContent='Saving your photo\u2026';}i.form.submit();});})();</script>"""
    return _shell(biz, site, "Me", f"""
<div class="mb-profile">{photo}
  <h1>{_e(me.get('name') or 'Me')}</h1>
  <span class="mp-muted">{_e(me.get('email') or '')}{' · ' if me.get('email') else ''}{_e(biz.get('name') or 'the church')}</span>
  <p class="mb-photo-note" id="mb-photo-note" role="status">{'Tap your photo to change it. ' if has else 'Tap to add a photo of you. '}{seen}</p>
  {remove}</div>
{flash}
<section class="mb-give-card" aria-labelledby="mp-giving">
  <div class="mb-give-top"><div><span class="mb-kick" id="mp-giving">Your giving · {year}</span>{total_html}</div>{bars}</div>
  <nav class="mp-years" aria-label="Year" style="margin-top:14px">{years}</nav>
  {giving}
  {buttons}
</section>
{ui.section('Your church life')}
<ul class="mb-list mb-cards" style="--inset:60px">
  {link('/my/events', 'calendar', 'Coming up', 'Say you&#x27;re coming, or sign up to serve')}
  {link('/my/serving', 'clock', 'My serving', 'Your Sundays, away dates and swaps') if serving else ''}
  {link('/my/groups', 'users', 'My groups', 'Your groups, and ones you can join')}
  {link('/my/messages', 'chat', 'Messages', 'Your chats and group chats') if msgs_on else ''}
  {link('/my/prayer', 'pray', 'Prayer', 'A private request to the pastors')}
  {link('/my/ask', 'send', 'Ask the church', _e(member_asks.me_sub(asks))) if asks else ''}
  {recurring}
  {link('/my/notifications', 'bell', 'Notifications', 'What this app tells you about') if notes_on else ''}
  {link('/my/details', 'user', 'My details', 'Phone and mailing address')}
  {link('/my/me/celebrations', 'star', 'Celebrations', 'Your birthday, anniversary and milestones') if celebrations else ''}
  {link('/my/pictures', 'camera', 'Pictures in the app', 'Choose the photo for every spot') if pictures else ''}
</ul>
<div class="mp-noprint" style="margin-top:8px">{switch}
<form method="post" action="/my/signout"><button class="mb-signout" type="submit">Sign out</button></form></div>""",
                  tab="me", who=me, back=("/my", "Home"), script=script)


def render_statement(biz: Dict[str, Any], site, stmt: Dict[str, Any],
                     who: Optional[Dict[str, Any]] = None) -> str:
    year = stmt.get("year")
    if stmt.get("empty"):
        body = (f'<h1>{_e(year)} statement</h1><p class="mp-muted">No gifts are recorded for you in {_e(year)}.</p>'
                '<p><a href="/my/me">Back to Me</a></p>')
        return _shell(biz, site, f"{year} statement", body, tab="me", who=who)
    rows = "".join(
        f'<tr><td>{_e(_day(g["date"]))}</td><td>{_e(g["fund"])}{" (refunded)" if g.get("refunded") else ""}</td>'
        f'<td class="n">{money(g["amount"])}</td></tr>' for g in stmt.get("gifts") or [])
    donor = stmt.get("donor") or {}
    body = f"""
<h1>Contribution statement, {_e(year)}</h1>
<p><strong>{_e(stmt.get('organisation') or biz.get('name') or '')}</strong><br>
For {_e(donor.get('name') or '')}{(' · ' + _e(donor.get('email'))) if donor.get('email') else ''}</p>
<table><thead><tr><th>Date</th><th>Fund</th><th class="n">Amount</th></tr></thead><tbody>{rows}</tbody>
<tfoot><tr><th colspan="2">Total</th><th class="n">{money(float(stmt.get('total') or 0))}</th></tr></tfoot></table>
<p style="margin-top:16px">{_e(stmt.get('declaration') or '')}</p>
<p class="mp-muted">{_e(stmt.get('disclaimer') or '')}</p>
<p class="mp-muted">Prepared {_e(_day(stmt.get('generated_on') or ''))}.</p>
<div class="mp-noprint mp-row">
  <button class="mp-go" type="button" id="mp-print">Print or save as PDF</button>
  <a class="mp-link" href="/my/me?year={_e(year)}">Back to Me</a>
</div>"""
    script = "<script>document.getElementById('mp-print').addEventListener('click',function(){window.print();});</script>"
    return _shell(biz, site, f"{year} statement", body, script=script, tab="me", who=who)


def _day(iso: str) -> str:
    try:
        d = date.fromisoformat(str(iso)[:10])
        return f"{d.strftime('%b')} {d.day}, {d.year}"
    except ValueError:
        return str(iso or "")


# ─── GET (called from public_site.subdomain_catch_all) ───────────────


def _page(content: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(content=content, status_code=status, headers=_SECURE_HEADERS)


def _year_arg(request: Request, this_year: int) -> int:
    try:
        y = int(request.query_params.get("year") or this_year)
    except ValueError:
        return this_year
    return y if 2000 <= y <= this_year else this_year


async def serve(request: Request, path: str) -> HTMLResponse:
    church = await asyncio.to_thread(_church_for_request, request)
    if not church:
        raise HTTPException(404, "Not found")
    biz, site = church["business"], church["site"]
    sub = path.rstrip("/") or "/my"
    if sub == "/my/preview":
        return await asyncio.to_thread(_open_preview, request, biz, site)
    # The owner's preview works before the page is switched on.
    if not portal_active(biz) and not _previewing(request, biz):
        return _page(render_unavailable(biz, site), 404)
    # Installing the page as an app (member_app_install.py): the manifest,
    # icons, service worker and offline page need no sign-in.
    import member_app_install as mai
    if sub in mai.ASSETS:
        return mai.serve_asset(biz, site, sub)
    if sub == "/my/offline":
        return _page(mai.render_offline(biz, site))
    sess = await asyncio.to_thread(_session_for, request, church)
    if sess and sess.get("me") and not sess.get("unavailable"):
        # Church, Youth or Kids (member_spaces): a teen is always in Youth;
        # anyone else in the space they switched to, if it's theirs.
        import member_spaces as msp
        # A member who holds a church role (or is asked to) gets the Lead
        # tab (member_portal_lead), in Church. The owner's preview never does.
        # Read alongside the space, not after it: every tab waits on both.
        import church_follow_up as cfu
        may_lead = not sess.get("preview") and cfu.is_church(biz) and not msp.is_youth(sess["me"])
        ctx, lead = await asyncio.gather(
            msp.resolve_async(biz["id"], sess["me"], request.cookies.get(msp.COOKIE) or ""),
            _leads(biz["id"], str(sess["me"]["id"]), biz, sess["me"]) if may_lead else _nothing())
        if may_lead and ctx.get("space", "church") == "church":
            ctx = dict(ctx, lead=lead)
        msp.CURRENT.set(ctx)
    resp = await _serve_page(request, church, sess, sub)
    if sess and sess.get("preview") and isinstance(resp, HTMLResponse):
        import member_portal_preview as pv
        resp = _page(pv.mark(resp.body.decode("utf-8"), (sess["me"] or {}).get("name") or ""), resp.status_code)
    return resp


async def _nothing():
    return None


async def _leads(business_id: str, me_id: str, biz: Optional[Dict[str, Any]] = None,
                 me: Optional[Dict[str, Any]] = None) -> bool:
    """Whether this member gets the Lead tab: a church role, held or asked
    (church_follow_up), or a group they lead (group_lead: their group lives
    on the Lead tab). Both read at once. With Who sees what on, it's the
    Serve tab, for every part: a place on a Sunday team too, or a kids room.
    A task the office handed them (church_leader_tasks) gives it too."""
    import church_follow_up as cfu
    import group_lead
    roles, led = await asyncio.gather(asyncio.to_thread(cfu.roles_for, business_id, me_id),
                                      asyncio.to_thread(group_lead.led_groups, business_id, me_id))
    if roles or led:
        return True
    if biz is not None:
        import church_leader_tasks
        if await asyncio.to_thread(church_leader_tasks.section, biz, me_id) is not None:
            return True
    import member_app_ui
    if biz is None or not member_app_ui.serve_mode():
        return False
    import member_portal_lead
    parts = await asyncio.to_thread(member_portal_lead.parts, biz, me_id, (me or {}).get("email"))
    return bool(parts["serving"] or parts["kids"] or parts["team"])


def _open_preview(request: Request, biz: Dict[str, Any], site) -> HTMLResponse:
    """The owner's one-time preview link: trade it for an hour-long
    preview cookie and land on Home. An expired or used link says so."""
    import member_portal_preview as pv
    claims = (pv.redeem_link_token(biz["id"], str(request.query_params.get("t") or ""))
              if portal_eligible(biz) else None)
    if not claims:
        return _page(_shell(biz, site, "Preview", """
<div class="mp-card"><h1>This preview link has expired</h1>
<p class="mp-muted">Preview links work once, for two minutes. Open a new one from Settings → Member page in the app.</p></div>"""), 410)
    # "Change pictures" in Settings → Member page opens the preview on the
    # app's pictures (member_app_pictures); any other link lands on Home.
    to = "/my/pictures" if request.query_params.get("next") == "pictures" else "/my"
    resp = RedirectResponse(to, status_code=303, headers=_SECURE_HEADERS)
    pv.set_cookie(resp, pv.mint_session(biz["id"], claims["cid"], claims.get("own") or ""))
    return resp


async def _serve_page(request: Request, church: Dict[str, Any], sess, sub: str):
    biz, site = church["business"], church["site"]
    if sess and sess.get("unavailable"):
        return _page(render_try_again(biz, site), 503)
    if not sess:
        if sub != "/my":
            return RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
        if not sign_in_open(biz):
            return _page(render_signin_paused(biz, site))
        return _page(render_signin(biz, site))
    if not sess["me"]:
        return _page(render_choose(biz, site, sess["people"]))
    me, this_year = sess["me"], date.today().year
    year = _year_arg(request, this_year)
    # The owner's preview fills what the church hasn't added yet with
    # tagged samples (member_app_samples); a member never sees one.
    import member_app_samples as samples
    preview = bool(sess.get("preview"))

    def fill(found, kind):
        return samples.fill(found, kind, preview)
    if sub == "/my/space":
        import member_spaces as msp
        ctx = msp.CURRENT.get() or {}
        to = str(request.query_params.get("to") or "")
        resp = RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
        if to in (ctx.get("options") or []):
            resp.set_cookie(msp.COOKIE, to, max_age=SESSION_TTL_SECONDS, path=COOKIE_PATH, httponly=True,
                            secure=True, samesite="lax")
        return resp
    if sub.startswith("/my/photo/"):
        import member_photos as ph
        from fastapi.responses import Response
        cid = sub[len("/my/photo/"):]
        if not UUID_RE.match(cid):
            return Response(status_code=404, headers=_SECURE_HEADERS)
        link = await asyncio.to_thread(ph.link_for, biz["id"], cid, str(me["id"]))
        if link is None:
            return Response(status_code=503, headers=_SECURE_HEADERS)
        if not link:
            return Response(status_code=404, headers=_SECURE_HEADERS)
        return RedirectResponse(link, status_code=302,
                                headers={**_SECURE_HEADERS, "Cache-Control": "private, max-age=600"})
    if sub == "/my/statement":
        import giving_statements
        gs = (biz.get("settings") or {}).get("giving") or {}
        try:
            stmt = await asyncio.to_thread(
                giving_statements.statement_for_contact, biz["id"], me["id"], year,
                org_name=biz.get("name"),
                goods_and_services=(gs.get("goods_and_services") if isinstance(gs, dict) else None) or "none")
        except Exception:
            logger.warning("member statement read failed", exc_info=True)
            return _page(_shell(biz, site, "Statement", '<p class="mp-err" role="alert">Your statement '
                                "couldn't load just now. Please try again in a moment.</p>"
                                '<p><a href="/my/me">Back to Me</a></p>', tab="me", who=me), 503)
        return _page(render_statement(biz, site, stmt, who=me))
    # Part 2 (member_portal_church.py): coming up, prayer, my details.
    import member_portal_church as mpc
    import member_portal_sermons as mps
    # The church's news (member_portal_news): the feed and one post with its
    # comments. The owner's preview reads it; nothing saves.
    if sub == "/my/news" or sub.startswith("/my/news/"):
        import member_portal_news as mpn
        out = await mpn.serve(request, biz, site, me, sub)
        if isinstance(out, tuple):
            return _page(out[0], out[1])
        return out
    if sub == "/my/events":
        occ = fill(await asyncio.to_thread(mpc.upcoming_for, biz["id"], me), "occasions")
        return _page(mpc.render_events(biz, site, request, occ, who=me))
    if sub == "/my/prayer":
        return _page(mpc.render_prayer(biz, site, request, who=me))
    # Ask the church (member_asks.py): only the asks the church turned on,
    # each landing in the office queue that already handles it.
    if sub == "/my/ask" or sub.startswith("/my/ask/"):
        import member_asks
        out = await member_asks.serve(request, biz, site, me, sub)
        if isinstance(out, tuple):
            return _page(out[0], out[1])
        return out
    if (sub == "/my/lead" or sub.startswith("/my/lead/")) and not preview:
        import church_follow_up as cfu
        import member_portal_lead as mpl
        if not cfu.is_church(biz):
            return RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
        html, status = await mpl.serve(request, biz, site, me, sub)
        return _page(html, status)
    if sub in ("/my/groups", "/my/classes", "/my/messages", "/my/directory") or sub.startswith("/my/messages/"):
        # Connect's Classes tab: when the church has a published class, or
        # in the owner's preview (member_portal_classes).
        import member_portal_classes as mcl
        mcl.TAB.set(preview or await asyncio.to_thread(mcl.classes_on, biz["id"]))
    # The member directory (member_directory.py): served only while the
    # church has it on, and only in Church (never in Youth or Kids, even
    # for an adult leader who switched there).
    if sub == "/my/directory":
        import member_directory as mdir
        import member_spaces as msp
        if not mdir.church_on(biz) or (msp.CURRENT.get() or {}).get("space", "church") != "church":
            return RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
        html, status = await mdir.serve(request, biz, site, me)
        return _page(html, status)
    if sub == "/my/classes":
        import member_portal_classes as mcl
        data = fill(await asyncio.to_thread(mcl.classes_for, biz["id"], me), "classes")
        return _page(mcl.render_classes(biz, site, request, data, who=me))
    if sub == "/my/messages" or sub.startswith("/my/messages/"):
        import member_portal_messaging as mpm
        out = await mpm.serve(request, biz, site, me, sub)
        if isinstance(out, tuple):
            return _page(out[0], out[1])
        return out
    if sub.startswith("/my/groups/live/"):
        import member_portal_group_live as mgl
        sid = sub[len("/my/groups/live/"):]
        if not UUID_RE.match(sid):
            return RedirectResponse("/my/groups", status_code=303, headers=_SECURE_HEADERS)
        s = await asyncio.to_thread(mgl.session, biz["id"], sid)
        g = m = False
        if s:
            g, m = await asyncio.gather(asyncio.to_thread(mgl.group, biz["id"], s["group_id"]),
                                        asyncio.to_thread(mgl.membership, biz["id"], s["group_id"], me["id"]))
        html, status = mgl.render_meeting(biz, site, me, s, g, m)
        return _page(html, status)
    if sub == "/my/groups":
        import member_portal_messaging as mpm
        # The All group leaders room's door, for the people in it, read
        # alongside the groups (render_groups shows it only when they loaded).
        import sunday_serving as ssv
        data, room, serving = await asyncio.gather(
            asyncio.to_thread(mpc.groups_for, biz["id"], me),
            asyncio.to_thread(mpm.in_leaders_room, biz["id"], str(me["id"])) if mpm.turned_on(biz) else _nothing(),
            asyncio.to_thread(ssv.serves, biz, str(me["id"])))
        data = fill(data, "groups")
        return _page(mpc.render_groups(biz, site, request, data, who=me, room=bool(room), serving=bool(serving)))
    # A group's own page (member_portal_groups): Home, Board, People. The
    # owner's preview reads it as the member they chose; nothing saves.
    if sub.startswith("/my/groups/"):
        import member_portal_groups as mpg
        html, status = await mpg.serve(request, biz, site, me, sub)
        return _page(html, status)
    # The app's pictures (member_app_pictures): the owner, from a preview,
    # and the people the owner named; nobody else sees these pages.
    import member_app_pictures as mapic
    can_picture = bool(mapic.may_edit(sess, biz))
    if sub in ("/my/pictures", "/my/pictures/spot"):
        if not can_picture:
            return RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
        import devotionals as devs_mod
        occ_all, groups_all, devs_all = await asyncio.gather(asyncio.to_thread(mpc.upcoming_for, biz["id"], me),
                                                             asyncio.to_thread(mapic.church_groups, biz["id"]),
                                                             asyncio.to_thread(devs_mod.catalog, biz["id"]))
        if sub == "/my/pictures":
            return _page(mapic.render_list(biz, site, request, me, occ_all, groups_all, devs_all))
        spot = mapic.find_spot(biz, str(request.query_params.get("key") or ""), occ_all, groups_all, devs_all)
        if not spot:
            return RedirectResponse("/my/pictures", status_code=303, headers=_SECURE_HEADERS)
        return _page(mapic.render_spot(biz, site, request, me, spot))
    if sub == "/my/details":
        import member_directory as mdir
        full, directory = await asyncio.gather(asyncio.to_thread(mpc.load_me, biz["id"], me["id"]),
                                               asyncio.to_thread(mdir.details_block, biz, str(me["id"])))
        if not full:
            return _page(render_try_again(biz, site), 503)
        return _page(mpc.render_details(biz, site, request, full, directory))
    if sub == "/my/notifications":
        import member_push
        import group_chat_notify as gcn
        off, quiet, chats = await asyncio.gather(asyncio.to_thread(member_push.turned_off, biz["id"], me["id"]),
                                                 asyncio.to_thread(member_push.quiet_prefs, biz["id"], me["id"]),
                                                 asyncio.to_thread(gcn.my_chats, biz, str(me["id"])))
        return _page(member_push.render_page(biz, site, request, me, off, quiet, chats))
    from giving_router import giving_is_active
    # Giving opens inside the app (2026-10-14): /my/give is the give
    # page's own form in the app's look, the member's name and email filled.
    give_url = "/my/give" if giving_is_active(biz) else ""
    if sub == "/my/give":
        if not give_url:
            # Give is always a tab (Kevin, 2026-10-15): before online
            # giving is on, it says how to give instead.
            return _page(render_give_off(biz, site, me, preview=preview))
        full = await asyncio.to_thread(mpc.load_me, biz["id"], me["id"]) or me
        return _page(render_give(biz, site, full, preview=preview))
    # A giver's own recurring gifts (member_portal_gifts.py).
    if sub == "/my/gifts":
        import member_portal_gifts as mpg
        full = await asyncio.to_thread(mpc.load_me, biz["id"], me["id"]) or me
        mine = await mpg.recurring_gifts(biz, full.get("email") or "")
        return _page(mpg.render_gifts(biz, site, request, full, mine, give_url),
                     503 if mine is None else 200)
    # Live, inside the app (member_portal_live.py).
    if sub in ("/my/live", "/my/live/feed"):
        import live_router as lr
        import member_portal_live as mpl
        from fastapi.responses import JSONResponse
        if sub == "/my/live/feed":
            try:
                v = int(request.query_params.get("v") or -1)
            except ValueError:
                v = -1
            data = await asyncio.to_thread(mpl.feed, biz["id"], me, v)
            return JSONResponse(data, status_code=503 if data.get("error") else 200, headers=_SECURE_HEADERS)
        cur = await asyncio.to_thread(lr.current, biz["id"])
        if cur:
            msgs, here_me, muted_me = await asyncio.gather(
                asyncio.to_thread(lr.messages, biz["id"], cur["id"], False, mpl.FEED_LIMIT),
                asyncio.to_thread(mpl.i_am_here, biz["id"], cur["id"], me["id"]),
                asyncio.to_thread(mpl.is_muted, biz["id"], cur["id"], me["id"]))
            return _page(mpl.render_live(biz, site, request, me, cur, msgs=msgs, here_me=here_me, muted_me=muted_me))
        occ, lib = (None, None)
        if cur == {}:
            occ, lib = await asyncio.gather(asyncio.to_thread(mpc.upcoming_for, biz["id"], me),
                                            asyncio.to_thread(mps.load_library, biz["id"]))
            occ, lib = fill(occ, "occasions"), fill(lib, "library")
        return _page(mpl.render_live(biz, site, request, me, cur, occasions=occ, library=lib),
                     503 if cur is None else 200)
    # The Bible (member_portal_bible.py).
    if sub == "/my/bible" or sub.startswith("/my/bible/"):
        import member_portal_bible as mpb
        return await mpb.serve(request, biz, site, me, sub, preview=preview)
    # Sermons, inside the app (member_portal_sermons.py).
    if sub == "/my/sermons" or sub.startswith("/my/sermons/"):
        rest = sub[len("/my/sermons"):].strip("/")
        import member_portal_bible as mpb
        if not rest:
            series = str(request.query_params.get("series") or "")
            # Watch leads with live, or the next gathering: all three at once.
            import live_router as lr
            lib, live, occ = await asyncio.gather(asyncio.to_thread(mps.load_library, biz["id"]),
                                                  asyncio.to_thread(lr.current, biz["id"]),
                                                  asyncio.to_thread(mpc.upcoming_for, biz["id"], me))
            lib, occ = fill(lib, "library"), fill(occ, "occasions")
            return _page(mps.render_library(biz, site, me, lib, series if UUID_RE.match(series) else "",
                                            bible=mpb.prefs(request)[0], live=live or None,
                                            next_occ=(occ or [None])[0]),
                         200 if lib is not None else 503)
        lib = fill(await asyncio.to_thread(mps.load_library, biz["id"]), "library")
        page = (mps.render_sermon(biz, site, me, lib, rest, give_url, bible=mpb.prefs(request)[0])
                if UUID_RE.match(rest) else None)
        if page is None:
            return RedirectResponse("/my/sermons", status_code=303, headers=_SECURE_HEADERS)
        return _page(page, 200 if lib is not None else 503)
    # Me → Celebrations (member_portal_celebrations): what the church celebrates.
    if sub == "/my/me/celebrations":
        import member_portal_celebrations as mcl
        html, status = await mcl.serve_me(request, biz, site, me)
        return _page(html, status)
    if sub == "/my/me":
        try:
            gifts: Optional[List[Dict[str, Any]]] = await asyncio.to_thread(gifts_for, biz["id"], me["id"], year)
        except Exception:
            logger.warning("member giving read failed", exc_info=True)
            gifts = None
        import sunday_serving as ssv
        serving = await asyncio.to_thread(ssv.serves, biz, str(me["id"]))
        return _page(render_me(biz, site, me=me, people=sess["people"], year=year, gifts=gifts,
                               give_url=give_url, this_year=this_year, flash=mpc._flash(request),
                               pictures=can_picture, serving=serving, asks=await _ask_entry(biz, me)))
    # The church's reading plan (reading_plans.py, member_portal_reading.py).
    import reading_plans as rp
    import member_portal_reading as mpr
    if sub == "/my/reading":
        plan = rp.current(biz)
        done = await asyncio.to_thread(rp.read_days, biz["id"], me["id"], plan) if plan else set()
        return _page(mpr.render_page(biz, site, request, me, done), 503 if done is None else 200)
    if sub.startswith("/my/kids/"):
        import member_spaces_kids as mk
        return await mk.serve(request, church, me, sub)
    # Sunday check-in (member_portal_checkin.py): the code on the welcome
    # slide opens the church's /here, which lands here.
    if sub == "/my/here":
        import church_checkin as cc
        import member_portal_checkin as mpk
        c = await asyncio.to_thread(cc.card, biz, me)
        return _page(mpk.render_page(biz, site, request, me, c), 503 if c.get("state") == "error" else 200)
    # My serving (ChurchSavvy Planning: sunday_serving.py, member_portal_serving.py).
    if sub == "/my/serving" or sub.startswith("/my/serving/"):
        import member_portal_serving as mpsv
        return await mpsv.serve(request, church, me, sub)
    # Get paid back, under Serve (church_checks.py, member_portal_checks.py).
    if sub == "/my/paid-back" or sub.startswith("/my/paid-back/"):
        import member_portal_checks as mpck
        return await mpck.serve(request, church, me, sub, preview=preview)
    if sub != "/my":
        return RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
    import live_router as lr
    import member_portal_devotionals as mpd
    import member_spaces as msp
    import church_follow_up as cfu
    ctx = msp.CURRENT.get() or {}
    space = ctx.get("space")
    today = rp.today_for(biz)

    async def checkin_card() -> str:
        # While Sunday check-in is open its card leads Home (church_checkin).
        import church_checkin as cc
        import member_portal_checkin as mpk
        try:
            return mpk.home_card(await asyncio.to_thread(cc.card, biz, me), request)
        except Exception:
            logger.warning("member home: check-in card skipped", exc_info=True)
            return ""
    # Everything Home shows, read at once (one after another, these were
    # most of the wait on every visit to Home).
    import church_news as cn
    import celebrations as cel
    import member_portal_celebrations as mcl
    church_home = space not in ("kids", "youth")
    import sunday_serving as ssv
    occ, groups, lib, live, done, extras, checkin, posts, news, open_, today_cel, asks, serve_asks = await asyncio.gather(
        asyncio.to_thread(mpc.upcoming_for, biz["id"], me),
        asyncio.to_thread(mpc.groups_for, biz["id"], me),
        asyncio.to_thread(mps.load_library, biz["id"]),
        asyncio.to_thread(lr.current, biz["id"]),
        asyncio.to_thread(rp.read_days, biz["id"], me["id"], rp.current(biz)) if today else _nothing(),
        # Today's devotional, and a reading plan of the member's own when
        # the church has none running (member_portal_devotionals).
        mpd.home_extras(biz, me, preview=preview, church_reading=bool(today)),
        checkin_card() if space not in ("kids", "youth") and cfu.is_church(biz) else _nothing(),
        asyncio.to_thread(msp.posts, biz["id"], "youth") if space == "youth" else _nothing(),
        # "From the church" and the bell (member_portal_news).
        asyncio.to_thread(cn.home_view, str(biz["id"]), str(me["id"])) if church_home else _nothing(),
        asyncio.to_thread(cn.comments_open, biz) if church_home else _nothing(),
        # "Celebrating today" and the church's once-only question (member_portal_celebrations).
        asyncio.to_thread(cel.today_posts, biz, str(me["id"])) if church_home else _nothing(),
        asyncio.to_thread(mcl.home_asks, biz, me) if church_home and not preview else _nothing(),
        # Asks to serve waiting on this member (member_portal_serving).
        asyncio.to_thread(ssv.waiting, biz, str(me["id"])) if church_home else _nothing())
    occ, groups, lib = fill(occ, "occasions"), fill(groups, "groups"), fill(lib, "library")
    devotional, own, own_done = extras
    if own and not today:
        today, done = own, own_done
    if preview and not today:
        today, done = samples.plan_today(), set()
    import member_portal_bible as mpb
    bible, where = mpb.prefs(request)
    if space == "kids":
        import member_spaces_kids as mk
        return await mk.home(request, church, me, occ, mpc._flash(request) or mpr._flash(request))
    if space == "youth":
        return _page(msp.render_youth_home(
            biz, site, me=me, occasions=occ, groups=groups, youth_posts=posts,
            reading=mpr.home_card(today, done), bible=bible, leader=(ctx.get("leader") or {}).get("youth"),
            flash=mpc._flash(request) or mpr._flash(request)))
    checkin = checkin or ""
    import member_portal_news as mpn
    news_posts, news_n = news if news else (None, 0)
    # No news reaches me yet: if I post, Home shows where it will go.
    rights = await asyncio.to_thread(cn.can_post, str(biz["id"]), str(me["id"])) if news_posts == [] else None
    news_html = mpn.home_block(biz, news_posts, occ, bool(open_), rights)
    mine, waiting = asks if asks else (None, [])
    celebrate = mcl.ask_card(biz, me, mine, waiting) + mcl.home_strip(today_cel)
    import member_portal_serving as mpsv
    serving = mpsv.home_card(serve_asks or [])
    import member_asks
    return _page(render_home(biz, site, me=me, occasions=occ, groups=groups, library=lib,
                             give_url=give_url, flash=mpc._flash(request) or mpr._flash(request),
                             live=live, reading=mpr.today_row(today, done), bible=bible, where=where,
                             checkin=checkin, serving=serving, devotional=devotional,
                             edit=can_picture and request.query_params.get("edit") == "pictures",
                             news=news_html, news_n=mpn.home_bell(news), celebrate=celebrate,
                             ask=member_asks.home_row(await _ask_entry(biz, me))))


async def _ask_entry(biz: Dict[str, Any], me: Dict[str, Any]) -> List[str]:
    """Ask the church's way in, for Home and Me (member_asks): nothing in
    Kids, or for an adult who switched into Youth (Ask lives in Church), and
    no read at all for a church with nothing turned on."""
    import member_asks
    import member_spaces as msp
    ctx = msp.CURRENT.get() or {}
    if ctx.get("space", "church") == "kids" or (ctx.get("space") == "youth" and not ctx.get("youth")):
        return []
    if not member_asks.turned_on(biz):
        return []
    try:
        return await asyncio.to_thread(member_asks.entry, biz, me)
    except Exception:
        logger.warning("member asks: the way in was skipped", exc_info=True)
        return []


# ─── POST ────────────────────────────────────────────────────────────


async def _church_or_404(request: Request) -> Dict[str, Any]:
    if not _same_origin(request):
        raise HTTPException(403, "Not allowed")
    church = await asyncio.to_thread(_church_for_request, request)
    if not church:
        raise HTTPException(404, "Not found")
    if not portal_active(church["business"]) and not _previewing(request, church["business"]):
        raise HTTPException(404, "Not found")
    return church


async def _send_code_email(biz: Dict[str, Any], email: str, name: str, code: str) -> None:
    from email_sender import send_via_resend
    church = (biz.get("name") or "Your church").strip()
    try:
        await send_via_resend(
            to_email=email, to_name=name or None,
            from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
            from_name=church,
            subject=f"{code} is your {church} sign-in code",
            body=(f"<p>Here's your code to sign in to your page at <strong>{_e(church)}</strong>:</p>"
                  f"<p style=\"font-size:30px;font-weight:700;letter-spacing:6px\">{code}</p>"
                  "<p>It works for 10 minutes. If you didn't ask for it, you can ignore this email — "
                  "nobody can sign in without the code.</p>"),
            reply_to=None, business_id=str(biz["id"]),
            idempotency_key=f"member-code-{biz['id']}-{hashlib.sha256((email + code).encode()).hexdigest()[:24]}",
        )
    except Exception as e:
        # Quiet: the page already said "if you're on the list". The error
        # text can carry the address, so only its kind is logged.
        logger.warning("member code email failed (%s) for business %s", type(e).__name__, biz.get("id"))


async def _send_code_text(biz: Dict[str, Any], phone: str, code: str) -> None:
    """Text the code. Deliberately NOT through sms_service.send_sms_core:
    that stores every message in the church's text history, where anyone
    on the team could read a live sign-in code. This goes straight to the
    carrier from the church's own line (or the platform line), and never
    to a number that texted STOP."""
    church = (biz.get("name") or "Your church").strip()
    try:
        import httpx
        import sms_service
        import twilio_sms
        from starlette.concurrency import run_in_threadpool
        if not sms_service._twilio_configured():
            logger.warning("member code text skipped: texting is not configured")
            return
        async with httpx.AsyncClient() as client:
            if await sms_service.is_opted_out(client, phone, str(biz["id"])):
                logger.info("member code text skipped: number opted out (business %s)", biz.get("id"))
                return
            sender = await sms_service.sender_for(client, str(biz["id"]))
        body = (f"{church}: {code} is your sign-in code for your member page. "
                f"It works for 10 minutes. Didn't ask for it? Ignore this. Reply STOP to opt out.")
        await run_in_threadpool(twilio_sms.send_sms, phone, body, from_number=sender)
    except Exception as e:
        logger.warning("member code text failed (%s) for business %s", type(e).__name__, biz.get("id"))


async def _issue_and_send(biz: Dict[str, Any], email: str) -> None:
    """Runs AFTER the response is sent, so a known address and an unknown
    one answer in the same time: the lookup, the stored code and the mail
    are all out of the reply's path."""
    try:
        people = await asyncio.to_thread(contacts_for_ident, biz["id"], email)
        if not people or len(people) > MAX_HOUSEHOLD:
            if people:
                logger.warning("member sign-in refused: an email or number is on more than %s record "
                               "at business %s", MAX_HOUSEHOLD, biz.get("id"))
            return
        failed = await asyncio.to_thread(failures_today, biz["id"], email)
        if failed is None or failed >= MAX_FAILED_PER_DAY:
            return
        code = await asyncio.to_thread(issue_code, biz["id"], email)
    except Exception:
        logger.warning("member code could not be issued", exc_info=True)
        return
    if is_phone(email):
        await _send_code_text(biz, email, code)
    else:
        await _send_code_email(biz, email, people[0].get("name") or "", code)


@router.post("/my/code", include_in_schema=False)
async def request_code(request: Request):
    church = await _church_or_404(request)
    biz, site = church["business"], church["site"]
    if not sign_in_open(biz):
        return _page(render_signin_paused(biz, site))
    import rate_limit
    form = await request.form()
    email = norm_ident(form.get("email"))
    if not valid_ident(email):
        return _page(render_signin(biz, site, error="Enter the email or mobile number the church has for you.",
                                   email=str(form.get("email") or "").strip()[:120]), 400)
    # Flood control per network, and per address a short cooldown plus a
    # daily ceiling — not an hourly cap a stranger could spend to keep a
    # member from ever getting a code. None of these depend on whether the
    # address is known, so none of them reveal it.
    ip = rate_limit.trusted_client_ip(request)
    key = f"{biz['id']}|{email}"
    if not rate_limit.allow_strict("member_code_ip", ip):
        return _page(render_code(biz, site, email=email,
                                 error="Lots of sign-ins from this network just now. Wait a few minutes, then send a new code."), 429)
    if not rate_limit.allow_strict("member_code_email_minute", key) or \
            not rate_limit.allow_strict("member_code_email_day", key):
        return _page(render_code(biz, site, email=email,
                                 error=("A code was just texted to this number. Give it a minute."
                                        if is_phone(email) else
                                        "A code was just sent to this address. Give it a minute, and check spam.")), 429)
    from starlette.background import BackgroundTask
    return HTMLResponse(content=render_code(biz, site, email=email), headers=_SECURE_HEADERS,
                        background=BackgroundTask(_issue_and_send, biz, email))


@router.post("/my/verify", include_in_schema=False)
async def verify_code(request: Request):
    church = await _church_or_404(request)
    biz, site = church["business"], church["site"]
    if not sign_in_open(biz):
        # a code sent before the pause is not spent, and does not sign in
        return _page(render_signin_paused(biz, site))
    import rate_limit
    form = await request.form()
    email = norm_ident(form.get("email"))
    if not rate_limit.allow_strict("member_verify", rate_limit.trusted_client_ip(request)):
        return _page(render_code(biz, site, email=email,
                                 error="Too many tries from this network. Wait a few minutes, then try again."), 429)
    if not valid_ident(email):
        return RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
    # Read the people BEFORE spending the code: a failed read must not
    # burn a correct code.
    people = await asyncio.to_thread(contacts_for_ident, biz["id"], email)
    if people is None:
        return _page(render_try_again(biz, site), 503)
    result = await asyncio.to_thread(check_code, biz["id"], email, str(form.get("code") or ""))
    if result != "ok" or not people:
        return _page(render_code(biz, site, email=email, error=GENERIC_CODE_ERROR), 400)
    if len(people) > MAX_HOUSEHOLD:
        return _page(render_shared_address(biz, site), 403)
    cid = people[0]["id"] if len(people) == 1 else ""
    resp = RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
    _set_session(resp, mint_session(biz["id"], email, cid))
    return resp


@router.post("/my/person", include_in_schema=False)
async def choose_person(request: Request):
    church = await _church_or_404(request)
    sess = await asyncio.to_thread(_session_for, request, church)
    resp = RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
    if not sess or sess.get("unavailable"):
        return resp
    form = await request.form()
    cid = str(form.get("cid") or "")
    # Only someone who shares the signed-in email; "" goes back to the chooser.
    if cid and not any(str(p["id"]) == cid for p in sess["people"]):
        return resp
    _set_session(resp, mint_session(church["business"]["id"], sess["claims"]["em"], cid))
    return resp


@router.post("/my/signout", include_in_schema=False)
async def sign_out(request: Request):
    import member_portal_preview as pv
    await _church_or_404(request)
    resp = RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
    resp.delete_cookie(SESSION_COOKIE, path=COOKIE_PATH, secure=True, httponly=True, samesite="lax")
    pv.clear_cookie(resp)
    return resp


@router.post("/my/preview/end", include_in_schema=False)
async def end_preview(request: Request):
    """Leave the owner's preview. Lands on /my when the page is on, else
    the church's home page (a switched-off /my would be a 404)."""
    import member_portal_preview as pv
    if not _same_origin(request):
        raise HTTPException(403, "Not allowed")
    church = await asyncio.to_thread(_church_for_request, request)
    if not church:
        raise HTTPException(404, "Not found")
    resp = RedirectResponse("/my" if portal_active(church["business"]) else "/", status_code=303,
                            headers=_SECURE_HEADERS)
    pv.clear_cookie(resp)
    return resp


# ─── Owner config ────────────────────────────────────────────────────


def _require_owner(business_id: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{quote(str(business_id), safe='')}"
        f"&select=id,name,type,owner_id,settings,stripe_account_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    return rows[0]


def _config_payload(biz: Dict[str, Any], site: Dict[str, Any], user: Optional[AuthedUser] = None) -> Dict[str, Any]:
    import vertical_family
    import vertical_scope
    from business_sites_helpers import PUBLIC_DOMAIN
    domain = ((site or {}).get("site_config") or {}).get("custom_domain")
    host = domain or f"{(site or {}).get('slug') or 'business'}.{PUBLIC_DOMAIN}"
    return {
        "ok": True,
        "business_id": biz.get("id"),
        "eligible": vertical_family.is_nonprofit_like(biz.get("type"))
                    and vertical_scope.client_surface_allowed(biz.get("type")),
        "enabled": bool(portal_settings(biz.get("settings")).get("enabled")),
        "active": portal_active(biz),
        "sign_in": sign_in_open(biz),
        "codes_ready": codes_can_go_out(),
        "url": f"https://{host}/my",
        # Notifications to members' phones (member_push.py): each kind
        # the church can switch on, whether it is, and whether this
        # server can send at all.
        "notifications": _notifications_payload(biz, user),
        # The app's base (black, dark gray, light gray, white; the
        # church's colour is the accent) and its own Home tiles.
        "base": _ui_base(biz),
        "bases": [{"key": k, "label": v} for k, v in _ui_labels().items()],
        "tiles": _tiles_of(biz),
        # Youth's colour (member_spaces): volt green unless the church picks one.
        "youth_color": _youth_colour(biz),
        # Round three (2026-10-19): the colour family beside the church's
        # colour, or the church's colour alone; and who besides the owner
        # can change the app's pictures (member_app_pictures).
        "colours": "church" if portal_settings(biz.get("settings")).get("colours") == "church" else "family",
        "photo_editors": _editors_of(biz),
        "pictures": len(portal_settings(biz.get("settings")).get("pictures") or {}),
        # Tabs your members see (member_app_ui.church_tabs, 2026-10-27): the
        # church's bar in order, every tab it can pick, and how many fit.
        **_tabs_payload(biz),
    }


def _tabs_payload(biz: Dict[str, Any]) -> Dict[str, Any]:
    import member_app_ui as ui
    choices = ui.tab_choices(biz)
    offered = {c["key"] for c in choices}
    # A tab that isn't offered now (the directory while it's off) isn't
    # shown as on the bar either.
    return {"tabs": [k for k in ui.church_tab_keys(biz) if k in offered], "tab_choices": choices,
            "tab_limit": ui.CHURCH_TAB_LIMIT, "tabs_default": list(ui.DEFAULT_TAB_KEYS)}


def _editors_of(biz: Dict[str, Any]) -> List[Dict[str, str]]:
    """The people the owner named to change pictures, with their names
    (anyone no longer in the records is left out)."""
    import member_app_pictures as mapic
    ids = mapic.editors(biz)
    if not ids:
        return []
    rows = sb_clients.sb_get_as_service(
        f"/contacts?business_id=eq.{quote(str(biz.get('id')), safe='')}&id=in.({','.join(ids)})&select=id,name,email")
    if not isinstance(rows, list):
        return [{"id": i, "name": ""} for i in ids]
    names = {str(r["id"]): (r.get("name") or r.get("email") or "") for r in rows}
    return [{"id": i, "name": names[i]} for i in ids if i in names]


def _youth_colour(biz: Dict[str, Any]) -> str:
    import member_spaces as msp
    return msp.youth_colour(biz)


def _ui_base(biz: Dict[str, Any]) -> str:
    import member_app_ui as ui
    return ui.base_of(biz)


def _ui_labels() -> Dict[str, str]:
    import member_app_ui as ui
    return dict(ui.BASE_LABELS)


def _tiles_of(biz: Dict[str, Any]) -> List[Dict[str, str]]:
    import member_portal_church as mpc
    return mpc.clean_tiles(portal_settings(biz.get("settings")).get("tiles")) or []


def _notifications_payload(biz: Dict[str, Any], user: Optional[AuthedUser] = None) -> Dict[str, Any]:
    import member_push
    import sunday_planning
    on = member_push.church_kinds(biz.get("settings"))
    # Serving waits for ChurchSavvy Planning: no switch where nobody can
    # schedule (one already on still shows, so it can be turned off).
    planning = user is not None and sunday_planning.open_to(user)
    return {
        "ready": member_push.ready(),
        "kinds": [{"key": k, "label": label, "hint": hint, "on": k in on}
                  for k, label, hint in member_push.KINDS if k != "serving" or planning or k in on],
    }


@router.get("/member-portal/{business_id}")
def get_member_portal_config(business_id: str, user: AuthedUser = Depends(require_user)):
    from business_sites_helpers import ensure_business_site
    biz = _require_owner(business_id, user)
    site, _ = ensure_business_site(biz)
    return _config_payload(biz, site, user)


@router.post("/member-portal/{business_id}/preview")
def create_member_preview(business_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """Owner only. Body: { contact_id, next?: "pictures" }. A one-time,
    two-minute link that opens the member app as that member, in a
    read-only preview (member_portal_preview.py) — no email or text
    involved. next = "pictures" lands on the app's pictures, the one thing
    the owner can change from a preview (member_app_pictures)."""
    import member_portal_preview as pv
    from business_sites_helpers import ensure_business_site
    biz = _require_owner(business_id, user)
    if not portal_eligible(biz):
        raise HTTPException(400, "Member pages are for churches and nonprofits.")
    contact_id = str((body or {}).get("contact_id") or "")
    if not UUID_RE.match(contact_id):
        raise HTTPException(400, "Choose who to preview as.")
    who = pv.load_contact(business_id, contact_id)
    if who is None:
        raise HTTPException(503, "Couldn't open a preview just now. Please try again.")
    if not who:
        raise HTTPException(404, "That person isn't in this church's records.")
    token = pv.issue_link_token(business_id, contact_id, str(user.id))
    if not token:
        raise HTTPException(503, "Couldn't open a preview just now. Please try again.")
    site, _ = ensure_business_site(biz)
    base = _config_payload(biz, site)["url"]
    nxt = "&next=pictures" if (body or {}).get("next") == "pictures" else ""
    return {"ok": True, "url": f"{base}/preview?t={quote(token, safe='')}{nxt}", "expires_in": pv.LINK_TTL_SECONDS}


@router.patch("/member-portal/{business_id}")
def patch_member_portal_config(business_id: str, body: Dict[str, Any],
                               user: AuthedUser = Depends(require_user)):
    """Owner-gated. Body: { enabled?: bool, sign_in?: bool, sign_out_all?: true,
    notifications?: {kind: bool}, base?: "black"|"charcoal"|"gray"|"white",
    tiles?: [{title, sub, href, photo}], youth_color?: "#rrggbb" | "",
    colours?: "family"|"church", photo_editors?: [contact id],
    tabs?: [tab key] | null }
    (the kinds are member_push.KINDS;
    tiles are checked by member_portal_church.clean_tiles; tabs by
    member_app_ui.clean_tab_keys: unknown keys are dropped, Home stays
    first, Give stays in, five at most; null is today's bar again).

    Turning the page ON, or "sign everyone out", moves the epoch to now:
    every session issued before it ends (a page switched off and on again
    must not revive six-month-old sessions). `sign_in` pauses or resumes
    new sign-ins (sign_in_open) and leaves the epoch alone."""
    from business_sites_helpers import ensure_business_site
    body = body or {}
    want = body.get("enabled")
    if "enabled" in body and not isinstance(want, bool):
        raise HTTPException(400, "enabled must be true or false")
    if "sign_in" in body and not isinstance(body.get("sign_in"), bool):
        raise HTTPException(400, "sign_in must be true or false")
    sign_out_all = body.get("sign_out_all") is True
    import member_app_ui as ui
    import member_portal_church as mpc
    if "base" in body and body.get("base") not in ui.BASES:
        raise HTTPException(400, "base must be black, charcoal, gray or white")
    if "youth_color" in body and not (body.get("youth_color") in ("", None)
                                      or re.fullmatch(r"#[0-9a-fA-F]{6}", str(body.get("youth_color")))):
        raise HTTPException(400, "youth_color must be a colour like #d4ff3a")
    tiles = None
    if "tiles" in body:
        tiles = mpc.clean_tiles(body.get("tiles"))
        if tiles is None:
            raise HTTPException(400, "tiles must be a list")
    if "colours" in body and body.get("colours") not in ("family", "church"):
        raise HTTPException(400, "colours must be family or church")
    editors_list = None
    if "photo_editors" in body:
        import member_app_pictures as mapic
        editors_list = mapic.clean_editors(body.get("photo_editors"))
        if editors_list is None:
            raise HTTPException(400, "photo_editors must be a list of people")
    switches = None
    if "notifications" in body:
        import member_push
        switches = member_push.clean_switches(body.get("notifications"))
    tab_keys = None
    if "tabs" in body and body.get("tabs") is not None:
        tab_keys = ui.clean_tab_keys(body.get("tabs"))
        if tab_keys is None:
            raise HTTPException(400, "tabs must be a list of tabs")
    biz = _require_owner(business_id, user)
    site, _ = ensure_business_site(biz)
    if ("enabled" in body or "sign_in" in body or sign_out_all or switches is not None or "base" in body
            or tiles is not None or "youth_color" in body or "colours" in body or editors_list is not None
            or "tabs" in body):
        import vertical_family
        import vertical_scope
        if want and not (vertical_family.is_nonprofit_like(biz.get("type"))
                         and vertical_scope.client_surface_allowed(biz.get("type"))):
            raise HTTPException(400, "Member sign-in is for churches and nonprofits.")
        # Settings are read again right before the write: the copy above
        # predates ensure_business_site, and a whole-object write from it
        # would undo a giving or brand change made meanwhile.
        fresh = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{quote(str(business_id), safe='')}&select=settings&limit=1")
        if not isinstance(fresh, list) or not fresh:
            raise HTTPException(503, "That change didn't save. Please try again.")
        settings = dict(fresh[0].get("settings") or {})
        cfg = dict(portal_settings(settings))
        was_on = bool(cfg.get("enabled"))
        if "enabled" in body:
            cfg["enabled"] = want
        if "sign_in" in body:
            cfg["sign_in"] = body["sign_in"]
        if sign_out_all or (want is True and not was_on):
            cfg["epoch"] = int(time.time())
        if switches is not None:
            cfg["notifications"] = {**(cfg.get("notifications") or {}), **switches}
        if "base" in body:
            cfg["base"] = body["base"]
        if "youth_color" in body:
            if body.get("youth_color"):
                cfg["youth_color"] = str(body["youth_color"]).lower()
            else:
                cfg.pop("youth_color", None)
        if tiles is not None:
            cfg["tiles"] = tiles
        if "colours" in body:
            cfg["colours"] = body["colours"]
        if editors_list is not None:
            cfg["photo_editors"] = editors_list
        if "tabs" in body:
            # The directory is a tab only while the church has it on.
            if tab_keys is not None and "directory" in tab_keys:
                import member_directory
                if not member_directory.church_on({"settings": {"member_portal": cfg}}):
                    tab_keys = [k for k in tab_keys if k != "directory"]
            # Today's bar is kept as no bar at all, so it follows ours.
            if tab_keys is None or tuple(tab_keys) == ui.DEFAULT_TAB_KEYS:
                cfg.pop("tabs", None)
            else:
                cfg["tabs"] = tab_keys
        settings["member_portal"] = cfg
        saved = sb_clients.sb_patch_as_service(
            f"/businesses?id=eq.{quote(str(business_id), safe='')}", {"settings": settings})
        if not saved:
            raise HTTPException(503, "That change didn't save. Please try again.")
        biz = {**biz, "settings": settings}
    return _config_payload(biz, site, user)
