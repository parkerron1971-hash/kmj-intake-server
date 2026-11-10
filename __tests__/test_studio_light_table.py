"""The Light Table: the Studio's brief becomes the same Creative Director flyer
Chief makes from a chat. No live services or paid calls."""
import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import creative_director as d
import image_studio as images
import sb_clients
import studio_light_table as lt

BIZ = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
USER = '11111111-1111-1111-1111-111111111111'
OWNER = 'owner@example.com'


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
    monkeypatch.setattr(images, 'business', AsyncMock(return_value={'id': BIZ, 'owner_id': USER}))


def brief(**over):
    body = {'request_id': str(uuid4()), 'kind': 'event', 'headline': 'Harvest Night',
            'sub': 'Food, music and a fire pit for the whole family.', 'when': 'Sat, Nov 21 · 6 PM',
            'where': 'Cedar Street Church, 410 Cedar St', 'last': 'All are welcome', 'format': 'post'}
    body.update(over)
    return body


# ── The switch ──────────────────────────────────────────────────────

def test_the_switch_opens_for_the_owner_first(monkeypatch):
    assert lt.mode() == 'owner'
    assert lt.open_to(owner_session().user)
    assert not lt.open_to(owner_session('pastor@church.org').user)
    monkeypatch.setenv('STUDIO_LIGHT_TABLE', 'on')
    assert lt.open_to(owner_session('pastor@church.org').user)
    monkeypatch.setenv('STUDIO_LIGHT_TABLE', 'off')
    assert not lt.open_to(owner_session().user)
    monkeypatch.setenv('STUDIO_LIGHT_TABLE', 'sideways')
    assert lt.mode() == 'off'


def test_closed_the_app_keeps_the_old_studio_and_design_is_not_there(monkeypatch):
    client = app_with(owner_session('pastor@church.org'))
    monkeypatch.setattr(lt, 'next_occasion', lambda *a, **k: (_ for _ in ()).throw(AssertionError('read while closed')))
    assert client.get(f'/ai/images/studio/{BIZ}').json() == {'light_table': False}
    assert client.post(f'/ai/images/studio/{BIZ}/design', json=brief()).status_code == 404


def test_only_the_business_owner_reaches_the_studio(monkeypatch):
    monkeypatch.setattr(images, 'business', AsyncMock(side_effect=HTTPException(403, 'Business access denied.')))
    client = app_with(owner_session())
    assert client.get(f'/ai/images/studio/{BIZ}').status_code == 403
    assert client.post(f'/ai/images/studio/{BIZ}/design', json=brief()).status_code == 403
    bare = FastAPI(); bare.include_router(lt.router)
    assert TestClient(bare).get(f'/ai/images/studio/{BIZ}').status_code in (401, 403)


def test_open_the_studio_says_what_a_flyer_costs_and_where_to_start(monkeypatch):
    import credit_ledger
    monkeypatch.setattr(credit_ledger, 'flyer_credits', lambda: 30)
    seen = {}
    def occasion(business_id, **k):
        seen['biz'] = business_id
        return {'headline': 'Harvest Night', 'when': 'Sat, Nov 21 · 6 PM'}
    monkeypatch.setattr(lt, 'next_occasion', occasion)
    body = app_with(owner_session()).get(f'/ai/images/studio/{BIZ}').json()
    assert body['light_table'] is True and body['flyer_credits'] == 30
    assert body['formats'] == ['post', 'story', 'wide']
    assert body['suggestion']['headline'] == 'Harvest Night' and seen['biz'] == BIZ


# ── The brief becomes Chief's flyer request ──────────────────────────

def test_the_brief_is_the_same_flyer_chief_makes(monkeypatch):
    seen = {}
    async def handle(client, biz, action):
        seen['biz'], seen['action'] = biz, action
        seen['turn'], seen['index'] = images.turn_id.get(), images.turn_image_index.get()
        return {'type': 'design_flyer', 'result': 'Designing', 'label': 'Designing your flyer', 'image': {'id': 'x'}}
    monkeypatch.setattr(d, 'handle_design_flyer', handle)
    body = brief(format='story')
    out = app_with(owner_session()).post(f'/ai/images/studio/{BIZ}/design', json=body)
    assert out.status_code == 200 and out.json()['image'] == {'id': 'x'}
    action = seen['action']
    # Only the brief's words, in reading order: the review checks each one.
    assert action['exact_copy'] == ['Harvest Night', 'Food, music and a fire pit for the whole family.',
                                    'Sat, Nov 21 · 6 PM', 'Cedar Street Church, 410 Cedar St', 'All are welcome']
    assert action['size'] == '1088x1920' and 'Harvest Night' in action['goal']
    # The request id is the identity, so a retried tap never pays twice.
    assert seen['turn'] == f"studio:{body['request_id']}" and seen['index'] == 0
    assert images.turn_id.get() == ''


def test_empty_lines_are_left_out_and_a_headline_is_required(monkeypatch):
    action = lt.brief_action(lt.Brief(**brief(sub='  ', where='', last='')))
    assert action['exact_copy'] == ['Harvest Night', 'Sat, Nov 21 · 6 PM']
    assert action['size'] == '1088x1360'
    with pytest.raises(HTTPException) as no_headline:
        lt.brief_action(lt.Brief(**brief(headline='   ')))
    assert no_headline.value.status_code == 422
    assert app_with(owner_session()).post(f'/ai/images/studio/{BIZ}/design', json=brief(headline='')).status_code == 422
    assert app_with(owner_session()).post(f'/ai/images/studio/{BIZ}/design', json=brief(price='$5')).status_code == 422


def test_an_added_photo_is_drawn_from_and_the_logo_is_left_to_the_director():
    photo = uuid4()
    action = lt.brief_action(lt.Brief(**brief(reference_ids=[str(photo)])))
    assert action['references'] == [{'id': str(photo), 'role': 'subject', 'use': 'A photo the owner added for this flyer'}]
    req = d.flyer_request(action)
    assert [r.source for r in req.reference_inputs] == [f'artwork:{photo}']
    assert req.size == '1088x1360' and req.exact_copy[0] == 'Harvest Night'


# ── The calendar's next occasion ─────────────────────────────────────

def test_when_reads_the_way_a_flyer_says_it():
    assert lt.when_words('2026-11-21T18:00') == 'Sat, Nov 21 · 6 PM'
    assert lt.when_words('2026-11-22T10:30:00') == 'Sun, Nov 22 · 10:30 AM'
    assert lt.when_words('2026-11-22T12:00') == 'Sun, Nov 22 · 12 PM'
    assert lt.when_words('2026-11-22') == 'Sun, Nov 22'
    assert lt.when_words('soon') == '' and lt.when_words(None) == ''


def test_the_next_occasion_skips_services_private_and_past_ones(monkeypatch):
    import church_checkin
    mod = {'id': 'm1', 'name': 'Services & Events', 'archetype_params': {}}
    entries = [
        {'id': 'past', 'module_id': 'm1', 'data': {'title': 'Fall Picnic', 'date': '2026-11-01T12:00'}},
        {'id': 'svc', 'module_id': 'm1', 'data': {'title': 'Sunday Worship', 'date': '2026-11-15T10:00', 'type': 'service'}},
        {'id': 'priv', 'module_id': 'm1', 'data': {'title': 'Elders retreat', 'date': '2026-11-12T09:00', 'private': True}},
        {'id': 'later', 'module_id': 'm1', 'data': {'title': 'Christmas Eve', 'date': '2026-12-24T19:00'}},
        {'id': 'next', 'module_id': 'm1', 'data': {'title': 'Harvest Night', 'date': '2026-11-21T18:00',
                                                   'location': 'Fellowship Hall',
                                                   'description': 'Food, music and a fire pit. Bring a chair.'}},
        {'id': 'far', 'module_id': 'm1', 'data': {'title': 'Spring Revival', 'date': '2027-04-01T19:00'}},
    ]
    monkeypatch.setattr(church_checkin, '_roster', lambda biz: [mod])
    monkeypatch.setattr(church_checkin, '_entries', lambda biz, ids: entries)
    got = lt.next_occasion(BIZ, now=datetime(2026, 11, 9, 9, 0))
    assert got == {'entry_id': 'next', 'kind': 'event', 'headline': 'Harvest Night',
                   'sub': 'Food, music and a fire pit.', 'when': 'Sat, Nov 21 · 6 PM',
                   'where': 'Fellowship Hall', 'source': 'Services & Events'}


def test_no_calendar_or_an_unreadable_one_starts_the_brief_empty(monkeypatch):
    import church_checkin
    monkeypatch.setattr(church_checkin, '_roster', lambda biz: [])
    assert lt.next_occasion(BIZ) is None
    monkeypatch.setattr(church_checkin, '_roster', lambda biz: (_ for _ in ()).throw(RuntimeError('down')))
    assert lt.next_occasion(BIZ) is None


# ── The proof shows each check ───────────────────────────────────────

def test_the_review_keeps_each_check_for_the_proof():
    review = d.Review(observed_text='HARVEST NIGHT Sat, Nov 21 · 6 PM', reference_match=True, readable=True,
                      composition_coherent=False, brand_assets_clean=True)
    verdict = d.review_verdict(review, {'copy': ['Harvest Night', 'Sat, Nov 21 · 6 PM', 'All are welcome']})
    assert verdict['checks'] == {'words': False, 'readable': True, 'layout': False, 'brand': True, 'likeness': True}
    assert d.public_state({'phase': 'needs_review', 'review': verdict})['checks'] == verdict['checks']
    # A face the meter scores low fails the likeness check too.
    judged = d.judge_likeness(dict(verdict, checks=dict(verdict['checks'], words=True)), 0.4)
    assert judged['checks']['likeness'] is False and judged['passed'] is False
    # Designs checked before this change show no breakdown, not a false one.
    assert d.public_state({'phase': 'complete', 'review': {'passed': True}})['checks'] is None
