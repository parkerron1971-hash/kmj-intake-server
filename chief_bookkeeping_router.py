"""
chief_bookkeeping_router.py — Phase G endpoints.

Owner-gated (require_user + explicit business_id ownership check), mirroring
plaid_router. Thin HTTP layer over chief_bookkeeping.py.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth_supabase import AuthedUser, require_user
import chief_bookkeeping

logger = logging.getLogger("chief_bookkeeping_router")

router = APIRouter(prefix="/chief", tags=["chief_bookkeeping"])


@router.post("/bookkeeping/analyze-unmatched/{business_id}")
def analyze_unmatched(business_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    chief_bookkeeping.owner_business(business_id, user.id)
    created = chief_bookkeeping.analyze_unmatched(business_id)
    return {"ok": True, "proposals": created, "count": len(created)}


@router.post("/bookkeeping/analyze-uncategorized/{business_id}")
def analyze_uncategorized(business_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    chief_bookkeeping.owner_business(business_id, user.id)
    created = chief_bookkeeping.analyze_uncategorized(business_id)
    return {"ok": True, "proposals": created, "count": len(created)}


@router.post("/bookkeeping/analyze-period-close/{business_id}")
def analyze_period_close(business_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """At a reconciled period end, Chief proposes closing the period."""
    chief_bookkeeping.owner_business(business_id, user.id)
    created = chief_bookkeeping.analyze_period_close(business_id)
    return {"ok": True, "proposals": created, "count": len(created)}


@router.post("/bookkeeping/analyze-gl/{business_id}")
def analyze_gl(business_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Phase I.5 — GL analyzers: bank↔ledger reconciliation drift + the
    post-close Opening Balance Equity reclass."""
    chief_bookkeeping.owner_business(business_id, user.id)
    created = chief_bookkeeping.analyze_gl(business_id)
    return {"ok": True, "proposals": created, "count": len(created)}


@router.get("/bookkeeping/counts/{business_id}")
def counts(business_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Drives the HOME nudge (linked + unmatched/uncategorized counts)."""
    chief_bookkeeping.owner_business(business_id, user.id)
    c = chief_bookkeeping.bookkeeping_counts(business_id)
    c["needs_attention"] = chief_bookkeeping.needs_attention(c)
    c["ok"] = True
    return c


@router.get("/proposals")
def list_proposals(biz: str, status: Optional[str] = None,
                   user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    chief_bookkeeping.owner_business(biz, user.id)
    return {"ok": True, "proposals": chief_bookkeeping.list_proposals(biz, status)}


class ProposalResolveBody(BaseModel):
    business_id: str


class RejectBody(BaseModel):
    business_id: str
    override: Optional[Dict[str, Any]] = None
    override_reason: Optional[str] = None


@router.post("/proposals/{proposal_id}/approve")
def approve(proposal_id: str, body: ProposalResolveBody,
            user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    chief_bookkeeping.owner_business(body.business_id, user.id)
    return chief_bookkeeping.approve_proposal(body.business_id, proposal_id, approved_by=str(user.id))


@router.post("/proposals/{proposal_id}/reject")
def reject(proposal_id: str, body: RejectBody,
           user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    chief_bookkeeping.owner_business(body.business_id, user.id)
    return chief_bookkeeping.reject_proposal(
        body.business_id, proposal_id, body.override, body.override_reason)


@router.post("/proposals/{proposal_id}/send-to-inbox")
def send_to_inbox(proposal_id: str, body: ProposalResolveBody,
                  user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    chief_bookkeeping.owner_business(body.business_id, user.id)
    return chief_bookkeeping.send_to_inbox(body.business_id, proposal_id)
