"""business_access.py — one declarative way to say "this route belongs to
a business, and the caller must be allowed to touch it".

The problem this exists for is not that any single route forgot a check.
It is that the check is a thing you have to REMEMBER to write, in the
body, after the signature, in 446 handlers that take a business id from
the caller. Roughly half do not have one, and the pattern that produces
them is almost invisible on review:

    def save(business_id: str, body: dict,
             _: UserSession = Depends(sb_clients.authed_request)):

That authenticates and then discards the session. It proves somebody is
signed in and nothing whatever about whose data is about to be written.
It reads as guarded because there is a Depends on the line.

So the check moves into the signature, where its absence is visible:

    def save(business_id: str, body: dict,
             biz: dict = Depends(business_access("admin"))):

FastAPI resolves `business_id` for the dependency out of the same path or
query the handler uses, so there is nothing to keep in sync. The
dependency hands back the business row, which means using it is also the
shortest way to get what the handler wanted next — the incentive points
the right way instead of relying on discipline.

Roles, not just ownership. `business_users_router.role_of` already
resolves owner-or-member and ranks the owner above admin; three routers
have copied a private `_access` helper from it. Building on it rather
than on a bare owner_id comparison is what keeps seats working — an
owner-only chokepoint would have locked every member out of their own
practice, which is a worse bug than the one being fixed.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict

from fastapi import Depends, HTTPException

import sb_clients
from auth_supabase import AuthedUser, UserSession, require_user

logger = logging.getLogger("business_access")

# viewer < member < admin < owner, per business_users_router._ROLE_RANK.
DEFAULT_MIN_ROLE = "viewer"


def _resolve_role(business_id: str, user_id: str):
    from business_users_router import role_of
    return role_of(business_id, user_id)


def _rank(role: str) -> int:
    from business_users_router import _ROLE_RANK
    return _ROLE_RANK.get(role, 0)


def business_access(min_role: str = DEFAULT_MIN_ROLE) -> Callable:
    """Dependency factory: require `min_role` on the business named by the
    request, and return that business row.

    Deliberately answers 404 both when the business does not exist AND
    when the caller has no role on it. The existing per-router helpers
    return 404 for missing and 403 for forbidden, which politely confirms
    to a stranger that a given business id is real. On a surface where
    ids are the only thing an attacker needs to guess, "no" should not be
    two distinguishable answers.
    """
    async def _dep(business_id: str,
                   session: UserSession = Depends(sb_clients.authed_request),
                   ) -> Dict[str, Any]:
        # Depends on authed_request, NOT on require_user, and that is
        # load-bearing. authed_request does two things: it verifies the
        # JWT *and* binds it to the request contextvar, so helpers like
        # brand_engine._sb_get forward the caller's token to PostgREST
        # and RLS evaluates against a real auth.uid(). Swapping it for a
        # plain require_user leaves those helpers falling through to the
        # SERVICE ROLE — the guard would tighten authorization while
        # quietly disabling row-level security underneath it.
        #
        # Folding it in here means a route cannot end up with the role
        # check but not the token binding. They arrive together or not
        # at all.
        user = session.user
        rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{business_id}&select=*&limit=1") or []
        if not rows:
            raise HTTPException(status_code=404, detail="business not found")

        role = None
        try:
            role = _resolve_role(business_id, str(user.id))
        except Exception as e:
            # Fail CLOSED. An access check that cannot run is not a
            # permission to proceed — the whole point of moving this into
            # one place is that its failure mode is decided once.
            logger.error("[access] role resolution failed for %s/%s: %s",
                         business_id, user.id, e)
            raise HTTPException(status_code=503,
                                detail="access check unavailable") from e

        if not role or _rank(role) < _rank(min_role):
            logger.warning("[access] denied %s on %s (role=%s, needs=%s)",
                           user.id, business_id, role or "none", min_role)
            raise HTTPException(status_code=404, detail="business not found")

        row = dict(rows[0])
        row["_caller_role"] = role
        return row

    return _dep


def assert_access(business_id: str, user: AuthedUser,
                  min_role: str = DEFAULT_MIN_ROLE) -> str:
    """The imperative form, for handlers where the business id is not a
    path or query parameter.

    A FastAPI dependency declares its own parameters, so `business_id`
    inside one is resolved as a QUERY parameter. That is right for most
    routes and wrong for the ones that take it from a multipart form or
    a request body — there, the dependency would look for a query string
    that never arrives and reject a perfectly valid request. Those call
    this from the body instead. Same rules, same failure mode, same
    indistinguishable 404.
    """
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id&limit=1") or []
    if not rows:
        raise HTTPException(status_code=404, detail="business not found")
    try:
        role = _resolve_role(business_id, str(user.id))
    except Exception as e:
        logger.error("[access] role resolution failed for %s/%s: %s",
                     business_id, user.id, e)
        raise HTTPException(status_code=503,
                            detail="access check unavailable") from e
    if not role or _rank(role) < _rank(min_role):
        logger.warning("[access] denied %s on %s (role=%s, needs=%s)",
                       user.id, business_id, role or "none", min_role)
        raise HTTPException(status_code=404, detail="business not found")
    return role


# The common cases, named so call sites read as intent rather than config.
owned_business = business_access("owner")
admin_business = business_access("admin")
member_business = business_access("member")
readable_business = business_access("viewer")
