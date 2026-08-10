"""
consent_router.py — read the AI disclosure, and record accepting it.

    GET  /consent/disclosure/{audience}   the current text + its hash
    GET  /consent/status                  has THIS user accepted it?
    POST /consent/accept                  record an acceptance

The client-facing disclosure is deliberately PUBLIC. Somebody texting a
salon has no account and never will, and a disclosure they have to log
in to read is not a disclosure.

Accepting is recorded in two places on purpose: consent_records is the
evidence (append-only, hash-pinned), and the action ledger gets a row so
the acceptance appears in the same trail as everything else that
happened to the business. An auditor reading one should not have to know
the other exists.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import ai_disclosure
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("consent_router")

router = APIRouter(prefix="/consent", tags=["consent"])


class AcceptBody(BaseModel):
    business_id: str
    audience: str = "practitioner"
    version: Optional[str] = None


@router.get("/disclosure/{audience}")
def disclosure(audience: str) -> Dict[str, Any]:
    """The current disclosure for an audience. PUBLIC by design.

    Returns the hash alongside the text so a reader can check later that
    what they were shown is what a consent record claims they were shown.
    """
    doc = ai_disclosure.current(audience)
    if not doc:
        raise HTTPException(404, f"no disclosure for audience {audience!r}")
    return doc


@router.get("/status")
def status(business_id: str, audience: str = "practitioner",
           user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Whether this user's acceptance still stands for this business.

    `current` is false both when nothing was ever accepted AND when the
    text has changed since — and the caller is told which, because
    "you never agreed" and "what you agreed to was replaced" are
    different conversations to have with someone.
    """
    import business_access
    business_access.assert_access(business_id, user, "viewer")

    cur = ai_disclosure.current(audience)
    if not cur:
        raise HTTPException(404, f"no disclosure for audience {audience!r}")

    rows = sb_clients.sb_get_as_service(
        f"/consent_records?business_id=eq.{business_id}"
        f"&user_id=eq.{user.id}&audience=eq.{audience}"
        f"&order=accepted_at.desc&limit=1&select=version,text_hash,accepted_at") or []
    latest = rows[0] if rows else None

    if not latest:
        return {"current": False, "reason": "never_accepted",
                "required_version": cur["version"], "accepted": None}

    ok = ai_disclosure.is_current(audience, latest.get("version"),
                                  latest.get("text_hash"))
    return {
        "current": ok,
        "reason": (None if ok else
                   ("version_superseded"
                    if latest.get("version") != cur["version"]
                    else "text_changed_since_acceptance")),
        "required_version": cur["version"],
        "accepted": latest,
    }


@router.post("/accept")
def accept(body: AcceptBody, request: Request,
           user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Record that this user accepted the disclosure.

    The HASH is taken from what we ship, not from the client. A caller
    that could post its own hash could manufacture a record of agreeing
    to text that was never shown to anyone.
    """
    import business_access
    business_access.assert_access(body.business_id, user, "member")

    doc = ai_disclosure.get(body.audience, body.version)
    if not doc:
        raise HTTPException(404, "unknown disclosure audience or version")
    if doc["version"] != (ai_disclosure.CURRENT.get(body.audience) or ""):
        # Accepting a superseded version would satisfy the check while
        # leaving the person unaware of what actually changed.
        raise HTTPException(409, "that version has been superseded")

    written = sb_clients.sb_post_as_service("/consent_records?select=id", {
        "business_id": body.business_id,
        "user_id": str(user.id),
        "audience": doc["audience"],
        "document": "ai_disclosure",
        "version": doc["version"],
        "text_hash": doc["hash"],
        "ip": (request.headers.get("x-forwarded-for") or "").split(",")[-1].strip() or None,
        "user_agent": (request.headers.get("user-agent") or "")[:300] or None,
    }, prefer="return=representation")

    if not written:
        # sb_clients returns None on 4xx/5xx without raising. Reporting
        # success over a lost consent record is the one outcome this
        # endpoint must never produce.
        logger.error("[consent] record LOST for %s/%s", body.business_id, user.id)
        raise HTTPException(502, "could not record the acceptance")

    try:
        import audit_log
        audit_log.record(
            body.business_id, actor_type="user", actor_id=str(user.id),
            verb="accept_ai_disclosure", ok=True, source="consent",
            authorized_by=f"{doc['audience']}:v{doc['version']}",
            summary=f"accepted the {doc['audience']} AI disclosure v{doc['version']}",
            payload={"version": doc["version"], "hash": doc["hash"]})
    except Exception as e:      # evidence is already stored; never fatal
        logger.warning("[consent] ledger row failed (non-fatal): %s", e)

    return {"ok": True, "audience": doc["audience"],
            "version": doc["version"], "hash": doc["hash"]}
