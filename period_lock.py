"""
period_lock.py — Phase I.3 PR2 — soft-lock helpers.

A date is "locked" when a CLOSED period of any granularity covers it (a closed
year locks every day in it; a closed month locks that month; 'reopened' is NOT
locked). Edits to locked rows are allowed WITH a reason that's recorded in
period_edit_overrides (pre/post snapshots) — never silent (R3).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import sb_clients

logger = logging.getLogger("period_lock")

# Most-specific first so the override row points at the tightest period.
_SPECIFICITY = {"month": 0, "quarter": 1, "year": 2}


def locked_period(business_id: str, day: str) -> Optional[Dict[str, Any]]:
    """Return the (most specific) CLOSED period covering `day` (yyyy-mm-dd),
    or None if the date isn't in any closed period."""
    if not day:
        return None
    rows = sb_clients.sb_get_as_service(
        f"/accounting_periods?business_id=eq.{business_id}&status=eq.closed"
        f"&period_start=lte.{day}&period_end=gte.{day}"
        f"&select=id,period_type,period_start,period_end,status&limit=10") or []
    if not rows:
        return None
    rows.sort(key=lambda p: _SPECIFICITY.get(p.get("period_type"), 9))
    return rows[0]


def record_override(business_id: str, period: Optional[Dict[str, Any]], *,
                    source_type: str, source_id: str, reason: str,
                    override_by: str, role: str = "owner",
                    pre: Any = None, post: Any = None) -> None:
    """Write the audit row. Best-effort logging on failure (the edit itself
    is the caller's concern)."""
    sb_clients.sb_post_as_service("/period_edit_overrides", {
        "business_id": business_id,
        "accounting_period_id": (period or {}).get("id"),
        "source_type": source_type, "source_id": str(source_id),
        "override_reason": reason, "override_by": override_by, "override_by_role": role,
        "pre_change_snapshot": pre, "post_change_snapshot": post,
    }, prefer=None)


def guard(business_id: str, day: str, *, source_type: str, source_id: str,
          reason: Optional[str], override_by: str, role: str = "owner",
          pre: Any = None, post: Any = None) -> None:
    """Backend gate for backend-mediated edits. If `day` is locked and no
    reason is supplied → 409. If a reason is supplied → record the override
    and allow. No-op when the date isn't locked."""
    from fastapi import HTTPException
    p = locked_period(business_id, day)
    if not p:
        return
    if not (reason or "").strip():
        raise HTTPException(409, {
            "error": "period_closed",
            "message": f"This is in a closed period ({p.get('period_start')}–{p.get('period_end')}). "
                       "Editing requires a reason (it will be logged in the audit trail).",
            "period_id": p.get("id"),
        })
    try:
        record_override(business_id, p, source_type=source_type, source_id=source_id,
                        reason=reason.strip(), override_by=override_by, role=role, pre=pre, post=post)
    except Exception as e:
        logger.warning(f"[period_lock] override record failed: {e}")
