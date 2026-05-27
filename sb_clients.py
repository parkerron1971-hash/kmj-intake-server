"""
sb_clients.py — central Supabase REST client helpers for the RLS-readiness
migration.

Three variants for backend → PostgREST traffic:

  ANONYMOUS (deprecated for businesses + other RLS-protected tables)
    sb_headers_anon(prefer=None)
    Headers signed with SUPABASE_ANON. Pre-RLS-era code shipped these.
    auth.uid() in PostgREST is NULL for anon callers, so any
    `policy USING (owner_id = auth.uid())` filters every row.
    Keep for migration transition; do not introduce new callers.

  USER-SCOPED (RLS-enforced; for UI-driven reads/writes)
    sb_as_user(client, method, path, user_jwt, body=None)              [async]
    sb_get_as_user(path, user_jwt) / sb_patch_as_user(path, body, …)   [sync]
    Headers signed with the practitioner's Supabase access token forwarded
    by the frontend. PostgREST verifies the JWT against the project's
    SUPABASE_JWT_SECRET (HS256) or JWKS (RS256/ES256) and sets auth.uid()
    to the user's sub claim. RLS policies evaluate honestly. This is the
    "Chief is logged in as Kevin" path — Kevin's businesses are visible,
    other practitioners' aren't.

  SERVICE-ROLE (RLS-bypassed; for genuinely server-initiated traffic)
    sb_as_service(client, method, path, body=None)                     [async]
    sb_get_as_service(path) / sb_patch_as_service(path, body, …)       [sync]
    Headers signed with SUPABASE_SERVICE_ROLE_KEY. RLS is bypassed by
    design — the server is the trusted intermediary. ONLY use for paths
    that have no user JWT in the picture:
      • public site rendering (anonymous viewers at mysolutionist.app/{slug})
      • cron / autopilot sweeps (server-scheduled)
      • webhook handlers (Stripe / Meta callbacks)
      • notification engine morning brief / midday ping
      • recurrence cron in Chief (runs before user context is needed)
    Do NOT use service-role to "fix" a missing JWT on a user-initiated
    endpoint — that would silently strip the security model. Use sb_as_user
    and trace why the JWT isn't being forwarded.

Env var contract:
  SUPABASE_URL                 required for all variants
  SUPABASE_ANON                used by anon variant
  SUPABASE_SERVICE_ROLE_KEY    used by service-role variant
  SUPABASE_JWT_SECRET / JWKS   used by auth_supabase.require_user on inbound
                               token verification (this module only forwards
                               the token; it doesn't verify — that's the
                               dependency's job)
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 15.0


# ─── Request-scoped user JWT propagation ──────────────────────────
#
# contextvars-based propagation lets a handler bind the practitioner's
# token at the request entry point, and every nested helper that calls
# _sb (across long files like chief_of_staff.py with ~30 helpers) picks
# it up automatically without a thread-through signature change.
#
# async-safe: contextvars are per-async-task by design, so concurrent
# requests don't bleed tokens into each other.
#
# Pattern:
#   @router.post("/something")
#   async def handler(req: Req, user_session = Depends(require_user_session)):
#       with sb_clients.with_user_jwt(user_session.token):
#           # any _sb / sb_as_current_context call inside here uses the user's
#           # JWT; PostgREST sees auth.uid() = user.sub; RLS resolves honestly.
#           ...

_user_jwt_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "sb_clients.user_jwt", default=None,
)


class with_user_jwt:
    """Context manager that binds a user JWT to the current async context.
    Re-entrant safe via contextvars reset tokens.

    Usage:
        with sb_clients.with_user_jwt(token):
            # all _sb calls in here see the token
            ...
    """

    def __init__(self, jwt: str):
        if not jwt:
            raise ValueError(
                "with_user_jwt requires a non-empty JWT. "
                "Use with_no_context or explicit sb_as_service for "
                "server-initiated paths."
            )
        self._jwt = jwt
        self._reset_token: Optional[contextvars.Token] = None

    def __enter__(self) -> str:
        self._reset_token = _user_jwt_ctx.set(self._jwt)
        return self._jwt

    def __exit__(self, *exc_info) -> None:
        if self._reset_token is not None:
            _user_jwt_ctx.reset(self._reset_token)
            self._reset_token = None


def get_current_user_jwt() -> Optional[str]:
    """Read the user JWT bound to the current async context, if any."""
    return _user_jwt_ctx.get()


def set_user_jwt(jwt: str) -> contextvars.Token:
    """Lower-level setter — handler binds the practitioner's JWT at request
    entry, captures the returned reset Token, and passes it to reset_user_jwt
    in a finally block. Equivalent to the with_user_jwt() context manager
    but lets handlers keep their existing try/except structure intact
    without re-indenting the body.

    Usage:
        _jwt_tok = sb_clients.set_user_jwt(user_session.token)
        try:
            ...
        finally:
            sb_clients.reset_user_jwt(_jwt_tok)
    """
    if not jwt:
        raise ValueError("set_user_jwt requires a non-empty JWT")
    return _user_jwt_ctx.set(jwt)


def reset_user_jwt(token: contextvars.Token) -> None:
    """Restore the prior user_jwt context. Paired with set_user_jwt."""
    _user_jwt_ctx.reset(token)


async def sb_as_current_context(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    body: Any = None,
    *,
    allow_service_fallback: bool = False,
) -> Optional[Any]:
    """Convenience: pick user-scoped vs service-role based on whether a
    user JWT is currently in async context. Most legacy `_sb` helpers
    can swap to this with no signature change at call sites.

      • If user JWT IS in context: forwards it (RLS-enforced).
      • If NOT and allow_service_fallback=True: uses service-role
        (for paths that legitimately have no user — cron, webhooks).
      • If NOT and allow_service_fallback=False: returns None and logs
        a warning. Surfaces the "we lost the user context" bug at the
        helper level rather than silently going anonymous.
    """
    user_jwt = _user_jwt_ctx.get()
    if user_jwt:
        return await sb_as_user(client, method, path, user_jwt, body)
    if allow_service_fallback:
        return await sb_as_service(client, method, path, body)
    logger.warning(
        "sb_as_current_context: no user JWT in context for %s %s — "
        "returning None. Use with_user_jwt() at the handler entry, or "
        "set allow_service_fallback=True for server-initiated paths.",
        method, path,
    )
    return None


# ─── Env readers ───────────────────────────────────────────────────

def sb_url() -> str:
    """Returns SUPABASE_URL trimmed of any trailing slash."""
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def sb_anon() -> str:
    """Returns SUPABASE_ANON. Empty string if unset."""
    return os.environ.get("SUPABASE_ANON", "")


def sb_service_role() -> str:
    """Returns SUPABASE_SERVICE_ROLE_KEY. Empty string if unset."""
    return os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


# ─── Header builders ───────────────────────────────────────────────

def _common_headers(prefer: Optional[str]) -> Dict[str, str]:
    h: Dict[str, str] = {"Content-Type": "application/json"}
    if prefer:
        h["Prefer"] = prefer
    return h


def sb_headers_anon(prefer: Optional[str] = "return=representation") -> Dict[str, str]:
    """Legacy anon headers. Use only for migration-period back-compat
    or for endpoints with no RLS exposure (unprotected tables)."""
    anon = sb_anon()
    h = _common_headers(prefer)
    h["apikey"] = anon
    h["Authorization"] = f"Bearer {anon}"
    return h


def sb_headers_user(user_jwt: str, prefer: Optional[str] = "return=representation") -> Dict[str, str]:
    """RLS-enforced headers. apikey stays the project anon key (PostgREST
    uses it to identify the project, not the caller). Authorization is
    the user's access token — PostgREST verifies it and sets auth.uid()
    to the JWT's sub claim. RLS policies then evaluate against the real
    practitioner identity.

    Caller is responsible for verifying the JWT before this — typically
    via auth_supabase.require_user as a FastAPI dependency.
    """
    if not user_jwt:
        raise ValueError(
            "sb_headers_user requires a user_jwt; pass the practitioner's "
            "access token (forwarded from frontend Authorization header). "
            "For server-initiated reads, use sb_headers_service instead."
        )
    h = _common_headers(prefer)
    h["apikey"] = sb_anon() or sb_service_role()
    h["Authorization"] = f"Bearer {user_jwt}"
    return h


def sb_headers_service(prefer: Optional[str] = "return=representation") -> Dict[str, str]:
    """RLS-bypassing headers. Service role key is privileged — every row
    is visible regardless of RLS policies. ONLY use for genuinely
    server-initiated traffic (cron, public site rendering, webhooks)."""
    key = sb_service_role()
    if not key:
        # Surface as a runtime error rather than silently degrading — a
        # missing service-role key on a "this path must work without a
        # user" call is a deploy-config bug worth crashing on.
        raise RuntimeError(
            "sb_headers_service requires SUPABASE_SERVICE_ROLE_KEY env var; "
            "set it on Railway or the equivalent deploy target."
        )
    h = _common_headers(prefer)
    h["apikey"] = key
    h["Authorization"] = f"Bearer {key}"
    return h


# ─── Async API (httpx.AsyncClient) — matches chief_of_staff._sb shape ───

async def _async_request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    headers: Dict[str, str],
    body: Any = None,
) -> Optional[Any]:
    url = f"{sb_url()}/rest/v1{path}"
    try:
        resp = await client.request(
            method,
            url,
            headers=headers,
            content=json.dumps(body) if body is not None else None,
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as e:
        logger.warning(f"sb_clients async {method} {path} transport error: {e}")
        return None
    if resp.status_code >= 400:
        logger.error(
            f"sb_clients async {method} {path}: {resp.status_code} {resp.text[:300]}"
        )
        return None
    text = resp.text
    return json.loads(text) if text else None


async def sb_as_user(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    user_jwt: str,
    body: Any = None,
) -> Optional[Any]:
    """RLS-enforced async PostgREST call. Forwards user_jwt as Bearer.
    Drop-in replacement for chief_of_staff._sb when a request has been
    authenticated via auth_supabase.require_user."""
    return await _async_request(
        client, method, path, sb_headers_user(user_jwt), body,
    )


async def sb_as_service(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    body: Any = None,
) -> Optional[Any]:
    """RLS-bypassing async PostgREST call. Use ONLY for server-initiated
    paths with no user JWT — cron, public site rendering, webhooks."""
    return await _async_request(
        client, method, path, sb_headers_service(), body,
    )


async def sb_as_anon(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    body: Any = None,
) -> Optional[Any]:
    """LEGACY anon call. Subject to RLS — will return zero rows for any
    RLS-protected table. Kept for migration-period back-compat only."""
    return await _async_request(
        client, method, path, sb_headers_anon(), body,
    )


# ─── Sync API (httpx.Client) — matches brand_engine._sb_get / _sb_patch ──

def _sync_request(
    method: str,
    path: str,
    headers: Dict[str, str],
    body: Any = None,
) -> Optional[Any]:
    url = f"{sb_url()}/rest/v1{path}"
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            if body is None:
                resp = client.request(method, url, headers=headers)
            else:
                resp = client.request(
                    method, url, headers=headers, content=json.dumps(body),
                )
    except httpx.HTTPError as e:
        logger.warning(f"sb_clients sync {method} {path} transport error: {e}")
        return None
    if resp.status_code >= 400:
        logger.warning(
            f"sb_clients sync {method} {path}: {resp.status_code} {resp.text[:300]}"
        )
        return None
    text = resp.text
    return json.loads(text) if text else None


def sb_get_as_user(path: str, user_jwt: str) -> Optional[Any]:
    """RLS-enforced sync GET. Forwards user_jwt as Bearer."""
    return _sync_request("GET", path, sb_headers_user(user_jwt))


def sb_patch_as_user(path: str, body: Dict[str, Any], user_jwt: str) -> Optional[Any]:
    """RLS-enforced sync PATCH. Forwards user_jwt as Bearer."""
    return _sync_request("PATCH", path, sb_headers_user(user_jwt), body)


def sb_post_as_user(path: str, body: Dict[str, Any], user_jwt: str) -> Optional[Any]:
    """RLS-enforced sync POST. Forwards user_jwt as Bearer."""
    return _sync_request("POST", path, sb_headers_user(user_jwt), body)


def sb_get_as_service(path: str) -> Optional[Any]:
    """RLS-bypassing sync GET. Server-initiated paths only."""
    return _sync_request("GET", path, sb_headers_service())


def sb_patch_as_service(path: str, body: Dict[str, Any]) -> Optional[Any]:
    """RLS-bypassing sync PATCH. Server-initiated paths only."""
    return _sync_request("PATCH", path, sb_headers_service(), body)


def sb_post_as_service(path: str, body: Dict[str, Any]) -> Optional[Any]:
    """RLS-bypassing sync POST. Server-initiated paths only."""
    return _sync_request("POST", path, sb_headers_service(), body)


def sb_get_as_anon(path: str) -> Optional[Any]:
    """LEGACY anon sync GET. Subject to RLS — returns zero rows for any
    RLS-protected table. Kept for migration-period back-compat only."""
    return _sync_request("GET", path, sb_headers_anon())


def sb_patch_as_anon(path: str, body: Dict[str, Any]) -> Optional[Any]:
    """LEGACY anon sync PATCH. Subject to RLS. Kept for back-compat only."""
    return _sync_request("PATCH", path, sb_headers_anon(), body)
