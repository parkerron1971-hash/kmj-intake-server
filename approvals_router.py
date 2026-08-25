"""
approvals_router.py — S11 close-out: draft approvals through the action
layer, not around it.

THE GAP (PR #355's finding): ApprovalQueue.tsx approved agent_queue
drafts via a direct PostgREST PATCH under the user's JWT plus a
client-side /email/send call — bypassing the server entirely, so
approvals left NO audit_log row, and only owners could act (the seat
write policies deliberately don't cover agent_queue). Meanwhile Chief's
approve_draft verb already did the same job properly through
chief_of_staff._do_approve_one.

THIS ROUTER is the HTTP door onto that SAME core:

  POST /approvals/{business_id}/{queue_id}/approve   (manager+)
  POST /approvals/{business_id}/{queue_id}/dismiss   (manager+)

- Role gate: business_users_router.require_role ladder, manager+.
  Viewer/member seats keep their RLS read (trust-seat-visibility
  migration) and the frontend's read-only banner.
- Execution: chief_of_staff._do_approve_one — the exact function
  approve_draft / edit_draft / autopilot use. No duplicated email
  sending, no second status machine. The PATCHes inside it run
  service-role (no user JWT is bound to this request's context), which
  is what lets a manager seat act at all — authorization happened here,
  server-side, first.
- Audit: every approve/dismiss writes an audit_log row with
  actor_type='user', actor_id=the approving user, and the ok/failed
  truth — including a row when execution BLOWS UP (ok=false), which is
  the entire reason this endpoint exists.
- Idempotent: only status='draft' rows execute. Re-approving a sent
  (or approved/dismissed) draft is a 409, never a double-send. Unknown
  or cross-tenant queue ids are 404 (the business filter is in the
  lookup, so another tenant's draft simply isn't found).

There is no GET on purpose: seats already read the queue via RLS.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
import audit_log
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("approvals_router")

router = APIRouter(prefix="/approvals", tags=["approvals"])

_QUEUE_SELECT = "select=*"


class ApproveBody(BaseModel):
    """Optional last-minute edits (the queue's Save & Approve path) —
    mirrors the edit_draft verb: persist the edit, then execute."""
    subject: Optional[str] = None
    body: Optional[str] = None
    source: Optional[str] = None  # desktop|mobile — audit display only
    # Send a document the auditor has blockers on. A deterministic rule
    # can still be wrong about one particular document, and a
    # practitioner who cannot send their own paper will send it from
    # somewhere the system never sees. So the gate yields — and
    # doc_guard records the override as an event, because a bypass
    # nobody can find afterwards would make the gate worse than absent.
    override_blockers: bool = False


class DismissBody(BaseModel):
    source: Optional[str] = None


def _load_biz(business_id: str) -> Dict[str, Any]:
    """The business row _do_approve_one needs (settings feed the email
    signature/closing rules). 404 when the id doesn't exist."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}"
        f"&select=id,name,owner_id,settings&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    return rows[0]


def _require_manager(business_id: str, user: AuthedUser) -> str:
    from business_users_router import require_role
    return require_role(business_id, str(user.id), "manager")


def _load_draft(business_id: str, queue_id: str) -> Dict[str, Any]:
    """Load the queue item SCOPED TO THIS BUSINESS — a queue id that
    belongs to another tenant is indistinguishable from a missing one
    (404), which is the point. 409 when it isn't a draft anymore."""
    rows = sb_clients.sb_get_as_service(
        f"/agent_queue?id=eq.{queue_id}&business_id=eq.{business_id}"
        f"&limit=1&{_QUEUE_SELECT}") or []
    if not rows:
        raise HTTPException(404, "draft not found")
    item = rows[0]
    status = item.get("status") or "draft"
    if status != "draft":
        raise HTTPException(409, f"already {status}")
    return item


def _source(value: Optional[str]) -> str:
    return value if value in ("desktop", "mobile", "voice") else "desktop"


@router.post("/{business_id}/{queue_id}/approve")
async def approve_draft_endpoint(
    business_id: str,
    queue_id: str,
    payload: Optional[ApproveBody] = None,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    biz = _load_biz(business_id)
    _require_manager(business_id, user)
    item = _load_draft(business_id, queue_id)

    payload = payload or ApproveBody()

    # Persist any edits BEFORE executing (edit_draft parity) so the
    # email that goes out is the text the approver actually saw.
    edits: Dict[str, Any] = {}
    if payload.subject is not None:
        edits["subject"] = payload.subject
    if payload.body is not None:
        edits["body"] = payload.body
    if edits:
        sb_clients.sb_patch_as_service(f"/agent_queue?id=eq.{queue_id}", edits)
        item = {**item, **edits}

    # The shared core — the SAME machinery the approve_draft verb uses.
    import chief_of_staff

    delivery: Dict[str, Any] = {}
    error: Optional[str] = None
    try:
        async with httpx.AsyncClient() as client:
            delivery = await chief_of_staff._do_approve_one(
                client, biz, item,
                override_blockers=bool(payload.override_blockers))
    except Exception as e:  # the "failed": True seam — audited, then surfaced
        error = str(e)[:300]
        logger.exception(f"[approvals] approve {queue_id} failed")

    # A document stopped by the auditor is not a failure — it is the
    # gate doing its job, and it needs its own status so the room can
    # show the findings and offer the override. 409, not 500: nothing
    # was sent and the draft is exactly as it was.
    if (delivery or {}).get("reason") == "blocked":
        raise HTTPException(409, (delivery.get("blocked")
                                  or {"error": "document_blocked"}))

    ok = error is None and bool(delivery.get("ok"))
    label = chief_of_staff._approve_label(item.get("subject"), delivery or {})

    audit_log.record(
        business_id,
        actor_type="user",
        actor_id=str(user.id),
        verb="approve_draft",
        ok=ok,
        error=error,
        summary=label if ok else f"Approve failed: {item.get('subject') or queue_id}",
        payload={"queue_id": queue_id, "agent": item.get("agent"),
                 "subject": item.get("subject"),
                 **({"edited": True} if edits else {})},
        result=delivery,
        target_type="agent_queue",
        target_id=queue_id,
        source=_source(payload.source),
    )

    if not ok:
        raise HTTPException(500, "approve failed — the draft is unchanged or partially processed; check History")

    return {
        "ok": True,
        "status": "sent" if delivery.get("sent") else "approved",
        "sent": bool(delivery.get("sent")),
        "reason": delivery.get("reason"),
        "to_email": delivery.get("to_email"),
        "to_name": delivery.get("to_name"),
        "label": label,
    }


@router.post("/{business_id}/{queue_id}/dismiss")
async def dismiss_draft_endpoint(
    business_id: str,
    queue_id: str,
    payload: Optional[DismissBody] = None,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    _load_biz(business_id)
    _require_manager(business_id, user)
    item = _load_draft(business_id, queue_id)

    payload = payload or DismissBody()

    sb_clients.sb_patch_as_service(f"/agent_queue?id=eq.{queue_id}", {
        "status": "dismissed",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    })

    audit_log.record(
        business_id,
        actor_type="user",
        actor_id=str(user.id),
        verb="dismiss_draft",
        ok=True,
        summary=f"Dismissed: {item.get('subject') or 'draft'}",
        payload={"queue_id": queue_id, "agent": item.get("agent"),
                 "subject": item.get("subject")},
        target_type="agent_queue",
        target_id=queue_id,
        source=_source(payload.source),
    )

    return {"ok": True, "status": "dismissed",
            "label": f"Dismissed: {item.get('subject') or 'draft'}"}
