"""
calendar_feeds_router.py — "Use the calendar you already have."

The practitioner pastes a private calendar link (Google's secret iCal
address, an Outlook published calendar, an iCloud public calendar, an
Acuity sync feed) and its busy times keep their booking slots honest.
All the work, and the reasons for it, live in outside_calendar.py.

Endpoints (all owner-gated: require_user + a service-role read of
businesses.owner_id, the contacts_router pattern):

  GET    /availability/{business_id}/calendar-feeds
         The connected calendars, link MASKED. {available: false} until
         the migration is applied, which the app shows as "coming soon".
  POST   /availability/{business_id}/calendar-feeds      {url, label?}
         Validates by fetching once; nothing is saved if the link can't
         be read, and the reason comes back in plain words.
  POST   /availability/{business_id}/calendar-feeds/{feed_id}/sync
         Sync now.
  DELETE /availability/{business_id}/calendar-feeds/{feed_id}
         Removes the feed and every busy time it produced.
  GET    /availability/{business_id}/busy-blocks?from=YYYY-MM-DD&to=YYYY-MM-DD
         Busy times (start, end, all-day only) for the calendar view.

The feed URL is never returned, logged or echoed. Nothing here is a paid
call, so nothing is metered; the fetch rides rate_limit (per user, fail
open) because each connect or sync makes the server fetch a URL.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import outside_calendar
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("calendar_feeds_router")

router = APIRouter(prefix="/availability", tags=["calendar-feeds"])

NOT_SET_UP = "Connecting another calendar isn't switched on yet."
BUSY_WINDOW_MAX_DAYS = 62


def _uuid(value: str, what: str) -> str:
    """Ids go into PostgREST query strings; only a real UUID gets there."""
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        raise HTTPException(status_code=404, detail=f"{what} not found")


def _require_owner(business_id: str, user: AuthedUser) -> None:
    """contacts_router's gate: service-role read of the owner, compared
    to the verified JWT subject. Independent of RLS."""
    _uuid(business_id, "business")
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=owner_id&limit=1"
    ) or []
    if not rows:
        raise HTTPException(status_code=404, detail="business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized for this business")


def _fetch_allowed(user: AuthedUser) -> None:
    try:
        import rate_limit
        if not rate_limit.allow("calendar_feed_fetch", str(user.id)):
            raise HTTPException(status_code=429,
                                detail="That's a lot of calendar checks. Try again in a minute.")
    except HTTPException:
        raise
    except Exception:
        pass  # fail open, like every rate_limit caller


class ConnectBody(BaseModel):
    url: str = Field(..., min_length=8, max_length=2048)
    label: Optional[str] = Field(None, max_length=80)


@router.get("/{business_id}/calendar-feeds")
def list_calendar_feeds(
    business_id: str,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    _require_owner(business_id, user)
    try:
        return outside_calendar.list_feeds(business_id)
    except Exception as e:
        logger.warning("[calendar] list failed for %s: %s", business_id, type(e).__name__)
        raise HTTPException(status_code=503,
                            detail="We couldn't load your connected calendars right now.")


@router.post("/{business_id}/calendar-feeds")
def connect_calendar_feed(
    business_id: str,
    body: ConnectBody,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    _require_owner(business_id, user)
    _fetch_allowed(user)
    try:
        out = outside_calendar.connect_feed(
            business_id, body.url, label=body.label, created_by=str(user.id))
    except outside_calendar.NotSetUp:
        raise HTTPException(status_code=503, detail=NOT_SET_UP)
    except outside_calendar.FeedError as e:
        raise HTTPException(status_code=400, detail=e.message)
    except outside_calendar.FeedConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.warning("[calendar] connect failed for %s: %s", business_id, type(e).__name__)
        raise HTTPException(status_code=503,
                            detail="We couldn't connect that calendar right now. Please try again.")
    return {"ok": True, **out}


@router.post("/{business_id}/calendar-feeds/{feed_id}/sync")
def sync_calendar_feed(
    business_id: str,
    feed_id: str,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    _require_owner(business_id, user)
    feed_id = _uuid(feed_id, "calendar")
    _fetch_allowed(user)
    try:
        out = outside_calendar.sync_now(business_id, feed_id)
    except outside_calendar.NotSetUp:
        raise HTTPException(status_code=503, detail=NOT_SET_UP)
    except LookupError:
        raise HTTPException(status_code=404, detail="calendar not found")
    except Exception as e:
        logger.warning("[calendar] sync failed for %s: %s", business_id, type(e).__name__)
        raise HTTPException(status_code=503,
                            detail="We couldn't check that calendar right now. Please try again.")
    return {"ok": True, **out}


@router.delete("/{business_id}/calendar-feeds/{feed_id}")
def remove_calendar_feed(
    business_id: str,
    feed_id: str,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    _require_owner(business_id, user)
    feed_id = _uuid(feed_id, "calendar")
    try:
        removed = outside_calendar.remove_feed(business_id, feed_id)
    except outside_calendar.NotSetUp:
        raise HTTPException(status_code=503, detail=NOT_SET_UP)
    except Exception as e:
        logger.warning("[calendar] remove failed for %s: %s", business_id, type(e).__name__)
        raise HTTPException(status_code=503,
                            detail="We couldn't remove that calendar right now. Please try again.")
    if not removed:
        raise HTTPException(status_code=404, detail="calendar not found")
    return {"ok": True, "removed": feed_id}


def _parse_day(value: Optional[str], default: date) -> date:
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid date: {value!r} (expect YYYY-MM-DD)")


@router.get("/{business_id}/busy-blocks")
def list_busy_blocks(
    business_id: str,
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Busy times from the practitioner's other calendars for [from, to]
    (UTC days, inclusive). Times only: no titles, no details."""
    _require_owner(business_id, user)
    today = datetime.now(timezone.utc).date()
    fd = _parse_day(from_date, today)
    td = _parse_day(to_date, fd + timedelta(days=14))
    if td < fd:
        raise HTTPException(status_code=400, detail="`to` is before `from`")
    if (td - fd).days > BUSY_WINDOW_MAX_DAYS:
        raise HTTPException(status_code=400,
                            detail=f"ask for at most {BUSY_WINDOW_MAX_DAYS} days at a time")
    lo = datetime.combine(fd, time(0), tzinfo=timezone.utc)
    hi = datetime.combine(td + timedelta(days=1), time(0), tzinfo=timezone.utc)
    rows = outside_calendar.busy_blocks_between(business_id, lo, hi)
    return {
        "ok": True,
        "available": not outside_calendar.tables_known_absent(),
        "from": fd.isoformat(),
        "to": td.isoformat(),
        "blocks": [{"starts_at": r.get("starts_at"), "ends_at": r.get("ends_at"),
                    "all_day": bool(r.get("all_day"))} for r in rows],
    }
