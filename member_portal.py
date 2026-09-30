"""
member_portal.py — a church member's own page, at <church site>/my.

WHAT IT IS (Kevin, 2026-09-29: "passwordless, permanent address, long
device session"). A member signs in with a 6-digit code sent to the email
the church already has for them — no password, no account in the
practitioner's user pool — and sees their own giving and their year-end
statement. Nothing else about anyone else: there is no member directory.

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
    "Referrer-Policy": "no-referrer",
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


def portal_active(biz: Dict[str, Any]) -> bool:
    """The ONE activation rubric: page, POSTs and the owner panel."""
    import vertical_family
    import vertical_scope
    t = biz.get("type")
    if not vertical_family.is_nonprofit_like(t):
        return False
    if not vertical_scope.client_surface_allowed(t):
        return False
    return bool(portal_settings(biz.get("settings")).get("enabled"))


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
        f"&select=id,name,email&order=created_at.asc&limit={MAX_HOUSEHOLD + 1}")
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
        f"&select=id,name,email,phone&order=created_at.asc&limit=20")
    if not isinstance(rows, list):
        return None
    return [r for r in rows if isinstance(r, dict) and _last10(r.get("phone")) == digits]


def contacts_for_ident(business_id: str, ident: str) -> Optional[List[Dict[str, Any]]]:
    """The people an email or a mobile number belongs to at this church."""
    ident = norm_ident(ident)
    if is_phone(ident):
        return contacts_for_phone(business_id, ident)
    return contacts_for_email(business_id, ident)


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
    sites = sb_clients.sb_get_as_service(
        f"/business_sites?{q}&order=updated_at.desc&limit=1"
        f"&select=slug,business_id,site_config") or []
    if not sites or (sites[0].get("site_config") or {}).get("offline"):
        return None
    biz = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{quote(str(sites[0].get('business_id')), safe='')}"
        f"&select=id,name,type,settings,stripe_account_id&limit=1") or []
    if not biz:
        return None
    return {"business": biz[0], "site": sites[0]}


def _same_origin(request: Request) -> bool:
    """A POST from another site is refused. Browsers send Origin on POST;
    a missing one (old clients, some privacy modes) falls back to Referer,
    and neither present is allowed — SameSite=Lax already keeps the
    session cookie off cross-site POSTs."""
    import public_site
    host = (public_site.public_host(request) or "").split(":")[0].lower()
    origin = request.headers.get("origin")
    if origin is not None:
        return origin != "null" and (urlparse(origin).hostname or "").lower() == host
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


def _shell(biz: Dict[str, Any], site: Optional[Dict[str, Any]], title: str,
           body: str, *, script: str = "", tab: Optional[str] = None,
           who: Optional[Dict[str, Any]] = None) -> str:
    """Every member page. Signed-in pages pass `tab` (the bottom bar's
    current tab) and `who` (their avatar, which opens Me); the sign-in
    pages pass neither and get no bar. The look is member_app_ui's."""
    import member_app_ui as ui
    from public_form_theme import resolve_theme, css_vars, font_links
    theme = resolve_theme(biz, site)
    name = (biz.get("name") or "").strip() or "Your church"
    logo = theme.get("logo_url") or ""
    logo_html = f'<img class="mp-logo" src="{_e(logo)}" alt="">' if logo else ""
    avatar = (f'<a class="mb-avatar mp-noprint" href="/my/me" aria-label="Me">{_e(ui.initials(who.get("name")))}</a>'
              if who else "")
    signed_in = tab is not None
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow">
<meta name="theme-color" content="{ui.GROUND}">
<title>{_e(title)} — {_e(name)}</title>
{font_links(theme)}
<style>{css_vars(theme)}</style>
<style>{ui.css(theme)}</style>
</head>
<body>
<main class="mp-shell{' mb-has-nav' if signed_in else ''}">
  <header class="mb-top"><span class="mb-brand">{logo_html}<p class="mp-church">{_e(name)}</p></span>{avatar}</header>
  {body}
  <footer class="mp-foot mp-noprint">Your page at {_e(name)} · Powered by Solutionist</footer>
</main>
{ui.nav(tab) if signed_in else ''}
{script}
</body>
</html>"""


def render_unavailable(biz: Dict[str, Any], site=None) -> str:
    return _shell(biz, site, "Not available", """
<div class="mp-card"><h1>This page isn't open yet</h1>
<p class="mp-muted">Member sign-in isn't turned on for this church. If you were expecting it, ask the church office.</p></div>""")


def render_signin(biz: Dict[str, Any], site=None, *, error: str = "", email: str = "") -> str:
    err = f'<p class="mp-err" role="alert">{_e(error)}</p>' if error else ""
    return _shell(biz, site, "Sign in", f"""
<h1>Welcome</h1>
<p class="mp-muted">Your page at {_e(biz.get('name') or 'the church')}: messages, your groups, what's coming up and your giving.
Sign in with the email or mobile number the church has for you. We'll send a 6-digit code — there's no password to remember.</p>
<form class="mp-card mp-form" method="post" action="/my/code">
  <label for="mp-email">Email or mobile number</label>
  <input class="mp-input" id="mp-email" name="email" type="text" autocomplete="username" autocapitalize="off" spellcheck="false" required value="{_e(email)}">
  {err}
  <button class="mp-go" type="submit">Send my code</button>
</form>""")


def render_code(biz: Dict[str, Any], site=None, *, email: str, error: str = "") -> str:
    err = f'<p class="mp-err" role="alert">{_e(error)}</p>' if error else ""
    texted = is_phone(email)
    return _shell(biz, site, "Enter your code", f"""
<h1>Check your {'texts' if texted else 'email'}</h1>
<p class="mp-muted">If <strong>{_e(show_ident(email))}</strong> is on {_e(biz.get('name') or 'the church')}'s list, a 6-digit code is on its way{' by text' if texted else ''}. It works for 10 minutes.</p>
<form class="mp-card mp-form" method="post" action="/my/verify">
  <input type="hidden" name="email" value="{_e(email)}">
  <label for="mp-code">6-digit code</label>
  <input class="mp-input mp-code" id="mp-code" name="code" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9 ]*" maxlength="7" required autofocus>
  {err}
  <button class="mp-go" type="submit">Sign in</button>
</form>
<form method="post" action="/my/code" class="mp-noprint">
  <input type="hidden" name="email" value="{_e(email)}">
  <p class="mp-muted">Nothing arrived? {'Give it a minute' if texted else 'Check spam'}, or <button class="mp-link" type="submit">send a new code</button>.
  Still nothing? Ask the church office which {'number' if texted else 'email'} they have for you.</p>
</form>
<p class="mp-muted"><a href="/my">Use a different email or number</a></p>""")


def render_try_again(biz: Dict[str, Any], site=None) -> str:
    return _shell(biz, site, "Try again", """
<div class="mp-card"><h1>We couldn't open your page just now</h1>
<p class="mp-muted">Nothing is wrong with your account. Please try again in a moment.</p>
<p><a class="mp-go" href="/my">Try again</a></p></div>""")


def render_shared_address(biz: Dict[str, Any], site=None) -> str:
    return _shell(biz, site, "Ask the church office", f"""
<div class="mp-card"><h1>This email is on more than one person's record</h1>
<p class="mp-muted">To keep everyone's giving private, each person signs in with their own email, so this one can't be used.
Ask {_e(biz.get('name') or 'the church office')} to put your own email on your record, then sign in with that.</p>
<p><a class="mp-link" href="/my">Back</a></p></div>""")


def render_choose(biz: Dict[str, Any], site, people: List[Dict[str, Any]]) -> str:
    buttons = "".join(
        f'<form method="post" action="/my/person"><input type="hidden" name="cid" value="{_e(p["id"])}">'
        f'<button class="mp-person" type="submit">{_e(p.get("name") or "Someone in your household")}</button></form>'
        for p in people)
    return _shell(biz, site, "Who's signing in?", f"""
<h1>Who's signing in?</h1>
<p class="mp-muted">This email is on more than one person's record at {_e(biz.get('name') or 'the church')}, so
anyone who reads it can see each of these people's giving. Choose yourself.</p>
<div class="mp-row">{buttons}</div>""")


def render_home(biz: Dict[str, Any], site, *, me: Dict[str, Any], occasions, groups, library,
                give_url: str, flash: str = "") -> str:
    """Home: what's next, the latest message, this person's week, what
    they haven't answered yet, and three quick ways in."""
    import member_app_ui as ui
    import member_portal_church as mpc
    import member_portal_sermons as mps
    hello = first_name(me.get("name") or "") or "there"
    quick = []
    if give_url:
        quick.append(f'<a href="{_e(give_url)}">{ui.icon("heart", 18)}Give</a>')
    quick.append(f'<a href="/my/prayer">{ui.icon("lock", 18)}Prayer</a>')
    quick.append(f'<a href="/my/events">{ui.icon("calendar", 18)}Events</a>')
    return _shell(biz, site, "Home", f"""
<h1>Hi, {_e(hello)}</h1>
{flash}
{mpc.next_strip(occasions)}
{mps.latest_hero(library)}
{mpc.week_list(occasions, groups)}
<nav class="mb-quick" aria-label="Quick actions">{''.join(quick)}</nav>
{mpc.coming_up(occasions)}""", tab="home", who=me)


def render_me(biz: Dict[str, Any], site, *, me: Dict[str, Any], people: List[Dict[str, Any]],
              year: int, gifts: Optional[List[Dict[str, Any]]], give_url: str,
              this_year: int, flash: str = "") -> str:
    """Me: this person's giving (and statements), and the ways to look
    after their own record — prayer, details, groups, sign out."""
    import member_app_ui as ui
    years = "".join(
        f'<a href="/my/me?year={y}"{" aria-current=\"page\"" if y == year else ""}>{y}</a>'
        for y in range(this_year, this_year - 4, -1))
    if gifts is None:
        giving = ('<p class="mp-err" role="alert">Your giving couldn\'t load just now. Your gifts are safe — '
                  'please try again in a moment.</p>')
    elif not gifts:
        giving = f'<p class="mp-muted">No gifts recorded for {year}.</p>'
    else:
        total = sum(g["amount"] for g in gifts)
        items = "".join(
            f'<li><span>{_e(_day(g["date"]))} · {_e(g["fund"])}{" (refunded)" if g["refunded"] else ""}</span>'
            f'<span>{money(g["amount"])}</span></li>' for g in gifts)
        giving = (f'<p class="mp-muted">Given in {year}</p><p class="mp-total">{money(total)}</p>'
                  f'<p class="mp-muted">{len(gifts)} gift{"" if len(gifts) == 1 else "s"}</p>'
                  f'<ul class="mp-gifts">{items}</ul>'
                  f'<p style="margin-top:14px"><a class="mp-go mp-go-2" style="width:100%" href="/my/statement?year={year}">Year-end statement for {year}</a></p>')
    give = (f'<p style="margin-top:12px"><a class="mp-go" href="{_e(give_url)}">{ui.icon("heart", 16)}Give</a></p>'
            if give_url else "")
    switch = ('<form method="post" action="/my/person"><input type="hidden" name="cid" value="">'
              '<button class="mp-link" type="submit">Not you? Choose someone else in your household</button></form>'
              if len(people) > 1 else "")
    link = lambda href, ic, title, sub: (
        f'<li><a href="{href}">{ui.icon(ic, 20)}<span class="mb-list-text"><strong>{title}</strong>'
        f'<span>{sub}</span></span>{ui.icon("chevron", 16)}</a></li>')
    return _shell(biz, site, "Me", f"""
<div class="mb-profile"><span class="mb-avatar" aria-hidden="true">{_e(ui.initials(me.get('name')))}</span>
  <span><h1 style="margin:0">{_e(me.get('name') or 'Me')}</h1>
  <span class="mp-muted">Your page at {_e(biz.get('name') or 'the church')}</span></span></div>
{flash}
<h2 class="mp-sect" id="mp-giving">My giving</h2>
<section class="mp-card" aria-labelledby="mp-giving">
  <nav class="mp-years" aria-label="Year">{years}</nav>
  {giving}
  {give}
</section>
<h2 class="mp-sect">My church life</h2>
<ul class="mb-list">
  {link('/my/events', 'calendar', 'Coming up', 'Say you&#x27;re coming, or sign up to serve')}
  {link('/my/groups', 'users', 'My groups', 'Your groups, and ones you can join')}
  {link('/my/prayer', 'lock', 'Prayer', 'A private request to the pastor')}
  {link('/my/details', 'user', 'My details', 'Phone and mailing address')}
</ul>
<div class="mp-noprint" style="margin-top:12px">{switch}
<form method="post" action="/my/signout"><button class="mp-link" type="submit">Sign out</button></form></div>""",
                  tab="me")


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
    if not portal_active(biz):
        return _page(render_unavailable(biz, site), 404)
    sess = await asyncio.to_thread(_session_for, request, church)
    sub = path.rstrip("/") or "/my"
    if sess and sess.get("unavailable"):
        return _page(render_try_again(biz, site), 503)
    if not sess:
        if sub != "/my":
            return RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
        return _page(render_signin(biz, site))
    if not sess["me"]:
        return _page(render_choose(biz, site, sess["people"]))
    me, this_year = sess["me"], date.today().year
    year = _year_arg(request, this_year)
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
    if sub == "/my/events":
        occ = await asyncio.to_thread(mpc.upcoming_for, biz["id"], me)
        return _page(mpc.render_events(biz, site, request, occ, who=me))
    if sub == "/my/prayer":
        return _page(mpc.render_prayer(biz, site, request, who=me))
    if sub == "/my/groups":
        data = await asyncio.to_thread(mpc.groups_for, biz["id"], me)
        return _page(mpc.render_groups(biz, site, request, data, who=me))
    if sub == "/my/details":
        full = await asyncio.to_thread(mpc.load_me, biz["id"], me["id"])
        if not full:
            return _page(render_try_again(biz, site), 503)
        return _page(mpc.render_details(biz, site, request, full))
    # Sermons, inside the app (member_portal_sermons.py).
    if sub == "/my/sermons" or sub.startswith("/my/sermons/"):
        lib = await asyncio.to_thread(mps.load_library, biz["id"])
        rest = sub[len("/my/sermons"):].strip("/")
        if not rest:
            series = str(request.query_params.get("series") or "")
            return _page(mps.render_library(biz, site, me, lib, series if UUID_RE.match(series) else ""),
                         200 if lib is not None else 503)
        page = mps.render_sermon(biz, site, me, lib, rest) if UUID_RE.match(rest) else None
        if page is None:
            return RedirectResponse("/my/sermons", status_code=303, headers=_SECURE_HEADERS)
        return _page(page, 200 if lib is not None else 503)
    from giving_router import giving_is_active
    give_url = "/give" if giving_is_active(biz) else ""
    if sub == "/my/me":
        try:
            gifts: Optional[List[Dict[str, Any]]] = await asyncio.to_thread(gifts_for, biz["id"], me["id"], year)
        except Exception:
            logger.warning("member giving read failed", exc_info=True)
            gifts = None
        return _page(render_me(biz, site, me=me, people=sess["people"], year=year, gifts=gifts,
                               give_url=give_url, this_year=this_year, flash=mpc._flash(request)))
    if sub != "/my":
        return RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
    occ, groups, lib = await asyncio.gather(
        asyncio.to_thread(mpc.upcoming_for, biz["id"], me),
        asyncio.to_thread(mpc.groups_for, biz["id"], me),
        asyncio.to_thread(mps.load_library, biz["id"]))
    return _page(render_home(biz, site, me=me, occasions=occ, groups=groups, library=lib,
                             give_url=give_url, flash=mpc._flash(request)))


# ─── POST ────────────────────────────────────────────────────────────


async def _church_or_404(request: Request) -> Dict[str, Any]:
    if not _same_origin(request):
        raise HTTPException(403, "Not allowed")
    church = await asyncio.to_thread(_church_for_request, request)
    if not church:
        raise HTTPException(404, "Not found")
    if not portal_active(church["business"]):
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
    await _church_or_404(request)
    resp = RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
    resp.delete_cookie(SESSION_COOKIE, path=COOKIE_PATH, secure=True, httponly=True, samesite="lax")
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


def _config_payload(biz: Dict[str, Any], site: Dict[str, Any]) -> Dict[str, Any]:
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
        "url": f"https://{host}/my",
    }


@router.get("/member-portal/{business_id}")
def get_member_portal_config(business_id: str, user: AuthedUser = Depends(require_user)):
    from business_sites_helpers import ensure_business_site
    biz = _require_owner(business_id, user)
    site, _ = ensure_business_site(biz)
    return _config_payload(biz, site)


@router.patch("/member-portal/{business_id}")
def patch_member_portal_config(business_id: str, body: Dict[str, Any],
                               user: AuthedUser = Depends(require_user)):
    """Owner-gated. Body: { enabled?: bool, sign_out_all?: true }.

    Turning the page ON, or "sign everyone out", moves the epoch to now:
    every session issued before it ends (a page switched off and on again
    must not revive six-month-old sessions)."""
    from business_sites_helpers import ensure_business_site
    body = body or {}
    want = body.get("enabled")
    if "enabled" in body and not isinstance(want, bool):
        raise HTTPException(400, "enabled must be true or false")
    sign_out_all = body.get("sign_out_all") is True
    biz = _require_owner(business_id, user)
    site, _ = ensure_business_site(biz)
    if "enabled" in body or sign_out_all:
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
        if sign_out_all or (want is True and not was_on):
            cfg["epoch"] = int(time.time())
        settings["member_portal"] = cfg
        saved = sb_clients.sb_patch_as_service(
            f"/businesses?id=eq.{quote(str(business_id), safe='')}", {"settings": settings})
        if not saved:
            raise HTTPException(503, "That change didn't save. Please try again.")
        biz = {**biz, "settings": settings}
    return _config_payload(biz, site)
