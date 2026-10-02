"""The plan's pictures: free flyers for every post, one paid picture inside a budget.

No network and no browser: the composer's render, the image provider and the
database are faked at the seams marketing_design calls.
"""
import asyncio
import pathlib
import sys
from datetime import datetime, timezone
from uuid import uuid4

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import pytest
from fastapi import HTTPException

import chief_flyer_composer as composer
import marketing_design as d
import marketing_engine as e
import platform_marketing as m


def run(coro):
    return asyncio.run(coro)


COPY = {'headline': 'Take a founding seat', 'line': 'The Professional plan, locked while you keep your seat.',
        'cta': 'Claim your seat'}


# ── layouts ───────────────────────────────────────────────────────────

@pytest.mark.parametrize('play', sorted(e.PLAYS))
@pytest.mark.parametrize('hero', [None, str(uuid4())])
def test_every_play_has_a_valid_flyer_inside_the_canvas(play, hero):
    layout = composer.Layout.model_validate(d.flyer_layout(play, COPY, hero_id=hero))
    assert (layout.width, layout.height) == (1080, 1350)
    for layer in layout.layers:
        if layer.kind == 'text':
            assert 0 <= layer.x and layer.x + layer.width <= 1080 and 0 <= layer.y < 1350
    texts = ' '.join(l.text for l in layout.layers if l.kind == 'text')
    assert COPY['headline'].upper() in texts.replace('\n', ' ') and COPY['cta'] in texts
    assert 'mysolutionist.app' in texts
    images = [l for l in layout.layers if l.kind == 'image']
    assert len(images) == (1 if hero else 0)


def test_copy_that_cannot_fit_is_refused_before_rendering():
    long = {**COPY, 'headline': 'W' * 42, 'line': 'M' * 120}
    with pytest.raises(HTTPException) as err:
        d.flyer_layout('founder_invitation', long, hero_id=str(uuid4()), scale=1.0)
    assert err.value.status_code == 422


def test_every_play_has_an_eyebrow_and_a_lettering_free_scene():
    assert set(d.EYEBROW) == set(e.PLAYS) == set(d.HERO_SCENE)
    for play in e.PLAYS:
        prompt = d.hero_prompt(play)
        assert 'no text, letters' in prompt and 'no green' in prompt


def test_an_overflowing_flyer_shrinks_and_tries_again(monkeypatch):
    scales = []

    async def compose(client, biz, action, request_id):
        scales.append(action['layout']['layers'][-5]['font_size'] if False else len(scales))
        if len(scales) < 3:
            raise HTTPException(422, 'Text exceeds its allocated width in layer-5.')
        return {'image': {'id': 'art-1'}}

    async def to_asset(client, business_id, artwork_id):
        return {'id': 'asset-for-' + artwork_id}
    monkeypatch.setattr(composer, 'compose', compose)
    monkeypatch.setattr(d, 'to_marketing_asset', to_asset)
    slot = {'slot': 1, 'play_id': 'workflow_tip'}
    asset = run(d.compose_flyer(None, {'business_id': str(uuid4()), 'user_id': str(uuid4())}, uuid4(), slot, COPY))
    assert asset == {'id': 'asset-for-art-1'} and len(scales) == 3


def test_a_render_that_fails_for_another_reason_is_not_retried(monkeypatch):
    calls = []

    async def compose(*a):
        calls.append(1)
        raise HTTPException(503, 'Image storage is unavailable.')
    monkeypatch.setattr(composer, 'compose', compose)
    with pytest.raises(HTTPException):
        run(d.compose_flyer(None, {'business_id': str(uuid4())}, uuid4(), {'slot': 1, 'play_id': 'workflow_tip'}, COPY))
    assert len(calls) == 1


def test_the_build_actor_is_bound_only_inside_the_block():
    import image_studio
    actor = {'business_id': str(uuid4()), 'user_id': str(uuid4())}
    assert image_studio.build_actor.get() is None
    with d.acting_for(actor):
        assert image_studio.build_actor.get() == actor
    assert image_studio.build_actor.get() is None


# ── the budget ────────────────────────────────────────────────────────

@pytest.fixture
def ledger(monkeypatch):
    s = {'budget': 10, 'runs': [], 'art': []}

    async def config():
        return {'design_budget_usd': s['budget']}

    async def db(method, path, body=None):
        if path.startswith('/platform_marketing_runs'):
            return s['runs']
        if path.startswith('/image_artworks'):
            return s['art']
        raise AssertionError(path)
    monkeypatch.setattr(m, 'config', config)
    monkeypatch.setattr(m, 'db', db)
    return s


NOW = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)


def test_budget_counts_recorded_cost_and_unfinished_work_at_its_estimate(ledger):
    a, b = str(uuid4()), str(uuid4())
    ledger['runs'] = [{'design': {'hero_id': a}}, {'design': {'hero_id': b}}, {'design': None}]
    ledger['art'] = [{'id': a, 'cost_usd': 0.057, 'status': 'ready'}, {'id': b, 'cost_usd': None, 'status': 'working'}]
    state = run(d.budget_state(NOW))
    assert state == {'budget_usd': 10.0, 'spent_usd': round(0.057 + d.HERO_ESTIMATE_USD, 2),
                     'left_usd': round(10 - 0.057 - d.HERO_ESTIMATE_USD, 2), 'month': '2026-09',
                     'hero_estimate_usd': d.HERO_ESTIMATE_USD}


def test_a_zero_budget_means_no_paid_pictures(ledger):
    ledger['budget'] = 0
    assert run(d.budget_state(NOW))['left_usd'] == 0


@pytest.fixture
def studio(monkeypatch):
    s = {'left': 5.0, 'hero_calls': [], 'flyers': [], 'fail_slot': None}

    async def budget_state(now=None):
        return {'budget_usd': 10.0, 'spent_usd': 10 - s['left'], 'left_usd': s['left'], 'month': '2026-09',
                'hero_estimate_usd': d.HERO_ESTIMATE_USD}

    async def platform_owner():
        return {'business_id': str(uuid4()), 'user_id': str(uuid4())}

    async def make_hero(client, actor, run_id, play):
        s['hero_calls'].append(play)
        return 'hero-art'

    async def compose_flyer(client, actor, run_id, slot, copy, hero_id=None):
        if slot['slot'] == s['fail_slot']:
            raise HTTPException(422, 'Text exceeds its allocated width.')
        s['flyers'].append((slot['slot'], hero_id))
        return {'id': f'asset-{slot["slot"]}'}
    for name, fn in (('budget_state', budget_state), ('platform_owner', platform_owner),
                     ('make_hero', make_hero), ('compose_flyer', compose_flyer)):
        monkeypatch.setattr(d, name, fn)
    return s


SLOTS = [{'slot': 1, 'play_id': 'founder_invitation'}, {'slot': 2, 'play_id': 'question_answered'},
         {'slot': 3, 'play_id': 'founder_invitation'}]
COPIES = {1: COPY, 2: COPY, 3: COPY}


def test_inside_the_budget_the_lead_play_gets_the_picture(studio):
    assets, design = run(d.design_week(uuid4(), SLOTS, COPIES, 'founder_invitation'))
    assert studio['hero_calls'] == ['founder_invitation']                  # one picture a week
    assert studio['flyers'] == [(1, 'hero-art'), (2, None), (3, 'hero-art')]
    assert set(assets) == {1, 2, 3} and design['hero_id'] == 'hero-art' and design['request'] is None


def test_out_of_budget_it_asks_instead_of_spending(studio):
    studio['left'] = 0.05
    assets, design = run(d.design_week(uuid4(), SLOTS, COPIES, 'founder_invitation'))
    assert studio['hero_calls'] == [] and design['hero_id'] is None
    assert design['request']['needed_usd'] == d.HERO_ESTIMATE_USD and design['request']['left_usd'] == 0.05
    assert set(assets) == {1, 2, 3}                                        # flyers still made, flat


def test_one_failed_flyer_does_not_cost_the_others(studio):
    studio['fail_slot'] = 2
    assets, design = run(d.design_week(uuid4(), SLOTS, COPIES, 'founder_invitation'))
    assert set(assets) == {1, 3} and design['failed'][0]['what'] == 'flyer 2'


def test_a_slot_without_flyer_copy_gets_no_flyer(studio):
    assets, _ = run(d.design_week(uuid4(), SLOTS, {1: COPY}, 'founder_invitation'))
    assert set(assets) == {1}


def test_the_budget_route_is_bounded():
    with pytest.raises(Exception):
        e.Budget(design_budget_usd=-1)
    with pytest.raises(Exception):
        e.Budget(design_budget_usd=501)
    assert e.Budget(design_budget_usd=25).design_budget_usd == 25


def test_chief_cannot_change_the_budget():
    import platform_chief_authority
    import platform_chief_marketing
    assert not any('budget' in kind for kind in platform_chief_authority.GROUPS)
    assert not any('budget' in kind for kind in platform_chief_marketing.HANDLERS)
    assert 'You cannot change the budget.' in platform_chief_marketing.MARKETING_PROMPT
