"""content_approval.py — approving a post, and scheduling what was approved.

The gate in post_approval.py refuses to publish anything unattended that
a human has not signed off. This is the other half: the door that lets a
human sign off, and the schedule that carries the signature forward.

Approving and scheduling are ONE call on purpose. Two calls would make
"approved but never scheduled" and "scheduled but never approved" both
reachable states, and the second one is the exact thing the gate exists
to prevent — it would just fail silently at 9am instead of loudly here.

Ownership is checked against businesses.owner_id, the same proof
/connect/meta/start requires. RLS is not the gate here because these
routes read and write through the service role.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import post_approval
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("content_approval")
router = APIRouter(prefix="/content", tags=["content_approval"])

MAX_SCHEDULE_DAYS = 90


# ─── Helpers ─────────────────────────────────────────────────────────

def _own_business(business_id: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,owner_id,settings&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized for this business")
    return rows[0]


def _calendar(settings: Dict[str, Any]) -> Dict[str, Any]:
    cal = settings.get("content_calendar")
    return cal if isinstance(cal, dict) else {}


def _find(planned: List[Dict[str, Any]], post_id: str) -> int:
    for i, p in enumerate(planned):
        if str(p.get("id")) == str(post_id):
            return i
    return -1


def _save_calendar(business_id: str, settings: Dict[str, Any],
                   cal: Dict[str, Any]) -> None:
    """Write the calendar back inside the settings blob it lives in.

    Read-modify-write against the settings handed in by the caller's own
    fresh read — content_calendar shares that object with website_content
    and brand_kit, and a stale copy would drop whichever one it had not
    seen.
    """
    merged = {**(settings or {}), "content_calendar": cal}
    sb_clients.sb_patch_as_service(f"/businesses?id=eq.{business_id}",
                                   {"settings": merged})


def _connected_pages(business_id: str) -> List[Dict[str, Any]]:
    return sb_clients.sb_get_as_service(
        f"/social_accounts?business_id=eq.{business_id}&provider=eq.meta"
        f"&status=eq.connected&select=page_id,page_name,ig_user_id") or []


# ─── Bodies ──────────────────────────────────────────────────────────

class ApproveBody(BaseModel):
    page_id: str
    to_instagram: bool = False
    run_at: Optional[str] = None          # ISO-8601; omit to approve only
    recurrence: Optional[str] = None      # daily | weekdays | weekly


class AutonomyBody(BaseModel):
    value: str                            # approve_all | auto_site


# ─── Routes ──────────────────────────────────────────────────────────

@router.get("/{business_id}/posts/pending")
def pending(business_id: str, user: AuthedUser = Depends(require_user)):
    """Posts waiting on a human, and posts whose approval has gone stale.

    A post edited after approval is listed as pending again rather than
    quietly holding at publish time — the gate would catch it either way,
    but catching it at 9am on a Tuesday tells nobody.
    """
    biz = _own_business(business_id, user)
    cal = _calendar(biz.get("settings") or {})
    out = []
    for p in (cal.get("planned_posts") or []):
        if not isinstance(p, dict):
            continue
        ap = p.get(post_approval.APPROVAL_KEY)
        approved = isinstance(ap, dict) and ap.get("at")
        stale = bool(approved and ap.get("fingerprint") != post_approval.fingerprint(p))
        if approved and not stale:
            continue
        out.append({
            "id": p.get("id"),
            "title": p.get("title") or "",
            "body": p.get("body") or "",
            "image_url": p.get("image_url"),
            "reason": "edited since you approved it" if stale else "not approved yet",
        })
    return {"ok": True, "pending": out, "count": len(out),
            "pages": _connected_pages(business_id)}


@router.post("/{business_id}/posts/{post_id}/approve")
def approve(business_id: str, post_id: str, body: ApproveBody,
            user: AuthedUser = Depends(require_user)):
    """Record that this human approved THIS post, for THIS Page — and,
    if a time is given, queue it."""
    biz = _own_business(business_id, user)
    settings = biz.get("settings") or {}
    cal = _calendar(settings)
    planned = list(cal.get("planned_posts") or [])
    idx = _find(planned, post_id)
    if idx < 0:
        raise HTTPException(404, "no planned post with that id")
    post = dict(planned[idx])

    if not (post.get("body") or post.get("title") or "").strip():
        raise HTTPException(400, "an empty post cannot be approved")

    pages = _connected_pages(business_id)
    page = next((p for p in pages if str(p.get("page_id")) == body.page_id), None)
    if not page:
        raise HTTPException(400, "that Page is not connected to this business")
    if body.to_instagram and not page.get("ig_user_id"):
        raise HTTPException(400, "that Page has no linked Instagram account")
    if body.to_instagram and not (post.get("image_url") or "").strip():
        raise HTTPException(400, "Instagram needs an image on the post")

    run_at: Optional[datetime] = None
    if body.run_at:
        try:
            run_at = datetime.fromisoformat(body.run_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, "run_at is not ISO-8601")
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if run_at <= now:
            raise HTTPException(400, "run_at is in the past")
        # An approval is a judgement about words at a moment. Ninety days
        # out it is a judgement about words nobody remembers writing.
        if run_at > now + timedelta(days=MAX_SCHEDULE_DAYS):
            raise HTTPException(
                400, f"a post cannot be scheduled more than {MAX_SCHEDULE_DAYS} days out")
    if body.recurrence and body.recurrence not in ("daily", "weekdays", "weekly"):
        raise HTTPException(400, "recurrence must be daily, weekdays, or weekly")
    if body.recurrence and not run_at:
        raise HTTPException(400, "a recurrence needs a start time")

    post[post_approval.APPROVAL_KEY] = post_approval.build(
        post, user_id=str(user.id), page_id=body.page_id,
        to_instagram=body.to_instagram,
        when_iso=datetime.now(timezone.utc).isoformat())
    planned[idx] = post
    cal["planned_posts"] = planned
    _save_calendar(business_id, settings, cal)

    scheduled_id = None
    if run_at:
        # page_name, not page_id: publish_post resolves the Page by name.
        # The approval still carries the id, and the gate compares ids —
        # so a rename cannot quietly redirect an approved post.
        row = sb_clients.sb_post_as_service("/chief_scheduled_actions", {
            "business_id": business_id,
            "owner_id": str(user.id),
            "label": f"Post: {(post.get('title') or '')[:80]}",
            "action": {
                "type": "publish_post",
                "post_id": post.get("id"),
                "page_name": page.get("page_name"),
                "to_instagram": bool(body.to_instagram),
            },
            "run_at": run_at.isoformat(),
            "recurrence": body.recurrence,
        })
        scheduled_id = (row or {}).get("id") if isinstance(row, dict) else None

    return {"ok": True, "approved": True, "post_id": post.get("id"),
            "page_name": page.get("page_name"),
            "scheduled_for": run_at.isoformat() if run_at else None,
            "scheduled_id": scheduled_id}


@router.get("/{business_id}/autonomy")
def get_autonomy(business_id: str, user: AuthedUser = Depends(require_user)):
    """The dial, and — deliberately — what it cannot reach.

    `social_always_approved` is returned as a fact, not a setting. A
    reader of this endpoint should not have to infer from an absence
    that Facebook has no automatic mode; absence is how people conclude
    a switch simply hasn't shipped yet.
    """
    import site_publish
    biz = _own_business(business_id, user)
    return {"ok": True,
            "value": site_publish.setting(biz.get("settings") or {}),
            "values": list(site_publish.VALUES),
            "social_always_approved": True}


@router.post("/{business_id}/autonomy")
def set_autonomy(business_id: str, body: AutonomyBody,
                 user: AuthedUser = Depends(require_user)):
    import site_publish
    if body.value not in site_publish.VALUES:
        raise HTTPException(400, f"value must be one of {', '.join(site_publish.VALUES)}")
    biz = _own_business(business_id, user)
    settings = {**(biz.get("settings") or {}), site_publish.SETTING_KEY: body.value}
    sb_clients.sb_patch_as_service(f"/businesses?id=eq.{business_id}",
                                   {"settings": settings})
    return {"ok": True, "value": body.value, "social_always_approved": True}


@router.post("/{business_id}/posts/{post_id}/unapprove")
def unapprove(business_id: str, post_id: str,
              user: AuthedUser = Depends(require_user)):
    """Withdraw an approval. Any queued run for this post stops being
    publishable immediately — the gate reads the post, not the schedule,
    so there is no window where a cancelled approval still fires."""
    biz = _own_business(business_id, user)
    settings = biz.get("settings") or {}
    cal = _calendar(settings)
    planned = list(cal.get("planned_posts") or [])
    idx = _find(planned, post_id)
    if idx < 0:
        raise HTTPException(404, "no planned post with that id")
    post = dict(planned[idx])
    post.pop(post_approval.APPROVAL_KEY, None)
    planned[idx] = post
    cal["planned_posts"] = planned
    _save_calendar(business_id, settings, cal)
    return {"ok": True, "approved": False, "post_id": post_id}
