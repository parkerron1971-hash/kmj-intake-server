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
from fastapi import HTTPException, Request

logger = logging.getLogger("ledger_unlock")

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
UNLOCK_TTL_SECONDS = 15 * 60
UNLOCK_HEADER = "X-Ledger-Unlock"

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


def mint(user_id: str) -> Dict[str, Any]:
    """A proof that THIS user re-entered their password just now.

    Bound to the user, not to a business: the person is what was
    re-verified. Which businesses they may then read is still decided
    by the read gate, which this does not touch.
    """
    now = int(time.time())
    payload = {"typ": "unlock", "sub": str(user_id),
               "iat": now, "exp": now + UNLOCK_TTL_SECONDS}
    p = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    return {"token": f"{p}.{_sig(p)}", "expires_in": UNLOCK_TTL_SECONDS}


def verify(token: str, user_id: str) -> bool:
    """Signature → type → expiry → SAME USER. The last check is what
    stops one signed-in user's unlock being replayed by another."""
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
        return str(claims.get("sub")) == str(user_id)
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


def require_unlock(request: Request, user_id: str) -> None:
    """Gate for every authenticated ledger surface.

    Raises 403 with a MACHINE-READABLE code. The frontend has to be
    able to tell "you must unlock" apart from "you may not read this
    at all" — rendering a password prompt at someone who will never be
    allowed in is its own small cruelty, and rendering "access denied"
    at someone who just needs to type their password is worse.
    """
    token = request.headers.get(UNLOCK_HEADER) or ""
    if not verify(token, user_id):
        raise HTTPException(
            status_code=403,
            detail={"code": "ledger_locked",
                    "message": "Confirm your password to open the ledger."})
