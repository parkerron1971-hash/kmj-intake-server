"""business_marketing_calendar.py — one calendar of everything that goes out.

The Reach plan's step 1 (Kevin, 2026-10-08: "ok all of the plans are great.
let's do it."): one calendar, any month, of what a business sends: its desk
posts (marketing_posts) and its Outreach emails and texts (campaigns_router:
a touch goes out on the campaign's start day plus the touch's offset).
Offers join when they exist (step 3).

  GET /marketing/{business_id}/calendar?month=YYYY-MM   (viewer)

  items   in time order, each {kind: post|email|text, at, ...}:
          post   the desk's own public post (status, caption, accounts, media)
          email  {campaign_id, campaign, touch, subject, preview, state, sent}
          text   {campaign_id, campaign, touch, preview, state, sent}
          state  planned (its day is ahead), sending (due, still going out:
                 quiet hours, a held link, the per-tick cap), sent (the touch
                 finished), paused (the campaign is paused); sent = how many
                 people it went to (campaign_sends)
  month   the month asked, on the business's own clock (days start at its
          local midnight); a draft campaign has no day yet and is not shown
  sources {posts, campaigns}: loaded | partial (at a row limit: a floor) |
          unavailable (a read failed: never shown as an empty month)

A read that fails is named in sources and its items are left out; the month
is still answered with what could be read. Nothing here writes.
"""
from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import business_marketing_store as store
import sb_clients
from business_marketing_desk import POST_COLUMNS, public_post, query_time

MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
POSTS_LIMIT = 500
CAMPAIGNS_LIMIT = 200
SENDS_LIMIT = 20000
PREVIEW = 140
ON_CALENDAR = ("running", "paused", "completed")


def month_bounds(month: str, tz) -> Tuple[date, datetime, datetime]:
    """(first day, its local midnight, the next month's) for "YYYY-MM"."""
    m = MONTH.match(month or "")
    if not m:
        raise ValueError("Ask for a month as YYYY-MM.")
    first = date(int(m.group(1)), int(m.group(2)), 1)
    following = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    return (first, datetime.combine(first, time(0), tz).astimezone(timezone.utc),
            datetime.combine(following, time(0), tz).astimezone(timezone.utc))


def _when(value: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _preview(text: Any) -> str:
    words = " ".join(str(text or "").split())
    return words if len(words) <= PREVIEW else words[:PREVIEW - 1].rstrip() + "…"


def touch_items(campaign: Dict[str, Any], sent: Dict[int, int], start: datetime, end: datetime,
                now: datetime) -> List[Dict[str, Any]]:
    """A campaign's touches that fall in [start, end): each on the campaign's
    start day plus its offset (campaigns_tick's own rule)."""
    began = _when(campaign.get("start_at"))
    if not began or campaign.get("status") not in ON_CALENDAR:
        return []
    out = []
    for idx, touch in enumerate(campaign.get("touches") or []):
        if not isinstance(touch, dict) or touch.get("channel") not in ("email", "sms"):
            continue
        try:
            at = began + timedelta(days=int(touch.get("offset_days") or 0))
        except (TypeError, ValueError):
            continue
        if not (start <= at < end):
            continue
        if touch.get("completed_at"):
            state = "sent"
        elif campaign.get("status") == "paused":
            state = "paused"
        elif at <= now:
            state = "sending"
        else:
            state = "planned"
        item = {"kind": "email" if touch["channel"] == "email" else "text", "at": at.isoformat(),
                "campaign_id": campaign["id"], "campaign": campaign.get("name") or "Outreach", "touch": idx,
                "preview": _preview(touch.get("body")), "state": state, "sent": sent.get(idx, 0)}
        if touch["channel"] == "email":
            item["subject"] = (touch.get("subject") or "").strip()
        out.append(item)
    return out


async def _posts(bid: str, start: datetime, end: datetime) -> List[Dict[str, Any]]:
    return await store.rows(
        f"/marketing_posts?business_id=eq.{bid}&run_at=gte.{query_time(start)}&run_at=lt.{query_time(end)}"
        f"&status=neq.cancelled&select={POST_COLUMNS}&order=run_at.asc&limit={POSTS_LIMIT}")


def _campaigns(bid: str) -> Tuple[Optional[List[Dict[str, Any]]], Dict[str, Dict[int, int]]]:
    rows = sb_clients.sb_get_as_service(
        f"/campaigns?business_id=eq.{bid}&status=in.({','.join(ON_CALENDAR)})&start_at=not.is.null"
        f"&select=id,name,status,start_at,touches&order=start_at.desc&limit={CAMPAIGNS_LIMIT}")
    if not isinstance(rows, list):
        return None, {}
    sent: Dict[str, Dict[int, int]] = {}
    ids = ",".join(str(UUID(str(r["id"]))) for r in rows)
    if ids:
        sends = sb_clients.sb_get_as_service(
            f"/campaign_sends?campaign_id=in.({ids})&select=campaign_id,touch_idx&limit={SENDS_LIMIT}")
        if not isinstance(sends, list):
            return None, {}
        for s in sends:
            by = sent.setdefault(str(s.get("campaign_id")), {})
            by[int(s.get("touch_idx") or 0)] = by.get(int(s.get("touch_idx") or 0), 0) + 1
    return rows, sent


async def month(business_id: Any, month_key: str, *, tz, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Everything that goes out in this month, on the business's clock."""
    bid = str(UUID(str(business_id)))
    now = now or datetime.now(timezone.utc)
    first, start, end = month_bounds(month_key, tz)
    sources = {"posts": "loaded", "campaigns": "loaded"}
    items: List[Dict[str, Any]] = []
    posts_read, campaigns_read = await asyncio.gather(
        _posts(bid, start, end), asyncio.to_thread(_campaigns, bid), return_exceptions=True)
    if isinstance(posts_read, BaseException):
        if not isinstance(posts_read, store.StoreError):
            raise posts_read
        sources["posts"] = "unavailable"
    else:
        if len(posts_read) >= POSTS_LIMIT:
            sources["posts"] = "partial"
        items += [{"kind": "post", "at": p.get("run_at"), "post": public_post(p)} for p in posts_read]
    if isinstance(campaigns_read, BaseException) or campaigns_read[0] is None:
        sources["campaigns"] = "unavailable"
    else:
        rows, sent = campaigns_read
        if len(rows) >= CAMPAIGNS_LIMIT:
            sources["campaigns"] = "partial"
        for c in rows:
            items += touch_items(c, sent.get(str(c["id"]), {}), start, end, now)
    never = datetime.min.replace(tzinfo=timezone.utc)
    items.sort(key=lambda i: (_when(i["at"]) or never, i["kind"]))
    return {"month": first.strftime("%Y-%m"), "time_zone": getattr(tz, "key", str(tz)),
            "items": items, "sources": sources}
