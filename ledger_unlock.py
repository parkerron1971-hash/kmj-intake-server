"""Step-up authentication for the ledger.

WHY THIS AND NOT A LEDGER PASSWORD. A second, separate password is the
wrong shape twice over. If it is the same secret as the account
password it is friction without protection. If it is a NEW secret it
needs a reset path — and whoever can reset it from inside an already
signed-in session is precisely the attacker it was meant to stop, so
the control evaporates. It would also be something a practitioner can
lose, locking them out of their own audit trail.

WHAT THIS DEFENDS. The realistic threat is not a stolen password, it is
an open session: a laptop left unlocked, a shared workstation at the
front desk, a browser someone walked away from. History is the single
highest-value read in the app — it aggregates who did what, to which
client, and when — so a walk-up reader gets everything at once.
Re-proving the credential they already have, and holding it for
fifteen minutes, targets exactly that.

WHAT IT DOES NOT DEFEND, STATED PLAINLY. It does nothing against a
compromised password or a stolen JWT: whoever holds those can complete
the step-up too. It narrows the window on an unattended session. It is
not a second factor and must not be described as one.

THE UNLOCK IS ITSELF A LEDGER ROW. Opening the record becomes part of
the record.

AUDIENCE IS A SEPARATE QUESTION. The read gate admits the owner, any
active seat (viewer included) and active accountant collaborators.
Step-up puts a prompt in front of that audience; it does not narrow
it. Conflating the two would be false comfort, so they stay separate
decisions.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

logger = logging.getLogger("ledger_unlock")

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
UNLOCK_TTL_SECONDS = 15 * 60
UNLOCK_HEADER = "X-Ledger-Unlock"

# ── SCOPES ───────────────────────────────────────────────────────────
# An unlock is a proof that a specific person re-entered their password
# just now. It is NOT a blanket authorisation for the next fifteen
# minutes of whatever they feel like.
#
# Without a scope, confirming your password to READ the audit trail
# would equally authorise disconnecting your payouts — two very
# different questions answered by one prompt the practitioner thought
# was about something else. This is the same domain-separation
# reasoning that already keeps an unlock token from verifying as an
# auditor link.
SCOPE_LEDGER = "ledger"    # read the record
SCOPE_ACCESS = "access"    # let someone else in: invites, audit links, redaction
SCOPE_DANGER = "danger"    # money, and things with no undo
SCOPE_CARE = "care"        # open Prayer & care (private_care.py), when the church asks for it
SCOPES = (SCOPE_LEDGER, SCOPE_ACCESS, SCOPE_DANGER, SCOPE_CARE)

# ── AN ACCESS OR DANGER UNLOCK IS FOR ONE BUSINESS (2026-11-18) ──────
# The step-up endpoint decides WHO MAY RE-PROVE A PASSWORD by the
# business named to it: the owner for danger; the owner, an Admin or
# whoever sets up jobs and sheets for access. The token it handed back
# said only "this person, this scope", so that decision did not travel
# with it. Anyone who owned ANY business could confirm their password
# there and carry the token to a business where they were a Manager: an
# invite the step-up should have stopped went through, and so did every
# danger gate whose own route lets a Manager or an Admin act.
#
# So the token now names the business it was confirmed for, and each
# gate names the business its action is for. A token for another
# business, or one that names none, is the same `ledger_locked` as no
# token: the app asks again, this time for the right business. The
# ledger scope is not bound: its pre-check is "may you read this
# ledger", which every ledger route asks again for its own business, so
# a carried token opens nothing its holder could not already open.
#
# The care scope (2026-11-18) is bound the same way: a church's Prayer &
# care asks for the password when that church says so, and a proof
# confirmed at one church opens no other's requests.
BOUND_SCOPES = (SCOPE_ACCESS, SCOPE_DANGER, SCOPE_CARE)

# What each scope is asking the practitioner to agree to, in their
# words. The prompt has to name the consequence or it is just a speed
# bump people learn to type through.
SCOPE_PROMPT = {
    SCOPE_LEDGER: "Confirm your password to open the ledger.",
    SCOPE_ACCESS: "Confirm your password to change who can get in.",
    SCOPE_DANGER: "Confirm your password — this one cannot be undone.",
    SCOPE_CARE: "Enter your password to open Prayer & care.",
}

# Same key as the rest of the ledger's signing, in its own DOMAIN. The
# auditor-session work established why that matters: without a distinct
# prefix an unlock token would verify as an auditor link and vice
# versa, one credential silently becoming another.
_UNLOCK_DOMAIN = b"ledger-unlock-v1|"
_SECRET_ENVS = ("AUDITOR_LINK_SECRET", "MCP_TOKEN_SECRET", "CUSTOMER_TOKEN_SECRET")


def _secret() -> bytes:
    for name in _SECRET_ENVS:
        s = os.environ.get(name)
        if s:
            return s.encode("utf-8")
    raise RuntimeError(
        "no token secret configured — set AUDITOR_LINK_SECRET before "
        "unlocking the ledger")


def _anon_key() -> str:
    return (os.environ.get("SUPABASE_ANON")
            or os.environ.get("SUPABASE_ANON_KEY") or "")


def _b64(raw: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(s: str) -> bytes:
    import base64
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sig(payload_b64: str) -> str:
    return _b64(hmac.new(_secret(), _UNLOCK_DOMAIN + payload_b64.encode("utf-8"),
                         hashlib.sha256).digest())


def _same_business(v: Any) -> str:
    """A business id as two of them are compared: a UUID in its one
    spelling, anything else trimmed and lower-cased. "" for none."""
    import uuid
    v = "" if v is None else str(v).strip()
    try:
        return str(uuid.UUID(v))
    except (ValueError, TypeError, AttributeError):
        return v.lower()


def mint(user_id: str, scope: str = SCOPE_LEDGER,
         business_id: Any = None, ttl_seconds: Optional[int] = None) -> Dict[str, Any]:
    """A proof that THIS user re-entered their password just now, FOR A
    PARTICULAR KIND OF ACTION, and for access and danger AT ONE BUSINESS
    (`business_id`: the one the step-up endpoint checked them against).

    A ledger unlock names no business: the person is what was
    re-verified, and each ledger route's own read gate decides which
    ledgers they may open. An access or danger unlock minted with no
    business opens nothing (verify), so a caller that forgets it gets a
    prompt that never clears rather than a token that works everywhere.
    """
    if scope not in SCOPES:
        raise ValueError(f"unknown step-up scope: {scope}")
    # Fifteen minutes, unless the caller names its own (Prayer & care's
    # lock: the church's quiet minutes), held between one minute and an hour.
    ttl = UNLOCK_TTL_SECONDS if ttl_seconds is None else max(60, min(3600, int(ttl_seconds)))
    now = int(time.time())
    payload = {"typ": "unlock", "sub": str(user_id), "scp": scope,
               "iat": now, "exp": now + ttl}
    if _same_business(business_id):
        payload["biz"] = _same_business(business_id)
    p = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    return {"token": f"{p}.{_sig(p)}", "expires_in": ttl}


def verify(token: str, user_id: str, scope: str = SCOPE_LEDGER,
           business_id: Any = None) -> bool:
    """Signature → type → expiry → SAME USER → SAME SCOPE → for access
    and danger, SAME BUSINESS.

    `business_id` is the business the action is for: one id, or a list
    of them where one action covers several (deleting an account takes
    every business its owner has). For access and danger the token must
    name one of them; none given, or a token that names none (one minted
    before 2026-11-18, at most fifteen minutes old), is a no. The ledger
    scope ignores it.

    The user check stops one signed-in user's unlock being replayed by
    another. The scope check stops a ledger unlock — which a
    practitioner may grant casually, several times a day — from
    silently authorising a payout change or a deletion.

    A token minted before scopes existed carries no `scp`. Those are
    read as `ledger`, which is what they were: the only gate that
    existed. They expire within fifteen minutes anyway, so this is a
    deployment courtesy rather than a permanent rule — but without it,
    shipping this would have kicked every practitioner mid-session out
    of a ledger they had just unlocked.
    """
    try:
        if not isinstance(token, str) or token.count(".") != 1:
            return False
        p, sig = token.split(".", 1)
        if not hmac.compare_digest(_sig(p), sig):
            return False
        claims = json.loads(_unb64(p))
        if not isinstance(claims, dict) or claims.get("typ") != "unlock":
            return False
        exp = claims.get("exp")
        if not isinstance(exp, int) or exp <= time.time():
            return False
        if str(claims.get("sub")) != str(user_id):
            return False
        if str(claims.get("scp") or SCOPE_LEDGER) != str(scope):
            return False
        if scope not in BOUND_SCOPES:
            return True
        named = _same_business(claims.get("biz"))
        if isinstance(business_id, (list, tuple, set, frozenset)):
            wanted = {_same_business(b) for b in business_id}
        else:
            wanted = {_same_business(business_id)}
        wanted.discard("")
        return bool(named) and named in wanted
    except Exception:
        return False


async def check_password(email: str, password: str) -> bool:
    """Re-prove the account password against Supabase.

    Deliberately uses the password grant rather than trusting anything
    the client says: the browser must not be able to assert "they typed
    it correctly". A non-200 is a wrong password; a transport failure
    is NOT — that raises, so an outage cannot read as a successful
    unlock. Fail closed, loudly.
    """
    if not SUPABASE_URL or not _anon_key():
        raise HTTPException(503, "Password check unavailable.")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            r = await client.post(
                f"{SUPABASE_URL}/auth/v1/token",
                params={"grant_type": "password"},
                headers={"apikey": _anon_key(), "Content-Type": "application/json"},
                json={"email": email, "password": password},
            )
    except Exception as e:
        logger.warning("[ledger_unlock] password check transport failure: %s", e)
        raise HTTPException(503, "Could not verify your password. Try again.")
    if r.status_code == 200:
        return True
    if r.status_code in (400, 401, 403):
        return False
    logger.warning("[ledger_unlock] unexpected auth status %s", r.status_code)
    raise HTTPException(503, "Could not verify your password. Try again.")


def require_unlock(request: Request, user_id: str,
                   scope: str = SCOPE_LEDGER, business_id: Any = None) -> None:
    """Gate for every surface that re-asks for the password.

    `business_id`: the business this action is for (verify). Every
    access and danger gate passes it; a token confirmed for another
    business is the same refusal as no token, so the app's prompt asks
    again for this one.

    Raises 403 with a MACHINE-READABLE code. The frontend has to be
    able to tell "you must unlock" apart from "you may not read this
    at all" — rendering a password prompt at someone who will never be
    allowed in is its own small cruelty, and rendering "access denied"
    at someone who just needs to type their password is worse.

    The code stays `ledger_locked` for every scope: it is what the
    existing client already branches on, and the SCOPE in the body is
    what tells the prompt which question to ask. Renaming it would
    break the one consumer that works today for no gain.
    """
    if scope not in SCOPES:
        raise ValueError(f"unknown step-up scope: {scope}")
    # No request at all (a caller with none to give) is the same as no
    # token: locked, never a pass.
    token = (request.headers.get(UNLOCK_HEADER) if request is not None else "") or ""
    if not verify(token, user_id, scope, business_id):
        raise HTTPException(
            status_code=403,
            detail={"code": "ledger_locked", "scope": scope,
                    "message": SCOPE_PROMPT[scope]})


# ─── The general step-up endpoint ────────────────────────────────────
#
# /audit/unlock predates scopes and still serves the ledger. It stays
# exactly as it was — its pre-check is "may you READ this ledger",
# which is the right question there and the wrong one here.
#
# This route answers the other two: before letting someone re-prove a
# password in order to grant access or do something irreversible, the
# pre-check is WHO IS ACTING.
#
#   danger ... the OWNER, and nobody else. A viewer seat should never be
#              handed a password oracle for an account-deletion gate.
#   access ... the owner, an ACTIVE Admin seat on that business, or an
#              ACTIVE Manager seat the owner or an Admin gave "Sets up
#              jobs and people's sheets" (church_job_defs.GRANT).
#
# A Manager who is over the office's lanes is NOT one of them. She moves
# her own team's duties (church_duties), and that route does not ask her
# for a password she has no way to confirm; letting her confirm one here
# would have handed her every other access gate too (an invite needs
# only a Manager).
#
# Why access is wider (2026-11-17). Re-proving your own password is the
# protection against an unlocked laptop, so it has to work for whoever
# is acting. It was the owner's alone, which meant an Admin could never
# confirm an invite the app said Admins may send, and a login given the
# grant could never give anyone an area: the gate in front of the
# action was one they had no way through. The people let in are exactly
# the ones the action's own route already lets act; each route still
# decides what they may do, and this adds nothing to that. Every lower
# seat (a Manager without the grant, a Member, a Viewer) and a login
# from another business stay out, for the oracle reason above.

from auth_supabase import AuthedUser, require_user  # noqa: E402
from pydantic import BaseModel  # noqa: E402

router = APIRouter(tags=["step-up"])


class _StepUpBody(BaseModel):
    business_id: str
    password: str
    scope: str


def _business_uuid(business_id: Any) -> str:
    """The business id as a UUID, or a 400: it goes into a PostgREST path,
    where anything else could rewrite the filter."""
    import uuid
    try:
        return str(uuid.UUID(str(business_id or "")))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, "That business id isn't valid.")


def _require_actor(business_id: str, user_id: str, scope: str) -> Dict[str, Any]:
    """Who may re-prove their password here for this scope (see the note
    above): the owner for either; for `access` also an active Admin seat,
    or an active Manager seat that holds the jobs-and-sheets grant, on
    this business. Everyone else is a 403; a read that fails is a 403
    too, never a pass. `business_id` is already a UUID."""
    import sb_clients
    from urllib.parse import quote
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,name,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) == str(user_id):
        return rows[0]
    if scope != SCOPE_ACCESS:
        raise HTTPException(403, "not authorized")
    seat = sb_clients.sb_get_as_service(
        f"/business_users?business_id=eq.{business_id}&user_id=eq.{quote(str(user_id), safe='')}"
        "&status=eq.active&select=role&limit=1")
    role = seat[0].get("role") if isinstance(seat, list) and seat else None
    if role == "admin":
        return rows[0]
    if role == "manager":
        try:
            import church_job_defs
            if church_job_defs.holds_grant(business_id, user_id, role):
                return rows[0]
        except Exception:  # noqa: BLE001 — unread is not a yes
            logger.warning("[step_up] the grant couldn't be read for %s", str(business_id)[:8])
    raise HTTPException(403, "not authorized")


@router.post("/auth/step-up")
async def step_up(body: _StepUpBody,
                  user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Re-prove the account password for one class of consequential action.

    Rate limited on the USER, not the IP, for the same reason the ledger
    unlock is: an attacker at an unlocked laptop already has the
    session, so varying their IP is free while varying whose account
    this is is not. FAIL-CLOSED — a limiter outage must not read as a
    successful step-up on this surface.

    Both outcomes are ledger rows. Repeated failed confirmations against
    an account's danger gate is precisely the pattern someone should be
    able to find afterwards.
    """
    import rate_limit
    scope = (body.scope or "").strip()
    if scope not in (SCOPE_ACCESS, SCOPE_DANGER, SCOPE_CARE):
        # SCOPE_LEDGER deliberately excluded: it has its own endpoint
        # with its own, correct, read-based pre-check.
        raise HTTPException(400, "unknown step-up scope")

    business_id = _business_uuid(body.business_id)
    ttl: Optional[int] = None
    if scope == SCOPE_CARE:
        # Who may open Prayer & care at all (the owner or an active seat;
        # private_care.care_access is a 403 for anyone else, before any
        # password is checked), and how long the church lets it stay open
        # with nothing done.
        import private_care
        private_care.care_access(business_id, user)
        ttl = private_care.unlock_ttl(business_id)
    else:
        _require_actor(business_id, str(user.id), scope)

    if not rate_limit.allow_strict("step_up", str(user.id)):
        raise HTTPException(429, "Too many attempts. Wait a moment.")
    if not (body.password or "").strip():
        raise HTTPException(400, "Enter your password.")

    from audit_log import record
    if not await check_password(user.email, body.password):
        try:
            record(business_id, actor_type="user", actor_id=str(user.id),
                   verb=f"stepup:{scope}_failed", ok=False,
                   summary=f"Failed password confirmation for a {scope} action",
                   authorized_by="step_up")
        except Exception:
            pass
        raise HTTPException(403, "That password did not match.")

    # For this business and no other: the check above was made here.
    out = mint(str(user.id), scope, business_id, ttl)
    try:
        record(business_id, actor_type="user", actor_id=str(user.id),
               verb=f"stepup:{scope}",
               summary=f"Confirmed password for {scope} actions",
               authorized_by="step_up")
    except Exception:
        pass
    return {"ok": True, "scope": scope, **out}
