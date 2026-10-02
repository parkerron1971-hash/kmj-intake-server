"""Real step-up verifier must reject missing, wrong-scope and wrong-user proofs."""
import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import business_users_router
import contractors_router as contractors
import financial_policy
import financial_policy_router as policies
import ledger_unlock
import sb_clients
import stripe_payments_router as payments


@pytest.mark.parametrize('operation', ['pay', 'refund', 'no_show', 'policy'])
@pytest.mark.parametrize('proof', ['missing', 'ledger', 'other_user'])
def test_financial_routes_require_current_user_danger_proof(monkeypatch, operation, proof):
    monkeypatch.setattr(ledger_unlock, '_secret', lambda: b'route-step-up-test-key')
    monkeypatch.setattr(business_users_router, 'require_role', lambda *a: 'owner')
    monkeypatch.setattr(policies, 'require_role', lambda *a: 'owner')
    monkeypatch.setattr(financial_policy, 'require_operational_write', lambda *a: None)
    monkeypatch.setattr(contractors, '_owner_for_contractor', lambda *a, **k: {'business_id': 'biz'})
    monkeypatch.setattr(payments, '_require_owner', lambda *a: {'id': 'biz'})
    monkeypatch.setattr(sb_clients, 'sb_get_as_service', lambda *a: [{'id': 'booking', 'business_id': 'biz'}])
    def forbidden(*a, **k):
        pytest.fail('Unauthenticated financial action reached mutation/provider access')
    monkeypatch.setattr(sb_clients, 'sb_post_as_service', forbidden)
    monkeypatch.setattr(payments.payments_core, 'provider_for', forbidden)
    headers = []
    if proof != 'missing':
        token = ledger_unlock.mint('intruder' if proof == 'other_user' else 'owner',
                                   scope='danger' if proof == 'other_user' else 'ledger')['token']
        headers = [(b'x-ledger-unlock', token.encode())]
    request = Request({'type': 'http', 'headers': headers})
    user = SimpleNamespace(id='owner')
    with pytest.raises(HTTPException) as exc:
        if operation == 'pay':
            asyncio.run(contractors.pay('contractor', contractors.PayBody(business_id='biz', amount=10), request, user))
        elif operation == 'refund':
            asyncio.run(payments.refund_charge('charge', payments.RefundBody(business_id='biz'), request, user))
        elif operation == 'no_show':
            asyncio.run(payments.charge_no_show(payments.ChargeNoShowBody(booking_id='booking'), request, user))
        else:
            policies.change_policy(UUID('00000000-0000-4000-8000-000000000001'), policies.Change(mode='view_only', reason='Program requires read only'), request, user)
    assert exc.value.status_code == 403
    assert exc.value.detail['code'] == 'ledger_locked'
    assert exc.value.detail['scope'] == 'danger'
