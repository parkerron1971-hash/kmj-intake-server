"""Where Solutionist's marketing stands, said plainly (marketing_desk).

The fixture is the live desk of 2026-10-02: next week (October 5–9) drafted on
Thursday morning as five posts on Instagram, X and Facebook, none approved, and
this week's drafts that nobody approved and that missed their time. No network:
every row is built here, and every assertion is a sentence the owner reads.
"""
import asyncio
import copy
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import pytest
from fastapi import HTTPException

import marketing_desk as d
import marketing_engine as e
import platform_marketing as m

ET = d.TZ


def run(coro):
    return asyncio.run(coro)


def at(y, mo, day, h, mi=0):
    return datetime(y, mo, day, h, mi, tzinfo=ET).astimezone(timezone.utc)


NOW = at(2026, 10, 2, 14)                      # Friday afternoon
NEXT = '2026-10-05'
RUN_ID = str(e.run_id_for(datetime(2026, 10, 5).date()))
OLD_RUN = str(e.run_id_for(datetime(2026, 9, 28).date()))
CAPTIONS = {5: 'Try this today: answer the oldest client first.', 6: 'Planned a post in Grow? Publish it to your site.',
            7: 'Send the invoice while the job is fresh.', 8: 'Does it read your business or guess?',
            9: 'Pick one place to keep your to-dos.'}
PLAYS = {5: 'workflow_tip', 6: 'feature_spotlight', 7: 'workflow_tip', 8: 'question_answered', 9: 'workflow_tip'}


def post(day, service, status='draft', run_id=RUN_ID, text=None, month=10, error=None, play=None):
    return {'id': str(uuid4()), 'revision': 1, 'status': status, 'run_at': at(2026, month, day, 11).isoformat(),
            'expires_at': at(2026, month, day, 17).isoformat(), 'run_id': run_id,
            'play_id': play or PLAYS.get(day), 'campaign': 'week-x', 'error': error, 'content_hash': 'h',
            'payload': {'text': text or CAPTIONS.get(day, f'Post for day {day}.'), 'service': service,
                        'channel_id': service, 'asset': None}}


def week_posts(status='draft'):
    return [post(day, s, status) for day in range(5, 10) for s in ('instagram', 'twitter', 'facebook')]


def missed_posts():
    return [post(30, 'twitter', run_id=OLD_RUN, month=9, text='Worried Chief might do something you did not want?'),
            post(2, 'twitter', run_id=OLD_RUN, text='Send every unpaid invoice a friendly nudge.'),
            post(2, 'facebook', run_id=OLD_RUN, text='Send every unpaid invoice a friendly nudge.')]


def plan_run(**kw):
    return {'id': RUN_ID, 'week_of': NEXT, 'status': 'succeeded', 'trigger': 'scheduled', 'attempts': 1,
            'created_at': at(2026, 10, 1, 7, 2).isoformat(), 'finished_at': at(2026, 10, 1, 7, 4).isoformat(),
            'signals': {'traffic': {'visits': 90, 'signups': 1, 'leads': 0}},
            'diagnosis': {'primary_problem': 'stay_visible', 'rule': 'steady', 'urgency': 'low',
                          'evidence': 'Nothing is off this week (90 visits, 1 signup in the last 7 days).'},
            'plays': [{'play_id': 'workflow_tip', 'label': 'Teach a useful move', 'posts': 3},
                      {'play_id': 'feature_spotlight', 'label': 'Show one new thing', 'posts': 1},
                      {'play_id': 'question_answered', 'label': 'Answer a real question', 'posts': 1}],
            'error': None, **kw}


CHANNELS = [{'id': s, 'service': s} for s in ('instagram', 'twitter', 'facebook')]


def state(posts=None, runs=None, paused=False, now=NOW, config=True):
    return {'now': now, 'runs': [plan_run()] if runs is None else runs,
            'posts': week_posts() + missed_posts() if posts is None else posts,
            'config': {'channels': CHANNELS, 'paused': paused} if config else None}


# ── the desk as it was on 2026-10-02 ──────────────────────────────────

def test_next_week_reads_as_drafted_with_its_deadline():
    f = d.facts(state())
    assert f['which_week'] == 'next week' and len(f['plan']) == len(f['plan_waiting']) == 5
    assert all(sorted(x['channels']) == ['Facebook', 'Instagram', 'X'] for x in f['plan'])
    head = d.masthead(f)
    assert (head['title'], head['accent']) == ('Next week is', 'drafted.')
    assert head['kicker'] == 'GROWTH · MARKETING · WEEK OF OCTOBER 5'
    assert 'Chief planned October 5–9 on Thursday morning: five posts on Instagram, X and Facebook.' in head['sub']
    assert 'Approve by Monday 11:00 AM' in head['sub']


def test_chiefs_read_carries_counted_numbers_and_the_plan():
    note = d.note(d.facts(state()))
    assert note['headline'] == 'Nothing is off, so the week stays steady.'
    assert note['body'][0] == ('90 people visited and 1 signed up in the 7 days before it was planned. The plan: three '
                               'useful moves, one new thing that shipped and one real question answered.')
    assert note['body'][1] == "Monday's post goes out at 11:00 AM once you approve it."
    assert 'Two posts from this week missed their time.' in note['body']
    assert note['tone'] == 'push' and note['kicker'] == "CHIEF'S READ · WORTH A PUSH"
    assert note['quick_replies'][:3] == ['Walk me through the week', 'Which post is strongest?',
                                         'What should I do with the missed posts?']


def test_the_note_key_changes_only_when_the_words_do():
    a, b = d.note(d.facts(state())), d.note(d.facts(state()))
    assert a['key'] == b['key']
    fewer = [p for p in week_posts() + missed_posts() if p['payload']['text'] != CAPTIONS[9]]
    assert d.note(d.facts(state(fewer)))['key'] == a['key']        # same words: Chief does not speak again
    monday_ok = week_posts() + missed_posts()
    for p in monday_ok[:3]:
        p['status'] = 'approved'
    assert d.note(d.facts(state(monday_ok)))['key'] != a['key']


def test_missed_drafts_leave_the_queue_and_become_a_to_do():
    f = d.facts(state())
    assert len(f['waiting']) == 5                              # never counted as awaiting review
    missed = next(i for i in d.attention(f) if i['kind'] == 'missed')
    assert missed['title'] == 'Two posts from this week missed their time'
    assert [len(x['items']) for x in missed['slots']] == [1, 2]   # Sep 30 on X; Oct 2 on X and Facebook
    assert sorted(missed['slots'][1]['channels']) == ['Facebook', 'X']


def test_today_says_chief_drafted_next_week_with_the_deadline():
    items = d.today_items(state())
    first = items[0]
    assert first['title'] == 'Chief drafted next week. Five posts wait for your OK'
    assert first['count'] == 5 and first['action'] == {'label': 'Review the week', 'nav': 'platform-growth'}
    assert first['detail'].startswith("Monday's goes out at 11:00 AM if you approve it by then.")
    assert first['lanes'] == ['people'] and first['secondary']['chief']
    assert items[1]['title'] == 'Two posts from this week missed their time'
    assert items[1]['action']['label'] == 'Reschedule or let go'


# ── as the week moves ─────────────────────────────────────────────────

def test_partly_approved_says_how_many_and_what_still_needs_you():
    posts = week_posts()
    for p in posts:
        if p['run_at'] == at(2026, 10, 5, 11).isoformat():
            p['status'] = 'approved'
    f = d.facts(state(posts))
    head = d.masthead(f)
    assert head['accent'] == 'under way.'
    assert head['sub'] == "One of five posts is approved. Tuesday's still needs your OK by 11:00 AM."
    assert d.note(f)['body'][1] == "One of five posts is approved; Tuesday's goes out at 11:00 AM once you approve it."


def test_all_approved_is_ready_and_nothing_waits_on_today():
    f = d.facts(state(week_posts('approved')))
    assert d.masthead(f)['accent'] == 'ready.'
    assert d.note(f)['body'][1] == 'All five are approved; they go out at their times.'
    assert not [i for i in d.today_items(state(week_posts('approved'))) if i['kind'] == 'posts']


def test_a_failed_post_is_red_and_carries_buffers_words():
    posts = week_posts('approved')
    posts.append(post(1, 'twitter', 'failed', run_id=OLD_RUN, error='Buffer reported a publishing failure.'))
    f = d.facts(state(posts))
    failed = d.attention(f)[0]
    assert failed['kind'] == 'failed' and failed['tone'] == 'red'
    assert failed['title'] == "A post didn't go out on X" and failed['detail'] == 'Buffer reported a publishing failure.'
    assert d.note(f)['tone'] == 'attention'


def test_an_unconfirmed_delivery_asks_for_a_check():
    posts = week_posts('approved') + [post(1, 'facebook', 'uncertain', run_id=OLD_RUN)]
    item = d.attention(d.facts(state(posts)))[0]
    assert item['kind'] == 'uncertain' and 'mark each one sent or not sent' in item['detail']


def test_paused_publishing_holding_approved_posts_is_named():
    item = d.attention(d.facts(state(week_posts('approved'), paused=True)))[0]
    assert item == {**item, 'kind': 'paused', 'title': 'Publishing is paused',
                    'detail': 'Five approved posts will not go out until you resume it.'}


def test_a_plan_that_could_not_be_written_says_why():
    runs = [plan_run(status='skipped', error='Connect a Facebook, X, LinkedIn or Instagram channel in Buffer first.')]
    s = state(posts=[], runs=runs)
    f = d.facts(s)
    item = next(i for i in d.attention(f) if i['kind'] == 'plan_failed')
    assert item['title'] == 'The plan for the week of October 5 could not be written'
    assert d.note(f)['headline'] == 'The plan for the week of October 5 could not be written.'
    assert d.masthead(f)['accent'] == 'needs you.'
    assert not any(i['kind'] == 'quiet' for i in d.attention(f))
    today = d.today_items(s)
    assert today[0]['lanes'] == ['systems'] and today[0]['action']['label'] == 'Plan it now'


def test_nothing_planned_and_nothing_going_out_is_quiet_with_the_next_plan_time():
    s = state(posts=[], runs=[])
    f = d.facts(s)
    quiet = d.attention(f)[0]
    assert quiet['kind'] == 'quiet' and quiet['detail'].startswith("Next week's plan is written Thursday at 7:00 AM.")
    assert d.masthead(f)['title'] == 'No plan' and d.note(f)['headline'] == 'There is no plan for the days ahead yet.'


def test_unreadable_posts_never_read_as_quiet():
    s = state(runs=[])
    s['posts'] = None
    f = d.facts(s)
    assert not f['readable'] and d.attention(f) == [] and d.today_items(s) == []


def test_planning_shows_while_the_run_is_young():
    runs = [plan_run(status='running', created_at=(NOW - timedelta(minutes=2)).isoformat(), finished_at=None)]
    f = d.facts(state(posts=[], runs=runs))
    assert f['planning'] and d.note(f)['headline'] == 'Chief is writing the week.'
    assert d.masthead(f)['accent'] == 'being written.'
    assert not any(i['kind'] == 'quiet' for i in d.attention(f))


# ── Chief and the phone ───────────────────────────────────────────────

def test_chiefs_digest_names_what_marketing_is_waiting_on():
    digest = d.chief_digest(state())
    assert digest['posts_waiting_for_approval'] == 5 and digest['first_waiting_goes_out'] == 'Monday 11:00 AM'
    assert digest['needs_owner'][0] == 'Chief drafted next week. Five posts wait for your OK'
    assert any(n.startswith('Two posts from this week missed their time') for n in digest['needs_owner'])
    assert digest['plan']['which_week'] == 'next week' and digest['next_plan'] == 'Thursday 7:00 AM'
    assert 'never approve for him' in d.DIGEST_PROMPT


@pytest.fixture
def pushed(monkeypatch):
    sent = []

    async def push(title, body, tag):
        sent.append((title, body, tag))
        return 1
    monkeypatch.setattr(d, 'push', push)
    return sent


def test_a_drafted_week_pushes_the_deadline(monkeypatch, pushed):
    async def read_state(now=None, runs=None):
        return state()
    monkeypatch.setattr(d, 'read_state', read_state)
    run(d.tell_owner_about_plan('succeeded', RUN_ID))
    assert pushed == [('Chief drafted next week',
                       "Five posts are ready for your review. Monday's needs your OK by 11:00 AM.", 'marketing-week')]


def test_a_plan_that_failed_pushes_the_reason(pushed):
    run(d.tell_owner_about_plan('skipped', RUN_ID, 'Connect a channel first.'))
    assert pushed[0][0] == "The marketing plan couldn't be written" and 'Connect a channel first.' in pushed[0][1]


def test_a_post_that_did_not_go_out_pushes_where_and_why(pushed):
    rows = [post(5, 'twitter', 'failed', error='Destination is disconnected, locked or paused in Buffer.')]
    run(d.tell_owner_about_delivery(rows))
    assert pushed == [("A post didn't go out", 'X: Destination is disconnected, locked or paused in Buffer.',
                       'marketing-delivery')]


def test_the_desk_overview_carries_the_read(monkeypatch):
    import marketing_design
    s = state()

    async def db(method, path, body=None):
        if path.startswith('/platform_marketing_runs'):
            return copy.deepcopy(s['runs'])
        if path.startswith('/platform_marketing_posts?run_id'):
            return [p for p in s['posts'] if p['run_id'] == RUN_ID]
        if path.startswith('/platform_marketing_posts'):
            return copy.deepcopy(s['posts'])
        raise AssertionError(path)

    async def config():
        return s['config']

    async def budget():
        return {'budget_usd': 10, 'spent_usd': 0.01}
    monkeypatch.setattr(m, 'db', db)
    monkeypatch.setattr(m, 'config', config)
    monkeypatch.setattr(m, 'now', lambda: NOW)
    monkeypatch.setattr(marketing_design, 'budget_state', budget)
    out = run(e.overview())
    assert out['masthead']['accent'] == 'drafted.' and out['note']['headline'].startswith('Nothing is off')
    assert out['relation'] == 'next week' and out['planning'] is False
    assert out['deadline'] == at(2026, 10, 5, 11).isoformat()
    assert [i['kind'] for i in out['attention']] == ['missed']
    assert set(out['attention'][0]['slots'][0]) == {'key', 'run_at', 'channels', 'text', 'items'}


def test_the_overview_still_shows_the_plan_when_the_read_fails(monkeypatch):
    import marketing_design

    async def db(method, path, body=None):
        if path.startswith('/platform_marketing_runs'):
            return [plan_run()]
        return []

    async def boom(*a, **k):
        raise RuntimeError('down')

    async def budget():
        return None
    monkeypatch.setattr(m, 'db', db)
    monkeypatch.setattr(m, 'now', lambda: NOW)
    monkeypatch.setattr(d, 'read_state', boom)
    monkeypatch.setattr(marketing_design, 'budget_state', budget)
    out = run(e.overview())
    assert out['latest']['id'] == RUN_ID and 'note' not in out
