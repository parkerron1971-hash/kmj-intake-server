"""The Creative Director for every business: a practitioner's flyer is planned,
drawn, checked and repaired once, on their own facts, limits and credits.
No live services or paid calls."""
import asyncio
import base64
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image

import chief_build_runtime as runtime
import creative_director as d
import image_studio as images
from chief_code import Step, WorkOrder, plan as plan_steps, question, stable_id

BIZ = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
USER = '11111111-1111-1111-1111-111111111111'


def run(coro):
    return asyncio.run(coro)


def png():
    out = io.BytesIO(); Image.new('RGB', (64, 96), (12, 20, 36)).save(out, 'PNG'); return out.getvalue()


def flyer_order(**facts):
    return WorkOrder.create({'kind': 'flyer', 'facts': {'prompt': 'Saturday special', **facts}}, business_id=BIZ,
                            user_id=USER, turn_id='turn-1', surface='desktop', words='Make me a flyer for Saturday')


# ── Sizes ────────────────────────────────────────────────────────────────

def test_phone_and_widescreen_sizes_are_offered_only_on_the_2_5_models(monkeypatch):
    assert {'1088x1920', '1920x1088'} <= set(images.model_sizes('gpt-image-2.5-sunburst'))
    assert {'1088x1920', '1920x1088'} <= set(images.model_sizes('gpt-image-2.5-flare'))
    assert images.model_sizes('gpt-image-2') == ('1024x1024', '1536x1024', '1024x1536')
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    monkeypatch.setattr(images, 'business', AsyncMock(return_value={'id': BIZ, 'owner_id': USER}))
    database = AsyncMock()
    monkeypatch.setattr(images, 'db', database)
    req = images.CreateImage(business_id=BIZ, request_id=uuid4(), prompt='A story cover', model='gpt-image-2', size='1088x1920')
    with pytest.raises(HTTPException) as refused:
        run(images.create(req, None))
    # Refused before any reservation, so nothing is charged or queued.
    assert refused.value.status_code == 422 and not database.called


# ── Facts, references and scope ──────────────────────────────────────────

def test_flyer_facts_are_only_what_the_business_publishes(monkeypatch):
    import agent_site
    bundle = {'facts': {'name': 'Fade Lab', 'phone': '555-0100', 'email': '', 'origin': 'https://fadelab.mysolutionist.app',
                        'booking_url': 'https://fadelab.mysolutionist.app/book'},
              'offerings': [{'name': 'Fade', 'current_price': 20, 'currency': 'USD', 'duration_min': 30},
                            {'name': 'Consult', 'current_price': 50, 'show_price_to_customer': False},
                            {'name': 'Beard trim', 'current_price': 12.5, 'currency': 'usd'}],
              'booking_open': False,
              'biz': {'settings': {'brand_kit': {'colors': {'primary': '#112233', 'accent': 'red;background:url(x)'}}}}}
    monkeypatch.setattr(agent_site, 'bundle_for', lambda business_id: bundle)
    facts = d.business_facts(BIZ)
    assert facts['offerings'] == [{'name': 'Fade', 'price': '$20', 'minutes': 30}, {'name': 'Consult'},
                                  {'name': 'Beard trim', 'price': '$12.50'}]
    # A hidden price stays hidden; a closed booking page is not advertised; only real colours pass.
    assert 'booking_url' not in facts and 'email' not in facts
    assert facts['brand_colors'] == {'primary': '#112233'}
    bundle['booking_open'] = True
    assert d.business_facts(BIZ)['booking_url'].endswith('/book')


def test_practitioner_design_is_scoped_to_its_own_business(monkeypatch):
    photo, logo = str(uuid4()), str(uuid4())
    monkeypatch.setattr(images, 'business', AsyncMock(return_value={'id': BIZ, 'owner_id': USER}))
    monkeypatch.setattr(images, 'artwork', AsyncMock(side_effect=lambda c, b, i: {'id': str(i), 'status': 'ready', 'storage_path': 'x'}))
    monkeypatch.setattr(images, 'original', AsyncMock(return_value=png()))
    monkeypatch.setattr(d, 'profile', AsyncMock(return_value={'logo_id': logo}))
    monkeypatch.setattr(d, 'business_facts', lambda business_id: {'name': 'Fade Lab'})
    req = d.flyer_request({'goal': 'Saturday special', 'exact_copy': 'Fades $20\n• Saturday 9 to 2',
                           'references': [{'id': photo}]})
    assert req.exact_copy == ['Fades $20', 'Saturday 9 to 2']
    spec = run(d.prepare_for_business(None, {'id': BIZ}, req, owner_request='Make me a flyer'))
    assert spec['scope'] == 'business' and spec['facts'] == {'name': 'Fade Lab'}
    # An unlabelled image is a photo to feature; the remembered logo rides along as a protected layer.
    assert [(r['id'], r['role']) for r in spec['references']] == [(photo, 'subject'), (logo, 'logo')]
    assert 'founder_offer' not in str(spec)
    from chief_flyer_direction import ReferenceInput
    chat = req.model_copy(update={'reference_inputs': [ReferenceInput(source='chat:1')]})
    with pytest.raises(HTTPException):
        run(d.prepare_for_business(None, {'id': BIZ}, chat, owner_request='x'))
    with pytest.raises(HTTPException):
        run(d.prepare_for_business(None, {'id': BIZ}, req.model_copy(update={'exact_copy': []}), owner_request='x'))


def test_business_designs_answer_to_their_own_limits_not_the_platform_budget(monkeypatch):
    import billing_limits
    import platform_chief_authority
    import spend_guard
    calls = []
    monkeypatch.setattr(spend_guard, 'over_budget', lambda business_id=None: calls.append(('spend', business_id)) or False)
    monkeypatch.setattr(billing_limits, 'require_units', lambda business_id: calls.append(('credits', business_id)))
    monkeypatch.setattr(platform_chief_authority, 'require_budget', AsyncMock(side_effect=AssertionError('platform budget')))
    run(d.guard(BIZ, 'business'))
    assert calls == [('spend', BIZ), ('credits', BIZ)]
    with pytest.raises(AssertionError):
        run(d.guard(BIZ))  # Mission Control's jobs still answer to the platform budget
    # Once the first render is paid, its free repair and review are never refused for credits.
    calls.clear()
    run(d.guard(BIZ, 'business', credits=False))
    assert calls == [('spend', BIZ)]
    assert d.scope_of({'director': {'version': 1}}) == 'platform'
    assert d.scope_of({'director': {'scope': 'business'}}) == 'business'


def test_a_repair_render_and_the_planning_calls_cost_no_credits(monkeypatch):
    import api_usage_logger
    from creative_director_render import render
    from creative_director_models import Plan
    row = dict(id=str(uuid4()), business_id=BIZ, model=images.MODELS[0], quality='high', size='1024x1536',
               director={'scope': 'business'})
    billed = []
    monkeypatch.setattr(d, 'guard', AsyncMock())
    monkeypatch.setattr(api_usage_logger, 'log_api_usage_sync', lambda **kw: billed.append(kw))
    async def record(**kw): billed.append(kw)
    monkeypatch.setattr(images, 'log_api_usage', record)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake-test-key')
    plan = {'concept': 'Bold', 'reference_analysis': 'None', 'typography': 'Condensed', 'composition': 'Centered',
            'palette': 'Navy', 'materials_light': 'Grain'}
    def respond(req):
        if '/images/' in str(req.url):
            return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(png()).decode()}],
                                             'usage': {'input_tokens': 10, 'output_tokens': 20}})
        return httpx.Response(200, json={'model': 'claude-sonnet-5', 'usage': {'input_tokens': 10, 'output_tokens': 20},
                                         'content': [{'type': 'tool_use', 'name': 'return_result', 'input': plan}]})
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            await d.structured(client, row, Plan, 'Plan this design', [{'type': 'text', 'text': 'brief'}])
            await render(client, row, 'first draft', [])
            await render(client, row, 'repair', [], charge=False)
    run(exercise())
    units = [b.get('units') for b in billed]
    assert units == [0, images.image_units('high'), 0]
    # A business's render shows under its own name in Costs, not Mission Control's.
    assert billed[1]['endpoint'] == '/ai/images/director/render'


# ── Chief's action ───────────────────────────────────────────────────────

def test_designed_flyer_uses_the_build_steps_own_image_identity(monkeypatch):
    seen = {}
    async def prepare(client, biz, req, **kw):
        seen['req'], seen['kw'] = req, kw
        return {'scope': 'business', 'references': [], 'goal': req.goal}
    async def create(req, client, *, director=None):
        seen['create'] = (req, director)
        return {'id': str(req.request_id), 'status': 'queued'}
    monkeypatch.setattr(images, 'db', AsyncMock(return_value=[]))
    monkeypatch.setattr(d, 'prepare_for_business', prepare)
    monkeypatch.setattr(images, 'create', create)
    turn, index = images.turn_id.set('order-1'), images.turn_image_index.set(0)
    try:
        result = run(d.handle_design_flyer(None, {'id': BIZ}, {'goal': 'Saturday special', 'exact_copy': ['Fades $20'],
                                                                'owner_request': 'Make me a flyer'}))
    finally:
        images.turn_id.reset(turn); images.turn_image_index.reset(index)
    req, director = seen['create']
    # The build's verify step looks for exactly this row.
    assert str(req.request_id) == stable_id(BIZ, 'order-1', 'image:0')
    assert director['scope'] == 'business' and seen['kw']['owner_request'] == 'Make me a flyer'
    assert result['result'] and result['label'] and result['type'] == 'design_flyer'


def test_a_replayed_flyer_returns_the_existing_card_without_paying_again(monkeypatch):
    existing = {'id': str(uuid4()), 'status': 'working'}
    monkeypatch.setattr(images, 'db', AsyncMock(return_value=[existing]))
    monkeypatch.setattr(images, 'present', AsyncMock(return_value=existing))
    monkeypatch.setattr(images, 'create', AsyncMock(side_effect=AssertionError('second paid job')))
    result = run(d.handle_design_flyer(None, {'id': BIZ}, {'goal': 'x', 'exact_copy': ['A']}))
    assert result['image'] == existing and result['result']


def test_design_flyer_is_a_class_c_explicit_request():
    import action_registry
    import chief_of_staff
    entry = action_registry.classification('design_flyer')
    assert entry['effect'] == action_registry.WRITE and entry['reversibility'] == 'C'
    assert chief_of_staff.ACTION_HANDLERS['design_flyer'] is d.handle_design_flyer


# ── The flyer work order ─────────────────────────────────────────────────

def test_flyer_orders_go_to_the_director_unless_switched_off(monkeypatch):
    monkeypatch.delenv('PRACTITIONER_CREATIVE_DIRECTOR', raising=False)
    o = flyer_order()
    assert [s.verb for s in plan_steps(o)] == ['design_flyer']
    # It prints only approved words, so it asks for them instead of inventing a headline.
    assert question(o)['field'] == 'exact_copy'
    o.facts['exact_copy'] = ['Fades $20']
    assert question(o) is None
    monkeypatch.setenv('PRACTITIONER_CREATIVE_DIRECTOR', 'off')
    old = flyer_order()
    assert [s.verb for s in plan_steps(old)] == ['generate_image'] and question(old) is None


def test_flyer_wording_and_reference_roles_are_validated():
    with pytest.raises(ValueError):
        flyer_order(references=[{'id': str(uuid4()), 'role': 'owner'}])
    with pytest.raises(ValueError):
        flyer_order(exact_copy=[1, 2])
    o = flyer_order(exact_copy='One line', references=[{'id': str(uuid4()), 'role': 'logo', 'use': 'Our logo'}])
    assert o.facts['exact_copy'] == ['One line'] and o.facts['references'][0]['role'] == 'logo'


def test_a_workshop_flyer_prints_only_the_saved_workshop_facts():
    f = {'title': 'Embrace the Shift Workshop', 'starts_at': '2026-10-13T19:00:00-04:00', 'timezone': 'America/Detroit',
         'location': '1084 Allen Avenue, Muskegon, MI', 'price': 0}
    assert runtime.event_flyer_copy(f) == ['Embrace the Shift Workshop', 'Tuesday, October 13, 2026 at 7:00 PM EDT',
                                           '1084 Allen Avenue, Muskegon, MI', 'Free']
    assert 'Free' not in runtime.event_flyer_copy({**f, 'price': None})


def test_designed_flyer_step_parameters_and_hold_wording(monkeypatch):
    o = WorkOrder.create({'kind': 'event_setup', 'facts': {'title': 'Embrace the Shift Workshop',
        'starts_at': '2026-10-13T19:00:00-04:00', 'timezone': 'America/Detroit', 'location': '1084 Allen Avenue',
        'price': 0, 'wants_flyer': True}}, business_id=BIZ, user_id=USER, turn_id='t', surface='desktop', words='Set up my workshop')
    adapter = runtime.Adapter(None, {'id': o.order_id, 'business_id': BIZ, 'user_id': USER}, 'lease', o)
    step = Step('flyer', 'design_flyer', 'Ready', sensitive=True)
    p = run(adapter.parameters(step, {}))
    assert p['exact_copy'][0] == 'Embrace the Shift Workshop' and p['exact_copy'][-1] == 'Free'
    assert p['references'] == [] and p['owner_request'] == 'Set up my workshop'
    assert 'checked before you see it' in run(adapter.confirmation(step, p))


def test_images_without_roles_become_a_revision_or_a_photo(monkeypatch):
    o = flyer_order(exact_copy=['A'])
    adapter = runtime.Adapter(None, {'id': o.order_id, 'business_id': BIZ, 'user_id': USER}, 'lease', o)
    generated, uploaded, older = str(uuid4()), str(uuid4()), str(uuid4())
    async def rows(table, extra=''):
        return [{'id': generated, 'model': 'gpt-image-2.5-sunburst'}, {'id': uploaded, 'model': None},
                {'id': older, 'model': 'gpt-image-2'}]
    adapter.rows = rows
    roles = run(adapter.reference_roles([uploaded, generated, older]))
    assert [r['role'] for r in roles] == ['subject', 'edit_target', 'style']


def test_designed_flyer_keeps_the_image_permission(monkeypatch):
    import policy_engine
    o = flyer_order(exact_copy=['A'])
    adapter = runtime.Adapter(None, {'id': o.order_id, 'business_id': BIZ, 'user_id': USER}, 'lease', o)
    verbs = []
    monkeypatch.setattr(runtime, 'owned_business', AsyncMock(return_value={'id': BIZ, 'owner_id': USER}))
    monkeypatch.setattr(policy_engine, 'evaluate', lambda *a, **kw: verbs.append(kw['verb']) or SimpleNamespace(allowed=True))
    run(adapter.assert_authority(Step('flyer', 'design_flyer', 'Ready', sensitive=True)))
    assert verbs == ['generate_image']


def test_chief_is_told_to_send_the_wording_only_when_the_director_is_on(monkeypatch):
    monkeypatch.setenv('CHIEF_BUILDS', 'on')
    monkeypatch.delenv('PRACTITIONER_CREATIVE_DIRECTOR', raising=False)
    assert 'exact_copy (every word' in runtime.routing_instructions()
    monkeypatch.setenv('PRACTITIONER_CREATIVE_DIRECTOR', 'off')
    assert runtime.FLYER_FACTS in runtime.routing_instructions()


# ── The practitioner's own design controls ───────────────────────────────

def test_business_design_controls_need_the_business_owner(monkeypatch):
    import sb_clients
    app = FastAPI(); app.include_router(d.business_router)
    client = TestClient(app)
    assert client.post(f'/ai/images/director/{uuid4()}/{uuid4()}/remember').status_code in (401, 403)
    assert client.get(f'/ai/images/director/{uuid4()}/{uuid4()}/master').status_code in (401, 403)
    app.dependency_overrides[sb_clients.authed_request] = lambda: SimpleNamespace(user=SimpleNamespace(id=USER))
    monkeypatch.setattr(images, 'business', AsyncMock(side_effect=HTTPException(403, 'Business access denied.')))
    assert client.post(f'/ai/images/director/{uuid4()}/{uuid4()}/remember').status_code == 403
    assert client.get(f'/ai/images/director/{uuid4()}/{uuid4()}/master').status_code == 403


def test_only_unpaid_steps_check_credits(monkeypatch):
    """Planning and the first render check credits; the review and the repair
    after a charged render do not, so the last 30 credits still buy a checked flyer."""
    from creative_director_render import render
    from creative_director_models import Plan, Review
    seen = []
    async def guard(business_id, scope='platform', *, credits=True):
        seen.append(credits)
        raise RuntimeError('stop before any provider call')
    monkeypatch.setattr(d, 'guard', guard)
    row = {'business_id': BIZ, 'director': {'scope': 'business'}, 'model': images.MODELS[0], 'quality': 'high', 'size': '1024x1536'}
    for call in (d.structured(None, row, Plan, 'plan', []), d.structured(None, row, Review, 'review', []),
                 render(None, row, 'draft', []), render(None, row, 'repair', [], charge=False)):
        with pytest.raises(RuntimeError):
            run(call)
    assert seen == [True, False, True, False]
