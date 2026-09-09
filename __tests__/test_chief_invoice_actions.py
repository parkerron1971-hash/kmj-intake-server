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
    with pytest.raises(ValueError, match='shared'):
        asyncio.run(links.disable_invoice_payment_link(stripe, BIZ, {**INVOICE, 'stripe_payment_url': 'https://buy.stripe.com/test'}))
    assert not any(call[0] == 'POST' for call in stripe.calls)


def test_completed_stripe_checkout_blocks_local_void(stripe_policy):
    stripe = Stripe(sessions=[{'id': 'cs_paid', 'status': 'complete', 'payment_status': 'paid'}])
    with pytest.raises(ValueError, match='completed payment'):
        asyncio.run(links.disable_invoice_payment_link(stripe, BIZ, {**INVOICE, 'stripe_payment_url': 'https://buy.stripe.com/test'}))
