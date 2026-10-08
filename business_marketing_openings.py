"""business_marketing_openings.py — Boss's open chairs: the chair calendar, read for posts, and the pulled post.

B11 of docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md (decision D5). A Boss
business (a barbershop or salon whose plan includes marketing_week and whose
booking calendar is live: business_marketing.level_for's `openings`) gets its
weekly plan barber-sized: its open chairs become posts. The run itself lives
in business_marketing_planner (run_openings, the same claim, fan-out,
headroom, jitter and owner's-request machinery as the week); this module is
the chair calendar's half, pure where it can be:

  read_calendar(...)     the week's open slots for one offering, grouped into windows
  pick(...)              the three windows to post about, and when each post goes out
  check_caption(...)     a caption never states a seat count, a wrong day or "tomorrow"
  photo_layout(...)      the owner's own work photo with the words laid over it (composer, free)
  check_work_photos(...) what PUT /marketing/{id}/settings accepts as work photos
  recheck(...)           is the window still as open as the post says? (the pull)
  watch(...), tell_pulled(...)   the 15-minute watch and its Today item, run by the planner's tick

WHICH OFFERING. The most-booked active, bookable offering over the last 60
days, counted from module_entries.data->>offering_id (the field the booking
widget and Chief's create_booking write, through
booking_widget_router._maybe_denormalize_offering; module_entries has no
offering_id column). With no booking that names one, or a bookings read that
fails or comes back at its row limit, the shortest bookable offering, as B7's capacity signal does
(marketing_signals.chair_offering), and the run records which.

WINDOWS. agent_site.slots_for (strict: a failed bookings or outside-calendar
read raises, never "nothing booked") gives one start time per open slot.
Starts on the same local day no further apart than the calendar's slot step
are one window: from its first start to its last start plus the offering's
length. open_count is how many starts it holds (start times, not seats:
compute_slots keeps a start open while any chair is free, so a count of
chairs is never known and never said).

RANK AND PICK. A window's minutes, doubled on the week's slowest weekday
(score = minutes x (2 - that weekday's share of the busiest weekday's
bookings over the last 60 days); no history: minutes alone). Highest first,
ties by the earlier start. Three are picked, at most one per day, each only
if its post can be scheduled.

WHEN A POST GOES OUT. The day before at the desk's hour, else the day
before at 3:00 PM, else that morning at 8:00, on the business's own clock:
the first of these that is at least an hour from now, not already taken by
another post, and leaves at least 30 minutes to send before the cut-off.
The cut-off is two hours before the window (or the calendar's lead time, if
longer), so a post never says a chair is open when it can no longer be
booked online: expires_at = min(run_at + 6 h, starts_at - the gap).
Instants are compared in UTC, so a daylight-saving change never moves one.

THE WORDS. One caption call writes the three captions; each is held to the
business caption checks (numbers and prices only from the facts plus this
window's own day and time, links only to the business's own site, at most
three hashtags) and to these: no count of chairs, seats, spots or times and
no "last one" or "going fast" (concurrent_capacity is not verified, D5); it
names its own day and no other, and never "today", "tonight" or "tomorrow"
(the post may move). A caption that fails gets the plain one, which always
holds: "Open chairs Thursday 2 to 5 pm. Book your time online ...". The
flyer's words are built here, never by the model: the day and time, "Book
your chair online.", "Book now".

THE PICTURE. The owner's newest work photos (marketing_desks.work_photo_ids:
ready photos of THIS business uploaded through /ai/images/upload, never one
the image model or the composer made), full-bleed at 4:5 (1080x1350), with
the words on a panel over the lower part by the free composer (cost 0).
Nothing redraws a real haircut: the photo's own pixels are placed, cropped
to fit. With no work photo, the business's branded flyer (B8's), and the run
says so.

THE PULL. A post's `opening` stores {offering_id, starts_at, ends_at,
open_count, duration_min, day, time_zone, gap_min, when}. Every 15 minutes
the planner's openings_watch_tick re-reads the approved and draft opening
posts going out in the next 48 hours, and the B5 sender re-reads a claimed
one just before sending. Fewer starts open than the post was made for, or
none (it filled up), or too close to the window: the post becomes `pulled`
(the safe direction: it never needs the owner's yes), with one Today item
and one push, once. A read that fails changes nothing: the watch leaves the
post alone; the sender holds it (back to approved) and tries again.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException

import business_marketing_store as store
import sb_clients

log = logging.getLogger(__name__)

PLAY_ID = 'open_chairs'
PLAY_LABEL = 'Open chairs'
EYEBROW = 'OPEN CHAIRS'
POSTS_PER_WEEK = 3
HISTORY_DAYS = 60
HISTORY_ROWS = 2000
POST_LEAD = timedelta(hours=2)        # a post goes out at least this long before its window
MORNING_HOUR = 8                      # "that morning", on the business's clock
OTHER_HOUR = 15                       # the day before at 3:00 PM, when the desk's hour is taken
SEND_SLACK = timedelta(minutes=30)    # a post's time to go out, at the least
SLOT_AFTER = timedelta(hours=1)       # a new post's time is at least this far away (the desk's rule)
WINDOW = timedelta(hours=6)           # how long past its time a post may still go out (the desk's rule)
WATCH_AHEAD = timedelta(hours=48)
WATCH_LIMIT = 200
TELL_BACK = timedelta(days=2)
TELL_LIMIT = 100
MAX_WORK_PHOTOS = 12
CHUNK = 100
WEEKDAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
OPENING_KEYS = ('offering_id', 'starts_at', 'ends_at', 'open_count', 'duration_min', 'day')

OFFERING_COLUMNS = ('id,name,slug,description,category,current_price,currency,duration_min,show_price_to_customer,'
                    'is_active,created_at')
PHOTO_COLUMNS = 'id,business_id,status,storage_path,created_at,model,size'

PLAY_BRIEF = ('Say we have open chairs at the time in this slot\'s opening and invite the reader to book online. '
              'Name the day and the time exactly as the opening gives them. Never say how many chairs, seats, '
              'spots or times are open or left, and never say it is the last one or that it will go fast. Do not '
              'say "today", "tonight" or "tomorrow". No discount or offer unless the facts state it. Name no '
              'person: no owner, staff, client or customer.')


class Unavailable(Exception):
    """A read the open chairs need did not happen. Never "nothing booked"."""


# ── small pure helpers ────────────────────────────────────────────────

def _utc(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        d = value
    else:
        try:
            d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except (TypeError, ValueError):
            return None
    if d.tzinfo is None:
        return None
    return d.astimezone(timezone.utc)


def _z(d: datetime) -> str:
    return d.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _hour_words(d: datetime) -> str:
    h = d.hour % 12 or 12
    return f'{h}' if d.minute == 0 else f'{h}:{d.minute:02d}'


def _half(d: datetime) -> str:
    return 'am' if d.hour < 12 else 'pm'


def time_words(starts: datetime, ends: datetime, tz: ZoneInfo) -> str:
    """'2 to 5 pm', '11 am to 2 pm', '9:30 to 11 am' on the business's clock."""
    a, b = starts.astimezone(tz), ends.astimezone(tz)
    if _half(a) == _half(b):
        return f'{_hour_words(a)} to {_hour_words(b)} {_half(b)}'
    return f'{_hour_words(a)} {_half(a)} to {_hour_words(b)} {_half(b)}'


def day_word(starts: datetime, tz: ZoneInfo) -> str:
    return WEEKDAYS[starts.astimezone(tz).weekday()]


def when_words(starts: datetime, ends: datetime, tz: ZoneInfo) -> str:
    """'Thursday 2 to 5 pm'."""
    return f'{day_word(starts, tz)} {time_words(starts, ends, tz)}'


def opening_facts(window: Dict[str, Any], tz: ZoneInfo) -> Dict[str, str]:
    """What a caption may say about this window: its day, date and time."""
    local = window['starts_at'].astimezone(tz)
    return {'day': day_word(window['starts_at'], tz), 'date': f'{local:%B} {local.day}',
            'time': time_words(window['starts_at'], window['ends_at'], tz)}


# ── windows, rank, pick ───────────────────────────────────────────────

def make_windows(slots: Iterable[Dict[str, Any]], *, step_min: Any, duration_min: Any) -> List[Dict[str, Any]]:
    """Open slot starts grouped into windows: the same local day, no
    further apart than the calendar's slot step. Each window runs from its
    first start to its last start plus the offering's length; open_count is
    how many starts it holds."""
    items = []
    for s in slots or []:
        at = _utc(s.get('start_utc'))
        local = str(s.get('start_local') or '')
        if at is None or len(local) < 10:
            continue
        items.append((at, local[:10]))
    items.sort()
    try:
        step = timedelta(minutes=max(int(step_min or 30), 1))
    except (TypeError, ValueError):
        step = timedelta(minutes=30)
    length = timedelta(minutes=max(int(duration_min or 0), 1))
    out: List[Dict[str, Any]] = []
    for at, day in items:
        last = out[-1] if out else None
        if last and last['day'] == day and at == last['_last']:
            continue                                  # the same start twice is one start
        if last and last['day'] == day and at - last['_last'] <= step:
            last['_last'] = at
            last['open_count'] += 1
        else:
            out.append({'day': day, 'starts_at': at, '_last': at, 'open_count': 1})
    for w in out:
        w['ends_at'] = w.pop('_last') + length
    return out


def weekday_counts(history: Optional[List[Dict[str, Any]]], tz: ZoneInfo) -> Counter:
    """Bookings by weekday (0 Monday) on the business's clock, over the history read."""
    out: Counter = Counter()
    for r in history or []:
        at = _utc(r.get('appointment_at'))
        if at is not None:
            out[at.astimezone(tz).weekday()] += 1
    return out


def score(window: Dict[str, Any], counts: Counter) -> float:
    """A window's minutes, doubled on the week's slowest weekday: minutes x
    (2 - its weekday's share of the busiest weekday's bookings)."""
    minutes = (window['ends_at'] - window['starts_at']).total_seconds() / 60
    top = max(counts.values(), default=0)
    share = counts.get(date.fromisoformat(window['day']).weekday(), 0) / top if top else 0.0
    return round(minutes * (2.0 - share), 2)


def rank(windows: List[Dict[str, Any]], counts: Counter) -> List[Dict[str, Any]]:
    """Bigger windows and historically slow days first; ties by the earlier start."""
    return sorted(windows, key=lambda w: (-score(w, counts), w['starts_at']))


def _hours(post_hour: Any) -> Tuple[int, ...]:
    try:
        hour = int(post_hour)
    except (TypeError, ValueError):
        hour = 11
    hour = hour if 6 <= hour <= 21 else 11
    return tuple(dict.fromkeys((hour, OTHER_HOUR)))


def post_time(window: Dict[str, Any], tz: ZoneInfo, post_hour: Any, at: datetime, gap: timedelta,
              taken: Iterable[float] = ()) -> Optional[Tuple[datetime, datetime]]:
    """(run_at, expires_at) in UTC for this window's post, or None.

    The day before at the desk's hour, then the day before at 3:00 PM, then
    that morning at 8:00, on the business's clock: the first that is at
    least an hour from now, not taken, and leaves SEND_SLACK before the
    cut-off (the window's start less the gap: two hours, or the calendar's
    lead time if longer). It stops trying at the cut-off."""
    taken = set(taken)
    cutoff = window['starts_at'].astimezone(timezone.utc) - gap
    day = date.fromisoformat(window['day'])
    tries = [(day - timedelta(days=1), h) for h in _hours(post_hour)] + [(day, MORNING_HOUR)]
    for d, hour in tries:
        when = datetime.combine(d, time(hour), tz).astimezone(timezone.utc)
        if when <= at.astimezone(timezone.utc) + SLOT_AFTER:
            continue
        if cutoff - when < SEND_SLACK:
            continue
        if when.timestamp() in taken:
            continue
        return when, min(when + WINDOW, cutoff)
    return None


def pick(windows: List[Dict[str, Any]], counts: Counter, *, tz: ZoneInfo, post_hour: Any, at: datetime,
         gap: timedelta, taken: Iterable[float] = (), n: int = POSTS_PER_WEEK) -> List[Dict[str, Any]]:
    """Up to n windows, ranked, at most one per day, each with the time its
    post goes out. Returned in the order they happen."""
    chosen: List[Dict[str, Any]] = []
    days, used = set(), set(taken)
    for w in rank(windows, counts):
        if len(chosen) >= n:
            break
        if w['day'] in days:
            continue
        times = post_time(w, tz, post_hour, at, gap, used)
        if not times:
            continue
        chosen.append({**w, 'score': score(w, counts), 'run_at': times[0], 'expires_at': times[1]})
        days.add(w['day'])
        used.add(times[0].timestamp())
    return sorted(chosen, key=lambda w: w['starts_at'])


# ── which offering ────────────────────────────────────────────────────

def booked_counts(history: Iterable[Dict[str, Any]]) -> Counter:
    return Counter(str(r['offering_id']) for r in history or [] if r.get('offering_id'))


def choose_offering(offerings: List[Dict[str, Any]],
                    history: Optional[List[Dict[str, Any]]]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(offering, how): the most-booked active, bookable offering over the
    history ('most_booked'); else the shortest bookable one ('shortest', or
    'shortest_unread' when the bookings could not be read)."""
    import agent_site
    import marketing_signals
    bookable = [o for o in offerings or [] if o.get('is_active', True) is not False
                and agent_site.public_offering(o)['bookable']]
    if not bookable:
        return None, None
    if history is None:
        return marketing_signals.chair_offering(bookable), 'shortest_unread'
    by_id = {str(o.get('id')): o for o in bookable}
    best = sorted((-n, str(by_id[i].get('name') or '').lower(), i)
                  for i, n in booked_counts(history).items() if i in by_id)
    if best:
        return by_id[best[0][2]], 'most_booked'
    return marketing_signals.chair_offering(bookable), 'shortest'


# ── reads ─────────────────────────────────────────────────────────────

def _query_time(d: datetime) -> str:
    return _z(d).replace('+', '%2B')


def read_history(business_id: str, at: datetime) -> Optional[List[Dict[str, Any]]]:
    """The last 60 days' active bookings: when (UTC, Z), and which offering
    (the booking's data->>offering_id), newest first. None when the read
    fails or comes back at its row limit (some bookings unseen, so "most
    booked" can't be told): the caller then takes the shortest bookable
    offering ('shortest_unread') and the weekday counts are empty.

    The shared bookings read (availability_engine.BOOKING_SELECT,
    booking_window_filter, booked_start): a booking is found by the
    appointment_at column OR data->>appointment_at and starts at the time in
    data, else the column. The column alone was empty on every production
    row until supabase/APPLY-2026-10-08-booking-columns.sql, so this history
    read 'no bookings' (7 by data on 2026-10-07). Whole days are read, the
    exact 60 days kept here, and the newest-first order is made here too:
    the database is not asked to order, because a data-only booking has an
    empty column (NULL sorts first descending), so a cut by the column's
    order was never a cut by date."""
    from availability_engine import BOOKING_SELECT, booked_start, booking_window_filter
    lo, hi = at - timedelta(days=HISTORY_DAYS), at
    rows = sb_clients.sb_get_as_service(
        f'/module_entries?business_id=eq.{business_id}&status=eq.active'
        f'&{booking_window_filter(lo.astimezone(timezone.utc).date(), hi.astimezone(timezone.utc).date() + timedelta(days=1))}'
        f'&select={BOOKING_SELECT},offering_id:data->>offering_id&limit={HISTORY_ROWS}')
    if not isinstance(rows, list) or len(rows) >= HISTORY_ROWS:
        return None
    kept = []
    for r in rows:
        start = booked_start(r)
        if start is not None and lo <= start < hi:
            kept.append((start, r.get('offering_id')))
    kept.sort(key=lambda pair: pair[0], reverse=True)
    return [{'appointment_at': _z(start), 'offering_id': offering_id} for start, offering_id in kept]


def read_offerings(business_id: str) -> List[Dict[str, Any]]:
    """The business's active offerings, read fail-closed (agent_site's bundle
    reads them `or []`, which would make a blip "nothing bookable")."""
    rows = sb_clients.sb_get_as_service(
        f'/offerings?business_id=eq.{business_id}&is_active=eq.true&select={OFFERING_COLUMNS}'
        '&order=name.asc&limit=200')
    if not isinstance(rows, list):
        raise Unavailable('offerings')
    return [r for r in rows if str(r.get('business_id', business_id)) == str(business_id)]


def _availability(business: Dict[str, Any]) -> Dict[str, Any]:
    if 'availability' in business:
        value = business.get('availability')
    else:
        settings = business.get('settings') if isinstance(business.get('settings'), dict) else {}
        value = settings.get('availability')
    return value if isinstance(value, dict) else {}


def _bundle(business_id: str, availability: Dict[str, Any], tz_name: Optional[str]) -> Dict[str, Any]:
    """The one input agent_site.slots_for reads, built from rows read here
    (never its 60-second, fail-soft cache)."""
    return {'facts': {'id': str(business_id), 'availability': availability, 'timezone': tz_name or None}}


def _slots(business_id: str, availability: Dict[str, Any], tz_name: Optional[str], offering: Dict[str, Any],
           start: date, end: date, at: datetime) -> List[Dict[str, Any]]:
    import agent_site
    try:
        return agent_site.slots_for(_bundle(business_id, availability, tz_name), offering, start, end,
                                    strict=True, now=at)
    except HTTPException:
        raise Unavailable('availability') from None


def read_calendar(business: Dict[str, Any], tz: ZoneInfo, week_of: date, at: datetime) -> Dict[str, Any]:
    """The week's open chairs for one business: its offering (and how it
    was chosen), the windows, the weekday history and the gap a post keeps
    before its window. state: 'ok', 'no_hours' (no weekly hours: the engine
    would call that open around the clock) or 'nothing_bookable'. A read
    that fails raises Unavailable."""
    from availability import BusinessAvailability, is_open_default
    bid = str(UUID(str(business['id'])))
    availability = _availability(business)
    av = BusinessAvailability.from_settings_dict(availability)
    if is_open_default(av):
        return {'state': 'no_hours'}
    history = read_history(bid, at)
    offering, how = choose_offering(read_offerings(bid), history)
    if offering is None:
        return {'state': 'nothing_bookable'}
    start = max(week_of, at.astimezone(tz).date())
    end = week_of + timedelta(days=6)
    slots = _slots(bid, availability, tz.key, offering, start, end, at) if start <= end else []
    duration = int(offering.get('duration_min') or 60)
    gap = max(POST_LEAD, timedelta(minutes=int(av.lead_time_min or 0)))
    return {'state': 'ok', 'offering': offering, 'offering_from': how, 'duration_min': duration,
            'windows': make_windows(slots, step_min=av.slot_granularity_min, duration_min=duration),
            'counts': weekday_counts(history, tz), 'history': 'unread' if history is None else 'read',
            'gap': gap, 'open_slots': len(slots)}


def opening_record(window: Dict[str, Any], offering: Dict[str, Any], duration: int, tz: ZoneInfo,
                   gap: timedelta) -> Dict[str, Any]:
    """What a post stores in `opening`: enough to recount the window later
    without the offering list (a failed read of which would look empty)."""
    return {'offering_id': str(offering['id']), 'offering': str(offering.get('name') or '').strip() or None,
            'starts_at': _z(window['starts_at']), 'ends_at': _z(window['ends_at']),
            'open_count': int(window['open_count']), 'duration_min': int(duration), 'day': window['day'],
            'time_zone': tz.key, 'gap_min': int(gap.total_seconds() // 60),
            'when': when_words(window['starts_at'], window['ends_at'], tz)}


# ── the words ─────────────────────────────────────────────────────────

_COUNT = (r'(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|a\s+couple(?:\s+of)?|'
          r'couple(?:\s+of)?|a\s+few|few|several|only|just|last|final|single|limited)')
_NOUN = r'(?:chairs?|seats?|spots?|slots?|openings?|appointments?|times?|places?|spaces?|bookings?)'
_SEATS = re.compile(rf'\b{_COUNT}\s+(?:(?:open|free|empty|available|more|remaining|left)\s+)?{_NOUN}\b', re.I)
_SCARCE = re.compile(rf'\b{_NOUN}\s+(?:left|remaining)\b|\b(?:fill|book|go|sell)(?:s|ing)?\s+(?:up\s+|out\s+)?fast\b|'
                     r"\bwon'?t\s+last\b|\bbefore\s+(?:they(?:'re|\s+are)\s+)?gone\b", re.I)
_NEAR = re.compile(r'\b(?:today|tonight|tomorrow)\b', re.I)


def seat_count_problem(text: str) -> Optional[str]:
    """A count of chairs, seats, spots or times, or a "last one" / "going
    fast" claim. concurrent_capacity is not verified (D5): no number of
    chairs is ever said."""
    if _SEATS.search(text or '') or _SCARCE.search(text or ''):
        return 'a count of chairs or a claim that they are running out'
    return None


def day_problem(text: str, day: str) -> Optional[str]:
    lower = (text or '').lower()
    others = [d for d in WEEKDAYS if d != day and re.search(rf'\b{d.lower()}s?\b', lower)]
    if others:
        return f'names another day ({others[0]})'
    if not re.search(rf'\b{day.lower()}\b', lower):
        return 'does not name its day'
    if _NEAR.search(lower):
        return 'says today, tonight or tomorrow'
    return None


def facts_for(facts: Dict[str, Any], words: Dict[str, str]) -> Dict[str, Any]:
    """The business's verified facts plus this window's own day, date and time."""
    return {**(facts or {}), 'opening': dict(words)}


def check_caption(text: Any, facts: Dict[str, Any], profile: Dict[str, Any], words: Dict[str, str]) -> Optional[str]:
    import business_marketing_engine as engine
    if not isinstance(text, str):
        return 'missing'
    return (engine.check_caption(text, facts_for(facts, words), profile)
            or seat_count_problem(text) or day_problem(text, words['day']))


def plain_caption(words: Dict[str, str]) -> str:
    """The caption that always holds, when the written one does not."""
    return f"Open chairs {words['day']} {words['time']}. Book your time online and we'll see you then."


def flyer_copy(words: Dict[str, str]) -> Dict[str, str]:
    """The flyer's words, built here (never by the model): the day and time,
    one line, the button."""
    return {'headline': f"{words['day']} {words['time']}", 'line': 'Book your chair online.', 'cta': 'Book now'}


def check_flyer(copy: Dict[str, str], facts: Dict[str, Any], profile: Dict[str, Any],
                words: Dict[str, str]) -> Optional[str]:
    import business_marketing_engine as engine
    return (engine.check_flyer(copy, facts_for(facts, words), profile)
            or seat_count_problem(' '.join(copy.values())))


# ── the picture: the owner's own photo, the words over it ─────────────

def photo_layout(photo_id: Any, copy: Dict[str, str], *, scale: float = 1.0, footer: Optional[Dict[str, Any]] = None,
                 palette: Optional[Dict[str, str]] = None, eyebrow: str = EYEBROW) -> Dict[str, Any]:
    """A composer Layout, 4:5 (1080x1350): the work photo full-bleed (its own
    pixels, cropped to fit, never redrawn), a panel in the business's own
    colour over the lower part, and the words on it. The top of the photo
    (at least 42% of its height) is left clear."""
    import marketing_design as design
    p = {**design.NEUTRAL_PALETTE, **(palette or {})}
    width, height = design.WIDTH, design.HEIGHT
    margin, inner = 80, width - 160
    eyebrow_size, head_size, line_size, cta_size, pill_h = 28, 104 * scale, 44 * scale, 34, 96
    head_lines = design._wrap(copy['headline'].upper(), head_size, inner, 'display')
    body_lines = design._wrap(copy['line'], line_size, inner, 'sans')
    block = (eyebrow_size + 26 + 8 + 40 + head_size * 1.02 * len(head_lines) + 34
             + line_size * 1.3 * len(body_lines) + 64 + pill_h)
    area_bottom = height - 170
    y = area_bottom - block
    panel = y - 64
    if panel < height * 0.42:
        raise HTTPException(422, 'The flyer copy does not fit.')
    layers = [
        {'kind': 'image', 'image_id': str(UUID(str(photo_id))), 'x': 0, 'y': 0, 'width': width, 'height': height,
         'fit': 'cover'},
        {'kind': 'shape', 'shape': 'rect', 'x': 0, 'y': panel - 120, 'width': width, 'height': 60, 'fill': p['bg'],
         'opacity': 0.22},
        {'kind': 'shape', 'shape': 'rect', 'x': 0, 'y': panel - 60, 'width': width, 'height': 60, 'fill': p['bg'],
         'opacity': 0.5},
        {'kind': 'shape', 'shape': 'rect', 'x': 0, 'y': panel, 'width': width, 'height': height - panel,
         'fill': p['bg'], 'opacity': 0.84},
        design._text(eyebrow, margin, y, inner, eyebrow_size, weight=800, fill=p['ice'], tracking=6),
    ]
    y += eyebrow_size + 26
    layers.append({'kind': 'shape', 'shape': 'rect', 'x': margin, 'y': y, 'width': 120, 'height': 8,
                   'fill': p['accent'], 'radius': 4})
    y += 8 + 40
    layers.append(design._text('\n'.join(head_lines), margin, y, inner, head_size, font='display', weight=400,
                               fill=p['ink'], line_height=1.02))
    y += head_size * 1.02 * len(head_lines) + 34
    layers.append(design._text('\n'.join(body_lines), margin, y, inner, line_size, weight=600, fill=p['mist'],
                               line_height=1.3))
    y += line_size * 1.3 * len(body_lines) + 64
    cta = copy['cta']
    pill_w = min(inner, len(cta) * cta_size * 0.62 + 110)
    layers.append({'kind': 'shape', 'shape': 'rect', 'x': margin, 'y': y, 'width': pill_w, 'height': pill_h,
                   'fill': p['accent'], 'radius': 48})
    layers.append(design._text(cta, margin, y + 22, pill_w, cta_size, weight=800, fill=p['on_accent'],
                               align='center'))
    foot_y = height - 110
    layers.append({'kind': 'shape', 'shape': 'rect', 'x': margin, 'y': foot_y - 28, 'width': inner, 'height': 2,
                   'fill': p['ice'], 'opacity': 0.25})
    layers += design._footer(footer or {}, p, margin, inner, foot_y)
    return {'width': width, 'height': height, 'title': f"{eyebrow.title()}: {copy['headline']}"[:180],
            'background': p['bg'], 'layers': layers}


# ── work photos ───────────────────────────────────────────────────────

NOT_HERE = "That picture isn't in this business's Media Library."
NOT_READY = 'That picture is still being made. Add it once it is ready.'
NOT_FINISHED = "That picture didn't finish, so it can't be used."
NOT_A_PHOTO = ('That picture was made in Image Studio. A work photo is a photo of your own work: upload one, '
               'and Chief puts the words over it.')
PHOTOS_DOWN = "Your pictures couldn't be read just now. Nothing was changed. Try again in a minute."


def _photo_rows(business_id: str, ids: List[str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(ids), CHUNK):
        chunk = ids[i:i + CHUNK]
        rows = sb_clients.sb_get_as_service(
            f"/image_artworks?business_id=eq.{business_id}&id=in.({','.join(chunk)})&select={PHOTO_COLUMNS}")
        if not isinstance(rows, list):
            raise Unavailable('image_artworks')
        for r in rows:
            if str(r.get('business_id')) == str(business_id):
                out[str(r['id'])] = r
    return out


def photo_problem(row: Optional[Dict[str, Any]]) -> Optional[Tuple[int, str]]:
    """Why this row is not a usable work photo, as (status, words), or None.
    A work photo is a ready upload of this business: a picture the image
    model (model/size) or the composer (size) made is not a photo of anyone's work."""
    if not row:
        return 404, NOT_HERE
    if row.get('status') in ('queued', 'working'):
        return 409, NOT_READY
    if row.get('status') != 'ready' or not row.get('storage_path'):
        return 409, NOT_FINISHED
    if row.get('model') or row.get('size'):
        return 422, NOT_A_PHOTO
    return None


def _newest_first(rows: Dict[str, Dict[str, Any]], ids: List[str]) -> List[str]:
    order = {i: n for n, i in enumerate(ids)}
    return sorted(ids, key=lambda i: (-(_utc(rows[i].get('created_at')) or datetime.min.replace(
        tzinfo=timezone.utc)).timestamp(), order[i]))


def check_work_photos(business_id: str, ids: Iterable[Any]) -> List[str]:
    """The ids PUT /settings saves: each a ready photo of THIS business
    (another business's id answers like a missing one), at most 12, newest
    first. Raises HTTPException in plain words; a failed read is a 503."""
    wanted = list(dict.fromkeys(str(UUID(str(i))) for i in ids or []))
    if len(wanted) > MAX_WORK_PHOTOS:
        raise HTTPException(422, f'Choose at most {MAX_WORK_PHOTOS} work photos.')
    if not wanted:
        return []
    try:
        rows = _photo_rows(str(business_id), wanted)
    except Unavailable:
        raise HTTPException(503, PHOTOS_DOWN) from None
    for i in wanted:
        problem = photo_problem(rows.get(i))
        if problem:
            raise HTTPException(problem[0], problem[1])
    return _newest_first(rows, wanted)


def work_photos(business_id: str, ids: Iterable[Any]) -> List[str]:
    """The desk's work photos still usable now (ready uploads of this
    business), newest first. A photo deleted or changed since is skipped;
    a read that fails raises Unavailable."""
    wanted = []
    for i in ids or []:
        try:
            wanted.append(str(UUID(str(i))))
        except ValueError:
            continue
    wanted = list(dict.fromkeys(wanted))[:MAX_WORK_PHOTOS]
    if not wanted:
        return []
    rows = _photo_rows(str(business_id), wanted)
    usable = [i for i in wanted if photo_problem(rows.get(i)) is None]
    return _newest_first(rows, usable)


# ── the pull ──────────────────────────────────────────────────────────

def valid(opening: Any) -> bool:
    if not isinstance(opening, dict) or any(opening.get(k) in (None, '') for k in OPENING_KEYS):
        return False
    try:
        UUID(str(opening['offering_id']))
        date.fromisoformat(str(opening['day']))
        return (_utc(opening['starts_at']) is not None and _utc(opening['ends_at']) is not None
                and int(opening['open_count']) > 0 and int(opening['duration_min']) > 0)
    except (TypeError, ValueError):
        return False


def read_availability(business_id: str) -> Dict[str, Any]:
    """The business's calendar settings, read fail-closed."""
    rows = sb_clients.sb_get_as_service(
        f'/businesses?id=eq.{UUID(str(business_id))}&select=id,availability:settings->availability&limit=1')
    if not isinstance(rows, list) or not rows:
        raise Unavailable('the business')
    value = rows[0].get('availability')
    return value if isinstance(value, dict) else {}


def open_now(business_id: str, opening: Dict[str, Any], availability: Dict[str, Any], at: datetime,
             cache: Optional[Dict[Any, List[Dict[str, Any]]]] = None) -> int:
    """How many starts are open in the post's window now. Raises Unavailable."""
    starts, ends = _utc(opening['starts_at']), _utc(opening['ends_at'])
    length = timedelta(minutes=int(opening['duration_min']))
    day = date.fromisoformat(str(opening['day']))
    key = (str(business_id), str(opening['offering_id']), int(opening['duration_min']), day.isoformat(),
           opening.get('time_zone'))
    slots = (cache or {}).get(key)
    if slots is None:
        offering = {'id': str(opening['offering_id']), 'duration_min': int(opening['duration_min'])}
        slots = _slots(str(business_id), availability, opening.get('time_zone'), offering, day, day, at)
        if cache is not None:
            cache[key] = slots
    count = 0
    for s in slots:
        at_ = _utc(s.get('start_utc'))
        if at_ is not None and starts <= at_ and at_ + length <= ends:
            count += 1
    return count


def recheck(business_id: str, opening: Dict[str, Any], availability: Dict[str, Any], at: datetime,
            cache: Optional[Dict[Any, List[Dict[str, Any]]]] = None) -> Optional[str]:
    """Why the post must come down, or None while its window is still as
    open as the post was made for: 'late' (too close to the window to post),
    'full' (nothing left open), 'fewer' (a time in it was booked). Raises
    Unavailable when the calendar cannot be read: never a guess."""
    gap = timedelta(minutes=max(int(opening.get('gap_min') or 0), int(POST_LEAD.total_seconds() // 60)))
    if at >= _utc(opening['starts_at']) - gap:
        return 'late'
    count = open_now(business_id, opening, availability, at, cache)
    if count <= 0:
        return 'full'
    if count < int(opening['open_count']):
        return 'fewer'
    return None


def pulled_words(opening: Dict[str, Any], why: str) -> Dict[str, str]:
    when = str((opening or {}).get('when') or 'An open time')
    if why == 'full':
        return {'title': f'{when} filled up, so its post was pulled',
                'body': 'Every open time in it was booked before the post went out, so nothing was posted. '
                        'Nothing needs your OK.'}
    if why == 'fewer':
        return {'title': f'{when} was booked into, so its post was pulled',
                'body': 'A time in it was booked before the post went out, so the post would no longer have been '
                        'right. Nothing was posted. Nothing needs your OK.'}
    return {'title': f'{when} is too close now, so its post was pulled',
            'body': 'It could no longer go out at least two hours before those chairs, so nothing was posted.'}


def pull_patch(row: Dict[str, Any], why: str, at: datetime) -> Dict[str, Any]:
    """The write that pulls a post: status pulled, a new revision (an open
    desk refreshes), the reason in plain words. The opening keeps why."""
    opening = {**(row.get('opening') if isinstance(row.get('opening'), dict) else {}),
               'pulled': {'why': why, 'at': _z(at)}}
    return {'status': 'pulled', 'revision': int(row.get('revision') or 1) + 1,
            'error': pulled_words(opening, why)['body'], 'opening': opening, 'checked_at': at.isoformat()}


WATCH_COLUMNS = 'id,business_id,revision,status,source,opening,run_at,expires_at'


async def watch(posts: List[Dict[str, Any]], at: datetime) -> Counter:
    """Recount each opening post's window; pull the ones that filled. Each
    write lands only on the post as read (same revision and status), so a
    post the sender just claimed is left to the sender's own check. A
    business whose calendar cannot be read is left exactly as it is."""
    tally: Counter = Counter()
    by_business: Dict[str, List[Dict[str, Any]]] = {}
    for p in posts:
        by_business.setdefault(str(UUID(str(p['business_id']))), []).append(p)
    for bid, items in by_business.items():
        try:
            availability = await asyncio.to_thread(read_availability, bid)
        except Unavailable:
            tally['unreadable'] += len(items)
            continue
        cache: Dict[Any, List[Dict[str, Any]]] = {}
        for p in items:
            try:
                if p.get('status') not in ('draft', 'approved') or not valid(p.get('opening')):
                    tally['skipped'] += 1
                    continue
                why = await asyncio.to_thread(recheck, bid, p['opening'], availability, at, cache)
                if not why:
                    tally['open'] += 1
                    continue
                saved = await store.request(
                    'PATCH', f"/marketing_posts?id=eq.{UUID(str(p['id']))}&business_id=eq.{bid}"
                             f"&revision=eq.{int(p.get('revision') or 1)}&status=eq.{p['status']}",
                    pull_patch(p, why, at))
                tally['pulled' if saved else 'moved_on'] += 1
            except Unavailable:
                tally['unreadable'] += 1
            except store.StoreError:
                tally['unwritten'] += 1
            except Exception:
                log.warning('marketing openings: %s could not be checked', str(p.get('id'))[:8], exc_info=True)
                tally['error'] += 1
    return tally


# ── telling the owner, once ───────────────────────────────────────────

def dedup_key(post_id: Any) -> str:
    return f'marketing_opening:{UUID(str(post_id))}'


def _already_told(business_id: str, key: str) -> Optional[bool]:
    rows = sb_clients.sb_get_as_service(
        f'/chief_notifications?business_id=eq.{business_id}&action_payload->>dedup_key=eq.{key}&select=id&limit=1')
    if rows is None:
        return None
    return bool(rows)


def _owners(ids: List[str]) -> Optional[Dict[str, str]]:
    rows = sb_clients.sb_get_as_service(f"/businesses?id=in.({','.join(ids)})&select=id,owner_id")
    if rows is None:
        return None
    return {str(r.get('id')): str(r['owner_id']) for r in rows if r.get('owner_id')}


def _today_item(business_id: str, row: Dict[str, Any], said: Dict[str, str], key: str) -> bool:
    saved = sb_clients.sb_post_as_service('/chief_notifications', {
        'business_id': business_id, 'type': 'reminder', 'priority': 'normal',
        'title': said['title'][:120], 'body': said['body'][:300], 'suggested_action': 'See the desk',
        'action_payload': {'type': 'navigate', 'tab': 'grow', 'sub': 'marketing', 'post_id': str(row['id']),
                           'dedup_key': key},
    })
    return bool(saved)


def _push(owner_id: str, row: Dict[str, Any], said: Dict[str, str]) -> int:
    try:
        import push_notifications
        return push_notifications.send_to_user(owner_id, title=said['title'][:80], body=said['body'][:160],
                                               nav='grow:marketing', tag=f"marketing-opening-{row['id']}")
    except Exception:
        log.warning('marketing openings: push for %s failed', row.get('id'), exc_info=True)
        return 0


async def tell_pulled(at: datetime, only: str = '') -> int:
    """One Today item and one push per pulled post, never twice (keyed by the
    post in chief_notifications.action_payload.dedup_key): the watch's own
    pulls and the sender's. If what was said cannot be read, nothing is said
    until it can."""
    rows = await store.rows(
        f'/marketing_posts?source=eq.opening&status=eq.pulled&updated_at=gte.{_query_time(at - TELL_BACK)}{only}'
        f'&select=id,business_id,revision,opening&order=updated_at.desc&limit={TELL_LIMIT}')
    if not rows:
        return 0
    owners = await asyncio.to_thread(_owners, sorted({str(UUID(str(r['business_id']))) for r in rows}))
    if owners is None:
        return 0
    told = 0
    for row in rows:
        bid = str(UUID(str(row['business_id'])))
        try:
            key = dedup_key(row['id'])
            if await asyncio.to_thread(_already_told, bid, key) is not False:
                continue
            opening = row.get('opening') if isinstance(row.get('opening'), dict) else {}
            said = pulled_words(opening, str((opening.get('pulled') or {}).get('why') or 'full'))
            if not await asyncio.to_thread(_today_item, bid, row, said, key):
                continue
            if owners.get(bid):
                await asyncio.to_thread(_push, owners[bid], row, said)
            told += 1
        except Exception:
            log.warning('marketing openings: could not tell the owner about %s', row.get('id'), exc_info=True)
    return told
