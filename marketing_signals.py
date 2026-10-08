"""marketing_signals.py — one business's numbers, read for its marketing.

B7 of docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md (D2). Solutionist's own
desk reads platform-wide numbers (marketing_engine.read_signals); a
business's weekly plan reads its own, here. Everything is a service-role
read filtered to this one business, bounded by a date window AND a row
limit, so a Thursday fan-out over every business stays cheap.

WHAT IS READ
  traffic        site_events, last 35 days (site_analytics.business_rows):
                 visits = distinct sessions in the last 7 days, and the
                 weekly average of the 28 days before
  leads          contacts created in the same 35 days (the same call)
  bookings       module_entries with an appointment, status active, from
                 28 days back to 7 days ahead: the next 7 days against the
                 trailing 4-week average
  capacity       open times in the next 7 days on a chair business's live
                 calendar (agent_site.slots_for), for its shortest bookable
                 offering; None for every other business
  new_offerings  active offerings created in the last 21 days
  news           settings.website_content.news (site_news.normalize_posts);
                 fresh = published in the last 21 days
  posts          marketing_posts and social_publications, the last 90 days
                 and the week ahead: when the last post went out, how many
                 went out lately, how many are approved for the week ahead
  used_subjects  what the last 8 weeks' plans were about (marketing_runs)

NONE, NEVER ZERO. A read that fails, or comes back at its row limit (a
count that might be cut off), is None, and its name is listed in `unread`.
Zero means it was counted and there were none. The diagnosis
(business_marketing_engine.diagnose) skips any rule whose signal is None,
so a database blip never reads as an empty calendar.

Read-only, no model call. Read by the weekly suggestion and the preview
(business_marketing_planner, B8).

SOLUTIONIST'S OWN (B15). For the platform business on the suite
(platform_suite.is_platform) read_signals answers platform_signals instead:
the platform desk's own numbers (marketing_engine.read_signals:
growth_summary, founder_offer, the news page, site_events with no business,
the Buffer desk's posts and plans) with the suite's own posts and plans
added in, so a week posted on either desk counts. Marked profile 'platform'.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

import business_marketing_store as store
import marketing_profile
import sb_clients
from business_marketing_desk import query_time

log = logging.getLogger(__name__)

WEEK = timedelta(days=7)
BEFORE_WEEKS = 4                       # the trailing average: the 4 weeks before this one
WINDOW = WEEK * (1 + BEFORE_WEEKS)     # 35 days
NEW_DAYS = 21                          # an offering or news post is new for three weeks
POSTS_BACK_DAYS = 90
USED_DAYS = 56

VISIT_ROWS = 5000                      # site_events rows (the traffic report reads up to 50,000)
LEAD_ROWS = 500
BOOKING_ROWS = 1000
NEW_OFFERING_ROWS = 20
POST_ROWS = 200
RUN_ROWS = 12
NEWS_KEPT = 10


class Unread(Exception):
    """A read that did not happen, or came back too big to count."""


def _when(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _get(path: str) -> List[Dict[str, Any]]:
    """A service-role GET that must come back as a list (sb_clients answers None when it fails)."""
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise Unread(path.split('?')[0])
    return rows


def _average(n: int) -> float:
    return round(n / BEFORE_WEEKS, 1)


# ── pure: rows to numbers ─────────────────────────────────────────────

def traffic_from(rows: List[Dict[str, Any]], now: datetime, limit: int = VISIT_ROWS) -> Optional[Dict[str, Any]]:
    """Visits as distinct sessions (one person reading four pages is one
    visit): the last 7 days, and the weekly average of the 28 days before.

    The rows come newest first. Cut off at the limit inside the last 7 days,
    the week was not all counted: None. Cut off earlier, the week stands and
    only the average before it is None. counted_any says the site's counter
    recorded something in the 35 days, so a 0 is a real 0 and not a site
    without the counter."""
    week_start, window_start = now - WEEK, now - WINDOW
    recent, before = set(), set()
    oldest = None
    for row in rows:
        ts = _when(row.get('ts'))
        if ts is None:
            continue
        oldest = ts if oldest is None or ts < oldest else oldest
        sid = row.get('session_id')
        if not sid:
            continue
        if ts >= week_start:
            recent.add(sid)
        elif ts >= window_start:
            before.add(sid)
    truncated = len(rows) >= limit
    if truncated and (oldest is None or oldest >= week_start):
        return None
    return {'visits': len(recent), 'weekly_visits_before': None if truncated else _average(len(before)),
            'counted_any': bool(rows), 'truncated': truncated}


def leads_from(rows: Optional[List[Dict[str, Any]]], now: datetime, limit: int = LEAD_ROWS) -> Optional[Dict[str, Any]]:
    """New contacts, from every door: the last 7 days and the weekly average
    before. The read is unordered, so one cut off at its limit cannot be
    split by week: None."""
    if rows is None or len(rows) >= limit:
        return None
    week_start = now - WEEK
    stamps = [d for d in (_when(r.get('created_at')) for r in rows) if d]
    return {'last_7_days': sum(1 for d in stamps if d >= week_start),
            'weekly_before': _average(sum(1 for d in stamps if now - WINDOW <= d < week_start))}


def bookings_from(rows: Optional[List[Dict[str, Any]]], now: datetime, limit: int = BOOKING_ROWS) -> Optional[Dict[str, Any]]:
    """Appointments booked SO FAR for the next 7 days, against what was
    already booked at the same point in each of the 4 weeks before (7 days
    ahead of that week). A week ahead is still filling in, so setting it
    against past weeks' final totals made every normal week look slow
    (review of #1314). A past booking without its booking time cannot be
    placed, so the whole reading is unknown: None."""
    if rows is None or len(rows) >= limit:
        return None
    ahead = 0
    before = 0
    for row in rows:
        at = _when(row.get('appointment_at'))
        if at is None:
            continue
        if now <= at < now + WEEK:
            ahead += 1
            continue
        for k in range(1, BEFORE_WEEKS + 1):
            moment = now - WEEK * k
            if moment <= at < moment + WEEK:
                made = _when(row.get('created_at'))
                if made is None:
                    return None
                if made <= moment:
                    before += 1
                break
    return {'next_7_days': ahead, 'weekly_before': _average(before)}


def chair_offering(offerings: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The offering open chairs are counted for: the shortest bookable one
    (ties by name). B11's open-chairs week counts the most-booked offering
    over 60 days instead (business_marketing_openings.choose_offering, from
    module_entries.data->>offering_id) and falls back to this."""
    import agent_site
    bookable = [o for o in offerings or [] if agent_site.public_offering(o)['bookable']]
    if not bookable:
        return None
    return min(bookable, key=lambda o: (int(o.get('duration_min') or 0), str(o.get('name') or '').lower()))


def capacity_from(slots: List[Dict[str, Any]], offering: Dict[str, Any], now: datetime,
                  start, end) -> Dict[str, Any]:
    """Open times still ahead in the window. open_slots is a count of start
    times for one offering; until compute_slots' concurrent_capacity is
    verified it is never put in a caption (D5)."""
    ahead = [s for s in slots or [] if (_when(s.get('start_utc')) or now) > now]
    days = sorted({str(s.get('start_local'))[:10] for s in ahead if s.get('start_local')})
    return {'offering_id': str(offering.get('id') or '') or None, 'offering': str(offering.get('name') or '').strip(),
            'duration_min': offering.get('duration_min'), 'open_slots': len(ahead), 'open_days': len(days),
            'days': days, 'from': start.isoformat(), 'to': end.isoformat()}


def posts_from(desk_rows: List[Dict[str, Any]], social_rows: List[Dict[str, Any]],
               now: datetime) -> Optional[Dict[str, Any]]:
    """When the business last posted through its marketing desk or its connected accounts, and what is approved
    ahead. A desk post that went out through Post for Me also has a
    social_publications row; it is counted once."""
    if len(desk_rows) >= POST_ROWS or len(social_rows) >= POST_ROWS:
        return None
    linked = {str(r['publication_id']) for r in desk_rows if r.get('publication_id')}
    sent, ahead = [], 0
    for row in desk_rows:
        at = _when(row.get('run_at'))
        if at is None:
            continue
        if row.get('status') in ('submitted', 'published', 'partly_published') and at <= now:
            sent.append(at)
        elif row.get('status') == 'approved' and now < at <= now + WEEK:
            ahead += 1
    for row in social_rows:
        if str(row.get('id')) in linked:
            continue
        at = _when(row.get('scheduled_at')) or _when(row.get('created_at'))
        if at is None:
            continue
        if row.get('status') in ('posted', 'partly_posted') and at <= now:
            sent.append(at)
        elif row.get('status') == 'scheduled' and now < at <= now + WEEK:
            ahead += 1
    return {'last_published': max(sent).isoformat() if sent else None,
            'published_last_7_days': sum(1 for s in sent if s >= now - WEEK),
            'published_last_14_days': sum(1 for s in sent if s >= now - 2 * WEEK),
            'approved_next_7_days': ahead, 'looked_back_days': POSTS_BACK_DAYS}


def news_from(settings: Any) -> List[Dict[str, Any]]:
    """The site's news posts, newest first, with times written out."""
    import site_news
    settings = settings if isinstance(settings, dict) else {}
    content = settings.get('website_content') if isinstance(settings.get('website_content'), dict) else {}
    out = []
    for post in site_news.normalize_posts(content.get('news'))[:NEWS_KEPT]:
        when = post.get('published_at')
        out.append({**post, 'published_at': when.isoformat() if isinstance(when, datetime) else None})
    return out


def used_from(runs: List[Dict[str, Any]]) -> List[str]:
    used = set()
    for run in runs or []:
        for slot in run.get('slots') or []:
            if isinstance(slot, dict) and slot.get('subject_key'):
                used.add(str(slot['subject_key']))
    return sorted(used)


def offering_key(name: Any) -> str:
    """What a plan was about, for an offering (business_marketing_engine uses the same key)."""
    return f"offering:{' '.join(str(name or '').split()).lower()}"


def news_key(post: Dict[str, Any]) -> str:
    return f"news:{post.get('id') or post.get('slug')}"


def fresh(items: Optional[List[Dict[str, Any]]], field: str, now: datetime) -> Optional[List[Dict[str, Any]]]:
    """The items dated in the last 21 days (an undated one is not new)."""
    if items is None:
        return None
    since = now - timedelta(days=NEW_DAYS)
    out = []
    for item in items:
        at = _when(item.get(field))
        if at is not None and since <= at <= now:
            out.append(item)
    return out


def unmarketed(items: Optional[List[Dict[str, Any]]], used: Optional[List[str]], key) -> Optional[List[Dict[str, Any]]]:
    """The new things no plan has been about yet; None when either list is unknown."""
    if items is None or used is None:
        return None
    done = set(used)
    return [i for i in items if key(i) not in done]


# ── reads ─────────────────────────────────────────────────────────────

async def _traffic(business_id: str, now: datetime):
    import site_analytics
    rows, leads = await site_analytics.business_rows(business_id, query_time(now - WINDOW),
                                                     limit=VISIT_ROWS, lead_limit=LEAD_ROWS)
    return traffic_from(rows, now, VISIT_ROWS), leads_from(leads, now, LEAD_ROWS)


def _bookings(business_id: str, now: datetime) -> Optional[Dict[str, Any]]:
    """The shared bookings read (availability_engine.BOOKING_SELECT,
    booking_window_filter, booked_start): a booking is found by the
    appointment_at column OR data->>appointment_at and starts at the time in
    data, else the column (the column alone was empty on every production
    row until supabase/APPLY-2026-10-08-booking-columns.sql). created_at
    rides along for the like-for-like count. Whole days are read, 4 weeks
    back to a week ahead; bookings_from keeps only its own windows, and
    every row read still counts toward the row limit."""
    from availability_engine import BOOKING_SELECT, booked_start, booking_window_filter
    lo = (now - WEEK * BEFORE_WEEKS).astimezone(timezone.utc).date()
    hi = (now + WEEK).astimezone(timezone.utc).date() + timedelta(days=1)
    rows = _get(f'/module_entries?business_id=eq.{business_id}&status=eq.active'
                f'&{booking_window_filter(lo, hi)}'
                f'&select={BOOKING_SELECT},created_at&order=appointment_at.asc&limit={BOOKING_ROWS}')
    rows = [{'appointment_at': booked_start(r),
             'created_at': r.get('created_at') if isinstance(r, dict) else None} for r in rows]
    out = bookings_from(rows, now, BOOKING_ROWS)
    if out is None:
        raise Unread('module_entries: more bookings than one read counts')
    return out


def _capacity(business: Dict[str, Any], now: datetime, tz: Optional[ZoneInfo]) -> Optional[Dict[str, Any]]:
    """Open chairs for the next 7 days, or None where there is nothing to
    count: not a chair business with a live calendar, no weekly hours set
    (the engine would call that open around the clock), or nothing bookable.
    A read that fails raises."""
    import agent_site
    import business_marketing
    from availability import BusinessAvailability, is_open_default
    from fastapi import HTTPException
    try:
        if not business_marketing.has_chair_calendar(business):
            return None
    except HTTPException:
        raise Unread('custom_modules') from None
    bundle = agent_site.bundle_for(str(business['id']))
    if not bundle:
        raise Unread('booking facts')
    if is_open_default(BusinessAvailability.from_settings_dict(bundle['facts'].get('availability'))):
        return None
    offering = chair_offering(bundle.get('offerings') or [])
    if offering is None:
        return None
    zone = tz or marketing_profile.time_zone(business)
    start = now.astimezone(zone).date()
    end = start + timedelta(days=6)
    try:
        slots = agent_site.slots_for(bundle, offering, start, end)
    except HTTPException:
        raise Unread('availability') from None
    return capacity_from(slots, offering, now, start, end)


def _new_offerings(business_id: str, now: datetime) -> List[Dict[str, Any]]:
    """Active offerings added in the last 21 days, in their public shape (a hidden price is absent)."""
    import agent_site
    rows = _get(f'/offerings?business_id=eq.{business_id}&is_active=eq.true'
                f'&created_at=gte.{query_time(now - timedelta(days=NEW_DAYS))}'
                '&select=id,name,slug,description,category,current_price,currency,duration_min,'
                f'show_price_to_customer,created_at&order=created_at.desc&limit={NEW_OFFERING_ROWS}')
    out = []
    for row in rows:
        public = agent_site.public_offering(row)
        if public['name']:
            public['description'] = (public.get('description') or '')[:300] or None
            out.append({**public, 'created_at': row.get('created_at')})
    return out


async def _posts(business_id: str, now: datetime) -> Optional[Dict[str, Any]]:
    since, until = query_time(now - timedelta(days=POSTS_BACK_DAYS)), query_time(now + WEEK)
    desk = await store.rows(
        f'/marketing_posts?business_id=eq.{business_id}'
        '&status=in.(approved,submitted,published,partly_published)'
        f'&run_at=gte.{since}&run_at=lt.{until}&select=id,status,run_at,publication_id'
        f'&order=run_at.desc&limit={POST_ROWS}')
    social = await asyncio.to_thread(
        _get, f'/social_publications?business_id=eq.{business_id}&status=in.(scheduled,posted,partly_posted)'
              f'&created_at=gte.{since}&select=id,status,scheduled_at,created_at'
              f'&order=created_at.desc&limit={POST_ROWS}')
    out = posts_from(desk, social, now)
    if out is None:
        raise Unread('posts: more than one read counts')
    return out


async def _used(business_id: str, now: datetime) -> List[str]:
    runs = await store.rows(
        f'/marketing_runs?business_id=eq.{business_id}'
        f'&created_at=gte.{query_time(now - timedelta(days=USED_DAYS))}'
        f'&select=slots,created_at&order=created_at.desc&limit={RUN_ROWS}')
    return used_from(runs)


async def read_signals(business_id: Any, *, now: Optional[datetime] = None,
                       business: Optional[Dict[str, Any]] = None,
                       tz: Optional[ZoneInfo] = None) -> Dict[str, Any]:
    """Everything one business's diagnosis may look at, each read or None.

    business: the row (marketing_profile.read_business), when the caller
    already has it. tz: the business's clock (the profile's), for the
    capacity window's days."""
    now = now or datetime.now(timezone.utc)
    bid = str(UUID(str(business_id)))
    import platform_suite
    if await platform_suite.is_platform_async(bid):
        return await platform_signals(bid, now=now)
    unread: List[str] = []

    async def safe(name, fetch):
        try:
            return await fetch()
        except Exception:
            log.warning('marketing signals: %s could not be read for %s', name, bid[:8], exc_info=True)
            unread.append(name)
            return None

    row = business
    if row is None:
        row = await safe('business', lambda: asyncio.to_thread(marketing_profile.read_business, bid))
    elif str(row.get('id')) != bid:
        raise ValueError('That business row is not this business.')
    if tz is None and row is not None:
        # The business's own clock when the caller did not pass it, so dates
        # in the diagnosis never fall back to UTC (review of #1314).
        try:
            tz = marketing_profile.time_zone(row)
        except Exception:
            tz = None

    async def capacity():
        if row is None:
            raise Unread('business')
        return await asyncio.to_thread(_capacity, row, now, tz)

    pair, bookings, cap, offerings, posts, used = await asyncio.gather(
        safe('traffic', lambda: _traffic(bid, now)),
        safe('bookings', lambda: asyncio.to_thread(_bookings, bid, now)),
        safe('capacity', capacity),
        safe('new_offerings', lambda: asyncio.to_thread(_new_offerings, bid, now)),
        safe('posts', lambda: _posts(bid, now)),
        safe('used_subjects', lambda: _used(bid, now)))
    traffic, leads = pair if pair is not None else (None, None)
    if traffic is None:
        unread.append('traffic')          # unreadable, or the week itself was cut off
    if leads is None:
        unread.append('leads')
    news = news_from(row.get('settings')) if row is not None else None
    if news is None:
        unread.append('news')
    fresh_news = fresh(news, 'published_at', now)
    new_offerings = fresh(offerings, 'created_at', now)
    return {
        'read_at': now.isoformat(), 'business_id': bid, 'time_zone': tz.key if tz else None,
        'traffic': traffic, 'leads': leads, 'bookings': bookings, 'capacity': cap,
        'new_offerings': new_offerings,
        'unmarketed_offerings': unmarketed(new_offerings, used, lambda o: offering_key(o.get('name'))),
        'news': news, 'fresh_news': fresh_news,
        'unmarketed_news': unmarketed(fresh_news, used, news_key),
        'posts': posts, 'used_subjects': used,
        'play_scores': {},                # each play's own results arrive with tracked links (B6)
        'unread': sorted(set(unread)),
    }


def summary(signals: Dict[str, Any]) -> Dict[str, Any]:
    """What a run records about its inputs: the numbers and titles, not page bodies."""
    if signals.get('profile') == 'platform':
        import marketing_engine as platform
        return {**platform.summary(signals), 'profile': 'platform', 'unread': signals.get('unread') or []}
    cap = signals.get('capacity')

    def names(items, field):
        return None if items is None else [i.get(field) for i in items]
    return {'read_at': signals.get('read_at'), 'traffic': signals.get('traffic'), 'leads': signals.get('leads'),
            'bookings': signals.get('bookings'),
            'capacity': None if cap is None else {k: cap.get(k) for k in ('offering', 'open_slots', 'open_days',
                                                                          'from', 'to')},
            'posts': signals.get('posts'),
            'new_offerings': names(signals.get('new_offerings'), 'name'),
            'unmarketed_offerings': names(signals.get('unmarketed_offerings'), 'name'),
            'unmarketed_news': names(signals.get('unmarketed_news'), 'title'),
            'unread': signals.get('unread') or []}


# ── Solutionist's own (B15) ───────────────────────────────────────────

def _merge_posts(buffer: Optional[Dict[str, Any]], suite: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """What went out (and is approved ahead) on either desk. Unknown on
    either side is unknown: never a quiet week by accident."""
    if buffer is None or suite is None:
        return None
    stamps = [s for s in (buffer.get('last_published'), suite.get('last_published')) if s]
    return {'last_published': max(stamps, key=lambda s: _when(s)) if stamps else None,
            'published_last_7_days': int(buffer.get('published_last_7_days') or 0)
            + int(suite.get('published_last_7_days') or 0),
            'approved_next_7_days': int(buffer.get('approved_next_7_days') or 0)
            + int(suite.get('approved_next_7_days') or 0)}


async def platform_signals(business_id: Any, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Everything Solutionist's own week may look at. The platform desk's
    reads (each None when unread, never 0) plus the suite's: its posts (the
    last post and what is approved, counted with the Buffer desk's) and its
    plans' subjects (so a news post told on either desk is not told again).
    play_scores is left for the planner (the suite's own links);
    buffer_play_scores carries the Buffer desk's, and the platform's plays
    weigh both."""
    import marketing_engine as platform
    now = now or datetime.now(timezone.utc)
    bid = str(UUID(str(business_id)))
    unread: List[str] = []

    async def safe(name, fetch):
        try:
            return await fetch()
        except Exception:
            log.warning('marketing signals: %s could not be read for the platform', name, exc_info=True)
            unread.append(name)
            return None

    base, suite_posts, suite_used = await asyncio.gather(
        platform.read_signals(now), safe('suite_posts', lambda: _posts(bid, now)),
        safe('suite_subjects', lambda: _used(bid, now)))
    for key in ('traffic', 'posts', 'news', 'founder'):
        if base.get(key) is None:
            unread.append(key)
    used = sorted(set(base.get('used_subjects') or []) | set(suite_used or []))
    news = base.get('news')
    fresh_news = None
    if news is not None and suite_used is not None:
        since = now - timedelta(days=NEW_DAYS)
        fresh_news = [n for n in news if _when(n.get('published_at')) and _when(n['published_at']) >= since
                      and news_key(n) not in used]
    return {**base, 'profile': 'platform', 'business_id': bid, 'time_zone': platform.TZ.key,
            'posts': _merge_posts(base.get('posts'), suite_posts),
            'used_subjects': used, 'unmarketed_news': fresh_news,
            'buffer_play_scores': base.get('play_scores') or {}, 'play_scores': {},
            'unread': sorted(set(unread))}
