"""The growth report in a church's and a nonprofit's words, and who may
read it (growth_words.py, growth_intelligence_router.authorize,
chief_growth_intelligence_actions). 2026-10-16."""
import asyncio
import copy
import json
import re
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import chief_growth_intelligence_actions as chief
import church_keys
import giving_records
import growth_intelligence_router as api
from growth_intelligence import report
from growth_words import re_say, voice_of

KEEPERS = []  # church_keepers rows; empty: nothing is locked


@pytest.fixture(autouse=True)
def keeper_store(monkeypatch):
    monkeypatch.delenv('CHURCH_KEYS', raising=False)
    KEEPERS.clear()
    monkeypatch.setattr(church_keys, '_keeper_rows', lambda biz, area=None: list(KEEPERS))
    monkeypatch.setattr(church_keys, '_open_key', lambda biz, user_id, area: None)


def giving_kept_by(user_id):
    KEEPERS.append({'area': 'giving_money', 'user_id': user_id, 'starts_at': '2026-01-01T00:00:00+00:00', 'ends_at': None})


NOW = datetime(2026, 9, 16, 12, tzinfo=timezone.utc)
PREFS = {'timezone': 'UTC', 'currency': 'USD', 'weekly_hours': 30}
BID = '10000000-0000-4000-8000-000000000001'
SALES = re.compile(r'\b(buyers?|invoices?|invoiced|revenue|purchases?|customers?|collections?)\b', re.I)
WARNINGS = ["Collections use paid invoice totals; partial payments and refunds need reconciliation in Revenue.",
            "Capacity combines Sessions and dated booking-calendar records, deduplicating mirrored online bookings.",
            "Costs are analytical allocations, not additional bookkeeping entries. Contributions use recorded direct costs only."]


def gift(id, person, paid, amount):
    return dict(id=id, contact_id=person, paid_at=paid, total=amount, status='paid', category=None)


def rows():
    return {'contacts': [{'id': 'a', 'name': 'Ada', 'created_at': '2026-01-01T00:00:00Z', 'source': 'subsplash_import'},
                         {'id': 'b', 'name': 'Bea', 'created_at': '2026-09-01T00:00:00Z', 'source': 'subsplash_import'}],
            'invoices': [gift('1', 'a', '2026-08-03T10:00:00Z', 100), gift('2', 'a', '2026-09-02T10:00:00Z', 150),
                         gift('3', None, '2026-09-05T10:00:00Z', 40), gift('4', 'b', '2026-09-06T10:00:00Z', 200)],
            'sessions': [], 'campaigns': [], 'events': [], 'costs': [], 'attributions': [], 'actions': [],
            'warnings': list(WARNINGS)}


def built():
    return report(rows(), PREFS, now=NOW)


def said(r):
    """Everything the voice changes, as one text."""
    return json.dumps([r['drivers'], r['retention_health']['definitions']['repeat_rate'], r['quality']['warnings']])


def test_voice_of_resolves_churches_nonprofits_and_everyone_else():
    assert [voice_of(t) for t in ('church', 'ministry', 'Church', 'pastor', 'nonprofit', 'coach', None, '')] == \
        ['church', 'church', 'church', 'church', 'nonprofit', 'business', 'business', 'business']


def test_one_test_decides_the_words_and_the_gate():
    # A "pastor" reads as a ministry in the registry but is not in the
    # accounting family's set: it must still be gated, not only reworded.
    from growth_words import giving_is_private
    for t in ('pastor', 'church', 'congregation', 'nonprofit', 'coach', None):
        assert giving_is_private(t) == (voice_of(t) != 'business'), t
    assert giving_is_private('pastor') and not giving_is_private('coach')


def test_business_voice_keeps_every_word_and_every_number():
    before = built()
    after = re_say(copy.deepcopy(before), 'business')
    assert [d['label'] for d in after['drivers']] == [d['label'] for d in before['drivers']]
    assert [d['key'] for d in after['drivers']] == ['first_time', 'returning', 'frequency', 'average', 'unlinked']
    assert after['quality'] == before['quality'] and 'vocabulary' not in after


def test_church_voice_says_gifts_and_givers_with_the_same_numbers():
    before = built()
    after = re_say(copy.deepcopy(before), 'church')
    assert [d['label'] for d in after['drivers']] == ['New givers', 'Returning givers', 'How often they give', 'Average gift', 'Anonymous gifts']
    assert [d['value'] for d in after['drivers']] == [d['value'] for d in before['drivers']]
    assert after['current'] == before['current'] and after['change'] == before['change']
    assert not SALES.search(said(after)), said(after)
    assert len(after['quality']['warnings']) == 2, 'the capacity warning has no meaning for gifts'
    assert after['voice'] == 'church' and 'givers' in after['vocabulary']


def test_nonprofit_voice_says_donors():
    after = re_say(built(), 'nonprofit')
    assert after['drivers'][0]['label'] == 'New donors'
    assert 'donors' in after['retention_health']['definitions']['repeat_rate']
    assert not SALES.search(said(after))


def church_business(monkeypatch, type_='church'):
    async def fake(*args): return [{'id': BID, 'owner_id': 'owner', 'type': type_}]
    monkeypatch.setattr(api, 'db', fake)


def finance_only(monkeypatch):
    def require(business_id, user):
        if user.id not in ('admin-seat', 'accountant'):
            raise HTTPException(403, 'Giving records require owner, admin, or accountant access.')
        return 'admin'
    monkeypatch.setattr(giving_records, 'require_finance', require)


def test_a_church_report_is_its_finance_roles(monkeypatch):
    import sys, types
    church_business(monkeypatch)
    finance_only(monkeypatch)
    roles = []
    monkeypatch.setitem(sys.modules, 'business_users_router', types.SimpleNamespace(require_role=lambda *a: roles.append(a)))
    assert asyncio.run(api.authorize(None, BID, SimpleNamespace(id='owner')))['type'] == 'church'
    assert asyncio.run(api.authorize(None, BID, SimpleNamespace(id='accountant')))['id'] == BID
    for write in (False, True):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(api.authorize(None, BID, SimpleNamespace(id='member-seat'), write))
        assert exc.value.status_code == 403
    assert roles == [], 'a church never falls back to the any-seat rule'


def test_a_pastor_typed_business_is_gated_too(monkeypatch):
    church_business(monkeypatch, 'pastor')
    finance_only(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.authorize(None, BID, SimpleNamespace(id='member-seat')))
    assert exc.value.status_code == 403


def test_a_business_report_keeps_its_team_rule(monkeypatch):
    import sys, types
    church_business(monkeypatch, 'coach')
    roles = []
    monkeypatch.setitem(sys.modules, 'business_users_router', types.SimpleNamespace(require_role=lambda *a: roles.append(a)))
    asyncio.run(api.authorize(None, BID, SimpleNamespace(id='member-seat')))
    assert roles and roles[0][2] == 'viewer'


def served(monkeypatch):
    data = rows()
    async def all_rows(client, table, bid, extra='', cap=50000):
        return data.get(table, [])
    monkeypatch.setattr(api, 'all_rows', all_rows)


def as_turn(user_id):
    import chief_of_staff
    return chief_of_staff._TURN_USER_ID.set(user_id)


CHURCH = {'id': BID, 'type': 'church', 'owner_id': 'owner'}


def test_chief_reads_a_church_report_in_its_words(monkeypatch):
    served(monkeypatch)
    import chief_of_staff
    token = as_turn('owner')
    try:
        r = asyncio.run(chief.handle_growth_report(None, CHURCH, {'section': 'drivers'}))
        care = asyncio.run(chief.handle_growth_report(None, CHURCH, {'section': 'client_health'}))
    finally:
        chief_of_staff._TURN_USER_ID.reset(token)
    assert not r.get('failed'), r
    assert r['data']['voice'] == 'church' and 'never buyers' in r['data']['vocabulary']
    assert [d['label'] for d in r['data']['drivers']][0] == 'New givers'
    assert 'attendance' in care['data']['church_note']


def test_no_person_in_the_call_reads_no_giving(monkeypatch):
    # After a turn the id is reset to "" (chief_of_staff); a job or task
    # outside a signed-in turn is refused, as church_people refuses care.
    served(monkeypatch)
    import chief_of_staff
    token = as_turn('')
    try:
        read = asyncio.run(chief.handle_growth_report(None, CHURCH, {'section': 'drivers'}))
    finally:
        chief_of_staff._TURN_USER_ID.reset(token)
    assert read['failed'] and 'data' not in read
    business = asyncio.run(chief.handle_growth_report(None, {'id': BID, 'type': 'coach'}, {'section': 'drivers'}))
    assert not business.get('failed'), 'a business report keeps working without a person in the call'


def test_chief_refuses_a_church_report_to_a_seat_without_finance(monkeypatch):
    served(monkeypatch)
    finance_only(monkeypatch)
    loaded = []
    real = chief.load_report
    async def spy(*args, **kwargs):
        loaded.append(args)
        return await real(*args, **kwargs)
    monkeypatch.setattr(chief, 'load_report', spy)
    import chief_of_staff
    token = as_turn('member-seat')
    try:
        read = asyncio.run(chief.handle_growth_report(None, CHURCH, {'section': 'client_health'}))
        write = asyncio.run(chief.handle_save_growth_record(None, CHURCH, {'kind': 'actions', 'data': {}}))
    finally:
        chief_of_staff._TURN_USER_ID.reset(token)
    assert read['failed'] and 'data' not in read and loaded == []
    assert write['failed'] and 'Nothing was saved' in write['result']
    token = as_turn('accountant')
    try:
        assert not asyncio.run(chief.handle_growth_report(None, CHURCH, {'section': 'drivers'})).get('failed')
    finally:
        chief_of_staff._TURN_USER_ID.reset(token)


def test_a_named_giving_keeper_locks_the_report_for_everyone_else(monkeypatch):
    # Who gave what, ranked by name, is a Giving door (church_keys): the
    # owner and an admin seat need the keeper's key too.
    church_business(monkeypatch)
    finance_only(monkeypatch)
    giving_kept_by('accountant')
    for who in ('owner', 'admin-seat'):
        for write in (False, True):
            with pytest.raises(HTTPException) as exc:
                asyncio.run(api.authorize(None, BID, SimpleNamespace(id=who), write))
            assert exc.value.status_code == 403 and exc.value.detail['code'] == 'area_locked', who
    assert asyncio.run(api.authorize(None, BID, SimpleNamespace(id='accountant')))['id'] == BID


def test_an_open_key_lets_the_owner_back_in(monkeypatch):
    church_business(monkeypatch)
    giving_kept_by('accountant')
    monkeypatch.setattr(church_keys, '_open_key',
                        lambda biz, user_id, area: {'id': 'k'} if (user_id, area) == ('owner', 'giving_money') else None)
    assert asyncio.run(api.authorize(None, BID, SimpleNamespace(id='owner')))['id'] == BID


def test_a_church_that_changes_its_type_keeps_its_keeper(monkeypatch):
    import sys, types
    church_business(monkeypatch, 'coach')
    monkeypatch.setitem(sys.modules, 'business_users_router', types.SimpleNamespace(require_role=lambda *a: None))
    giving_kept_by('accountant')
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.authorize(None, BID, SimpleNamespace(id='member-seat')))
    assert exc.value.detail['code'] == 'area_locked'


def test_the_report_stays_shut_when_the_keys_cannot_be_read(monkeypatch):
    def down(biz, area=None):
        raise HTTPException(503, "The keys couldn't be read just now. Try again.")
    monkeypatch.setattr(church_keys, '_keeper_rows', down)
    church_business(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.authorize(None, BID, SimpleNamespace(id='owner')))
    assert exc.value.status_code == 503
    served(monkeypatch)
    import chief_of_staff
    token = as_turn('owner')
    try:
        read = asyncio.run(chief.handle_growth_report(None, CHURCH, {'section': 'drivers'}))
    finally:
        chief_of_staff._TURN_USER_ID.reset(token)
    assert read['failed'] and 'data' not in read


def test_chief_needs_the_key_where_giving_is_kept(monkeypatch):
    served(monkeypatch)
    finance_only(monkeypatch)
    giving_kept_by('accountant')
    import chief_of_staff
    retyped = {'id': BID, 'type': 'coach', 'owner_id': 'owner'}
    for who, biz in (('owner', CHURCH), ('admin-seat', CHURCH), ('', CHURCH), ('member-seat', retyped), ('', retyped)):
        token = as_turn(who)
        try:
            read = asyncio.run(chief.handle_growth_report(None, biz, {'section': 'drivers'}))
            write = asyncio.run(chief.handle_save_growth_record(None, biz, {'kind': 'actions', 'data': {}}))
        finally:
            chief_of_staff._TURN_USER_ID.reset(token)
        assert read['failed'] and 'data' not in read, (who, biz['type'])
        assert write['failed'] and 'Nothing was saved' in write['result'], (who, biz['type'])
        if who:
            assert 'keeper' in read['result'], who
    token = as_turn('accountant')
    try:
        assert not asyncio.run(chief.handle_growth_report(None, CHURCH, {'section': 'drivers'})).get('failed')
    finally:
        chief_of_staff._TURN_USER_ID.reset(token)
