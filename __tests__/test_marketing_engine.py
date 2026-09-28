"""The Monday plan: rules pick the problem, code picks the plays, the model only writes.

No network. The database, Buffer config and the model are faked at the seams
the engine calls, and every assertion is about what reaches the review queue.
"""
import asyncio
import copy
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import httpx
import pytest
from fastapi import HTTPException

import marketing_engine as e
import platform_marketing as m


def run(coro):
    return asyncio.run(coro)


ET = e.TZ


def at(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=ET).astimezone(timezone.utc)


MONDAY_8AM = at(2026, 9, 28, 8)          # 2026-09-28 is a Monday


def news(i, days_ago=2, now=MONDAY_8AM):
    return {'id': f'news-{i}', 'title': f'Update {i}', 'body': f'Body of update {i}.', 'slug': f'update-{i}',
            'published_at': (now - timedelta(days=days_ago)).isoformat(), 'image_url': None}


def signals(**kw):
    base = {'read_at': MONDAY_8AM.isoformat(),
            'traffic': {'visits': 30, 'signups': 1, 'leads': 0, 'weekly_visits_before': 28.0, 'weekly_signups_before': 1.0},
            'posts': {'last_published': (MONDAY_8AM - timedelta(days=2)).isoformat(),
                      'published_last_7_days': 1, 'approved_next_7_days': 0},
            'news': [], 'unmarketed_news': [], 'founder': None, 'founder_available': False,
            'used_subjects': [], 'play_scores': {}}
    base.update(kw)
    return base


FACTS = {'product': {'trial_days': 7, 'standard_monthly_prices_usd': {'starter': 79.0}},
         'public_claims': {'features': [], 'faq': [{'question': 'What does the free trial include?', 'answer': '7 days free.'},
                                                   {'question': 'Can I bring my assistant?', 'answer': 'Yes.'}]},
         'news': []}


# ── diagnosis ─────────────────────────────────────────────────────────

def test_an_unmarketed_update_comes_first():
    d = e.diagnose(signals(unmarketed_news=[news(1), news(2)], founder_available=True,
                           traffic={'visits': 50, 'signups': 0, 'leads': 0, 'weekly_visits_before': 50, 'weekly_signups_before': 0}))
    assert d['primary_problem'] == 'launch_offering' and d['rule'] == 'unmarketed_news'
    assert '"Update 1"' in d['evidence'] and 'September 26' in d['evidence'] and '1 more new update' in d['evidence']


def test_visits_without_signups_needs_an_open_founder_offer():
    t = {'visits': 41, 'signups': 0, 'leads': 0, 'weekly_visits_before': 40, 'weekly_signups_before': 1}
    d = e.diagnose(signals(traffic=t, founder_available=True))
    assert d['primary_problem'] == 'generate_leads'
    assert d['evidence'] == '41 people visited the site in the last 7 days and none of them signed up.'
    assert e.diagnose(signals(traffic=t, founder_available=False))['primary_problem'] != 'generate_leads'


def test_traffic_drop_carries_the_counted_numbers():
    d = e.diagnose(signals(traffic={'visits': 12, 'signups': 1, 'leads': 0, 'weekly_visits_before': 40, 'weekly_signups_before': 1}))
    assert d['primary_problem'] == 'build_authority'
    assert 'down 70%' in d['evidence'] and '12 in the last 7 days' in d['evidence'] and 'about 40' in d['evidence']


def test_gone_quiet_is_urgent():
    d = e.diagnose(signals(posts={'last_published': (MONDAY_8AM - timedelta(days=12)).isoformat(),
                                  'published_last_7_days': 0, 'approved_next_7_days': 0}))
    assert d['primary_problem'] == 'stay_visible' and d['urgency'] == 'high'
    assert 'since September 16' in d['evidence']


def test_unreadable_numbers_never_become_a_diagnosis():
    d = e.diagnose(signals(traffic=None, posts=None))
    assert d['primary_problem'] == 'stay_visible' and d['rule'] == 'steady'
    assert 'could not be read' in d['evidence']


def test_every_problem_and_play_is_in_the_closed_library():
    assert set(e.PREFERENCE) == set(e.PROBLEMS)
    for problem, plays in e.PREFERENCE.items():
        for play in plays:
            assert problem in e.PLAYS[play]['solves']


# ── the week ──────────────────────────────────────────────────────────

def test_monday_morning_plans_monday_to_friday_at_eleven():
    week_of, times = e.week_window(MONDAY_8AM)
    assert week_of.isoformat() == '2026-09-28' and len(times) == 5
    assert all(t.hour == 11 and t.tzinfo == ET for t in times)
    assert [t.weekday() for t in times] == [0, 1, 2, 3, 4]


def test_late_in_the_week_plans_the_next_one():
    week_of, times = e.week_window(at(2026, 10, 1, 14))       # Thursday afternoon: only Friday left
    assert week_of.isoformat() == '2026-10-05' and len(times) == 5
    week_of, times = e.week_window(at(2026, 9, 30, 9))        # Wednesday morning: Wed, Thu, Fri
    assert week_of.isoformat() == '2026-09-28' and len(times) == 3


def slots_for(sig, facts=FACTS, now=MONDAY_8AM):
    d = e.diagnose(sig)
    return d, e.pick_plays(d, sig, facts, e.week_window(now)[1])


def test_launch_week_alternates_the_new_thing_with_support():
    d, plan = slots_for(signals(unmarketed_news=[news(1)], news=[news(1)]))
    plays = [s['play_id'] for s in plan['slots']]
    assert len(plays) == 5 and plays[0] == 'feature_spotlight'
    assert plays.count('feature_spotlight') == 1            # one update, spotlighted once
    assert 'behind_the_build' in plays and 'workflow_tip' in plays
    assert all(plays.count(p) <= e.PLAYS[p]['max_per_week'] for p in set(plays))
    spot = plan['slots'][0]
    assert spot['subject_key'] == 'news:news-1' and spot['landing_url'] == 'https://mysolutionist.app/news/update-1'
    assert plan['plays'][0]['reason'].startswith('Tell people about something new: "Update 1"')


def test_founder_play_only_when_seats_and_price_are_verified():
    t = {'visits': 41, 'signups': 0, 'leads': 0, 'weekly_visits_before': 40, 'weekly_signups_before': 1}
    _, plan = slots_for(signals(traffic=t, founder_available=True), facts={**FACTS, 'founder': {'seats_left': 12}})
    assert plan['slots'][0]['play_id'] == 'founder_invitation'
    assert plan['slots'][0]['landing_url'] == 'https://mysolutionist.app/start?plan=founder'
    _, plan = slots_for(signals(traffic=t, founder_available=True), facts=FACTS)   # no verified founder facts
    assert 'founder_invitation' not in [s['play_id'] for s in plan['slots']]


def test_a_quiet_week_still_fills_without_inventing_subjects():
    _, plan = slots_for(signals())
    plays = [s['play_id'] for s in plan['slots']]
    assert plays and set(plays) <= {'workflow_tip', 'question_answered', 'feature_spotlight'}
    faq = [s for s in plan['slots'] if s['play_id'] == 'question_answered']
    assert {s['subject'] for s in faq} <= {q['question'] for q in FACTS['public_claims']['faq']}


def test_used_faq_questions_wait_their_turn():
    sig = signals(used_subjects=['faq:0'])
    subjects = e._subjects('question_answered', sig, FACTS)
    assert subjects[0]['subject_key'] == 'faq:1'


def test_results_reorder_support_but_never_the_problems_own_play():
    scores = {'question_answered': {'samples': 4, 'average': 9.0}, 'behind_the_build': {'samples': 1, 'average': 50.0}}
    assert e._rank(['workflow_tip', 'behind_the_build', 'question_answered'], scores) == \
        ['workflow_tip', 'question_answered', 'behind_the_build']


# ── captions ──────────────────────────────────────────────────────────

ALLOWED = e._numbers(json.dumps(FACTS))


@pytest.mark.parametrize('text,problem', [
    ('Seven days free, and you can leave before then with nothing owed. Try it.', None),
    ('Try it free for 7 days and see your whole week in one place.', None),
    ('Join 500 businesses already running on Solutionist today.', 'number not in the facts (500)'),
    ('Starter is $49 a month, which is less than your coffee budget.', 'number not in the facts (49)'),
    ('See it at mysolutionist.app and start your trial today.', 'link in the caption'),
    ('Your week, handled. #smallbusiness #solutionist', 'hashtag'),
    ('Too short', 'length'),
    ('x' * 221, 'length'),
])
def test_caption_rules(text, problem):
    assert e.check_caption(text, ALLOWED) == problem


@pytest.fixture
def model(monkeypatch):
    import llm_call
    box = {'captions': [], 'calls': 0}

    async def write(client, payload, **kw):
        box['calls'] += 1
        box['payload'] = payload
        return httpx.Response(200, request=httpx.Request('POST', 'https://llm.example'),
                              json={'content': [{'type': 'text', 'text': json.dumps({'captions': box['captions']})}]})
    monkeypatch.setattr(llm_call, 'apost', write)
    monkeypatch.setattr(llm_call, 'api_key', lambda: 'configured')
    return box


def test_bad_captions_are_dropped_not_saved(model):
    slots = [{'slot': 1, 'play_id': 'workflow_tip', 'subject': None}, {'slot': 2, 'play_id': 'workflow_tip', 'subject': None},
             {'slot': 3, 'play_id': 'workflow_tip', 'subject': None}]
    model['captions'] = [{'slot': 1, 'text': 'Send the follow-up the same day. Solutionist keeps it on the contact.'},
                         {'slot': 2, 'text': 'Over 1,000 owners switched this month.'}]
    kept, dropped = run(e.write_captions(slots, FACTS))
    assert set(kept) == {1}
    assert {d['slot']: d['reason'] for d in dropped} == {2: 'number not in the facts (1000)', 3: 'missing'}
    assert 'Use ONLY the supplied facts' in model['payload']['system']
    sent = json.loads(model['payload']['messages'][0]['content'])
    assert [s['play'] for s in sent['slots']] == ['Teach a useful move'] * 3     # the model is handed the play


# ── the run ───────────────────────────────────────────────────────────

CHANNELS = [{'id': 'fb', 'name': 'Solutionist', 'displayName': 'The Solutionist System', 'service': 'facebook',
             'isDisconnected': False, 'isLocked': False, 'isQueuePaused': False},
            {'id': 'x', 'name': 'SolutionistSys', 'service': 'twitter',
             'isDisconnected': False, 'isLocked': False, 'isQueuePaused': False},
            {'id': 'ig', 'name': 'solutionistsystem', 'service': 'instagram',
             'isDisconnected': False, 'isLocked': False, 'isQueuePaused': False}]


@pytest.fixture
def world(monkeypatch, model):
    import spend_guard
    s = {'claim': True, 'existing': [], 'writes': [], 'run': {}, 'channels': CHANNELS}

    async def config():
        return {'organization_id': 'org', 'channels': s['channels'], 'paused': False}

    async def db(method, path, body=None):
        if path.startswith('/rpc/platform_marketing_claim_run'):
            s['claimed_with'] = body
            return s['claim']
        if method == 'GET' and path.startswith('/platform_marketing_posts?run_id'):
            return s['existing']
        if method == 'GET' and path.startswith('/platform_marketing_runs'):
            return [s['run']] if s['run'] else []
        if method == 'PATCH' and path.startswith('/platform_marketing_runs'):
            s['run'].update(copy.deepcopy(body))
            return [s['run']]
        if method == 'POST' and path == '/platform_marketing_posts':
            s['writes'].append(copy.deepcopy(body))
            return body
        raise AssertionError(f'unexpected {method} {path}')

    async def fake_signals(now=None):
        return signals(unmarketed_news=[news(1)], news=[news(1)])
    monkeypatch.setattr(m, 'config', config)
    monkeypatch.setattr(m, 'db', db)
    monkeypatch.setattr(m, 'now', lambda: MONDAY_8AM)
    monkeypatch.setattr(e, 'read_signals', fake_signals)
    monkeypatch.setattr(e, 'verified_facts', lambda sig: FACTS)
    monkeypatch.setattr(spend_guard, 'over_budget', lambda: False)
    model['captions'] = [{'slot': i, 'text': f'Caption number {"one two three four five".split()[i - 1]} for a busy owner.'}
                         for i in range(1, 6)]
    return s


def test_a_week_becomes_drafts_for_text_channels_only(world, model):
    out = run(e.run_week('scheduled'))
    assert out['status'] == 'succeeded' and model['calls'] == 1
    assert world['claimed_with'] == {'run_id': str(e.run_id_for(e.week_window(MONDAY_8AM)[0])),
                                     'week': '2026-09-28', 'source': 'scheduled'}
    rows = world['writes'][0]
    assert len(world['writes']) == 1 and len(rows) == 10                      # 5 slots x Facebook + X
    assert {r['payload']['service'] for r in rows} == {'facebook', 'twitter'}  # Instagram needs a picture
    assert all(r['campaign'] == 'week-2026-09-28' and r['payload']['ai_assisted'] for r in rows)
    assert all('approved_hash' not in r and 'status' not in r for r in rows)   # drafts, never approved
    assert all(r['run_id'] == str(e.run_id_for(e.week_window(MONDAY_8AM)[0])) and r['play_id'] in e.PLAYS for r in rows)
    assert all('/go/' in r['payload']['publish_text'] for r in rows)
    assert world['run']['status'] == 'succeeded' and len(world['run']['post_ids']) == 10
    assert world['run']['diagnosis']['primary_problem'] == 'launch_offering'


def test_draft_ids_are_stable_for_the_week(world):
    run(e.run_week('scheduled'))
    first = [r['id'] for r in world['writes'][0]]
    world['writes'].clear()
    world['run'].clear()
    run(e.run_week('manual'))
    assert [r['id'] for r in world['writes'][0]] == first


def test_a_planned_week_is_not_redone(world, model):
    world['claim'] = False
    world['run'] = {'id': 'r', 'status': 'succeeded', 'post_ids': ['a']}
    out = run(e.run_week('manual'))
    assert out['status'] == 'exists' and model['calls'] == 0 and world['writes'] == []


def test_drafts_saved_before_a_crash_are_kept_not_rewritten(world, model):
    world['existing'] = [{'id': 'p1'}, {'id': 'p2'}]
    out = run(e.run_week('scheduled'))
    assert out['status'] == 'succeeded' and model['calls'] == 0 and world['writes'] == []
    assert world['run']['post_ids'] == ['p1', 'p2']


def test_no_text_channel_skips_with_a_reason_and_no_spend(world, model):
    world['channels'] = [c for c in CHANNELS if c['service'] == 'instagram']
    out = run(e.run_week('scheduled'))
    assert out['status'] == 'skipped' and 'Instagram needs a picture' in out['reason']
    assert model['calls'] == 0 and world['run']['status'] == 'skipped'


def test_when_every_caption_breaks_a_rule_nothing_is_saved(world, model):
    model['captions'] = [{'slot': i, 'text': f'Join {i}00 happy owners on Solutionist today.'} for i in range(1, 6)]
    with pytest.raises(HTTPException) as err:
        run(e.run_week('scheduled'))
    assert err.value.status_code == 502 and world['writes'] == []
    assert world['run']['status'] == 'failed' and len(world['run']['dropped']) == 5


def test_the_scheduled_tick_waits_for_monday_morning(monkeypatch):
    calls = []

    async def fake(trigger, now=None):
        calls.append(trigger)
    monkeypatch.setattr(e, 'run_week', fake)
    for when, expected in ((at(2026, 9, 28, 6), 0), (at(2026, 9, 28, 7, 5), 1), (at(2026, 10, 1, 9), 1), (at(2026, 10, 2, 9), 0)):
        calls.clear()
        monkeypatch.setattr(m, 'now', lambda when=when: when)
        run(e.engine_tick())
        assert len(calls) == expected, when
    monkeypatch.setenv('MARKETING_ENGINE', 'off')
    monkeypatch.setattr(m, 'now', lambda: at(2026, 9, 28, 9))
    calls.clear()
    run(e.engine_tick())
    assert calls == []


# ── facts ─────────────────────────────────────────────────────────────

def test_public_claims_skip_mockups_and_unopened_publishing():
    claims = e.public_claims()
    text = json.dumps(claims)
    assert claims['features'] and claims['faq']
    assert '3,140' not in text and 'Marcus Bell' not in text          # mock-up data is not a fact
    assert not any('Facebook' in f['area'] for f in claims['features'])


def test_facts_carry_dollars_and_founder_terms_only_when_verified():
    sig = signals(news=[news(1)])
    facts = e.verified_facts(sig)
    assert 'founder' not in facts
    assert facts['product']['standard_monthly_prices_usd']
    sig = signals(founder={'plan': 'professional', 'credits_monthly': 6000, 'seat_limit': 50, 'seats_left': 12,
                           'rate_terms': 'held while the seat is kept', 'unit_amount': 9900, 'currency': 'usd',
                           'interval': 'month', 'price_status': 'verified', 'availability_status': 'verified'},
                  founder_available=True)
    assert e.verified_facts(sig)['founder']['monthly_price_usd'] == 99.0


# ── Chief ─────────────────────────────────────────────────────────────

def test_chief_can_ask_for_the_week_and_it_is_a_drafts_action():
    import platform_chief_actions
    import platform_chief_authority
    import platform_chief_marketing
    assert platform_chief_authority.GROUPS['marketing_run_week'] == 'drafts'
    assert 'marketing_run_week' in platform_chief_actions.HANDLERS
    assert '"marketing_run_week"' in platform_chief_marketing.MARKETING_PROMPT
