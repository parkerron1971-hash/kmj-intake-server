"""platform_suite.py — Solutionist's own marketing desk on the suite (B15).

Step 5 of docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md. Mission Control's
Marketing desk stops being a separate single-tenant system (Buffer, the
platform_marketing_* tables, marketing_engine's Thursday job) and becomes the
desk for Solutionist's own business on the suite every business uses: one
posting path (Post for Me, through the business's own connected accounts),
one store (marketing_*), one planner.

Two switches, both server-side only:

  MC_MARKETING_SUITE   off (default) | on. Off: today's platform desk, exactly
                       as before. On: Mission Control's desk runs on the suite
                       (/platform/marketing/suite/*, platform_marketing_suite),
                       nothing new goes to Buffer, and posts approved there
                       before the switch are left to go out (the drain).
  PLATFORM_BUSINESS_ID the businesses.id of Solutionist's own business (the
                       row platform_console sets up with settings.platform_books
                       true under the platform owner's account). Unset, the
                       suite path refuses in plain words: nothing guesses which
                       business is the platform's.

WHY AN ID AND NOT THE FLAG. settings.platform_books is how Mission Control
finds the row today, with the signed-in owner's id in the same filter
(platform_console._find_platform_business). The worker has no signed-in
owner, and settings is the owner's own JSON, so the flag alone is not an
identity a server-side grant can rest on. The id is configuration nobody
outside the server can set; Mission Control's routes check both (the id names
a row whose platform_books is true and whose owner is the signed-in platform
owner), and nothing a request sends ever names the business.

WHAT "THE PLATFORM BUSINESS" GETS (only while the switch is on, only that id):
  * its level is autopilot (the week, its clips, standing OKs) whatever its
    billing row says (effective_row: comp_tier practice, in memory only);
  * its profile is Solutionist's own (marketing_profile.platform_profile): the
    platform's audience, caption instructions, clock (America/New_York),
    mysolutionist.app as its site, no hashtags, no address in a caption;
  * its numbers are the platform's (marketing_signals.platform_signals:
    growth_summary, founder_offer, the news page, site_events with no
    business) plus the suite's own posts;
  * its plays are the platform's library (business_marketing_engine's
    platform half), and its links are mysolutionist.app/go/<code>;
  * the suite's fan-out includes it whatever MARKETING_DESK says.

ONE LOOP A WEEK. While the switch is off the platform business is never in
the suite's fan-out (desk_on_for answers False for it once the id is set),
and marketing_engine's Thursday job plans the week. While it is on, the old
job does nothing and the suite plans. Across the switch: the suite does not
plan a week whose Buffer plan already has a post approved or out
(buffer_week_live), and the old job does not plan a week whose suite plan
does (suite_week_live). A read that fails plans nothing that hour.
"""
from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any, Dict, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

FLAG = 'MC_MARKETING_SUITE'
ID_ENV = 'PLATFORM_BUSINESS_ID'
TZ = ZoneInfo('America/New_York')          # marketing_engine.TZ: the platform desk's clock
LEVEL_PLAN = 'practice'                    # the plan whose features are the autopilot level

# What the old desk refuses while the switch is on (409), and what Platform
# Chief says instead of making a Buffer post.
BUFFER_CLOSED = ("Solutionist's marketing runs on the marketing suite now, so nothing new goes to Buffer. "
                 'Make, approve and post it on the suite desk. Posts already approved here still go out.')
NOT_ON = ("Solutionist's own desk isn't on the marketing suite yet (MC_MARKETING_SUITE is off). "
          'The Buffer desk is still the one in use.')
NO_ID = ("The server doesn't know which business is Solutionist's own yet (PLATFORM_BUSINESS_ID is not set), "
         'so the suite desk is not opened. Nothing was changed.')
WRONG_ID = ("PLATFORM_BUSINESS_ID doesn't name Solutionist's own business under your account, so the suite desk "
            'is not opened. Nothing was changed.')
BUFFER_WEEK = ("That week was planned on the Buffer desk before the switch, and some of its posts are already "
               "approved or out, so Chief won't plan it again here. Make single posts on this desk, or plan "
               'next week from Thursday.')
BUFFER_WEEK_UNREAD = ("The Buffer desk's plan for that week couldn't be read just now, so Chief didn't plan it "
                      'here. It tries again later.')

LIVE_BUFFER = ('approved', 'dispatching', 'submitted', 'published', 'uncertain')
LIVE_SUITE = ('approved', 'dispatching', 'submitted', 'published', 'partly_published', 'uncertain')


# ── the switches ──────────────────────────────────────────────────────

def suite_on() -> bool:
    return (os.environ.get(FLAG) or 'off').strip().lower() == 'on'


def platform_id() -> Optional[str]:
    """PLATFORM_BUSINESS_ID as a canonical uuid, or None (unset or not a uuid)."""
    raw = (os.environ.get(ID_ENV) or '').strip()
    if not raw:
        return None
    try:
        return str(UUID(raw))
    except ValueError:
        log.warning('platform suite: %s is not a business id; the suite desk stays closed.', ID_ENV)
        return None


def _same(business_id: Any, pid: Optional[str]) -> bool:
    if not pid or business_id is None:
        return False
    try:
        return str(UUID(str(business_id))) == pid
    except ValueError:
        return False


def is_platform(business_id: Any) -> bool:
    """This is Solutionist's own business AND its desk is on the suite. Every
    platform-only behaviour (level, profile, signals, plays, site, clock) asks
    this; with the switch off it is False for every business."""
    return suite_on() and _same(business_id, platform_id())


def desk_switch(business_id: Any) -> Optional[bool]:
    """MARKETING_DESK's answer for the platform business, or None for any
    other business (and for every business while PLATFORM_BUSINESS_ID is
    unset). On the suite it is always switched on; off the suite it is never
    switched on, so the two loops never both plan its week."""
    if not _same(business_id, platform_id()):
        return None
    return suite_on()


def with_platform(scope: Any) -> Any:
    """MARKETING_DESK's scope (None, '*' or a frozenset of ids) with the
    platform business in it while the suite is on, and out of it while off.
    Unchanged when PLATFORM_BUSINESS_ID is unset."""
    pid = platform_id()
    if not pid:
        return scope
    if suite_on():
        if scope is None:
            return frozenset({pid})
        return scope if scope == '*' else frozenset(scope) | {pid}
    if scope is None or scope == '*':
        return scope                       # '*': desk_on_for answers False for it
    return (frozenset(scope) - {pid}) or None


def effective_row(row: Any) -> Any:
    """The platform business's row as the plan gates read it: comp_tier
    practice (the autopilot level) whatever its billing says, in memory only.
    Any other row (and every row while the switch is off) comes back as it
    is. Never written anywhere; never from a request."""
    if isinstance(row, dict) and is_platform(row.get('id')):
        return {**row, 'comp_tier': LEVEL_PLAN}
    return row


def zone_for(business_id: Any) -> Optional[ZoneInfo]:
    """The platform desk's clock for the platform business on the suite, else None."""
    return TZ if is_platform(business_id) else None


def close_buffer() -> None:
    """Refuse a write that would put a new post on Buffer's way while the
    suite is on (409). A no-op while it is off."""
    if suite_on():
        from fastapi import HTTPException
        raise HTTPException(409, BUFFER_CLOSED)


# ── one loop a week ───────────────────────────────────────────────────

async def buffer_week_live(week_of: date) -> Optional[bool]:
    """Whether the Buffer desk's own weekly plan for this week (its run id is
    marketing_engine.run_id_for(week)) has a post approved or out. None when
    that cannot be read: the suite then plans nothing for the hour."""
    import marketing_engine
    import platform_marketing as marketing
    from fastapi import HTTPException
    rid = marketing_engine.run_id_for(week_of)
    try:
        rows = await marketing.db('GET', f"/platform_marketing_posts?run_id=eq.{rid}"
                                         f"&status=in.({','.join(LIVE_BUFFER)})&select=id&limit=1")
    except HTTPException:
        return None
    except Exception:
        log.warning('platform suite: the Buffer week could not be read', exc_info=True)
        return None
    return bool(rows)


async def suite_week_live(week_of: date) -> Optional[bool]:
    """Whether the suite's plan for the platform business this week has a
    post approved or out. False at once (no read) while PLATFORM_BUSINESS_ID
    is unset; None when it cannot be read (the old job then waits an hour)."""
    pid = platform_id()
    if not pid:
        return False
    import business_marketing_store as store
    rid = store.run_id_for(pid, week_of)
    try:
        rows = await store.rows(f"/marketing_posts?business_id=eq.{pid}&run_id=eq.{rid}"
                                f"&status=in.({','.join(LIVE_SUITE)})&select=id&limit=1")
    except store.StoreError:
        return None
    return bool(rows)


# ── its site: mysolutionist.app ───────────────────────────────────────

def platform_site(business_id: Any) -> Optional[Dict[str, Any]]:
    """The platform business's "site" for its links: mysolutionist.app itself
    (business_marketing_links reads `platform`: hosts mysolutionist.app and
    www, origin https://mysolutionist.app). None for any other business.
    Keyed on PLATFORM_BUSINESS_ID alone, so a link already out still resolves
    if the switch is turned back off."""
    pid = platform_id()
    if not _same(business_id, pid):
        return None
    from business_sites_helpers import PUBLIC_DOMAIN
    return {'business_id': pid, 'slug': '', 'domain': PUBLIC_DOMAIN, 'published': True, 'platform': True}
