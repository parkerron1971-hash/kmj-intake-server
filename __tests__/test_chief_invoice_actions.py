import asyncio
from copy import deepcopy
from urllib.parse import unquote

import pytest
import chief_invoice_actions as actions
import invoice_payment_links as links
import financial_policy

BIZ = {'id': '11111111-1111-4111-8111-111111111111', 'stripe_account_id': 'acct_test'}
INVOICE = {'id': '22222222-2222-4222-8222-222222222222', 'business_id': BIZ['id'], 'invoice_number': 'INV-001', 'status': 'draft', 'paid_at': None, 'sent_at': None, 'updated_at': '2026-09-09T00:00:00Z'}


@pytest.fixture
def db(monkeypatch):
    rows = [deepcopy(INVOICE)]
    calls = []
    async def request(client, method, path, body=None):
        calls.append((method, path, body))
        if method == 'GET':
            return deepcopy(rows)
        return deepcopy(rows)
    monkeypatch.setattr(actions, 'sb_as_current_context', request)
    monkeypatch.setattr(financial_policy, 'require_operational_write', lambda bid: None)
    return rows, calls


def run(handler, action=None):
    return asyncio.run(handler(None, BIZ, action or {'invoice_number': 'INV-001'}))


def test_delete_unsent_draft_is_scoped_and_conditional(db):
    out = run(actions.handle_delete_invoice)
    assert not out.get('failed') and out['invoice_id'] == INVOICE['id']
    method, path, body = db[1][-1]
    assert method == 'DELETE' and f"business_id=eq.{BIZ['id']}" in path
    assert 'sent_at=is.null' in path and 'paid_at=is.null' in path and 'updated_at=eq.' in path
    assert 'status=eq."draft"' in unquote(path)


@pytest.mark.parametrize('status', ['sent', 'viewed', 'overdue', 'paid', 'cancelled'])
def test_delete_refuses_non_draft_without_writing(db, status):
    db[0][0]['status'] = status
    assert run(actions.handle_delete_invoice)['failed']
    assert len(db[1]) == 1


def test_void_preserves_record_and_stops_recurrence(db):
    db[0][0].update(status='sent', is_recurring=True)
    out = run(actions.handle_void_invoice)
    assert not out.get('failed')
    assert db[1][-1][0] == 'PATCH'
    assert db[1][-1][2] == {'status': 'cancelled', 'stripe_payment_url': None, 'recurrence_paused': True}


@pytest.mark.parametrize('payment', [{'status': 'paid'}, {'paid_at': '2026-09-09'}, {'amount_paid_cents': 100}])
def test_void_cannot_remove_payment_facts(db, payment):
    db[0][0].update(payment)
    assert run(actions.handle_void_invoice)['failed']
    assert len(db[1]) == 1


def test_archive_paid_invoice_only_sets_archive_timestamp(db):
    db[0][0]['status'] = 'paid'
    assert not run(actions.handle_archive_invoice).get('failed')
    assert set(db[1][-1][2]) == {'archived_at'}
    assert db[1][-1][2]['archived_at']
    assert not run(actions.handle_restore_invoice).get('failed')
    assert db[1][-1][2] == {'archived_at': None}


@pytest.mark.parametrize('count', [0, 2])
def test_missing_or_ambiguous_target_never_writes(db, count):
    db[0][:] = [deepcopy(INVOICE) for _ in range(count)]
    assert run(actions.handle_delete_invoice)['failed']
    assert len(db[1]) == 1


def test_filter_injection_is_quoted_and_invalid_uuid_refused(db):
    run(actions.handle_archive_invoice, {'invoice_number': 'INV&business_id=eq.other'})
    assert '&business_id=eq.other' not in db[1][0][1]
    db[1].clear()
    assert run(actions.handle_delete_invoice, {'invoice_id': 'latest'})['failed']
    assert not db[1]


def test_concurrent_change_is_not_reported_as_success(monkeypatch, db):
    async def request(client, method, path, body=None):
        return [INVOICE] if method == 'GET' else []
    monkeypatch.setattr(actions, 'sb_as_current_context', request)
    assert run(actions.handle_void_invoice)['failed']


def test_financial_lock_is_respected(monkeypatch, db):
    from fastapi import HTTPException
    def denied(bid):
        raise HTTPException(403, 'This business is view-only for finances.')
    monkeypatch.setattr(financial_policy, 'require_operational_write', denied)
    out = run(actions.handle_void_invoice)
    assert out['failed'] and 'view-only' in out['result'] and len(db[1]) == 1


class Response:
    def __init__(self, data): self.data = data
    def raise_for_status(self): pass
    def json(self): return self.data


class Stripe:
    def __init__(self, metadata=None, sessions=None):
        self.calls = []
        self.metadata = metadata if metadata is not None else {'source_type': 'invoice', 'source_id': INVOICE['id'], 'business_id': BIZ['id']}
        self.sessions = sessions or []
    async def get(self, url, **kwargs):
        self.calls.append(('GET', url, kwargs))
        rows = [{'id': 'plink_test', 'url': 'https://buy.stripe.com/test', 'metadata': self.metadata}] if url.endswith('/payment_links') else self.sessions
        return Response({'data': rows, 'has_more': False})
    async def post(self, url, **kwargs):
        self.calls.append(('POST', url, kwargs))
        return Response({})


@pytest.fixture
def stripe_policy(monkeypatch):
    monkeypatch.setattr(links, '_secret_key', lambda: 'fake-test-key')
    monkeypatch.setattr(links, 'require_stripe_write', lambda account: None)


def test_void_deactivates_owned_link_and_expires_open_checkout(stripe_policy):
    stripe = Stripe(sessions=[{'id': 'cs_test', 'status': 'open', 'payment_status': 'unpaid'}])
    asyncio.run(links.disable_invoice_payment_link(stripe, BIZ, {**INVOICE, 'stripe_payment_url': 'https://buy.stripe.com/test'}))
    writes = [call for call in stripe.calls if call[0] == 'POST']
    assert writes[0][2]['data'] == {'active': 'false'}
    assert writes[1][1].endswith('/cs_test/expire')
    assert all(call[2]['headers']['Stripe-Account'] == 'acct_test' for call in stripe.calls)


def test_shared_payment_link_is_never_disabled(stripe_policy):
    stripe = Stripe(metadata={})
    with pytest.raises(links.UnverifiedLink, match="couldn't confirm"):
        asyncio.run(links.disable_invoice_payment_link(stripe, BIZ, {**INVOICE, 'stripe_payment_url': 'https://buy.stripe.com/test'}))
    assert not any(call[0] == 'POST' for call in stripe.calls)


def test_completed_stripe_checkout_blocks_local_void(stripe_policy):
    stripe = Stripe(sessions=[{'id': 'cs_paid', 'status': 'complete', 'payment_status': 'paid'}])
    with pytest.raises(ValueError, match='Stripe shows a payment'):
        asyncio.run(links.disable_invoice_payment_link(stripe, BIZ, {**INVOICE, 'stripe_payment_url': 'https://buy.stripe.com/test'}))


SHARED = 'https://buy.stripe.com/business-link'


def test_void_with_the_business_pay_link_detaches_it_and_leaves_it_on(monkeypatch, db):
    """Every invoice without its own link carries the pasted business link.
    Voiding one must not refuse (it used to: 'shared') and must not switch
    that link off for every other invoice."""
    biz = {**BIZ, 'settings': {'payments': {'stripe_link': SHARED}}}
    db[0][0].update(status='sent', stripe_payment_url=SHARED)
    provider = Stripe()
    out = asyncio.run(actions.handle_void_invoice(provider, biz, {'invoice_number': 'INV-001'}))
    assert not out.get('failed'), out
    assert 'stays on for your other invoices' in out['result']
    assert db[1][-1][2]['stripe_payment_url'] is None and db[1][-1][2]['status'] == 'cancelled'
    assert provider.calls == []


def test_business_pay_link_needs_no_connected_account(stripe_policy):
    biz = {'id': BIZ['id'], 'settings': {'payments': {'stripe_link': SHARED + ' '}}}
    provider = Stripe()
    assert asyncio.run(links.disable_invoice_payment_link(provider, biz, {**INVOICE, 'stripe_payment_url': SHARED})) == 'shared'
    assert provider.calls == []


def test_an_unknown_link_is_still_refused(stripe_policy):
    biz = {**BIZ, 'settings': {'payments': {'stripe_link': SHARED}}}
    with pytest.raises(links.UnverifiedLink):
        asyncio.run(links.disable_invoice_payment_link(Stripe(metadata={}), biz, {**INVOICE, 'stripe_payment_url': 'https://buy.stripe.com/test'}))


# ── POST /invoices/{id}/void — the drawer's Void button ─────────────

from types import SimpleNamespace
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


_REAL_CHANGE = actions._change


@pytest.fixture
def api(monkeypatch):
    import business_users_router
    app = FastAPI()
    app.include_router(actions.router)
    reads, roles, changes = [], [], []

    def service_get(path):
        reads.append(path)
        if path.startswith('/invoices'):
            return [{'business_id': BIZ['id']}]
        return [{**BIZ, 'settings': {}}]

    def require_role(biz_id, user_id, min_role):
        roles.append((biz_id, user_id, min_role))
        if user_id == 'viewer':
            raise HTTPException(403, 'requires member access or above')
        return 'owner'

    async def change(client, biz, action, verb):
        changes.append((biz, action, verb))
        return {'type': verb, 'result': 'Invoice INV-001 voided.', 'label': 'Invoice INV-001 voided',
                'invoice_id': action['invoice_id'], 'invoice_number': 'INV-001'}

    monkeypatch.setattr(actions.sb_clients, 'sb_get_as_service', service_get)
    monkeypatch.setattr(business_users_router, 'require_role', require_role)
    monkeypatch.setattr(actions, '_change', change)
    client = TestClient(app)

    def as_user(uid):
        app.dependency_overrides[actions.sb_clients.authed_request] = lambda: SimpleNamespace(user=SimpleNamespace(id=uid, email=None))
    yield SimpleNamespace(client=client, as_user=as_user, reads=reads, roles=roles, changes=changes)
    client.close()


def test_void_endpoint_requires_sign_in(api):
    assert api.client.post(f"/invoices/{INVOICE['id']}/void").status_code == 401
    assert not api.changes


def test_void_endpoint_refuses_a_bad_id_before_any_read(api):
    api.as_user('owner-user')
    assert api.client.post('/invoices/latest/void').status_code == 404
    assert not api.reads and not api.changes


def test_void_endpoint_checks_the_seat_before_changing_anything(api):
    api.as_user('viewer')
    assert api.client.post(f"/invoices/{INVOICE['id']}/void").status_code == 403
    assert api.roles == [(BIZ['id'], 'viewer', 'member')] and not api.changes


def test_void_endpoint_runs_chiefs_void_on_the_invoices_own_business(api):
    api.as_user('owner-user')
    res = api.client.post(f"/invoices/{INVOICE['id']}/void")
    assert res.status_code == 200, res.text
    assert res.json()['result'] == 'Invoice INV-001 voided.'
    biz, action, verb = api.changes[0]
    assert verb == 'void_invoice' and biz['id'] == BIZ['id']
    assert action == {'invoice_id': INVOICE['id'], 'link_off_confirmed': False}


def test_void_endpoint_reports_the_refusal_reason(api, monkeypatch):
    async def refused(client, biz, action, verb):
        return actions._fail(verb, 'This invoice has a payment. Archive it to retain the payment record; voiding is not a refund.')
    monkeypatch.setattr(actions, '_change', refused)
    api.as_user('owner-user')
    res = api.client.post(f"/invoices/{INVOICE['id']}/void")
    assert res.status_code == 409 and 'has a payment' in res.json()['detail']


def test_void_endpoint_runs_the_real_void_and_a_blocked_read_is_a_clean_refusal(api, monkeypatch):
    """No fake _change: the route binds the caller, _change reads through
    sb_as_current_context, and a row the caller's RLS hides reads as []."""
    monkeypatch.setattr(actions, '_change', _REAL_CHANGE)
    calls = []

    async def rls_hides_the_row(client, method, path, body=None):
        calls.append((method, path))
        return []
    monkeypatch.setattr(actions, 'sb_as_current_context', rls_hides_the_row)
    monkeypatch.setattr(financial_policy, 'require_operational_write', lambda bid: None)
    api.as_user('member-user')
    res = api.client.post(f"/invoices/{INVOICE['id']}/void")
    assert res.status_code == 409 and res.json()['detail'] == 'Invoice not found in this business.'
    assert [m for m, _ in calls] == ['GET'] and f"business_id=eq.{BIZ['id']}" in calls[0][1]


def test_a_lost_race_after_the_link_is_off_says_the_invoice_is_still_open(monkeypatch, db):
    db[0][0].update(status='sent', stripe_payment_url='https://buy.stripe.com/test')

    async def switched_off(client, biz, inv, link_off_confirmed=False):
        return 'disabled'
    monkeypatch.setattr(links, 'disable_invoice_payment_link', switched_off)

    async def request(client, method, path, body=None):
        return deepcopy(db[0]) if method == 'GET' else []
    monkeypatch.setattr(actions, 'sb_as_current_context', request)
    out = run(actions.handle_void_invoice)
    assert out['failed'] and 'still open' in out['result'] and 'pay link is now switched off' in out['result']


def test_disable_reports_that_it_switched_the_link_off(stripe_policy):
    stripe = Stripe()
    assert asyncio.run(links.disable_invoice_payment_link(stripe, BIZ, {**INVOICE, 'stripe_payment_url': 'https://buy.stripe.com/test'})) == 'disabled'


# ── links Stripe can't confirm: older tags, the platform account, the owner's word ──

URL = 'https://buy.stripe.com/test'


class Accounts:
    """Stripe, per account: 'connected' (Stripe-Account header) or 'platform'."""
    def __init__(self, connected=(), platform=(), fail=()):
        self.rows = {'connected': list(connected), 'platform': list(platform)}
        self.fail = set(fail)
        self.calls = []
    def _on(self, kwargs):
        return 'connected' if (kwargs.get('headers') or {}).get('Stripe-Account') else 'platform'
    async def get(self, url, **kwargs):
        on = self._on(kwargs)
        self.calls.append(('GET', on, url))
        if on in self.fail:
            import httpx
            request = httpx.Request('GET', url)
            raise httpx.HTTPStatusError('forbidden', request=request, response=httpx.Response(403, request=request))
        rows = self.rows[on] if url.endswith('/payment_links') else []
        return Response({'data': rows, 'has_more': False})
    async def post(self, url, **kwargs):
        self.calls.append(('POST', self._on(kwargs), url))
        return Response({})


def _link(**metadata):
    return {'id': 'plink_x', 'url': URL, 'metadata': metadata}


def _disable(stripe, **kw):
    return asyncio.run(links.disable_invoice_payment_link(stripe, BIZ, {**INVOICE, 'stripe_payment_url': URL}, **kw))


def test_a_link_from_before_business_tags_is_still_this_invoices_own(stripe_policy):
    stripe = Accounts(connected=[_link(source_type='invoice', source_id=INVOICE['id'])])
    assert _disable(stripe) == 'disabled'
    assert ('POST', 'connected', f'{links.STRIPE_API_BASE}/payment_links/plink_x') in stripe.calls


def test_another_business_tag_is_never_accepted(stripe_policy):
    stripe = Accounts(connected=[_link(source_type='invoice', source_id=INVOICE['id'], business_id='someone-else')])
    with pytest.raises(links.UnverifiedLink):
        _disable(stripe)
    assert not [c for c in stripe.calls if c[0] == 'POST']


def test_a_link_on_the_platform_account_is_found_and_switched_off_there(stripe_policy):
    stripe = Accounts(platform=[_link(source_type='invoice', source_id=INVOICE['id'])])
    assert _disable(stripe) == 'disabled'
    posts = [c for c in stripe.calls if c[0] == 'POST']
    assert posts and all(on == 'platform' for _, on, _ in posts)


def test_a_stripe_error_on_one_account_falls_through_to_the_next(stripe_policy):
    stripe = Accounts(platform=[_link(source_type='invoice', source_id=INVOICE['id'])], fail={'connected'})
    assert _disable(stripe) == 'disabled'


def test_unverified_link_needs_the_owners_word_and_is_then_left_alone(stripe_policy):
    stripe = Accounts(connected=[_link()], platform=[])
    with pytest.raises(links.UnverifiedLink):
        _disable(stripe)
    assert _disable(stripe, link_off_confirmed=True) == 'confirmed_off'
    assert not [c for c in stripe.calls if c[0] == 'POST']


def test_void_refusal_for_an_unverified_link_carries_a_code_and_the_override_voids(monkeypatch, db):
    db[0][0].update(status='sent', stripe_payment_url=URL)
    async def unverified(client, biz, inv, link_off_confirmed=False):
        if link_off_confirmed:
            return 'confirmed_off'
        raise links.UnverifiedLink(links.UNVERIFIED)
    monkeypatch.setattr(links, 'disable_invoice_payment_link', unverified)
    out = run(actions.handle_void_invoice)
    assert out['failed'] and out['code'] == 'link_unverified' and len(db[1]) == 1
    out = run(actions.handle_void_invoice, {'invoice_number': 'INV-001', 'link_off_confirmed': True})
    assert not out.get('failed') and 'off in Stripe' in out['result']
    assert db[1][-1][2]['stripe_payment_url'] is None and db[1][-1][2]['status'] == 'cancelled'


@pytest.mark.parametrize('value', [False, 'false', None, 'no', 0])
def test_only_a_real_yes_overrides(monkeypatch, db, value):
    seen = []
    async def unverified(client, biz, inv, link_off_confirmed=False):
        seen.append(link_off_confirmed)
        raise links.UnverifiedLink(links.UNVERIFIED)
    monkeypatch.setattr(links, 'disable_invoice_payment_link', unverified)
    db[0][0].update(status='sent', stripe_payment_url=URL)
    assert run(actions.handle_void_invoice, {'invoice_number': 'INV-001', 'link_off_confirmed': value})['failed']
    assert seen == [False]


def test_void_endpoint_passes_the_owners_word_and_returns_the_code(api, monkeypatch):
    async def change(client, biz, action, verb):
        api.changes.append((biz, action, verb))
        if not action['link_off_confirmed']:
            return actions._fail(verb, links.UNVERIFIED, code='link_unverified')
        return {'result': 'Invoice INV-001 voided.', 'invoice_id': action['invoice_id'], 'invoice_number': 'INV-001'}
    monkeypatch.setattr(actions, '_change', change)
    api.as_user('owner-user')
    res = api.client.post(f"/invoices/{INVOICE['id']}/void")
    assert res.status_code == 409 and res.json()['code'] == 'link_unverified'
    res = api.client.post(f"/invoices/{INVOICE['id']}/void", json={'link_off_confirmed': True})
    assert res.status_code == 200 and api.changes[-1][1]['link_off_confirmed'] is True
