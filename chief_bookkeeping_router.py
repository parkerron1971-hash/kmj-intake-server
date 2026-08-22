"""
chief_bookkeeping_router.py — Phase G endpoints.

Owner-gated (require_user + explicit business_id ownership check), mirroring
plaid_router. Thin HTTP layer over chief_bookkeeping.py.

Tier gate (2026-08-22): chief_bookkeeping is a Professional-plan feature —
it has been ADVERTISED on the live plan cards since the 8/18 offer pass but
had zero enforcement, so every plan shipped it (the 7/30 audit class). The
gate rides the six INTELLIGENCE routes (the four analyzers + the two
LLM-in-loop endpoints). counts / list / approve / reject / send-to-inbox
stay ungated on purpose: counts drives the HOME nudge, and a practitioner
who downgrades must still be able to see and resolve proposals Chief
already made — data is never held hostage behind a plan. Dormant like
every gate: BILLING_ENFORCE off → require_feature never raises.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth_supabase import AuthedUser, require_user
import billing_limits
import chief_bookkeeping

logger = logging.getLogger("chief_bookkeeping_router")

router = APIRouter(prefix="/chief", tags=["chief_bookkeeping"])


@router.post("/bookkeeping/analyze-unmatched/{business_id}")
def analyze_unmatched(business_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    chief_bookkeeping.owner_business(business_id, user.id)
    billing_limits.require_feature(business_id, "chief_bookkeeping")
    created = chief_bookkeeping.analyze_unmatched(business_id)
    return {"ok": True, "proposals": created, "count": len(created)}


@router.post("/bookkeeping/analyze-uncategorized/{business_id}")
def analyze_uncategorized(business_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    chief_bookkeeping.owner_business(business_id, user.id)
    billing_limits.require_feature(business_id, "chief_bookkeeping")
    created = chief_bookkeeping.analyze_uncategorized(business_id)
    return {"ok": True, "proposals": created, "count": len(created)}


@router.post("/bookkeeping/analyze-period-close/{business_id}")
def analyze_period_close(business_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """At a reconciled period end, Chief proposes closing the period."""
    chief_bookkeeping.owner_business(business_id, user.id)
    billing_limits.require_feature(business_id, "chief_bookkeeping")
    created = chief_bookkeeping.analyze_period_close(business_id)
    return {"ok": True, "proposals": created, "count": len(created)}


@router.post("/bookkeeping/analyze-gl/{business_id}")
def analyze_gl(business_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Phase I.5 — GL analyzers: bank↔ledger reconciliation drift + the
    post-close Opening Balance Equity reclass."""
    chief_bookkeeping.owner_business(business_id, user.id)
    billing_limits.require_feature(business_id, "chief_bookkeeping")
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


# ─── Phase G v1.5 — LLM-in-loop endpoints ────────────────────────────

class AskTransactionBody(BaseModel):
    business_id: str
    transaction_id: str
    question: Optional[str] = None


@router.post("/bookkeeping/ask-transaction")
async def ask_transaction(body: AskTransactionBody,
                          user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Practitioner highlights a transaction and asks Chief about it.
    Claude answers in the archetype voice; a confident categorization comes
    back as a PENDING proposal through the normal trust pipeline."""
    biz_row = chief_bookkeeping.owner_business(body.business_id, user.id)
    billing_limits.require_feature(body.business_id, "chief_bookkeeping")
    import chief_llm
    return await chief_llm.ask_transaction(
        body.business_id, biz_row.get("type"), body.transaction_id, body.question)


@router.post("/bookkeeping/analyze-hard/{business_id}")
async def analyze_hard(business_id: str,
                       user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """LLM pass over the transactions the deterministic analyzers deflected
    on (one batched call, ≤15 txns). Results are pending proposals."""
    biz_row = chief_bookkeeping.owner_business(business_id, user.id)
    billing_limits.require_feature(business_id, "chief_bookkeeping")
    import chief_llm
    return await chief_llm.analyze_hard(business_id, biz_row.get("type"))


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
    # Category D — an active accountant collaborator may approve
    # period-close proposals (the two-signature counterparty). Everything
    # else stays owner-only.
    try:
        chief_bookkeeping.owner_business(body.business_id, user.id)
    except Exception:
        from business_collaborators_router import is_active_accountant
        p = chief_bookkeeping._get_proposal(body.business_id, proposal_id)
        if not (p and p.get("proposal_type") == "propose_period_close"
                and is_active_accountant(body.business_id, str(user.id))):
            raise
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
