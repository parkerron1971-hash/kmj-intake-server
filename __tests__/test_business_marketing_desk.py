"""Where one business's marketing stands, said plainly (business_marketing_desk).

Every assertion is a sentence the owner reads, on the business's own clock.
No network: rows are built here, and read_state runs against a fake store.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import business_marketing_desk as d
import business_marketing_store as store
import marketing_desk

LONDON = ZoneInfo('Europe/London')
BIZ = '0a1b2c3d-4e5f-4a6b-8c7d-8e9f0a1b2c3d'
NOW = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)                # Wednesday 10:00 BST
FB = {'connection_id': 'c0000000-0000-4000-8000-000000000002', 'platform': 'facebook', 'username': 'fade',
      'provider_account_id': 'spc_fb'}
IG = {'connection_id': 'c0000000-0000-4000-8000-000000000001', 'platform': 'instagram', 'username': 'fade',
      'provider_account_id': 'spc_ig'}
ACCOUNTS = [{'id': IG['connection_id'], 'platform': 'instagram'}, {'id': FB['connection_id'], 'platform': 'facebook'}]


def at(day, hour, minute=0, month=10):
    return datetime(2026, month, day, hour, minute, tzinfo=LONDON).astimezone(timezone.utc)


def post(day, hour=11, status='draft', targets=(FB,), caption=None, error=None, run_id=None, month=10):
    when = at(day, hour, month=month)
    return {'id': str(uuid4()), 'business_id': BIZ, 'revision': 1, 'status': status, 'source': 'owner',
            'caption': caption or f'Post for day {day}.', 'targets': list(targets), 'media': {},
            'run_at': when.isoformat(), 'expires_at': (when + timedelta(hours=6)).isoformat(),
            'run_id': run_id, 'play_id': None, 'error': error, 'content_hash': 'a' * 64}


def state(posts=(), runs=(), desk=None, connections=ACCOUNTS, now=NOW, next_run=None):
    return {'business_id': BIZ, 'now': now, 'tz': LONDON, 'runs': list(runs) if runs is not None else None,
            'posts': list(posts) if posts is not None else None, 'desk': {} if desk is None else desk,
            'connections': connections, 'next_run': next_run, 'unreadable': []}


def kinds(s):
    return [i['kind'] for i in d.attention(d.facts(s))]


# ── the business's clock ──────────────────────────────────────────────

def test_times_are_said_on_the_business_clock():
    s = state([post(9, 11)])
    note = d.note(d.facts(s))
    assert note['headline'] == 'One post waits for your OK.'
    assert note['body'][0] == "Friday's goes out at 11:00 AM once you approve it."      # 10:00Z, said in BST
    assert marketing_desk.clock(at(9, 11)) == '6:00 AM'                                 # the platform's Eastern


def test_the_platform_wording_defaults_are_unchanged():
    when = '2026-10-09T15:00:00+00:00'
    assert marketing_desk.clock(when) == marketing_desk.clock(when, None) == '11:00 AM'
    assert marketing_desk.day_name(when, LONDON) == 'Friday' and marketing_desk.clock(when, LONDON) == '4:00 PM'
    assert marketing_desk.span([{'run_at': when}]) == 'October 9'


# ── what needs a look ─────────────────────────────────────────────────

def test_waiting_posts_and_missed_ones_are_counted_apart():
    s = state([post(8), post(9), post(6, caption='Missed one.'), post(5, caption='Missed too.')])
    f = d.facts(s)
    assert len(f['waiting']) == 2 and len(f['missed']) == 2
    missed = next(i for i in d.attention(f) if i['kind'] == 'missed')
    assert missed['title'] == 'Two posts from this week missed their time'
    assert missed['slots'][0]['items'] == [{'id': s['posts'][3]['id'], 'revision': 1}]
    assert set(d.desk(s)['attention'][0]['slots'][0]) == {'key', 'run_at', 'channels', 'text', 'items'}
    head = d.masthead(f)
    assert (head['title'], head['accent']) == ('Two posts', 'need your OK.')
    assert head['sub'] == "Approve by Thursday 11:00 AM and Thursday's post goes out on time."


def test_a_failed_post_is_red_and_carries_the_services_words():
    s = state([post(9, status='approved'), post(6, status='failed', targets=(FB, IG),
                                                error='The posting service did not accept it.')])
    item = d.attention(d.facts(s))[0]
    assert item['kind'] == 'failed' and item['tone'] == 'red'
    assert item['title'] == "A post didn't go out on Facebook and Instagram"
    assert d.note(d.facts(s))['tone'] == 'attention'


def test_an_unconfirmed_delivery_says_how_to_settle_it():
    item = d.attention(d.facts(state([post(6, status='uncertain')])))[0]
    assert item['kind'] == 'uncertain' and item['title'] == 'One post may or may not have gone out'
    assert item['detail'] == ('Sending was interrupted. Check your accounts; if it is not there, mark it not sent '
                              'and give it a new time.')
    assert 'Buffer' not in item['detail']


def test_a_post_that_went_out_on_only_some_accounts_is_named():
    item = d.attention(d.facts(state([post(6, status='partly_published', targets=(FB, IG))])))[0]
    assert item['kind'] == 'partly' and item['title'] == 'A post went out on only some of Facebook and Instagram'


def test_paused_posting_holding_approved_posts_is_named():
    s = state([post(9, status='approved'), post(12, status='approved')], desk={'paused': True})
    item = d.attention(d.facts(s))[0]
    assert item['kind'] == 'paused' and item['detail'] == 'Two approved posts will not go out until you resume it.'


def test_no_accounts_asks_for_one_and_never_reads_as_quiet():
    s = state(connections=[])
    assert kinds(s) == ['connect']
    today = d.today_items(s)
    assert today[0]['action'] == {'label': 'Connect an account', 'nav': 'build:social-media'}


def test_nothing_going_out_is_quiet_and_promises_no_plan():
    s = state([post(20, status='approved')])                       # 13 days out: not in the next 7
    quiet = d.attention(d.facts(s))[0]
    assert quiet['kind'] == 'quiet' and quiet['title'] == 'Nothing is going out in the next 7 days'
    assert quiet['detail'] == 'Write a post and it takes the next open time, or ask Chief to draft one.'
    assert 'Thursday' not in repr(d.desk(s))
    planned = d.attention(d.facts(state(next_run=at(8, 7).isoformat())))[0]
    assert planned['detail'].endswith("Next week's plan is written Thursday at 7:00 AM.")


def test_unreadable_posts_never_read_as_nothing_to_do():
    s = state(posts=None)
    f = d.facts(s)
    assert not f['readable'] and d.attention(f) == [] and d.today_items(s) == []
    assert d.note(f)['headline'] == "The posts couldn't be read just now."
    unread_desk = state([post(9, status='approved')], desk=None)
    unread_desk['desk'] = None
    assert d.facts(unread_desk)['paused'] is None


# ── Chief's read, Today and the digest ────────────────────────────────

def test_nothing_lined_up_says_so_and_offers_to_write():
    note = d.note(d.facts(state()))
    assert note['headline'] == 'Nothing is lined up to go out yet.'
    assert 'Write a post for this week' in note['quick_replies']
    assert d.masthead(d.facts(state()))['accent'] == 'lined up yet.'


def test_approved_posts_read_as_ready():
    f = d.facts(state([post(9, status='approved')]))
    assert d.note(f)['headline'] == 'One post is ready to go out.'
    assert d.note(f)['body'][0] == 'The next goes out Friday at 11:00 AM.'
    assert d.masthead(f)['title'] == 'Ready'


def test_today_names_the_business_and_never_approves():
    s = state([post(7, hour=15), post(9)])
    items = d.today_items(s)
    assert items[0]['id'] == f'marketing:{BIZ}:waiting' and items[0]['title'] == 'Two posts wait for your OK'
    assert items[0]['tone'] == 'amber'                                     # today at 3 PM: under a day away
    assert items[0]['detail'].startswith("Wednesday's goes out at 3:00 PM if you approve it by then.")
    assert items[0]['action'] == {'label': 'Review the posts', 'nav': 'grow:marketing'}


def test_the_digest_says_what_marketing_waits_on():
    digest = d.chief_digest(state([post(8), post(6, status='failed', error='Refused.')]))
    assert digest['posts_waiting_for_approval'] == 1 and digest['first_waiting_goes_out'] == 'Thursday 11:00 AM'
    assert digest['time_zone'] == 'Europe/London' and digest['accounts'] == ['Instagram', 'Facebook']
    assert digest['needs_owner'][0] == 'One post waits for your OK'
    assert any(n.startswith("A post didn't go out on Facebook: Refused.") for n in digest['needs_owner'])
    assert 'never approve for the owner' in ' '.join(d.DIGEST_PROMPT.split())


def test_a_written_plan_reads_like_the_platform_desk():
    run_id = str(uuid4())
    run = {'id': run_id, 'week_of': '2026-10-12', 'status': 'succeeded', 'created_at': at(8, 7).isoformat(),
           'finished_at': at(8, 7, 3).isoformat(),
           'diagnosis': {'headline': 'The chairs are quiet on Tuesdays.', 'evidence': 'Two bookings last Tuesday.',
                         'urgency': 'low'}}
    s = state([post(12, run_id=run_id), post(14, run_id=run_id)], runs=[run], now=at(8, 9))
    f = d.facts(s)
    assert f['which_week'] == 'next week'
    head = d.masthead(f)
    assert head['kicker'] == 'GROW · MARKETING · WEEK OF OCTOBER 12' and head['accent'] == 'drafted.'
    assert head['sub'].startswith('Chief planned October 12–14 on Thursday morning: two posts on Facebook.')
    note = d.note(f)
    assert note['headline'] == 'The chairs are quiet on Tuesdays.' and note['body'][0] == 'Two bookings last Tuesday.'
    assert d.today_items(s)[0]['title'] == 'Chief drafted next week. Two posts wait for your OK'


def test_weeks_split_on_the_business_clock():
    late = post(11, hour=23)                                          # Sunday 23:00 BST is Sunday 22:00Z
    s = state([post(5), late, post(12), post(25)])
    w = d.weeks(s)
    assert w['this_week']['week_of'] == '2026-10-05' and len(w['this_week']['posts']) == 2
    assert [p['id'] for p in w['next_week']['posts']] == [s['posts'][2]['id']]
    assert w['this_week']['posts'][0]['targets'] == [{'connection_id': FB['connection_id'], 'platform': 'facebook',
                                                       'label': 'Facebook', 'username': 'fade'}]


# ── reading the rows ──────────────────────────────────────────────────

class Store:
    def __init__(self, fail=()):
        self.fail, self.paths = fail, []

    async def request(self, method, path, body=None):
        self.paths.append(path)
        assert '+' not in path.split('?', 1)[1]
        if any(f in path for f in self.fail):
            raise store.StoreUnavailable('down')
        return []


def test_read_state_is_strict_for_the_desk_and_says_what_it_could_not_read(monkeypatch):
    fake = Store(fail=('/marketing_posts',))
    monkeypatch.setattr(store, 'request', fake.request)
    with pytest.raises(store.StoreUnavailable):
        asyncio.run(d.read_state(BIZ, tz=LONDON, now=NOW))
    soft = asyncio.run(d.read_state(BIZ, tz=LONDON, now=NOW, strict=False))
    assert soft['posts'] is None and soft['unreadable'] == ['posts'] and soft['desk'] == {} and soft['runs'] == []
    posts = next(p for p in fake.paths if p.startswith('/marketing_posts'))
    assert f'business_id=eq.{BIZ}' in posts and 'or=(run_at.gte.2026-09-16T09:00:00Z,status.eq.uncertain)' in posts
    assert 'status=neq.cancelled' in posts


def test_a_failed_digest_read_is_not_an_empty_desk(monkeypatch):
    monkeypatch.setattr(store, 'request', Store(fail=('/marketing_posts', '/marketing_desks')).request)
    digest = asyncio.run(d.digest(BIZ, LONDON, connections=ACCOUNTS))
    assert digest['posts_readable'] is False and digest['posting_paused'] is None
    assert digest['needs_owner'] == []
