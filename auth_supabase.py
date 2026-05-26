"""
auth_supabase.py — Supabase JWT verification helper.

Endpoints under tenant control (publish, send-report, build, etc.) take
`business_id` from the client and trust the application layer to filter
results — this works because Supabase RLS today is permissive and only
Kevin's desktop app calls us.

When we open the system to real practitioners, every endpoint that mutates
a tenant's data needs to verify that the calling user actually owns that
business. This module is the foundation for that — it doesn't gate any
endpoint yet, it just provides the helper Phase 3 will plug in.

USAGE (after Phase 3 wiring):

    from fastapi import Depends
    from auth_supabase import require_user, AuthedUser

    @router.post("/something")
    async def something(user: AuthedUser = Depends(require_user)):
        # user.id is the Supabase auth.uid
        ...

DEPLOYMENT REQUIREMENTS:

    1. pip install pyjwt   (added to requirements.txt)
    2. Railway env var: SUPABASE_JWT_SECRET
       (Supabase dashboard → Settings → API → JWT Secret)
    3. Frontend must send `Authorization: Bearer <supabase_access_token>`

NOTES:

  • Supabase signs JWTs with HS256 by default. We decode + verify with
    the project's shared secret — no JWKS round-trip, no async fetch.
  • Tokens are short-lived (1 hour default); the supabase-js client
    auto-refreshes them. We don't accept expired tokens.
  • Anonymous + service-role keys are NOT user JWTs — calls signed with
    those bypass this helper. RLS handles them at the database layer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

try:
    import jwt  # PyJWT
    from jwt import InvalidTokenError
except ImportError:  # pragma: no cover — surfaced at import time on Railway
    jwt = None
    InvalidTokenError = Exception  # type: ignore[misc,assignment]

from fastapi import Header, HTTPException, status


SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "").strip()
SUPABASE_JWT_AUDIENCE = os.environ.get("SUPABASE_JWT_AUDIENCE", "authenticated")


@dataclass
class AuthedUser:
    """Resolved identity for the current request."""
    id: str         # auth.users.id (a UUID string)
    email: Optional[str]
    role: str       # usually "authenticated"


def _verify_token(token: str) -> AuthedUser:
    if jwt is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="auth_supabase: PyJWT not installed (pip install pyjwt)",
        )
    if not SUPABASE_JWT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="auth_supabase: SUPABASE_JWT_SECRET not configured",
        )
    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience=SUPABASE_JWT_AUDIENCE,
        )
    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
        )
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing sub claim",
        )
    return AuthedUser(
        id=str(sub),
        email=payload.get("email"),
        role=str(payload.get("role") or "authenticated"),
    )


def require_user(authorization: Optional[str] = Header(default=None)) -> AuthedUser:
    """FastAPI dependency that requires a valid Supabase JWT.

    Raises 401 if missing/invalid. Returns the authed user otherwise.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token",
        )
    token = authorization.split(" ", 1)[1].strip()
    return _verify_token(token)


def optional_user(authorization: Optional[str] = Header(default=None)) -> Optional[AuthedUser]:
    """FastAPI dependency that resolves the user if a valid token is present,
    otherwise returns None. Use this on endpoints that work both pre- and
    post-auth-hardening so anonymous traffic doesn't get 401'd.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    try:
        return _verify_token(token)
    except HTTPException:
        return None
