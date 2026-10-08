"""Boss's open-chairs week (business_marketing_openings.py + the planner's run_openings, B11).

The chair calendar's slots grouped into windows; bigger windows and slow
days first; three picked, one a day; each post the day before or that
morning, at least two hours before its window, on the business's own clock
(daylight saving included); captions that never state a seat count; the
owner's work photo with the words laid over by the free composer, or the
branded flyer; the work photos the settings accept; the pull, by the
15-minute watch and by the sender just before sending, with one Today item;
a failed calendar read changes nothing; the fan-out, the owner's request and
the preview; the shared slot computation's bookings read.

No network: the marketing tables, the service-role reads, the model, the
composer, the slot computation and the push sender are fakes at the seams
the planner calls (the B8 and B9 suites' fakes, extended).
"""
from __future__ import annotations

import asyncio
import copy
import json
import pathlib
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '__tests__'))

import pytest
from fastapi import HTTPException

import agent_site
import business_marketing as bm
import business_marketing_dispatch as dispatch
import business_marketing_links as links
import business_marketing_openings as op
import business_marketing_planner as plan
import business_marketing_store as store
import chief_flyer_composer as composer
import creative_director as cd
import image_studio as images
import marketing_profile as prof
import outside_calendar
import sb_clients

from test_business_marketing_planner import (  # noqa: E402  (the B8 suite's fakes)
    CHICAGO, NEXT_MONDAY, PRO, PRO_OWNER, THU, connection)
from test_business_marketing_week import BOSS, BOSS_OWNER, MEMBER, w  # noqa: E402,F401  (the B9 fixture)

run = asyncio.run
UTC = timezone.utc
BOSS_IG = 'c0000000-0000-4000-8000-0000000000b1'
CUT = 'd0000000-0000-4000-8000-000000000001'
BEARD = 'd0000000-0000-4000-8000-000000000002'
OLD_PHOTO = 'e0000000-0000-4000-8000-000000000001'
NEW_PHOTO = 'e0000000-0000-4000-8000-000000000002'
BOSS_FACTS = {'name': 'Fade Lab', 'type': 'barbershop', 'city': 'Cleveland',
              'offerings': [{'name': 'Classic cut', 'price': '$35', 'minutes': 30}]}
HOURS = {'timezone': 'America/Chicago', 'slot_granularity_min': 30, 'lead_time_min': 0,
         'weekly': {k: [{'start': '09:00', 'end': '18:00'}] for k in ('mon', 'tue', 'wed', 'thu', 'fri', 'sat')}}


def local(day: int, hour: int, minute: int = 0) -> datetime:
    """A naive Chicago wall time in October 2026."""
    return datetime(2026, 10, day, hour, minute)


def starts(day, first, last, step=30):
    """Every start from `first` to `last` (hours as h or (h, m)) on that October day."""
    a = local(day, *(first if isinstance(first, tuple) else (first,)))
    b = local(day, *(last if isinstance(last, tuple) else (last,)))
    out = []
    while a <= b:
        out.append(a)
        a += timedelta(minutes=step)
    return out


# Next week (October 12-18), Chicago:
#   Mon 10:00-11:00 (2 starts)   Tue 2-5 pm (6)   Wed 9:00 (1)
#   Thu 2-3:30 pm (3) and 4:30-5 pm (1)            Sat 10 am-1 pm (6)
OPEN = (starts(12, 10, (10, 30)) + starts(13, 14, (16, 30)) + starts(14, 9, 9)
        + starts(15, 14, 15) + starts(15, (16, 30), (16, 30)) + starts(17, 10, (12, 30)))
# The last 60 days: Tuesdays are busy, Saturdays half as busy, the rest quiet.
HISTORY = ([{'appointment_at': f'2026-09-{d:02d}T19:00:00Z', 'offering_id': CUT} for d in (1, 8, 15, 22, 29)] * 2
           + [{'appointment_at': f'2026-09-{d:02d}T16:00:00Z', 'offering_id': CUT} for d in (5, 12, 19, 26)]
           + [{'appointment_at': '2026-09-26T17:00:00Z', 'offering_id': BEARD}])


def reply_for(texts):
    return {'captions': [{'slot': i + 1, 'text': t,
                          'flyer': {'headline': 'x' * 8, 'line': 'y' * 12, 'cta': 'Book now'}}
                         for i, t in enumerate(texts)]}


GOOD = ['Open chairs Tuesday 2 to 5 pm. Come in for a fresh fade and book your time online. #barber',
        'Two chairs open Thursday 2 to 3:30 pm, so grab one before they are gone!',
        'Saturday 10 am to 1 pm still has open chairs. Book online and walk out sharp. #fade #barbershop']


@pytest.fixture
def o(w, monkeypatch):
    """The B9 fixture with a Boss barbershop whose calendar is live and has hours."""
    state = w
    state.open_local = set(OPEN)
    state.slots_error = None
    state.slot_calls = []
    state.history = copy.deepcopy(HISTORY)
    state.composed = []
    state.reply = reply_for(GOOD)
    boss = state.svc.businesses[BOSS]
    boss['settings']['availability'] = copy.deepcopy(HOURS)
    state.svc.connections.append(connection(BOSS_IG, 'instagram', biz=BOSS))
    state.svc.offerings += [
        {'id': CUT, 'business_id': BOSS, 'name': 'Classic cut', 'slug': 'classic-cut', 'category': 'service',
         'duration_min': 30, 'current_price': 35, 'currency': 'USD', 'show_price_to_customer': True,
         'is_active': True, 'created_at': '2026-01-01T00:00:00Z'},
        {'id': BEARD, 'business_id': BOSS, 'name': 'Beard trim', 'slug': 'beard-trim', 'category': 'service',
         'duration_min': 15, 'current_price': 15, 'currency': 'USD', 'show_price_to_customer': True,
         'is_active': True, 'created_at': '2026-01-01T00:00:00Z'}]
    state.svc.images += [
        {'id': OLD_PHOTO, 'business_id': BOSS, 'status': 'ready', 'storage_path': f'{BOSS}/{OLD_PHOTO}.png',
         'created_at': '2026-09-01T12:00:00Z', 'model': None, 'size': None},
        {'id': NEW_PHOTO, 'business_id': BOSS, 'status': 'ready', 'storage_path': f'{BOSS}/{NEW_PHOTO}.png',
         'created_at': '2026-10-01T12:00:00Z', 'model': None, 'size': None}]

    real_table = state.db.table

    def table(rows, key, method, path, body):          # the touch trigger: updated_at on every write
        if key == 'id' and method in ('POST', 'PATCH') and isinstance(body, dict):
            body = {**body, 'updated_at': state.now.isoformat()}
        return real_table(rows, key, method, path, body)
    state.db.table = table

    real_get = state.svc.get

    def get(path):
        if path.split('?', 1)[0] == '/module_entries':
            state.svc.reads.append(path)
            if any(f in path for f in state.svc.fail):
                return None
            return copy.deepcopy(state.history)
        return real_get(path)
    monkeypatch.setattr(sb_clients, 'sb_get_as_service', get)

    def slots_for(b, off, start, end, *, strict=False, now=None):
        state.slot_calls.append({'offering': str(off.get('id')), 'duration': off.get('duration_min'), 'start': start,
                                 'end': end, 'strict': strict, 'tz': b['facts'].get('timezone'), 'now': now,
                                 'business': b['facts']['id']})
        if state.slots_error:
            raise state.slots_error
        tz = ZoneInfo(b['facts'].get('timezone') or 'UTC')
        return [{'start_utc': t.replace(tzinfo=tz).astimezone(UTC).isoformat(), 'start_local': t.isoformat(),
                 'duration_min': int(off['duration_min'])}
                for t in sorted(state.open_local) if start <= t.date() <= end]
    monkeypatch.setattr(agent_site, 'slots_for', slots_for)

    async def read_profile(bid, *, business=None):
        site = next((x for x in state.svc.sites if x['business_id'] == bid), None)
        return prof.build_profile(business, hosts=links.own_hosts(links.site_from_row(site)), tz=CHICAGO,
                                  booking_live=True, chair_calendar=bid == BOSS)
    monkeypatch.setattr(prof, 'read_profile', read_profile)
    monkeypatch.setattr(cd, 'business_facts', lambda bid: copy.deepcopy(BOSS_FACTS if bid == BOSS else {}))

    async def compose(client, biz, action, request_id):
        layout = composer.Layout.model_validate(action['layout'])          # the composer's own contract
        state.composed.append({'biz': biz['id'], 'layout': layout.model_dump(mode='json'),
                               'request_id': str(request_id), 'actor': images.build_actor.get()})
        return {'image': {'id': str(uuid5(UUID(biz['id']), f'chief-composition:{request_id}')), 'cost_usd': 0}}
    monkeypatch.setattr(composer, 'compose', compose)

    async def no_render(*a, **k):
        raise AssertionError('an open-chairs picture is never an image-model render')
    monkeypatch.setattr(images, 'create', no_render)
    return state


def boss_posts(s, status=None):
    return sorted((p for p in s.db.posts.values() if p['business_id'] == BOSS and (status is None or p['status'] == status)),
                  key=lambda p: p['run_at'])


def boss_run(s):
    return next(r for r in s.db.runs.values() if r['business_id'] == BOSS)


def plan_boss(s, **kw):
    return run(plan.run_openings(BOSS, trigger='scheduled', **kw))


def at_utc(day, hour, minute=0):
    return local(day, hour, minute).replace(tzinfo=CHICAGO).astimezone(UTC)


# ── windows, rank, pick (pure) ────────────────────────────────────────

def slot_rows(times, tz=CHICAGO, minutes=30):
    return [{'start_utc': t.replace(tzinfo=tz).astimezone(UTC).isoformat(), 'start_local': t.isoformat(),
             'duration_min': minutes} for t in times]


def test_open_slots_group_into_windows_by_day_and_step():
    windows = op.make_windows(slot_rows(OPEN), step_min=30, duration_min=30)
    got = [(w['day'], w['starts_at'].astimezone(CHICAGO).strftime('%H:%M'),
            w['ends_at'].astimezone(CHICAGO).strftime('%H:%M'), w['open_count']) for w in windows]
    assert got == [('2026-10-12', '10:00', '11:00', 2), ('2026-10-13', '14:00', '17:00', 6),
                   ('2026-10-14', '09:00', '09:30', 1), ('2026-10-15', '14:00', '15:30', 3),
                   ('2026-10-15', '16:30', '17:00', 1), ('2026-10-17', '10:00', '13:00', 6)]
    # The same start twice is one start; a wider step joins what 30 minutes keeps apart.
    twice = slot_rows([local(15, 14), local(15, 14), local(15, 14, 30)])
    assert [w['open_count'] for w in op.make_windows(twice, step_min=30, duration_min=30)] == [2]
    joined = op.make_windows(slot_rows(starts(15, 14, 15) + [local(15, 16, 30)]), step_min=90, duration_min=30)
    assert [(w['open_count'], w['ends_at'].astimezone(CHICAGO).hour) for w in joined] == [(4, 17)]
    # Midnight splits days whatever the step.
    late = slot_rows([local(15, 23, 30), local(16, 0, 0)])
    assert len(op.make_windows(late, step_min=60, duration_min=30)) == 2
    assert op.make_windows([], step_min=30, duration_min=30) == []


def test_bigger_windows_and_slow_days_rank_first():
    windows = op.make_windows(slot_rows(OPEN), step_min=30, duration_min=30)
    counts = op.weekday_counts(HISTORY, CHICAGO)
    assert counts[1] == 10 and counts[5] == 5 and counts[3] == 0           # Tuesday, Saturday, Thursday
    ranked = [(w['day'], w['starts_at'].astimezone(CHICAGO).hour, op.score(w, counts)) for w in op.rank(windows, counts)]
    # Saturday's 3 hours on a half-busy day beat Tuesday's 3 hours on the busiest; Thursday's
    # 90 quiet minutes tie Tuesday and lose on the clock.
    assert ranked[:4] == [('2026-10-17', 10, 270.0), ('2026-10-13', 14, 180.0), ('2026-10-15', 14, 180.0),
                          ('2026-10-12', 10, 120.0)]
    # No history: minutes alone.
    plain = op.rank(windows, Counter())
    assert [w['day'] for w in plain[:2]] == ['2026-10-13', '2026-10-17']


def test_three_are_picked_one_a_day_in_the_order_they_happen():
    windows = op.make_windows(slot_rows(OPEN), step_min=30, duration_min=30)
    picked = op.pick(windows, op.weekday_counts(HISTORY, CHICAGO), tz=CHICAGO, post_hour=11, at=THU,
                     gap=op.POST_LEAD)
    assert [(w['day'], w['starts_at'].astimezone(CHICAGO).hour) for w in picked] == [
        ('2026-10-13', 14), ('2026-10-15', 14), ('2026-10-17', 10)]
    assert [w['run_at'] for w in picked] == [at_utc(12, 11), at_utc(14, 11), at_utc(16, 11)]
    # A window whose post cannot be scheduled is passed over for the next one.
    taken = {at_utc(16, 11).timestamp(), at_utc(16, 15).timestamp(), at_utc(17, 8).timestamp()}
    picked = op.pick(windows, op.weekday_counts(HISTORY, CHICAGO), tz=CHICAGO, post_hour=11, at=THU,
                     gap=op.POST_LEAD, taken=taken)
    assert [w['day'] for w in picked] == ['2026-10-12', '2026-10-13', '2026-10-15']
    assert op.pick([], Counter(), tz=CHICAGO, post_hour=11, at=THU, gap=op.POST_LEAD) == []


def test_a_post_goes_out_the_day_before_or_that_morning_two_hours_ahead():
    window = {'day': '2026-10-15', 'starts_at': at_utc(15, 14), 'ends_at': at_utc(15, 17), 'open_count': 6}
    run_at, expires = op.post_time(window, CHICAGO, 11, THU, op.POST_LEAD)
    assert run_at == at_utc(14, 11) and expires == at_utc(14, 17)              # the day before; six hours to go
    # The desk's hour taken: 3 PM the day before; both taken: 8 that morning.
    run_at, expires = op.post_time(window, CHICAGO, 11, THU, op.POST_LEAD, {at_utc(14, 11).timestamp()})
    assert run_at == at_utc(14, 15) and expires == at_utc(14, 21)
    both = {at_utc(14, 11).timestamp(), at_utc(14, 15).timestamp()}
    run_at, expires = op.post_time(window, CHICAGO, 11, THU, op.POST_LEAD, both)
    assert run_at == at_utc(15, 8) and expires == at_utc(15, 12)               # out by noon, two hours ahead
    assert window['starts_at'] - expires == timedelta(hours=2)
    # The morning needs two hours plus half an hour to send: a 10:15 window cannot use it.
    early = {**window, 'starts_at': at_utc(15, 10, 15)}
    assert op.post_time(early, CHICAGO, 11, THU, op.POST_LEAD, both) is None
    assert op.post_time({**window, 'starts_at': at_utc(15, 10, 30)}, CHICAGO, 11, THU, op.POST_LEAD,
                        both)[0] == at_utc(15, 8)
    # Never within an hour of now: planned Wednesday at 10:30, the day-before 11:00 is too soon.
    wed = at_utc(14, 10, 30)
    assert op.post_time(window, CHICAGO, 11, wed, op.POST_LEAD)[0] == at_utc(14, 15)
    # A calendar lead time longer than two hours moves the cut-off with it.
    _, expires = op.post_time(window, CHICAGO, 11, THU, timedelta(hours=24))
    assert expires == at_utc(14, 14)
    assert op.post_time(window, CHICAGO, 11, THU, timedelta(hours=27)) is None   # nothing leaves time to send
    # The desk's own hour (7 PM) is used as set.
    assert op.post_time(window, CHICAGO, 19, THU, op.POST_LEAD)[0] == at_utc(14, 19)


def test_post_times_hold_across_daylight_saving():
    # Sunday 1 November 2026: Chicago falls back from CDT (UTC-5) to CST (UTC-6) at 2 AM.
    sunday = datetime(2026, 11, 1, 10, 0, tzinfo=CHICAGO)
    assert sunday.utcoffset() == timedelta(hours=-6)
    window = {'day': '2026-11-01', 'starts_at': sunday.astimezone(UTC),
              'ends_at': (sunday + timedelta(hours=3)).astimezone(UTC), 'open_count': 6}
    at = datetime(2026, 10, 29, 15, 0, tzinfo=UTC)
    run_at, expires = op.post_time(window, CHICAGO, 11, at, op.POST_LEAD)
    assert run_at == datetime(2026, 10, 31, 16, 0, tzinfo=UTC)                 # Saturday 11:00 CDT
    assert run_at.astimezone(CHICAGO).hour == 11
    assert expires == run_at + timedelta(hours=6)
    assert window['starts_at'] - run_at == timedelta(hours=24)                  # a 23-hour wall gap, 24 real
    # That morning, after the change: 8:00 CST is 14:00 UTC, two real hours before 10:00 CST.
    taken = {run_at.timestamp(), datetime(2026, 10, 31, 20, 0, tzinfo=UTC).timestamp()}
    late = {**window, 'starts_at': datetime(2026, 11, 1, 10, 30, tzinfo=CHICAGO).astimezone(UTC)}
    run_at, expires = op.post_time(late, CHICAGO, 11, at, op.POST_LEAD, taken)
    assert run_at == datetime(2026, 11, 1, 14, 0, tzinfo=UTC) and run_at.astimezone(CHICAGO).hour == 8
    assert late['starts_at'] - expires == timedelta(hours=2)
    # Spring forward (8 March 2026): the day before is CST, the window CDT.
    window = {'day': '2026-03-08', 'starts_at': datetime(2026, 3, 8, 14, 0, tzinfo=CHICAGO).astimezone(UTC),
              'ends_at': datetime(2026, 3, 8, 17, 0, tzinfo=CHICAGO).astimezone(UTC), 'open_count': 6}
    run_at, _ = op.post_time(window, CHICAGO, 11, datetime(2026, 3, 5, 12, 0, tzinfo=UTC), op.POST_LEAD)
    assert run_at == datetime(2026, 3, 7, 17, 0, tzinfo=UTC) and run_at.astimezone(CHICAGO).hour == 11


def test_the_time_is_said_plainly():
    tz = CHICAGO
    assert op.time_words(at_utc(15, 14), at_utc(15, 17), tz) == '2 to 5 pm'
    assert op.time_words(at_utc(15, 11), at_utc(15, 14), tz) == '11 am to 2 pm'
    assert op.time_words(at_utc(15, 9, 30), at_utc(15, 11), tz) == '9:30 to 11 am'
    assert op.time_words(at_utc(15, 12), at_utc(15, 12, 30), tz) == '12 to 12:30 pm'
    assert op.when_words(at_utc(15, 14), at_utc(15, 17), tz) == 'Thursday 2 to 5 pm'


# ── the words ─────────────────────────────────────────────────────────

@pytest.mark.parametrize('text', [
    'Two chairs open Thursday 2 to 5 pm.', '3 open chairs Thursday afternoon.', 'Only 2 spots left Thursday!',
    'A couple of seats free on Thursday.', 'Thursday: one chair left, book now.', 'Grab the last chair Thursday.',
    'Thursday fills up fast, book today.', 'Thursday has a few open times.', 'Chairs left Thursday at 2.',
    'Thursday 2 to 5 pm, before they are gone.', 'Just one appointment open Thursday.'])
def test_a_caption_never_states_a_seat_count(text):
    assert op.seat_count_problem(text)


@pytest.mark.parametrize('text', [
    'Open chairs Thursday 2 to 5 pm. Book your time online.', 'We have open chairs on Thursday afternoon.',
    'Book a time Thursday between 2 and 5 pm.', 'Thursday 2 to 5 pm is open for walk-ins booked online.'])
def test_a_caption_without_a_count_passes(text):
    assert op.seat_count_problem(text) is None


def test_the_caption_checks():
    profile = prof.build_profile({'id': BOSS, 'name': 'Fade Lab', 'type': 'barbershop'},
                                 hosts={'fade-lab.mysolutionist.app'})
    facts = {'name': 'Fade Lab', 'offerings': [{'name': 'Classic cut', 'price': '$35', 'minutes': 30}]}
    words = {'day': 'Thursday', 'date': 'October 15', 'time': '2 to 5 pm'}
    ok = 'Open chairs Thursday 2 to 5 pm. Book your Classic cut online. #barber'
    assert op.check_caption(ok, facts, profile, words) is None
    assert op.check_caption('Open chairs Thursday 2 to 7 pm. Book online now.', facts, profile, words).startswith(
        'number not in the facts')
    assert op.check_caption('Two chairs open Thursday 2 to 5 pm. Book online.', facts, profile, words)
    assert op.check_caption('Open chairs Friday 2 to 5 pm. Book online today.', facts, profile, words) == \
        'names another day (Friday)'
    assert op.check_caption('Open chairs 2 to 5 pm this week. Book online.', facts, profile, words) == \
        'does not name its day'
    assert op.check_caption('Open chairs tomorrow, Thursday 2 to 5 pm. Book online.', facts, profile, words) == \
        'says today, tonight or tomorrow'
    assert op.check_caption('Open chairs Thursday 2 to 5 pm. #a #b #c #d', facts, profile, words) == \
        'more than 3 hashtags'
    assert op.check_caption(None, facts, profile, words) == 'missing'
    plain = op.plain_caption(words)
    assert plain == "Open chairs Thursday 2 to 5 pm. Book your time online and we'll see you then."
    assert op.check_caption(plain, facts, profile, words) is None
    copy_ = op.flyer_copy(words)
    assert copy_ == {'headline': 'Thursday 2 to 5 pm', 'line': 'Book your chair online.', 'cta': 'Book now'}
    assert op.check_flyer(copy_, facts, profile, words) is None


def test_the_most_booked_offering_else_the_shortest():
    offerings = [{'id': CUT, 'name': 'Classic cut', 'category': 'service', 'duration_min': 30},
                 {'id': BEARD, 'name': 'Beard trim', 'category': 'service', 'duration_min': 15},
                 {'id': str(uuid4()), 'name': 'Gift card', 'category': 'product', 'duration_min': None}]
    assert op.choose_offering(offerings, HISTORY) == (offerings[0], 'most_booked')
    # Bookings that name no offering (an older calendar), or name one no longer bookable: the shortest.
    assert op.choose_offering(offerings, [{'appointment_at': '2026-09-01T19:00:00Z', 'offering_id': None}] * 9) == \
        (offerings[1], 'shortest')
    assert op.choose_offering(offerings, [{'offering_id': offerings[2]['id']}] * 9) == (offerings[1], 'shortest')
    assert op.choose_offering(offerings, None) == (offerings[1], 'shortest_unread')
    assert op.choose_offering([offerings[2]], HISTORY) == (None, None)


# ── the week, planned ─────────────────────────────────────────────────

def test_the_open_chairs_week_is_planned_from_the_calendar(o):
    out = plan_boss(o)
    assert out['status'] == 'succeeded' and out['week_of'] == NEXT_MONDAY.isoformat()
    posts = boss_posts(o)
    assert len(posts) == 3 and {p['status'] for p in posts} == {'draft'}
    assert {p['source'] for p in posts} == {'opening'} and {p['play_id'] for p in posts} == {'open_chairs'}
    # The windows: Tuesday 2-5 pm, Thursday 2-3:30 pm, Saturday 10 am-1 pm, each posted the day before at 11.
    assert [p['opening']['when'] for p in posts] == ['Tuesday 2 to 5 pm', 'Thursday 2 to 3:30 pm',
                                                     'Saturday 10 am to 1 pm']
    assert [store._utc(p['run_at']) for p in posts] == [store._utc(at_utc(d, 11)) for d in (12, 14, 16)]
    first = posts[0]['opening']
    assert {k: first[k] for k in ('offering_id', 'open_count', 'duration_min', 'day', 'time_zone', 'gap_min')} == {
        'offering_id': CUT, 'open_count': 6, 'duration_min': 30, 'day': '2026-10-13', 'time_zone': 'America/Chicago',
        'gap_min': 120}
    assert first['starts_at'] == '2026-10-13T19:00:00Z' and first['ends_at'] == '2026-10-13T22:00:00Z'
    for p in posts:
        starts_at = datetime.fromisoformat(p['opening']['starts_at'].replace('Z', '+00:00'))
        assert datetime.fromisoformat(p['expires_at']) <= starts_at - timedelta(hours=2)
        assert [t['platform'] for t in p['targets']] == ['instagram', 'facebook']        # Instagram first
        assert p['landing_url'] == 'https://fade-lab.mysolutionist.app/book'
        assert p['link_code'] and p['link_code'] in p['publish_text']
        assert p['content_hash'] == store.digest(p) and p['design_status'] == 'ready' and p['media']['artwork_ids']
    # One caption call, metered to the business, no credits; the seat count was replaced by the plain caption.
    assert len(o.calls) == 1 and o.calls[0][1]['task'] == plan.OPENINGS_TASK and o.calls[0][1]['units'] == 0
    sent = json.loads(o.calls[0][0]['messages'][0]['content'])
    assert [s['opening']['time'] for s in sent['slots']] == ['2 to 5 pm', '2 to 3:30 pm', '10 am to 1 pm']
    assert posts[0]['caption'] == GOOD[0] and posts[2]['caption'] == GOOD[2]
    assert posts[1]['caption'] == "Open chairs Thursday 2 to 3:30 pm. Book your time online and we'll see you then."
    r = boss_run(o)
    assert r['kind'] == 'openings' and r['status'] == 'succeeded' and r['diagnosis']['rule'] == 'open_chairs'
    assert r['signals']['calendar']['offering_from'] == 'most_booked'
    assert r['dropped'] == [{'slot': 2, 'reason': 'a count of chairs or a claim that they are running out',
                             'plain': True}]
    assert 'still has open times on Monday, Tuesday, Wednesday, Thursday and Saturday' in r['diagnosis']['evidence']
    # The calendar was read strictly, for the most-booked offering, on the business's clock.
    call = o.slot_calls[0]
    assert call['strict'] is True and call['offering'] == CUT and call['tz'] == 'America/Chicago'
    assert (call['start'], call['end']) == (NEXT_MONDAY, NEXT_MONDAY + timedelta(days=6))
    # The owner is told once; nothing is approved or sent.
    items = [n for n in o.svc.notifications if n['business_id'] == BOSS]
    assert len(items) == 1 and items[0]['title'] == "Chief planned next week's open chairs: 3 posts wait for your OK"
    assert 'comes down by itself if its time books first' in items[0]['body']
    assert len([p for p in o.pushes if p['user'] == BOSS_OWNER]) == 1
    again = plan_boss(o)
    assert again['status'] == 'exists' and len(boss_posts(o)) == 3 and len(o.svc.notifications) == 1


def test_the_owners_newest_work_photo_carries_the_words_at_no_cost(o):
    o.db.desks[BOSS]['work_photo_ids'] = [OLD_PHOTO, NEW_PHOTO]
    plan_boss(o)
    posts = boss_posts(o)
    assert len(o.composed) == 3
    for made, photo in zip(o.composed, (NEW_PHOTO, OLD_PHOTO, NEW_PHOTO)):     # newest first, then round again
        layers = made['layout']['layers']
        assert made['layout']['width'] == 1080 and made['layout']['height'] == 1350               # 4:5
        assert layers[0] == {**layers[0], 'kind': 'image', 'image_id': photo, 'x': 0, 'y': 0, 'width': 1080,
                             'height': 1350, 'fit': 'cover'}                                       # its own pixels
        texts = [layer['text'] for layer in layers if layer['kind'] == 'text']
        assert texts[0] == 'OPEN CHAIRS' and 'FADE LAB' in texts
        assert all(layer['kind'] != 'image' for layer in layers[1:])
        panel = min(layer['y'] for layer in layers[1:] if layer['kind'] == 'shape')
        assert panel >= 1350 * 0.42 - 120                                       # the top of the photo stays clear
        assert made['actor'] == {'business_id': BOSS, 'user_id': BOSS_OWNER}
    assert 'TUESDAY 2 TO 5 PM' in [l['text'] for l in o.composed[0]['layout']['layers'] if l['kind'] == 'text']
    assert images.build_actor.get() is None
    pictures = boss_run(o)['design']['pictures']
    assert {p['picture'] for p in pictures.values()} == {'photo'} and {p['cost_usd'] for p in pictures.values()} == {0}
    assert [p['media']['artwork_ids'][0] for p in posts] == [str(uuid5(UUID(BOSS), f"chief-composition:{m['request_id']}"))
                                                             for m in o.composed]
    item = next(n for n in o.svc.notifications if n['business_id'] == BOSS)
    assert item['body'].startswith('Each shows one of your work photos.')


def test_without_a_work_photo_the_branded_flyer_and_it_says_so(o):
    o.db.desks[BOSS]['work_photo_ids'] = [str(uuid4())]                       # gone since: skipped
    plan_boss(o)
    assert len(o.composed) == 3
    for made in o.composed:
        assert not [layer for layer in made['layout']['layers'] if layer['kind'] == 'image']
        texts = [layer['text'] for layer in made['layout']['layers'] if layer['kind'] == 'text']
        assert texts[0] == 'OPEN CHAIRS' and 'THE SOLUTIONIST SYSTEM' not in texts
    assert {p['picture'] for p in boss_run(o)['design']['pictures'].values()} == {'flyer'}
    item = next(n for n in o.svc.notifications if n['business_id'] == BOSS)
    assert item['body'].startswith('They use your brand flyer; add work photos on the desk')


def test_a_photo_that_cannot_be_placed_falls_back_to_the_flyer(o, monkeypatch):
    o.db.desks[BOSS]['work_photo_ids'] = [NEW_PHOTO]
    real = composer.compose

    async def compose(client, biz, action, request_id):
        if any(layer.get('kind') == 'image' for layer in action['layout']['layers']):
            raise HTTPException(404, 'Image not found')
        return await real(client, biz, action, request_id)
    monkeypatch.setattr(composer, 'compose', compose)
    plan_boss(o)
    assert len(boss_posts(o)) == 3 and {p['design_status'] for p in boss_posts(o)} == {'ready'}
    pictures = boss_run(o)['design']['pictures']
    assert {p['picture'] for p in pictures.values()} == {'flyer'}
    assert pictures['1']['failed'][0]['what'] == 'photo'


def test_a_failed_calendar_read_fails_the_run_and_writes_nothing(o):
    o.slots_error = HTTPException(503, 'the bookings could not be read')
    out = plan_boss(o)
    assert out['status'] == 'failed' and out['reason'] == plan.READ_FAILED
    assert boss_posts(o) == [] and o.calls == [] and not [n for n in o.svc.notifications if n['business_id'] == BOSS]
    o.slots_error = None
    o.svc.fail = ('/offerings',)
    o.now += timedelta(hours=1)
    assert plan_boss(o)['status'] == 'failed' and boss_posts(o) == []        # the retry the claim allows


@pytest.mark.parametrize('setup,reason', [
    (lambda s: s.open_local.clear(), plan.CALENDAR_FULL),
    (lambda s: s.svc.businesses[BOSS]['settings'].update(availability={'timezone': 'America/Chicago'}), plan.NO_HOURS),
    (lambda s: [o_.update(is_active=False) for o_ in s.svc.offerings], plan.NOTHING_BOOKABLE),
    (lambda s: setattr(s.svc, 'connections', [c for c in s.svc.connections if not (c['business_id'] == BOSS)]
                       + [connection(str(uuid4()), 'linkedin', biz=BOSS)]), plan.NO_CHAIR_ACCOUNTS),
])
def test_what_leaves_the_week_unwritten(o, setup, reason):
    setup(o)
    out = plan_boss(o)
    assert out['status'] == 'skipped' and out['reason'] == reason
    assert boss_posts(o) == [] and boss_run(o)['error'] == reason


def test_the_history_unread_falls_back_to_the_shortest_offering(o):
    o.svc.fail = ('/module_entries',)
    plan_boss(o)
    assert o.slot_calls[0]['offering'] == BEARD and o.slot_calls[0]['duration'] == 15
    assert boss_run(o)['signals']['calendar']['offering_from'] == 'shortest_unread'
    assert {p['opening']['offering_id'] for p in boss_posts(o)} == {BEARD}


def test_the_writer_down_still_writes_the_plain_captions(o, monkeypatch):
    import llm_call

    async def down(*a, **k):
        raise RuntimeError('overloaded')
    monkeypatch.setattr(llm_call, 'apost', down)
    plan_boss(o)
    assert [p['caption'].split('.')[0] for p in boss_posts(o)] == [
        'Open chairs Tuesday 2 to 5 pm', 'Open chairs Thursday 2 to 3:30 pm', 'Open chairs Saturday 10 am to 1 pm']


# ── the work photos the desk accepts ──────────────────────────────────

def put(s, body, biz=BOSS):
    return s.client.put(f'/marketing/{biz}/settings', json=body)


def test_settings_take_work_photos_newest_first(o):
    o.user = BOSS_OWNER
    r = put(o, {'work_photo_ids': [OLD_PHOTO, NEW_PHOTO, OLD_PHOTO]})
    assert r.status_code == 200, r.text
    assert r.json()['desk']['work_photo_ids'] == [NEW_PHOTO, OLD_PHOTO]
    assert o.db.desks[BOSS]['work_photo_ids'] == [NEW_PHOTO, OLD_PHOTO]
    assert put(o, {'work_photo_ids': []}).json()['desk']['work_photo_ids'] == []


@pytest.mark.parametrize('setup,code,detail', [
    (lambda s: s.svc.images.append({'id': 'e0000000-0000-4000-8000-0000000000ff', 'business_id': PRO,
                                     'status': 'ready', 'storage_path': 'x.png', 'created_at': '2026-10-01T00:00:00Z',
                                     'model': None, 'size': None}), 404, op.NOT_HERE),
    (lambda s: s.svc.images.append({'id': 'e0000000-0000-4000-8000-0000000000ff', 'business_id': BOSS,
                                     'status': 'working', 'storage_path': None, 'created_at': '2026-10-01T00:00:00Z',
                                     'model': None, 'size': None}), 409, op.NOT_READY),
    (lambda s: s.svc.images.append({'id': 'e0000000-0000-4000-8000-0000000000ff', 'business_id': BOSS,
                                     'status': 'failed', 'storage_path': None, 'created_at': '2026-10-01T00:00:00Z',
                                     'model': None, 'size': None}), 409, op.NOT_FINISHED),
    (lambda s: s.svc.images.append({'id': 'e0000000-0000-4000-8000-0000000000ff', 'business_id': BOSS,
                                     'status': 'ready', 'storage_path': 'x.png', 'created_at': '2026-10-01T00:00:00Z',
                                     'model': 'gpt-image-2', 'size': '1024x1024'}), 422, op.NOT_A_PHOTO),
])
def test_settings_refuse_a_photo_that_is_not_this_businesss_ready_upload(o, setup, code, detail):
    o.user = BOSS_OWNER
    setup(o)
    before = copy.deepcopy(o.db.desks[BOSS])
    r = put(o, {'work_photo_ids': [NEW_PHOTO, 'e0000000-0000-4000-8000-0000000000ff']})
    assert r.status_code == code and r.json()['detail'] == detail
    assert o.db.desks[BOSS] == before


def test_settings_refuse_too_many_photos_a_failed_read_and_a_member(o):
    o.user = BOSS_OWNER
    seen = len([p for p in o.svc.reads if p.startswith('/image_artworks')])
    r = put(o, {'work_photo_ids': [str(uuid4()) for _ in range(13)]})
    assert r.status_code == 422 and len([p for p in o.svc.reads if p.startswith('/image_artworks')]) == seen
    o.svc.fail = ('/image_artworks',)
    r = put(o, {'work_photo_ids': [NEW_PHOTO]})
    assert r.status_code == 503 and r.json()['detail'] == op.PHOTOS_DOWN
    o.svc.fail = ()
    o.user = MEMBER
    assert put(o, {'work_photo_ids': [NEW_PHOTO]}).status_code == 403
    assert o.db.desks[BOSS].get('work_photo_ids') in (None, [])


# ── the pull ──────────────────────────────────────────────────────────

SUNDAY = at_utc(11, 13)          # Sunday 1 PM: Tuesday's post (Monday 11:00) is inside the next 48 hours


def planned(s):
    plan_boss(s)
    s.now = SUNDAY
    return copy.deepcopy(boss_posts(s))


def test_the_watch_pulls_a_post_whose_window_was_booked_and_tells_once(o):
    tue, thu, sat = planned(o)
    o.db.posts[thu['id']]['status'] = 'approved'
    o.open_local.discard(local(13, 15))                                        # someone booked Tuesday at 3
    before = len(o.svc.notifications)
    out = run(plan.openings_watch_tick(o.now))
    assert out['pulled'] == 1 and out['told'] == 1
    pulled = o.db.posts[tue['id']]
    assert pulled['status'] == 'pulled' and pulled['revision'] == tue['revision'] + 1
    assert pulled['opening']['pulled']['why'] == 'fewer' and 'Nothing needs your OK' in pulled['error']
    assert pulled['content_hash'] == tue['content_hash']                       # nothing about the post itself changed
    items = o.svc.notifications[before:]
    assert [i['title'] for i in items] == ['Tuesday 2 to 5 pm was booked into, so its post was pulled']
    assert items[0]['action_payload']['dedup_key'] == f"marketing_opening:{tue['id']}"
    assert o.pushes[-1]['user'] == BOSS_OWNER and o.pushes[-1]['nav'] == 'grow:marketing'
    # Thursday's post is 70 hours out: not watched yet. Saturday's likewise.
    assert o.db.posts[thu['id']]['status'] == 'approved' and o.db.posts[sat['id']]['status'] == 'draft'
    again = run(plan.openings_watch_tick(o.now + timedelta(minutes=15)))
    assert again.get('told', 0) == 0 and len(o.svc.notifications) == before + 1
    # Thursday fills up completely two days later: "filled up".
    o.now = at_utc(13, 13)
    for t in starts(15, 14, 15):
        o.open_local.discard(t)
    out = run(plan.openings_watch_tick(o.now))
    assert out['pulled'] == 1 and o.db.posts[thu['id']]['status'] == 'pulled'
    assert o.svc.notifications[-1]['title'] == 'Thursday 2 to 3:30 pm filled up, so its post was pulled'


def test_a_window_still_open_is_left_alone_and_the_watch_reads_strictly(o):
    tue, _, _ = planned(o)
    o.slot_calls.clear()
    out = run(plan.openings_watch_tick(o.now))
    assert out == {'open': 1, 'told': 0}
    assert o.db.posts[tue['id']]['status'] == 'draft'
    assert o.slot_calls == [{'offering': CUT, 'duration': 30, 'start': date(2026, 10, 13), 'end': date(2026, 10, 13),
                             'strict': True, 'tz': 'America/Chicago', 'now': o.now, 'business': BOSS}]


@pytest.mark.parametrize('how', ['slots', 'business'])
def test_a_failed_calendar_read_changes_nothing_in_the_watch(o, how):
    tue, _, _ = planned(o)
    o.open_local.clear()                                                      # everything booked...
    if how == 'slots':
        o.slots_error = HTTPException(503, 'the bookings could not be read')
    else:
        o.svc.fail = ('select=id,availability',)
    before = copy.deepcopy(o.db.posts)
    out = run(plan.openings_watch_tick(o.now))
    assert out['unreadable'] == 1 and o.db.posts == before                    # ...but it could not be read
    assert not [n for n in o.svc.notifications if 'pulled' in n['title']]


def test_the_watch_does_nothing_unless_the_desk_covers_the_business(o, monkeypatch):
    planned(o)
    o.open_local.clear()
    monkeypatch.setenv('MARKETING_DESK', 'off')
    assert run(plan.openings_watch_tick(o.now)) == {'skipped': 'off'}
    monkeypatch.setenv('MARKETING_DESK', PRO)
    assert run(plan.openings_watch_tick(o.now)) == {'told': 0}
    assert {p['status'] for p in boss_posts(o)} == {'draft'}


def claimed(s, post):
    row = s.db.posts[post['id']]
    row.update(status='dispatching', approved_hash=row['content_hash'], approved_by=BOSS_OWNER,
               approved_via='owner', claimed_at=s.now.isoformat())
    return copy.deepcopy(row)


@pytest.fixture
def sender(o, monkeypatch):
    monkeypatch.setattr(dispatch, 'now', lambda: o.now)

    def reached(business_id):
        raise dispatch.Hold('the opening check passed', note='REACHED THE SEND')
    monkeypatch.setattr(dispatch, '_owner_of', reached)
    return o


def test_the_sender_pulls_a_post_whose_window_filled_just_before_sending(sender):
    o = sender
    tue, _, _ = planned(o)
    o.now = at_utc(12, 11, 1)                                                 # Monday, its time
    for t in starts(13, 14, (16, 30)):
        o.open_local.discard(t)
    patch = run(dispatch.dispatch(claimed(o, tue)))
    assert patch['status'] == 'pulled' and patch['claimed_at'] is None
    row = o.db.posts[tue['id']]
    assert row['status'] == 'pulled' and row['opening']['pulled']['why'] == 'full'
    out = run(plan.openings_watch_tick(o.now))                                # the watch tells the owner, once
    assert out['told'] == 1 and o.svc.notifications[-1]['title'] == 'Tuesday 2 to 5 pm filled up, so its post was pulled'


def test_the_sender_holds_a_post_whose_calendar_cannot_be_read(sender):
    o = sender
    tue, _, _ = planned(o)
    o.now = at_utc(12, 11, 1)
    o.slots_error = HTTPException(503, 'the bookings could not be read')
    patch = run(dispatch.dispatch(claimed(o, tue)))
    assert patch == {'status': 'approved', 'claimed_at': None, 'error': dispatch.CHAIRS_UNCHECKED}
    assert o.db.posts[tue['id']]['status'] == 'approved'
    # Readable and still open: it goes on to send (here, the next check after it).
    o.slots_error = None
    patch = run(dispatch.dispatch(claimed(o, tue)))
    assert patch['error'] == 'REACHED THE SEND'


def test_the_sender_pulls_a_post_moved_too_close_to_its_window(sender):
    o = sender
    tue, _, _ = planned(o)
    o.now = at_utc(13, 12, 30)                                                # Tuesday 12:30: 90 minutes before 2 pm
    moved = o.db.posts[tue['id']]                                             # the owner moved it, and approved it again
    moved['expires_at'] = (o.now + timedelta(hours=3)).isoformat()
    moved['content_hash'] = store.digest(moved)
    patch = run(dispatch.dispatch(claimed(o, tue)))
    assert patch['status'] == 'pulled' and o.db.posts[tue['id']]['opening']['pulled']['why'] == 'late'


def test_the_sender_refuses_an_opening_post_without_its_opening(sender):
    o = sender
    tue, _, _ = planned(o)
    o.now = at_utc(12, 11, 1)
    row = claimed(o, tue)
    row['opening'] = {'when': 'Tuesday'}
    assert run(dispatch.dispatch(row)) == {'status': 'failed', 'error': dispatch.OPENING_UNREADABLE}


def test_other_posts_are_sent_without_a_calendar_read(sender):
    o = sender
    o.svc.connections.append(connection(str(uuid4()), 'facebook', biz=PRO))
    row = {'id': str(uuid4()), 'business_id': PRO, 'source': 'plan', 'revision': 1, 'caption': 'Words here for all.',
           'publish_text': 'Words here for all.', 'landing_url': None, 'media': {}, 'opening': None,
           'targets': [{'connection_id': str(uuid4()), 'platform': 'facebook', 'provider_account_id': 'x'}],
           'run_at': o.now.isoformat(), 'expires_at': (o.now + timedelta(hours=6)).isoformat(), 'status': 'dispatching'}
    row['content_hash'] = row['approved_hash'] = store.digest(row)
    o.db.posts[row['id']] = copy.deepcopy(row)
    o.slot_calls.clear()
    assert run(dispatch.dispatch(row))['error'] == 'REACHED THE SEND' and o.slot_calls == []


# ── the fan-out, the owner's request, the preview ─────────────────────

def test_the_fan_out_plans_the_open_chairs_with_the_same_safety_rules(o, monkeypatch):
    tick_at = THU + timedelta(hours=3)
    o.share = plan.HEADROOM_SHARE                                             # today's spend at 60% of the cap
    assert run(plan.marketing_tick(tick_at)) == {'deferred': 'platform spend'} and boss_posts(o) == []
    o.share = 0.0
    monkeypatch.setenv('POST_FOR_ME_PILOT_BUSINESSES', PRO)                   # the pilot is off for Boss
    out = run(plan.marketing_tick(tick_at))
    assert 'openings_succeeded' not in out and boss_posts(o) == []
    monkeypatch.setenv('POST_FOR_ME_PILOT_BUSINESSES', '*')
    o.over = {BOSS}                                                           # Boss over its own ceiling
    out = run(plan.marketing_tick(tick_at))
    assert out['over_budget'] == 1 and boss_posts(o) == []
    o.over = set()
    out = run(plan.marketing_tick(tick_at))
    assert out['openings_succeeded'] == 1 and len(boss_posts(o)) == 3
    assert run(plan.marketing_tick(tick_at + timedelta(hours=1))).get('openings_succeeded') is None   # claimed once
    # Never overnight, and only from Thursday 7:00 + the business's jitter.
    assert plan.due_week(datetime(2026, 10, 9, 3, 0, tzinfo=UTC), CHICAGO, BOSS) is None


def test_the_fan_out_leaves_boss_out_while_the_desk_names_only_others(o, monkeypatch):
    monkeypatch.setenv('MARKETING_DESK', PRO)
    run(plan.marketing_tick(THU + timedelta(hours=3)))
    assert boss_posts(o) == [] and not [r for r in o.db.runs.values() if r['business_id'] == BOSS]


def ask(s, biz=BOSS):
    return s.client.post(f'/marketing/{biz}/engine/run')


def test_the_owner_asks_for_the_open_chairs_and_a_replan_keeps_the_old_until_the_new_is_saved(o):
    o.user = BOSS_OWNER
    r = ask(o)
    assert r.status_code == 202, r.text
    assert r.json()['kind'] == 'openings' and r.json()['message'] == plan.OPENINGS_QUEUED
    assert boss_posts(o) == [] and o.calls == []                              # the web process wrote nothing
    out = run(plan.manual_tick(o.now))
    assert out == {'openings_succeeded': 1}
    first = boss_posts(o)
    assert len(first) == 3
    # Saturday books up; the owner asks again: the new week is saved, then the old drafts go.
    for t in starts(17, 10, (12, 30)):
        o.open_local.discard(t)
    o.now += timedelta(minutes=5)
    assert ask(o).status_code == 202
    run(plan.manual_tick(o.now))
    live = boss_posts(o, 'draft')
    assert len(live) == 3 and not {p['id'] for p in live} & {p['id'] for p in first}
    assert {o.db.posts[p['id']]['status'] for p in first} == {'cancelled'}
    assert 'Saturday 10 am to 1 pm' not in [p['opening']['when'] for p in live]
    r = boss_run(o)
    assert r['design']['replans'] == 1 and set(r['design']['replaced']) == {p['id'] for p in first}
    # Once a post is approved the week is the owner's: no replan.
    o.db.posts[live[0]['id']]['status'] = 'approved'
    o.now += timedelta(minutes=5)
    r = ask(o)
    assert r.status_code == 409 and r.json()['detail'] == plan.WEEK_BUSY


def test_a_pulled_post_does_not_hold_the_week_and_replans_stop_at_two(o):
    o.user = BOSS_OWNER
    plan_boss(o)
    tue = boss_posts(o)[0]
    o.db.posts[tue['id']]['status'] = 'pulled'
    for n in range(2):
        o.now += timedelta(minutes=5)
        assert ask(o).status_code == 202
        run(plan.manual_tick(o.now))
    o.now += timedelta(minutes=5)
    r = ask(o)
    assert r.status_code == 429 and r.json()['detail'] == plan.REPLANNED_TWICE


def test_a_request_that_writes_nothing_keeps_the_earlier_week(o):
    o.user = BOSS_OWNER
    plan_boss(o)
    first = boss_posts(o)
    o.now += timedelta(minutes=5)
    assert ask(o).status_code == 202
    o.slots_error = HTTPException(503, 'the bookings could not be read')
    run(plan.manual_tick(o.now))
    assert [p['status'] for p in boss_posts(o)] == ['draft'] * 3 and boss_posts(o) == first
    r = boss_run(o)
    assert r['status'] == 'succeeded' and r['design']['outcome'] == 'kept'
    assert r['error'] == f'{plan.READ_FAILED} {plan.OPENINGS_KEPT}'


def test_the_preview_shows_the_open_chairs_and_writes_nothing(o):
    o.user = BOSS_OWNER
    r = o.client.get(f'/marketing/{BOSS}/preview')
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['level'] == 'openings'
    chairs = body['openings']
    assert chairs['state'] == 'ok' and chairs['offering'] == 'Classic cut' and chairs['offering_from'] == 'most_booked'
    assert [w_['when'] for w_ in chairs['windows']] == ['Tuesday 2 to 5 pm', 'Thursday 2 to 3:30 pm',
                                                       'Saturday 10 am to 1 pm']
    assert o.db.writes == [] and o.composed == [] and o.calls == []


def test_the_professional_preview_has_no_open_chairs(o):
    o.user = PRO_OWNER
    body = o.client.get(f'/marketing/{PRO}/preview').json()
    assert body['level'] == 'week' and 'openings' not in body


# ── the shared slot computation ───────────────────────────────────────

def test_slots_for_reads_the_booked_length_and_strict_never_counts_a_failed_read_as_free(monkeypatch):
    importlib_av = {'timezone': 'America/Chicago', 'slot_granularity_min': 30,
                    'weekly': {'thu': [{'start': '14:00', 'end': '16:00'}]}}
    bundle = {'facts': {'id': BOSS, 'availability': importlib_av, 'timezone': 'America/Chicago'}}
    reads = []
    booking = {'appointment_at': '2026-10-15T19:30:00+00:00', 'duration_min_at_booking': None, 'booked_min': '60'}

    def get(path):
        reads.append(path)
        return [dict(booking)]
    monkeypatch.setattr(sb_clients, 'sb_get_as_service', get)
    monkeypatch.setattr(outside_calendar, 'busy_blocks_between', lambda *a, strict=False: [])
    now = datetime(2026, 10, 8, 15, 0, tzinfo=UTC)
    slots = agent_site.slots_for(bundle, {'id': CUT, 'duration_min': 30}, date(2026, 10, 15), date(2026, 10, 15),
                                 strict=True, now=now)
    # 2:30-3:30 pm is booked (its length is in data): 2:00 is free, 2:30 and 3:00 are not, 3:30 is.
    assert [s['start_local'][11:16] for s in slots] == ['14:00', '15:30']
    assert 'select=appointment_at,duration_min_at_booking,booked_min:data->>duration_min_at_booking' in reads[0]
    assert ',duration_min&' not in reads[0]                                   # a column module_entries does not have

    monkeypatch.setattr(sb_clients, 'sb_get_as_service', lambda path: None)
    with pytest.raises(HTTPException) as err:
        agent_site.slots_for(bundle, {'id': CUT, 'duration_min': 30}, date(2026, 10, 15), date(2026, 10, 15),
                             strict=True, now=now)
    assert err.value.status_code == 503
    # Not strict (the agent surface, the concierge): unchanged, a failed read still answers.
    loose = agent_site.slots_for(bundle, {'id': CUT, 'duration_min': 30}, date(2026, 10, 15), date(2026, 10, 15),
                                 now=now)
    assert len(loose) == 4

    monkeypatch.setattr(sb_clients, 'sb_get_as_service', lambda path: [{}] * agent_site.BOOKING_ROWS)
    with pytest.raises(HTTPException):
        agent_site.slots_for(bundle, {'id': CUT, 'duration_min': 30}, date(2026, 10, 15), date(2026, 10, 15),
                             strict=True, now=now)


def test_a_strict_outside_calendar_read_raises_unless_the_feature_is_not_set_up(monkeypatch):
    lo, hi = datetime(2026, 10, 15, tzinfo=UTC), datetime(2026, 10, 16, tzinfo=UTC)
    monkeypatch.setattr(outside_calendar, '_absent_until', 0.0)
    monkeypatch.setattr(outside_calendar, '_rest', lambda *a, **k: (0, None))
    assert outside_calendar.busy_blocks_between(BOSS, lo, hi) == []
    with pytest.raises(outside_calendar.BusyUnavailable):
        outside_calendar.busy_blocks_between(BOSS, lo, hi, strict=True)
    monkeypatch.setattr(outside_calendar, '_rest', lambda *a, **k: (200, [{'starts_at': 'a', 'ends_at': 'b'}]))
    assert len(outside_calendar.busy_blocks_between(BOSS, lo, hi, strict=True)) == 1

    def missing(*a, **k):
        outside_calendar._mark_absent()
        return 404, None
    monkeypatch.setattr(outside_calendar, '_rest', missing)
    assert outside_calendar.busy_blocks_between(BOSS, lo, hi, strict=True) == []   # not set up: nothing is busy


# ── the job ───────────────────────────────────────────────────────────

APP = (ROOT / 'kmj_intake_automation.py').read_text(encoding='utf-8')


def test_the_watch_is_registered_leader_gated_every_15_minutes():
    startup = APP.index('async def startup')
    started = APP.index('if runs_scheduled_jobs():\n        scheduler.start()')
    at = APP.index('g("business_marketing_openings_watch", _marketing_planner.openings_watch_tick)')
    assert startup < at < started
    call = APP[at:APP.index('\n', APP.index('id="business_marketing_openings_watch"'))]
    assert 'minutes=15' in call and 'max_instances=1' in call
    assert APP.index('g("business_marketing_designs"') < at                  # beside the other marketing jobs


def test_the_ticks_take_no_arguments_from_the_scheduler(monkeypatch):
    monkeypatch.setenv('MARKETING_DESK', 'off')
    assert run(plan.openings_watch_tick()) == {'skipped': 'off'}
