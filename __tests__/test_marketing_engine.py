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
    assert plan['plays'][0]['reason'] == e.LEAD_REASON['feature_spotlight']
    assert set(e.LEAD_REASON) == set(e.PLAYS)


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
    kept, flyers, dropped = run(e.write_captions(slots, FACTS))
    assert set(kept) == {1} and flyers == {}
    assert {d['slot']: d['reason'] for d in dropped} == {1: 'no flyer copy', 2: 'number not in the facts (1000)', 3: 'missing'}
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
        if method == 'GET' and path.startswith('/platform_marketing_assets'):
            return [a for a in s['assets'].values() if a['id'] in path]
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
    model['captions'] = [{'slot': i, 'text': f'Caption number {"one two three four five".split()[i - 1]} for a busy owner.',
                          'flyer': FLYER} for i in range(1, 6)]
    import marketing_design
    s['assets'] = {i: {'id': str(uuid4()), 'name': f'flyer {i}', 'kind': 'image', 'url': f'https://x/{i}.png', 'sha256': 'h'}
                   for i in range(1, 6)}
    s['design_calls'] = []

    async def design_week(run_id, slots, copies, lead):
        s['design_calls'].append({'slots': [x['slot'] for x in slots], 'copies': copies, 'lead': lead})
        return ({k: v for k, v in s['assets'].items() if k in {x['slot'] for x in slots}},
                {'flyers': {str(k): v['id'] for k, v in s['assets'].items()}, 'hero_id': None, 'request': None, 'failed': []})
    monkeypatch.setattr(marketing_design, 'design_week', design_week)

    async def asset_row(path):
        return [a for a in s['assets'].values() if a['id'] in path]
    s['asset_row'] = asset_row
    return s


def test_with_no_flyers_a_week_is_drafts_for_text_channels_only(world, model):
    world['assets'] = {}
    out = run(e.run_week('scheduled'))
    assert out['status'] == 'succeeded' and model['calls'] == 1
    assert world['claimed_with'] == {'run_id': str(e.run_id_for(e.week_window(MONDAY_8AM)[0])),
                                     'week': '2026-09-28', 'source': 'scheduled', 'replan': False}
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


def test_no_channel_skips_with_a_reason_and_no_spend(world, model):
    world['channels'] = []
    out = run(e.run_week('scheduled'))
    assert out['status'] == 'skipped' and 'Connect a Facebook' in out['reason']
    assert model['calls'] == 0 and world['run']['status'] == 'skipped'


def test_instagram_only_with_no_flyers_saves_nothing(world, model):
    world['channels'] = [c for c in CHANNELS if c['service'] == 'instagram']
    world['assets'] = {}
    out = run(e.run_week('scheduled'))
    assert out['status'] == 'skipped' and world['writes'] == []
    assert 'no flyer' in world['run']['error']


FLYER = {'headline': 'Follow up the same day', 'line': 'A quick note after every session keeps clients coming back.',
         'cta': 'See how it works'}


@pytest.mark.parametrize('copy,problem', [
    (FLYER, None),
    ({**FLYER, 'headline': 'x' * 43}, 'flyer headline length'),
    ({**FLYER, 'cta': 'Visit mysolutionist.app'}, 'flyer cta length'),
    ({**FLYER, 'line': 'Go to mysolutionist.app for the details.'}, 'link on the flyer'),
    ({**FLYER, 'line': 'Trusted by 300 owners across the country.'}, 'number on the flyer not in the facts (300)'),
    ({**FLYER, 'line': 'Seven days free: 7 of them, on the plan you pick.'}, None),
    ({'headline': 'Only a headline here'}, 'flyer line length'),
    (None, 'no flyer copy'),
])
def test_flyer_rules(copy, problem):
    assert e.check_flyer(copy, ALLOWED) == problem


def test_a_bad_flyer_costs_the_picture_not_the_caption(model):
    slots = [{'slot': 1, 'play_id': 'workflow_tip', 'subject': None}, {'slot': 2, 'play_id': 'workflow_tip', 'subject': None}]
    model['captions'] = [{'slot': 1, 'text': 'Send the follow-up the same day. Solutionist keeps it on the contact.', 'flyer': FLYER},
                         {'slot': 2, 'text': 'Answer the question before they ask it, and the booking follows.',
                          'flyer': {**FLYER, 'line': 'Trusted by 300 owners.'}}]
    kept, flyers, dropped = run(e.write_captions(slots, FACTS))
    assert set(kept) == {1, 2} and set(flyers) == {1}
    assert dropped == [{'slot': 2, 'reason': 'number on the flyer not in the facts (300)', 'flyer_only': True}]
    assert 'headline at most 42 characters' in model['payload']['system']


def test_flyers_ride_on_every_channel_and_bring_instagram_in(world, model):
    run(e.run_week('scheduled'))
    rows = world['writes'][0]
    by_slot = {}
    for r in rows:
        by_slot.setdefault(r['run_at'], []).append(r)
    assert len(rows) == 15                                            # 5 slots x Facebook + X + Instagram
    assert {r['payload']['service'] for r in rows} == {'facebook', 'twitter', 'instagram'}
    slot_of = {str(e.uuid5(e.run_id_for(e.week_window(MONDAY_8AM)[0]), f'{i}:{c["id"]}')): i
               for i in range(1, 6) for c in CHANNELS}
    assert all(r['payload']['asset']['id'] == world['assets'][slot_of[r['id']]]['id'] for r in rows)
    assert all(r['payload']['asset'] for r in rows)
    assert world['design_calls'][0]['lead'] == world['run']['plays'][0]['play_id']
    assert world['run']['design']['flyers']


def test_a_slot_without_a_flyer_stays_off_instagram(world, model):
    world['assets'].pop(2)
    run(e.run_week('scheduled'))
    rows = world['writes'][0]
    assert len(rows) == 14
    slot_two = [r for r in rows if r['id'] in {str(e.uuid5(e.run_id_for(e.week_window(MONDAY_8AM)[0]), f'2:{c["id"]}')) for c in CHANNELS}]
    assert {r['payload']['service'] for r in slot_two} == {'facebook', 'twitter'}
    assert all(r['payload']['asset'] is None for r in slot_two)


def test_a_failed_design_step_keeps_the_week_text_only(world, model, monkeypatch):
    import marketing_design

    async def broken(*a, **kw):
        raise RuntimeError('renderer down')
    monkeypatch.setattr(marketing_design, 'design_week', broken)
    out = run(e.run_week('scheduled'))
    rows = world['writes'][0]
    assert out['status'] == 'succeeded' and len(rows) == 10
    assert {r['payload']['service'] for r in rows} == {'facebook', 'twitter'}
    assert world['run']['design']['failed'][0]['what'] == 'design'


def test_plan_now_runs_in_the_background_once(monkeypatch):
    started = []

    async def slow(trigger, now=None, replan=False):
        started.append((trigger, replan))
        await asyncio.sleep(0.05)

    async def scenario():
        monkeypatch.setattr(e, 'run_week', slow)
        first, second = e.start_week(), e.start_week()
        await asyncio.sleep(0.1)
        return first, second, e.start_week()
    first, second, third = run(scenario())
    assert (first, second, third) == (True, False, True) and started[:1] == [('manual', False)]


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


# ── the founding price (the first live plan quoted the standard price) ─

FOUNDER_FACTS = {**FACTS, 'product': {**FACTS['product'], 'standard_monthly_prices_usd': {'professional': 149.0}},
                 'founder': {'monthly_price_usd': 99.0, 'seat_limit': 50}}


@pytest.mark.parametrize('text,play,problem', [
    ('Take a founding seat on Professional at $149 a month, held while you keep it.', 'founder_invitation',
     'a price that is not the founding price'),
    ('Take a founding seat on Professional at $99 a month, held while you keep it.', 'founder_invitation', None),
    ('Founding seats: $99 a month, versus $149 for everyone else later on.', 'founder_invitation',
     'a price that is not the founding price'),
    ('Take a founding seat and keep your rate as long as you keep the seat.', 'founder_invitation', None),
    ('Professional is $149 a month and includes the whole workspace.', 'workflow_tip', None),
])
def test_a_founder_post_only_ever_quotes_the_founding_price(text, play, problem):
    assert e.price_problem(text, play, FOUNDER_FACTS) == problem


def test_the_wrong_founder_price_is_dropped_from_caption_and_flyer(model):
    slots = [{'slot': 1, 'play_id': 'founder_invitation', 'subject': 'founding seat'},
             {'slot': 2, 'play_id': 'founder_invitation', 'subject': 'founding seat'}]
    model['captions'] = [
        {'slot': 1, 'text': 'A founding seat on Professional is $149 a month while you keep it.', 'flyer': FLYER},
        {'slot': 2, 'text': 'A founding seat on Professional is $99 a month while you keep it.',
         'flyer': {**FLYER, 'line': 'Professional at $149 a month, locked while you keep your seat.'}}]
    kept, flyers, dropped = run(e.write_captions(slots, FOUNDER_FACTS))
    assert set(kept) == {2} and flyers == {}
    assert {(d['slot'], d['reason']) for d in dropped} == {(1, 'a price that is not the founding price'),
                                                           (2, 'a price that is not the founding price')}


def test_seats_left_is_only_a_fact_once_seats_are_taken():
    base = signals(founder_available=True)
    full = {'plan': 'professional', 'seat_limit': 50, 'seats_left': 50, 'unit_amount': 9900}
    assert 'seats_left' not in e.verified_facts({**base, 'founder': full})['founder']
    assert e.verified_facts({**base, 'founder': {**full, 'seats_left': 38}})['founder']['seats_left'] == 38


def test_the_founder_brief_names_the_trap():
    brief = e.PLAYS['founder_invitation']['brief']
    assert 'standard plan prices are NOT the founding price' in brief
    assert 'do not mention lifetime or one-time' in brief


# ── starting a week over ──────────────────────────────────────────────

def test_start_over_asks_the_claim_to_replan_and_writes_new_ids(world):
    run(e.run_week('scheduled'))
    first = [r['id'] for r in world['writes'][0]]
    world['writes'].clear()
    world['run'].update(attempts=2)
    run(e.run_week('manual', replan=True))
    assert world['claimed_with']['replan'] is True
    second = [r['id'] for r in world['writes'][0]]
    assert not set(first) & set(second)                               # beside the cancelled drafts, not over them


def test_only_the_owner_can_start_over():
    assert run_body_replan('scheduled') is False


def run_body_replan(trigger):
    captured = {}

    async def db(method, path, body=None):
        captured.update(body or {})
        return False

    async def get_run(run_id):
        return None
    import unittest.mock as mock
    with mock.patch.object(m, 'db', db), mock.patch.object(e, 'get_run', get_run):
        run(e.run_week(trigger, now=MONDAY_8AM, replan=True))
    return captured['replan']


def test_crash_recovery_ignores_cancelled_drafts(world, model):
    paths = []
    original = m.db

    async def spy(method, path, body=None):
        paths.append(path)
        return await original(method, path, body)
    m.db = spy
    try:
        run(e.run_week('scheduled'))
    finally:
        m.db = original
    assert any('run_id=eq.' in p and 'status=neq.cancelled' in p for p in paths)
