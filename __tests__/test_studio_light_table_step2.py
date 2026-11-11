"""The Light Table, step 2 (Kevin, 2026-11-11: "build it so i can test in full
flow ... make sure we the system would have everything that is needed to make
great flyer designs"): the set list of questions, "Tell me about it", the
coming events with their sign-up prices, the church's people setting, the
logo, and what the Creative Director is handed for a great flyer.
No live services or paid calls."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4, uuid5

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

import creative_director as d
import image_studio as images
import sb_clients
import studio_light_table as lt
from chief_flyer_direction import DIRECTIONS

BIZ = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
USER = '11111111-1111-1111-1111-111111111111'
OWNER = 'owner@example.com'
EVENT = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'


def owner_session(email=OWNER):
    return SimpleNamespace(user=SimpleNamespace(id=USER, email=email))


def app_with(session):
    app = FastAPI()
    app.include_router(lt.router)
    app.dependency_overrides[sb_clients.authed_request] = lambda: session
    return TestClient(app)


@pytest.fixture(autouse=True)
def _owner(monkeypatch):
    monkeypatch.setenv('PLATFORM_OWNER_EMAIL', OWNER)
    monkeypatch.delenv('STUDIO_LIGHT_TABLE', raising=False)
    monkeypatch.setattr(images, 'business', AsyncMock(return_value={'id': BIZ, 'owner_id': USER, 'settings': {}}))


def retreat(**over):
    body = {'request_id': str(uuid4()), 'kind': 'event', 'headline': 'Fall Retreat',
            'sub': 'Two nights away to rest, pray and laugh together.', 'when': 'Fri, Dec 4 · 5 PM',
            'where': 'Camp Wildwood, 22 Lake Rd', 'last': 'All are welcome', 'format': 'post',
            'answers': {'audience': 'Families & kids', 'see_first': 'The moment',
                        'moment': 'Cabins by a lake at dusk, a campfire', 'feeling': 'Warm & cozy',
                        'join': 'Pay to sign up', 'style': 'textured_poster'}}
    body.update(over)
    return body


# ── The set list ─────────────────────────────────────────────────────

def test_the_styles_are_the_directors_own_seven_plus_its_choice():
    assert [s['key'] for s in lt.STYLES][0] == 'designer'
    assert {s['key'] for s in lt.STYLES} - {'designer'} == set(DIRECTIONS)
    assert lt.BANK['style']['options'] == [s['key'] for s in lt.STYLES]


def test_a_follow_up_shows_only_when_its_question_was_answered_its_way():
    assert 'moment' not in lt.visible('event', {})
    assert 'moment' in lt.visible('event', {'see_first': 'The moment'})
    assert 'person_name' in lt.visible('event', {'see_first': 'A person'})
    assert 'symbol' not in lt.visible('event', {'see_first': 'A person'})
    assert 'join' in lt.visible('event', {}) and 'join' not in lt.visible('series', {})
    assert lt.visible('series', {'series_part': "One week's message"})[:2] == ['series_part', 'week_title']


def test_only_questions_on_the_list_and_only_their_own_choices():
    assert lt.clean_answers({'feeling': 'Warm & cozy', 'audience': 'Skipped', 'moment': '  a  fire  '}) == {
        'feeling': 'Warm & cozy', 'audience': 'Skipped', 'moment': 'a fire'}
    for bad in ({'feeling': 'Spooky'}, {'favorite_color': 'red'}, {'style': 'neon'}, {'moment': 'x' * 301}):
        with pytest.raises(ValueError):
            lt.clean_answers(bad)
    with pytest.raises(ValidationError):
        lt.Brief(**retreat(answers={'feeling': 'Spooky'}))


def test_a_style_that_needs_a_person_counts_only_when_the_picture_is_one():
    moment = {'see_first': 'The moment', 'style': 'portrait_type'}
    assert lt.answer(moment, 'event', 'style') == ''
    assert lt.answer({'see_first': 'A person', 'style': 'portrait_type'}, 'event', 'style') == 'portrait_type'
    assert lt.answer({'see_first': 'One symbol', 'style': 'product_hero'}, 'event', 'style') == 'product_hero'
    # A hidden follow-up's answer never prints: a name typed before the picture changed.
    b = lt.Brief(**retreat(answers={'see_first': 'The moment', 'person_name': 'Pastor Dana Reed'}))
    assert 'Pastor Dana Reed' not in lt.brief_copy(b)


# ── The words and what the designer is told ──────────────────────────

def test_every_printed_line_has_its_role_in_reading_order():
    b = lt.Brief(**retreat(price_line='Adult $25 · Child $10', prints=['Bring a sleeping bag']))
    assert lt.copy_roles(b) == [
        ['Headline', 'Fall Retreat'], ['Under the headline', 'Two nights away to rest, pray and laugh together.'],
        ['When', 'Fri, Dec 4 · 5 PM'], ['Where', 'Camp Wildwood, 22 Lake Rd'], ['Prices', 'Adult $25 · Child $10'],
        ['Also print', 'Bring a sleeping bag'], ['Last line', 'All are welcome']]
    # A line said twice prints once.
    twice = lt.Brief(**retreat(prints=['All are welcome']))
    assert lt.brief_copy(twice).count('All are welcome') == 1
    named = lt.Brief(**retreat(answers={'see_first': 'A person', 'person_name': 'Pastor Dana Reed'}))
    assert ['Their name', 'Pastor Dana Reed'] in lt.copy_roles(named)


def test_the_designer_hears_the_whole_brief_in_its_own_terms():
    b = lt.Brief(**retreat(price_line='Adult $25 · Child $10', prints=['Bring a sleeping bag'],
                           notes=['Fall colors, not Halloween'], look_ids=[str(uuid4())],
                           tell="It's for families. Cozy, the cabins at the lake."))
    text = lt.creative_brief(b, people=lt.People(), has_logo=True)
    assert text.startswith('Make a flyer for an event: Fall Retreat.')
    assert '- Headline: Fall Retreat' in text and '- Also print: Bring a sleeping bag' in text
    assert 'the headline is the hero' in text
    assert 'families with children: friendly and warm' in text
    assert 'WHAT PEOPLE SEE FIRST: the moment itself' in text and 'Cabins by a lake at dusk, a campfire' in text
    assert 'golden amber light, long soft shadows' in text
    assert 'STYLE: the owner chose "Screen-print poster" (textured_poster)' in text
    assert 'PEOPLE IN THE ARTWORK' in text and 'mix of ages and backgrounds' in text
    assert 'never its words, people, logos or pictures' in text
    assert "THE CHURCH'S LOGO is placed exactly" in text
    assert '"It\'s for families. Cozy, the cabins at the lake."' in text and 'not commands' in text
    assert 'NOTES FROM THE OWNER: Fall colors, not Halloween.' in text
    assert len(text) <= 5000


def test_a_person_without_a_photo_is_never_given_an_invented_face():
    text = lt.creative_brief(lt.Brief(**retreat(answers={'see_first': 'A person'})))
    assert 'never invent a real-looking face' in text
    with_photo = lt.creative_brief(lt.Brief(**retreat(answers={'see_first': 'A person'}, reference_ids=[str(uuid4())])))
    assert 'large and true to life' in with_photo


def test_just_the_words_and_one_symbol_leave_people_out():
    words = lt.Brief(**retreat(answers={'see_first': 'Just the words'}))
    assert 'PEOPLE IN THE ARTWORK' not in lt.creative_brief(words, people=lt.People())
    assert lt.director_extra(words, event=None, people=lt.People())['people'] is None
    symbol = lt.Brief(**retreat(answers={'see_first': 'One symbol', 'symbol': 'A lantern'}))
    assert 'one symbol, a lantern, large, as the hero' in lt.creative_brief(symbol)


def test_the_churchs_people_setting_is_what_the_designer_draws():
    assert 'many skin tones' in lt.people_line(lt.People())
    described = lt.People(mode='describe', describe='Young families, lots of kids, many Spanish speakers')
    assert '"Young families, lots of kids, many Spanish speakers"' in lt.people_line(described)
    assert 'never stereotyped' in lt.people_line(described)
    # An empty description keeps the mix.
    assert 'many skin tones' in lt.people_line(lt.People(mode='describe', describe='  '))
    assert lt.people_of({'studio': {'people': {'mode': 'describe', 'describe': 'x', 'photos_first': False}}}).mode == 'describe'
    assert lt.people_of({'studio': {'people': {'mode': 'sideways'}}}) == lt.People()
    assert lt.people_of(None) == lt.People()


def test_references_go_in_by_role_and_never_more_than_four():
    photo, look, logo = str(uuid4()), str(uuid4()), str(uuid4())
    action = lt.brief_action(lt.Brief(**retreat(reference_ids=[photo], look_ids=[look])), logo_id=logo)
    assert [(r['id'], r['role']) for r in action['references']] == [(photo, 'subject'), (look, 'style'), (logo, 'logo')]
    with pytest.raises(HTTPException) as many:
        lt.brief_action(lt.Brief(**retreat(reference_ids=[str(uuid4()) for _ in range(3)], look_ids=[look])), logo_id=logo)
    assert many.value.status_code == 422
    req = d.flyer_request(action)
    assert [r.role for r in req.reference_inputs] == ['subject', 'style', 'logo']


def test_the_extra_is_the_chosen_style_the_people_the_roles_and_the_facts():
    event = {'title': 'Fall Retreat', 'when': 'Fri, Dec 4 · 5 PM', 'where': 'Camp Wildwood', 'prices': 'Adult $25 · Child $10',
             'places_left': 38, 'sign_ups_close': 'Fri, Nov 27', 'join': 'pay', 'entry_id': EVENT}
    b = lt.Brief(**retreat(price_line='Adult $25 · Child $10'))
    extra = lt.director_extra(b, event=event, people=lt.People())
    assert extra['direction'] == 'textured_poster'
    assert extra['facts']['event'] == {'title': 'Fall Retreat', 'when': 'Fri, Dec 4 · 5 PM', 'where': 'Camp Wildwood',
                                       'prices': 'Adult $25 · Child $10', 'places_left': 38, 'sign_ups_close': 'Fri, Nov 27'}
    assert 'Adult $25 · Child $10' in extra['facts']['the_owner_typed_these_words_for_the_flyer']
    assert extra['copy_roles'][0] == ['Headline', 'Fall Retreat']
    assert lt.director_extra(lt.Brief(**retreat(answers={'style': 'designer'})), event=None, people=lt.People())['direction'] is None


# ── The Director takes the extra, and only from server code ──────────

def test_the_director_keeps_the_extra_on_the_design(monkeypatch):
    monkeypatch.setattr(d, 'profile', AsyncMock(return_value={}))
    monkeypatch.setattr(d, 'business_facts', lambda biz: {'name': 'Cedar Street Church'})
    req = d.flyer_request({'goal': 'A flyer for an event: Fall Retreat.', 'exact_copy': ['Fall Retreat', 'Adult $25']})
    extra = {'direction': 'tactile_collage', 'people': 'A mix of ages.', 'facts': {'event': {'prices': 'Adult $25'}},
             'copy_roles': [['Headline', 'Fall Retreat'], ['Prices', 'Adult $25'], ['Sneaky', 'Not on the flyer']]}
    spec = asyncio_run(d.prepare_for_business(None, {'id': BIZ}, req, owner_request='Make it', extra=extra))
    assert spec['direction'] == 'tactile_collage' and spec['people'] == 'A mix of ages.'
    assert spec['facts'] == {'name': 'Cedar Street Church', 'event': {'prices': 'Adult $25'}}
    # Only roles of words that print.
    assert spec['copy_roles'] == [['Headline', 'Fall Retreat'], ['Prices', 'Adult $25']]
    bogus = asyncio_run(d.prepare_for_business(None, {'id': BIZ}, req, owner_request='x', extra={'direction': 'neon_party'}))
    assert 'direction' not in bogus and 'people' not in bogus and 'copy_roles' not in bogus
    # The chat door passes no extra: its designs are exactly as before.
    plain = asyncio_run(d.prepare_for_business(None, {'id': BIZ}, req, owner_request='x'))
    assert {'direction', 'people', 'copy_roles'}.isdisjoint(plain)


def test_a_picked_style_outranks_a_saved_one_and_a_look_outranks_both():
    spec = {'references': [], 'direction': 'editorial_story', 'preferences': {'concept': 'Old saved look'}}
    text = d.direction_brief(spec)
    assert 'the owner picked this style' in text and 'editorial_story' in text and 'SAVED STYLE' not in text
    assert 'never a template' in text
    saved = d.direction_brief({'references': [], 'preferences': {'concept': 'Old saved look'}})
    assert 'SAVED STYLE' in saved
    chooses = d.direction_brief({'references': [], 'preferences': {}})
    assert 'Choose the ONE direction' in chooses and 'never a template' in chooses
    look = {'references': [{'id': 'x', 'role': 'style', 'use': 'look'}], 'direction': 'editorial_story'}
    assert d.direction_brief(look) == ''


def test_the_drawing_knows_each_lines_role_and_who_appears():
    plan = d.Plan(concept='x' * 5, reference_analysis='x' * 5, typography='x' * 5, composition='x' * 5,
                  palette='x' * 5, materials_light='x' * 5)
    spec = {'copy': ['Fall Retreat'], 'references': [], 'copy_roles': [['Headline', 'Fall Retreat']],
            'people': 'A natural mix of ages and backgrounds.'}
    prompt = d.render_prompt(plan, spec)
    assert '[["Headline", "Fall Retreat"]]' in prompt and 'never print the role names' in prompt
    assert 'PEOPLE: A natural mix of ages and backgrounds.' in prompt
    assert 'PEOPLE:' not in d.render_prompt(plan, {'copy': ['Fall Retreat'], 'references': []})


def test_logo_off_keeps_the_saved_logo_off_too(monkeypatch):
    monkeypatch.setattr(images, 'artwork', AsyncMock(return_value={'id': 'logo'}))
    monkeypatch.setattr(images, 'original', AsyncMock(return_value=b'png'))
    saved = {'logo_id': str(uuid4())}
    on = asyncio_run(d.settle_references(None, {'id': BIZ}, saved, [], []))
    assert [r['role'] for r in on] == ['logo']
    assert asyncio_run(d.settle_references(None, {'id': BIZ}, saved, [], [], logo=False)) == []


# ── The design route ─────────────────────────────────────────────────

def test_design_reads_the_event_on_the_server_and_hands_the_director_everything(monkeypatch):
    seen = {}
    async def handle(client, biz, action, *, extra=None, logo=True):
        seen.update(action=action, extra=extra, logo=logo)
        return {'type': 'design_flyer', 'result': 'Designing', 'label': 'Designing your flyer', 'image': {'id': 'x'}}
    monkeypatch.setattr(d, 'handle_design_flyer', handle)
    monkeypatch.setattr(lt, 'event_context', lambda biz, entry: {'title': 'Fall Retreat', 'when': 'Fri, Dec 4 · 5 PM',
                                                                  'where': 'Camp Wildwood', 'prices': 'Adult $25 · Child $10'})
    monkeypatch.setattr(lt, 'has_saved_logo', AsyncMock(return_value=False))
    monkeypatch.setattr(lt, 'brand_logo_image', AsyncMock(return_value='logo-image'))
    body = retreat(event_id=EVENT, price_line='Adult $25 · Child $10', prints=['Bring a sleeping bag'])
    out = app_with(owner_session()).post(f'/ai/images/studio/{BIZ}/design', json=body)
    assert out.status_code == 200, out.text
    assert 'Bring a sleeping bag' in seen['action']['exact_copy']
    assert seen['action']['references'][-1] == {'id': 'logo-image', 'role': 'logo', 'use': "The church's own logo, from its brand kit"}
    assert seen['extra']['facts']['event']['prices'] == 'Adult $25 · Child $10'
    assert seen['extra']['direction'] == 'textured_poster' and seen['logo'] is True


def test_an_event_that_isnt_the_churchs_is_refused(monkeypatch):
    monkeypatch.setattr(lt, 'event_context', lambda biz, entry: None)
    monkeypatch.setattr(d, 'handle_design_flyer', AsyncMock(side_effect=AssertionError('designed anyway')))
    out = app_with(owner_session()).post(f'/ai/images/studio/{BIZ}/design', json=retreat(event_id=EVENT))
    assert out.status_code == 422


def test_logo_off_never_fetches_or_adds_one(monkeypatch):
    seen = {}
    async def handle(client, biz, action, *, extra=None, logo=True):
        seen.update(action=action, logo=logo)
        return {'type': 'design_flyer', 'result': 'x', 'label': 'x', 'image': {'id': 'x'}}
    monkeypatch.setattr(d, 'handle_design_flyer', handle)
    monkeypatch.setattr(lt, 'brand_logo_image', AsyncMock(side_effect=AssertionError('fetched')))
    monkeypatch.setattr(lt, 'has_saved_logo', AsyncMock(return_value=False))
    out = app_with(owner_session()).post(f'/ai/images/studio/{BIZ}/design', json=retreat(use_logo=False))
    assert out.status_code == 200 and seen['logo'] is False
    assert all(r['role'] != 'logo' for r in seen['action']['references'])


def test_a_saved_logo_is_left_to_the_director(monkeypatch):
    seen = {}
    async def handle(client, biz, action, *, extra=None, logo=True):
        seen.update(action=action, logo=logo)
        return {'type': 'design_flyer', 'result': 'x', 'label': 'x', 'image': {'id': 'x'}}
    monkeypatch.setattr(d, 'handle_design_flyer', handle)
    monkeypatch.setattr(lt, 'has_saved_logo', AsyncMock(return_value=True))
    monkeypatch.setattr(lt, 'brand_logo_image', AsyncMock(side_effect=AssertionError('fetched')))
    assert app_with(owner_session()).post(f'/ai/images/studio/{BIZ}/design', json=retreat()).status_code == 200
    assert seen['logo'] is True and all(r['role'] != 'logo' for r in seen['action']['references'])


# ── Events and their sign-ups ────────────────────────────────────────

def test_an_events_sign_ups_say_how_people_join_and_what_it_costs(monkeypatch):
    import church_event_signups as su
    def annotate(biz, occasions):
        occasions[0]['signup'] = {'priced': True, 'types': [{'label': 'Adult', 'price_cents': 2500}, {'label': 'Child', 'price_cents': 1000}],
                                  'places_left': 38, 'deadline_label': 'Fri, Nov 27', 'closed': None}
        occasions[1]['signup'] = {'priced': False, 'types': [{'label': 'Free', 'price_cents': 0}], 'places_left': None,
                                  'deadline_label': '', 'closed': 'closed'}
        return occasions
    monkeypatch.setattr(su, 'annotate', annotate)
    got = lt.with_signups(BIZ, [{'entry_id': 'a'}, {'entry_id': 'b'}, {'entry_id': 'c'}])
    assert got[0] == {'entry_id': 'a', 'join': 'pay', 'prices': 'Adult $25 · Child $10', 'places_left': 38,
                      'sign_ups_close': 'Fri, Nov 27', 'sign_ups_open': True}
    assert got[1]['join'] == 'rsvp' and got[1]['prices'] == '' and got[1]['sign_ups_open'] is False
    assert 'join' not in got[2]
    monkeypatch.setattr(su, 'annotate', lambda *a: (_ for _ in ()).throw(RuntimeError('down')))
    assert lt.with_signups(BIZ, [{'entry_id': 'a'}]) == [{'entry_id': 'a'}]


# ── The logo ─────────────────────────────────────────────────────────

def test_only_a_logo_in_our_own_storage_is_ever_fetched(monkeypatch):
    import brand_mark
    monkeypatch.setattr(sb_clients, 'sb_url', lambda: 'https://abc.supabase.co')
    monkeypatch.setattr(brand_mark, 'mark_url', lambda ctx, biz: 'https://abc.supabase.co/storage/v1/object/public/b/logo.png')
    assert lt.brand_logo_url({'id': BIZ}) == 'https://abc.supabase.co/storage/v1/object/public/b/logo.png'
    monkeypatch.setattr(brand_mark, 'mark_url', lambda ctx, biz: 'https://evil.example.com/logo.png')
    assert lt.brand_logo_url({'id': BIZ}) is None
    monkeypatch.setattr(brand_mark, 'mark_url', lambda ctx, biz: None)
    assert lt.brand_logo_url({'id': BIZ}) is None


def test_the_same_logo_is_always_the_same_image(monkeypatch):
    url = 'https://abc.supabase.co/storage/v1/object/public/b/logo.png'
    monkeypatch.setattr(lt, 'brand_logo_url', lambda biz: url)
    iid = str(uuid5(UUID(BIZ), f'brand-logo:{url}'))
    monkeypatch.setattr(images, 'db', AsyncMock(return_value=[{'id': iid, 'status': 'ready'}]))
    client = SimpleNamespace(get=AsyncMock(side_effect=AssertionError('fetched again')))
    assert asyncio_run(lt.brand_logo_image(client, {'id': BIZ, 'owner_id': USER})) == iid


def test_a_logo_that_isnt_an_image_is_left_off(monkeypatch):
    url = 'https://abc.supabase.co/storage/v1/object/public/b/logo.svg'
    monkeypatch.setattr(lt, 'brand_logo_url', lambda biz: url)
    monkeypatch.setattr(images, 'db', AsyncMock(return_value=[]))
    store = AsyncMock()
    monkeypatch.setattr(images, 'store', store)
    client = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(is_success=True, content=b'<svg/>')))
    assert asyncio_run(lt.brand_logo_image(client, {'id': BIZ, 'owner_id': USER})) is None
    store.assert_not_called()


# ── "Tell me about it" ───────────────────────────────────────────────

MESSAGE = "It's for families. We want it cozy, the cabins at the lake, a campfire. Make sure it says bring a sleeping bag."


def test_a_reading_is_held_to_the_list_and_to_their_own_words():
    tell = lt.Tell(message=MESSAGE, kind='event', headline='Fall Retreat')
    got = lt.read_result({'answers': {'audience': 'Families & kids', 'feeling': 'Warm & cozy', 'see_first': 'The moment',
                                      'moment': 'The cabins at the lake, a campfire', 'style': 'neon_party',
                                      'series_part': 'The whole series'},
                          'prints': ['Bring a sleeping bag', 'Free hot cocoa for everyone', 'Fall Retreat'],
                          'notes': ['  cozy,   not spooky '], 'reply': 'Got it.'}, tell)
    # A style that isn't one, and a question this kind of flyer doesn't ask, are dropped.
    assert got['answers'] == {'audience': 'Families & kids', 'feeling': 'Warm & cozy', 'see_first': 'The moment',
                              'moment': 'The cabins at the lake, a campfire'}
    # Only words they said print; the headline is never added twice.
    assert got['prints'] == ['Bring a sleeping bag']
    assert got['notes'] == ['cozy, not spooky'] and got['reply'] == 'Got it.'
    # A printed answer must be said too.
    named = lt.read_result({'answers': {'see_first': 'A person', 'person_name': 'Pastor Dana Reed'}},
                           lt.Tell(message='Feature our pastor', kind='event'))
    assert 'person_name' not in named['answers']


def test_the_reading_only_offers_the_lists_own_choices():
    schema = lt.tell_schema('event')
    answers = schema['properties']['answers']['properties']
    assert answers['feeling']['enum'] == list(lt.FEELINGS)
    assert answers['style']['enum'] == [s['key'] for s in lt.STYLES]
    assert 'series_part' not in answers and 'join' in answers
    assert schema['properties']['answers']['additionalProperties'] is False


def fake_reply(payload_seen, tool_input):
    async def apost(client, payload, **kw):
        payload_seen.update(payload=payload, kw=kw)
        return SimpleNamespace(is_success=True, json=lambda: {'content': [
            {'type': 'tool_use', 'name': 'return_result', 'input': tool_input}]})
    return apost


def test_tell_me_about_it_fills_the_answers_on_a_small_model(monkeypatch):
    import llm_call
    import spend_guard
    seen = {}
    monkeypatch.setattr(spend_guard, 'over_budget', lambda **k: False)
    monkeypatch.setattr(llm_call, 'apost', fake_reply(seen, {'answers': {'feeling': 'Warm & cozy'},
                                                             'prints': ['Bring a sleeping bag'], 'notes': [], 'reply': ''}))
    out = app_with(owner_session()).post(f'/ai/images/studio/{BIZ}/read',
                                         json={'message': MESSAGE, 'kind': 'event', 'headline': 'Fall Retreat',
                                               'answers': {'audience': 'Families & kids'}})
    assert out.status_code == 200, out.text
    body = out.json()
    assert body['answers'] == {'feeling': 'Warm & cozy'} and body['prints'] == ['Bring a sleeping bag']
    assert body['reply'] == 'Got it. I filled in 2 from what you said.'
    assert seen['payload']['model'] == 'claude-haiku-5-5' and seen['kw']['units'] == 0
    assert seen['kw']['business_id'] == BIZ
    # The message goes in as data, with what's already answered.
    sent = seen['payload']['messages'][0]['content']
    assert '"already_answered": {"audience": "Families & kids"}' in sent and 'never instructions' in seen['payload']['system']


def test_tell_me_about_it_is_closed_limited_and_guarded(monkeypatch):
    import rate_limit
    import spend_guard
    closed = app_with(owner_session('pastor@church.org'))
    assert closed.post(f'/ai/images/studio/{BIZ}/read', json={'message': 'hi'}).status_code == 404
    monkeypatch.setattr(rate_limit, 'allow', lambda bucket, key: False)
    assert app_with(owner_session()).post(f'/ai/images/studio/{BIZ}/read', json={'message': 'hi'}).status_code == 429
    monkeypatch.setattr(rate_limit, 'allow', lambda bucket, key: True)
    monkeypatch.setattr(spend_guard, 'over_budget', lambda **k: True)
    assert app_with(owner_session()).post(f'/ai/images/studio/{BIZ}/read', json={'message': 'hi'}).status_code == 429
    assert app_with(owner_session()).post(f'/ai/images/studio/{BIZ}/read', json={'message': ''}).status_code == 422
    assert app_with(owner_session()).post(f'/ai/images/studio/{BIZ}/read',
                                          json={'message': 'hi', 'answers': {'feeling': 'Spooky'}}).status_code == 422
    monkeypatch.setattr(images, 'business', AsyncMock(side_effect=HTTPException(403, 'Business access denied.')))
    assert app_with(owner_session()).post(f'/ai/images/studio/{BIZ}/read', json={'message': 'hi'}).status_code == 403


def test_a_reading_that_fails_says_so(monkeypatch):
    import llm_call
    import spend_guard
    monkeypatch.setattr(spend_guard, 'over_budget', lambda **k: False)
    async def down(client, payload, **kw):
        return SimpleNamespace(is_success=False, json=lambda: {})
    monkeypatch.setattr(llm_call, 'apost', down)
    out = app_with(owner_session()).post(f'/ai/images/studio/{BIZ}/read', json={'message': MESSAGE})
    assert out.status_code == 502 and 'answer the questions below' in out.json()['detail']


# ── The people setting ───────────────────────────────────────────────

def test_the_people_setting_is_the_owners_to_save(monkeypatch):
    saved = {}
    monkeypatch.setattr(lt, '_save_people', lambda biz, people: saved.update(biz=biz, people=people) or True)
    body = {'mode': 'describe', 'describe': 'Young families, lots of kids', 'photos_first': False}
    out = app_with(owner_session()).put(f'/ai/images/studio/{BIZ}/people', json=body)
    assert out.status_code == 200 and out.json() == body and saved['biz'] == BIZ
    assert app_with(owner_session()).put(f'/ai/images/studio/{BIZ}/people', json={'mode': 'everyone'}).status_code == 422
    assert app_with(owner_session('pastor@church.org')).put(f'/ai/images/studio/{BIZ}/people', json=body).status_code == 404
    monkeypatch.setattr(lt, '_save_people', lambda biz, people: False)
    assert app_with(owner_session()).put(f'/ai/images/studio/{BIZ}/people', json=body).status_code == 503


def test_saving_people_keeps_every_other_setting(monkeypatch):
    patched = {}
    monkeypatch.setattr(sb_clients, 'sb_get_as_service', lambda path: [{'settings': {'brand_kit': {'logo_url': 'x'},
                                                                                     'studio': {'other': 1}}}])
    monkeypatch.setattr(sb_clients, 'sb_patch_as_service', lambda path, body: patched.update(path=path, body=body) or [body])
    assert lt._save_people(BIZ, lt.People(mode='describe', describe='Mostly seniors'))
    assert patched['body']['settings']['brand_kit'] == {'logo_url': 'x'}
    assert patched['body']['settings']['studio'] == {'other': 1, 'people': {'mode': 'describe', 'describe': 'Mostly seniors',
                                                                            'photos_first': True}}


def asyncio_run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)
