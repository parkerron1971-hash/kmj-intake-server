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
SCOPES = (SCOPE_LEDGER, SCOPE_ACCESS, SCOPE_DANGER)

# What each scope is asking the practitioner to agree to, in their
# words. The prompt has to name the consequence or it is just a speed
# bump people learn to type through.
SCOPE_PROMPT = {
    SCOPE_LEDGER: "Confirm your password to open the ledger.",
    SCOPE_ACCESS: "Confirm your password to change who can get in.",
    SCOPE_DANGER: "Confirm your password — this one cannot be undone.",
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


def mint(user_id: str, scope: str = SCOPE_LEDGER) -> Dict[str, Any]:
    """A proof that THIS user re-entered their password just now, FOR A
    PARTICULAR KIND OF ACTION.

    Bound to the user, not to a business: the person is what was
    re-verified. Which businesses they may then touch is still decided
    by the ownership and read gates, which this does not replace.
    """
    if scope not in SCOPES:
        raise ValueError(f"unknown step-up scope: {scope}")
    now = int(time.time())
    payload = {"typ": "unlock", "sub": str(user_id), "scp": scope,
               "iat": now, "exp": now + UNLOCK_TTL_SECONDS}
    p = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    return {"token": f"{p}.{_sig(p)}", "expires_in": UNLOCK_TTL_SECONDS}


def verify(token: str, user_id: str, scope: str = SCOPE_LEDGER) -> bool:
    """Signature → type → expiry → SAME USER → SAME SCOPE.

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
        return str(claims.get("scp") or SCOPE_LEDGER) == str(scope)
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
                   scope: str = SCOPE_LEDGER) -> None:
    """Gate for every surface that re-asks for the password.

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
    token = request.headers.get(UNLOCK_HEADER) or ""
    if not verify(token, user_id, scope):
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
# pre-check is OWNERSHIP. A viewer seat should never be handed a
# password oracle for an account-deletion gate.

from auth_supabase import AuthedUser, require_user  # noqa: E402
from pydantic import BaseModel  # noqa: E402

router = APIRouter(tags=["step-up"])


class _StepUpBody(BaseModel):
    business_id: str
    password: str
    scope: str


def _require_owner(business_id: str, user_id: str) -> Dict[str, Any]:
    import sb_clients
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,name,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user_id):
        raise HTTPException(403, "not authorized")
    return rows[0]


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
    if scope not in (SCOPE_ACCESS, SCOPE_DANGER):
        # SCOPE_LEDGER deliberately excluded: it has its own endpoint
        # with its own, correct, read-based pre-check.
        raise HTTPException(400, "unknown step-up scope")

    _require_owner(body.business_id, str(user.id))

    if not rate_limit.allow_strict("step_up", str(user.id)):
        raise HTTPException(429, "Too many attempts. Wait a moment.")
    if not (body.password or "").strip():
        raise HTTPException(400, "Enter your password.")

    from audit_log import record
    if not await check_password(user.email, body.password):
        try:
            record(body.business_id, actor_type="user", actor_id=str(user.id),
                   verb=f"stepup:{scope}_failed", ok=False,
                   summary=f"Failed password confirmation for a {scope} action",
                   authorized_by="step_up")
        except Exception:
            pass
        raise HTTPException(403, "That password did not match.")

    out = mint(str(user.id), scope)
    try:
        record(body.business_id, actor_type="user", actor_id=str(user.id),
               verb=f"stepup:{scope}",
               summary=f"Confirmed password for {scope} actions",
               authorized_by="step_up")
    except Exception:
        pass
    return {"ok": True, "scope": scope, **out}
