"""platform_marketing_suite.py — Mission Control's Marketing desk on the suite (B15).

Solutionist's own business gets the same desk every business has
(business_marketing, business_marketing_planner), reached from Mission
Control. The paths and the answers are the business desk's own, under
/platform/marketing/suite instead of /marketing/{business_id}, so Mission
Control can mount the shared desk (BusinessMarketingDesk) with one request
prop (F7):

  GET  /platform/marketing/suite/status                  is the suite desk open, and for which business
  GET  /platform/marketing/suite/engine                  the desk (= GET /marketing/{id}/engine)
  GET  /platform/marketing/suite/ideas/next-slot         the next open time
  POST /platform/marketing/suite/ideas                   a new post (a draft, or post now)
  POST /platform/marketing/suite/approve                 approve exact reviewed versions
  POST /platform/marketing/suite/slot/edit               change a post; it goes back to draft
  POST /platform/marketing/suite/slot/cancel             skip a post
  POST /platform/marketing/suite/post-now                a reviewed post goes out in two minutes
  POST /platform/marketing/suite/posts/{id}/not-sent     an unconfirmed delivery did not go out
  PUT  /platform/marketing/suite/settings                the desk's settings
  GET  /platform/marketing/suite/results                 what came through the post links
  POST /platform/marketing/suite/engine/run              queue Chief's week (the worker writes it)
  GET  /platform/marketing/suite/preview                 what Chief would write about, read-only
  GET  /platform/marketing/drain                         the Buffer posts still to go out

WHO. Every route is the platform owner's alone (lead_admin.require_owner:
the verified JWT's email is PLATFORM_OWNER_EMAIL). The business is never
named by the request: it is PLATFORM_BUSINESS_ID, and it must be a row with
settings.platform_books true whose owner_id is the signed-in platform owner.
The business desk's own owner check then runs as well (each route below calls
the business route itself). A tenant owner, or anyone else, is refused by
require_owner before anything is read.

THE SWITCH. MC_MARKETING_SUITE=on opens these routes; off (the default)
they refuse in plain words (409) and Mission Control's Buffer desk is
exactly as it was. PLATFORM_BUSINESS_ID unset: refused in plain words.
/drain answers either way (it only reads).
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

import business_marketing as bm
import business_marketing_planner as planner
import business_marketing_store as store
import platform_suite
import sb_clients
from lead_admin import require_owner

router = APIRouter(prefix='/platform/marketing', tags=['platform-marketing-suite'],
                   dependencies=[Depends(require_owner)])

READ_DOWN = "Solutionist's own business couldn't be read just now. Nothing was changed. Try again in a minute."


def _platform_row(owner_id: str) -> Dict[str, Any]:
    """Solutionist's own business row (service role), checked: the switch is
    on, PLATFORM_BUSINESS_ID is set and names a platform_books row owned by
    the signed-in platform owner. Refuses in plain words otherwise."""
    if not platform_suite.suite_on():
        raise HTTPException(409, platform_suite.NOT_ON)
    pid = platform_suite.platform_id()
    if not pid:
        raise HTTPException(409, platform_suite.NO_ID)
    rows = sb_clients.sb_get_as_service(f'/businesses?id=eq.{pid}&select=*&limit=1')
    if rows is None:
        raise HTTPException(503, READ_DOWN)
    row = rows[0] if rows else None
    settings = (row or {}).get('settings') if isinstance((row or {}).get('settings'), dict) else {}
    if (not row or str(row.get('id')) != pid or str(row.get('owner_id')) != str(owner_id)
            or settings.get('platform_books') not in (True, 'true')):
        raise HTTPException(409, platform_suite.WRONG_ID)
    return row


async def platform_business(owner) -> Dict[str, Any]:
    row = await asyncio.to_thread(_platform_row, str(owner.id))
    import billing_context
    billing_context.set_current(str(row['id']))       # whose bill any spend on this request lands on
    return row


def _id(row: Dict[str, Any]) -> UUID:
    return UUID(str(row['id']))


# ── is it open ────────────────────────────────────────────────────────

@router.get('/suite/status')
async def suite_status(owner=Depends(require_owner)):
    """Whether Mission Control's desk runs on the suite, and if not why not,
    in plain words. Mission Control (F7) reads this to choose its desk."""
    try:
        row = await platform_business(owner)
    except HTTPException as exc:
        return {'on': platform_suite.suite_on(), 'ready': False, 'business_id': None, 'reason': exc.detail}
    return {'on': True, 'ready': True, 'business_id': str(row['id']), 'reason': None}


# ── the desk (the business desk's own routes, for this one business) ──

@router.get('/suite/engine')
async def suite_engine(owner=Depends(require_owner)):
    row = await platform_business(owner)
    biz = {**platform_suite.effective_row(row), '_caller_role': 'owner'}
    return await bm.engine(_id(row), biz)


@router.get('/suite/ideas/next-slot')
async def suite_next_slot(owner=Depends(require_owner)):
    row = await platform_business(owner)
    return await bm.next_slot_route(_id(row), owner)


@router.post('/suite/ideas')
async def suite_create_idea(req: bm.Idea, owner=Depends(require_owner)):
    row = await platform_business(owner)
    return await bm.create_idea_route(_id(row), req, owner)


@router.post('/suite/approve')
async def suite_approve(req: bm.Review, owner=Depends(require_owner)):
    row = await platform_business(owner)
    return await bm.approve_route(_id(row), req, owner)


@router.post('/suite/slot/edit')
async def suite_edit_slot(req: bm.SlotEdit, owner=Depends(require_owner)):
    row = await platform_business(owner)
    return await bm.edit_slot_route(_id(row), req, owner)


@router.post('/suite/slot/cancel')
async def suite_cancel_slot(req: bm.SlotCancel, owner=Depends(require_owner)):
    row = await platform_business(owner)
    return await bm.cancel_slot_route(_id(row), req, owner)


@router.post('/suite/post-now')
async def suite_post_now(req: bm.PostNow, owner=Depends(require_owner)):
    row = await platform_business(owner)
    return await bm.post_now_route(_id(row), req, owner)


@router.post('/suite/posts/{post_id}/not-sent')
async def suite_not_sent(post_id: UUID, req: bm.Revision, owner=Depends(require_owner)):
    row = await platform_business(owner)
    return await bm.mark_not_sent(_id(row), post_id, req, owner)


@router.put('/suite/settings')
async def suite_settings(req: bm.Settings, owner=Depends(require_owner)):
    row = await platform_business(owner)
    return await bm.save_settings(_id(row), req, owner)


@router.get('/suite/results')
async def suite_results(owner=Depends(require_owner)):
    import business_marketing_outcomes as outcomes
    row = await platform_business(owner)
    try:
        return await outcomes.for_business(str(row['id']), now=bm.now())
    except store.StoreError:
        raise HTTPException(503, bm.READ_DOWN) from None


@router.post('/suite/engine/run', status_code=202)
async def suite_run(owner=Depends(require_owner)):
    """Queue Chief's week for Solutionist's own business. A week the Buffer
    desk planned, with a post of it approved or out, is not planned again
    (one loop a week); the worker checks the same before it writes."""
    row = await platform_business(owner)
    at = planner._now()
    held = await platform_suite.buffer_week_live(planner.target_week(at, platform_suite.TZ))
    if held is None:
        raise HTTPException(503, platform_suite.BUFFER_WEEK_UNREAD)
    if held:
        raise HTTPException(409, platform_suite.BUFFER_WEEK)
    return await planner.run_route(_id(row), owner)


@router.get('/suite/preview')
async def suite_preview(owner=Depends(require_owner)):
    row = await platform_business(owner)
    return await planner.preview_route(_id(row), owner)


# ── the Buffer drain ──────────────────────────────────────────────────

DRAIN_LIMIT = 2000


@router.get('/drain')
async def drain(owner=Depends(require_owner)):
    """How many of the Buffer desk's posts are still on their way, so Kevin
    knows when BUFFER_PUBLISHING can go off. Reads the platform tables only:
    no Buffer call, and nothing in Buffer is ever cancelled.

      queued       approved, its delivery window still open: the minute job
                   hands it to Buffer at its time (needs BUFFER_PUBLISHING=on)
      sending      claimed and being handed over right now
      in_buffer    handed to Buffer, waiting for Buffer to say it went out
                   (checked every 10 minutes while BUFFER_API_KEY is set;
                   BUFFER_PUBLISHING does not stop that check)
      unconfirmed  may or may not have gone out: check Buffer, then mark it
      missed       approved, but its window closed: it will not go out
      drafts       never approved; nothing approves them while the suite is on

    Safe to switch BUFFER_PUBLISHING off once queued and sending are both 0."""
    import platform_marketing as marketing
    now = marketing.now()
    rows = await marketing.db('GET', '/platform_marketing_posts?status=in.(approved,dispatching,submitted,uncertain,draft)'
                                     f'&select=id,status,run_at,expires_at&order=run_at.asc&limit={DRAIN_LIMIT + 1}')
    truncated = len(rows) > DRAIN_LIMIT
    try:
        paused = bool((await marketing.config()).get('paused'))
    except HTTPException:
        paused = None

    def when(value):
        return marketing.aware(value) if value else None

    queued = [r for r in rows if r.get('status') == 'approved' and (when(r.get('expires_at')) or now) > now]
    count = {
        'queued': len(queued),
        'sending': sum(1 for r in rows if r.get('status') == 'dispatching'),
        'in_buffer': sum(1 for r in rows if r.get('status') == 'submitted'),
        'unconfirmed': sum(1 for r in rows if r.get('status') == 'uncertain'),
        'missed': sum(1 for r in rows if r.get('status') == 'approved' and r not in queued),
        'drafts': sum(1 for r in rows if r.get('status') == 'draft'),
    }
    publishing = os.environ.get('BUFFER_PUBLISHING', 'off').lower() == 'on'
    safe = not truncated and count['queued'] == 0 and count['sending'] == 0
    last = max((when(r['run_at']) for r in queued), default=None)
    if truncated:
        message = 'More posts are waiting than one read counts. Check again before switching anything off.'
    elif safe:
        message = ('Nothing is left to hand to Buffer. It is safe to set BUFFER_PUBLISHING=off.'
                   + (f" {count['in_buffer']} already in Buffer are still being checked." if count['in_buffer'] else ''))
    elif not publishing:
        message = (f"{count['queued']} approved posts are waiting, but BUFFER_PUBLISHING is off, so they will not go "
                   'out. Switch it back on to let them drain, or cancel them on the Buffer desk.')
    elif paused:
        message = (f"{count['queued']} approved posts are held because publishing is paused on the Buffer desk. "
                   'Resume it to let them go out, or cancel them there.')
    else:
        message = (f"{count['queued'] + count['sending']} posts are still on their way to Buffer; the last goes out "
                   f"{last.isoformat() if last else 'soon'}. Keep BUFFER_PUBLISHING on until this reaches 0.")
    return {'suite_on': platform_suite.suite_on(), 'buffer_publishing': publishing, 'paused': paused,
            **count, 'last_goes_out': last.isoformat() if last else None, 'truncated': truncated,
            'safe_to_switch_off': safe, 'message': message, 'checked_at': now.isoformat()}
