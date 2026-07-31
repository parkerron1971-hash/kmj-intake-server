"""
payroll_router.py — Rails demand-driven arc — payroll interest capture.

The ruling: payroll (Gusto Embedded) is heavy compliance and real
per-customer cost — don't pay to validate demand nobody has voiced.
And the dead-weight rule forbids a "coming soon" card that does
nothing. This is the honest middle: a card whose button RECORDS the
demand and tells Kevin, so the day the count justifies the Gusto
contract, the waitlist already exists.

  POST /payroll/interest?biz=  — owner records interest (idempotent);
                                 Kevin hears about it in the Mission
                                 Control inbox.
  GET  /payroll/interest?biz=  — has this business already raised a
                                 hand? (drives the on-the-list state)
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("payroll_router")

router = APIRouter(prefix="/payroll", tags=["payroll"])


def _owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    return rows[0]


@router.get("/interest")
def get_interest(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    rows = sb_clients.sb_get_as_service(
        f"/payroll_interest?business_id=eq.{biz}&select=id,requested_at&limit=1") or []
    return {"ok": True, "requested": bool(rows),
            "requested_at": rows[0]["requested_at"] if rows else None}


@router.post("/interest")
async def record_interest(biz: str,
                          user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    b = _owner(biz, user)
    existing = sb_clients.sb_get_as_service(
        f"/payroll_interest?business_id=eq.{biz}&select=id&limit=1") or []
    if existing:
        return {"ok": True, "requested": True, "already": True}

    sb_clients.sb_post_as_service("/payroll_interest", {
        "business_id": biz,
        "requested_by": str(user.id),
    }, prefer=None)

    # Kevin hears about real demand where he reads mail: the platform
    # inbox. Best-effort — the interest row is the record.
    try:
        from email_sender import send_via_resend
        count_rows = sb_clients.sb_get_as_service(
            "/payroll_interest?select=id&limit=1000") or []
        await send_via_resend(
            to_email="admin@mysolutionist.app",
            to_name="Kevin",
            from_email="noreply@mysolutionist.app",
            from_name="The Solutionist System",
            subject=f"Payroll interest: {b.get('name') or biz[:8]} "
                    f"({len(count_rows)} total)",
            body=(f"{b.get('name') or 'A business'} asked for payroll.\n\n"
                  f"Total businesses on the payroll waitlist: {len(count_rows)}.\n"
                  f"The Gusto ruling: activate when demand justifies the "
                  f"per-customer cost — this is the demand signal."),
            reply_to=None,
        )
    except Exception as e:
        logger.warning(f"[payroll] interest email failed (row recorded): {e}")

    import audit_log
    audit_log.record(biz, actor_type="user", actor_id=str(user.id),
                     verb="payroll_interest", summary="Asked for payroll (Gusto waitlist)",
                     source="desktop")
    logger.info(f"[payroll] interest recorded biz={biz[:8]}")
    return {"ok": True, "requested": True, "already": False}
