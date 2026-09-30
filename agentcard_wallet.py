"""Customer-owned Agentcard.sh Vault. No PAN/CVC, issuing, balances or unattended approvals."""
import hashlib
import hmac
import json
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit, parse_qs
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

import agentcard_client as provider
from agentcard_store import Wallet, cipher
from auth_supabase import UserSession
import business_access
import sb_clients
from ledger_unlock import require_unlock, SCOPE_DANGER

router = APIRouter(prefix='/agentcard', tags=['wallet'])
NO_STORE = {'Cache-Control': 'no-store', 'Pragma': 'no-cache'}


def enabled():
    return os.getenv('AGENTCARD_ENABLED') == 'true' and provider.configured()


def owner(bid, session):
    try:
        bid = str(UUID(bid))
    except (ValueError, TypeError):
        raise HTTPException(422, 'Select a valid business.', headers=NO_STORE) from None
    business_access.assert_access(bid, session.user, 'owner')
    if not enabled():
        raise HTTPException(503, 'Wallet setup is not enabled yet.', headers=NO_STORE)
    allow = os.getenv('AGENTCARD_ALLOWED_USER_IDS', '')
    if allow and str(session.user.id) not in allow.split(','):
        raise HTTPException(403, 'Wallet access is not enabled for this account yet.', headers=NO_STORE)
    return bid, str(session.user.id)


def future(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')) > datetime.now(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        return False


def text(value, limit=1000):
    return str(value or '')[:limit]


def user_token(wallet):
    connection = wallet.state.get('connection') or {}
    if not connection.get('user_id') or connection.get('refresh_uncertain'):
        raise provider.AgentcardError('Connect your wallet again to continue.', status=409)
    if connection.get('expires_at', 0) > time.time() + 90:
        return connection['access_token']
    # Persist before exchange: a lost response must never reuse a rotating token.
    connection['refresh_uncertain'] = True
    wallet.save()
    result = provider.call('POST', '/api/v2/connect/refresh', {'refresh_token': connection['refresh_token']})
    if not all(isinstance(result.get(k), str) and result[k] for k in ('access_token', 'refresh_token')):
        raise provider.AgentcardError()
    connection.update(access_token=result['access_token'], refresh_token=result['refresh_token'],
                      expires_at=time.time() + int(result.get('expires_in', 3600)), refresh_uncertain=False)
    wallet.save()
    return connection['access_token']


def refresh_cards(wallet):
    uid = (wallet.state.get('connection') or {}).get('user_id')
    if not uid:
        return
    result = provider.call('GET', '/api/v2/vault_cards?user_id=' + quote(provider.identifier(uid, 'usr_'), safe=''))
    if not isinstance(result.get('data'), list):
        raise provider.AgentcardError()
    cards = []
    for c in result['data']:
        if not isinstance(c, dict) or not re.fullmatch(r'\d{4}', str(c.get('last4', ''))):
            continue
        cards.append({'id': provider.identifier(c.get('id'), 'vc_'), 'brand': text(c.get('brand'), 30),
                      'last4': c['last4'], 'expiry_month': c.get('expiry_month'), 'expiry_year': c.get('expiry_year')})
    wallet.state['cards'] = cards
    wallet.save()


def cart_view(value):
    if not isinstance(value, dict):
        return None
    amount = value.get('totalCents')
    if type(amount) is not int or amount <= 0 or not isinstance(value.get('hash'), str):
        return None
    items = value.get('items')
    if not isinstance(items, list) or not items:
        return None
    return {'hash': text(value['hash'], 256), 'merchant': text(value.get('merchant'), 100),
            'merchant_name': text(value.get('merchant_name'), 200), 'total_cents': amount,
            'service_fees_cents': value.get('serviceFeesCents', 0), 'tip_cents': value.get('tipCents', 0),
            'items': [{'name': text(i.get('name'), 300), 'quantity': i.get('qty'),
                       'price_cents': i.get('priceCents')} for i in items if isinstance(i, dict)]}


def snapshot(wallet):
    state = wallet.state
    connection = state.get('connection') or {}
    attempt = state.get('attempt') or {}
    enrollment = state.get('enrollment') or {}
    purchase = state.get('purchase')
    result = {'available': True, 'mode': provider.mode(),
              'checkout_enabled': os.getenv('AGENTCARD_CHECKOUT_ENABLED') == 'true',
              'connected': bool(connection.get('user_id')) and not connection.get('refresh_uncertain'),
              'cards': state.get('cards', []),
              'verification_pending': bool(attempt.get('id')) and future(attempt.get('expires_at')),
              'enrollment_url': provider.safe_url(enrollment.get('url'), 'enroll') if future(enrollment.get('expires_at')) else None,
              'enrollment_pending': enrollment.get('status') == 'pending' and future(enrollment.get('expires_at')),
              'purchase': purchase, 'history': state.get('history', [])[-20:]}
    # Purchase objects are already a whitelist; tokens never enter them.
    return result


def approval_id(url):
    if not provider.safe_url(url, 'approve'):
        raise provider.AgentcardError('The approval address could not be verified.')
    return parse_qs(urlsplit(url).query)['id'][0]


def reconcile(wallet):
    p = wallet.state.get('purchase')
    if not p or not p.get('conversation_id') or p['phase'] in {'draft', 'cart', 'closed'}:
        return
    result = provider.request('GET', '/buy/conversations/' + provider.identifier(p['conversation_id'], 'conv_'), token=user_token(wallet))
    if result.get('conversation_id') != p['conversation_id']:
        raise provider.AgentcardError()
    if result.get('turn_in_progress'):
        return
    orders = result.get('orders') or []
    if orders:
        p['orders'] = [{'order_id': text(o.get('order_id'), 200), 'merchant_name': text(o.get('merchant_name'), 200),
                        'status': o.get('status'), 'total_cents': o.get('total_cents')} for o in orders if isinstance(o, dict)]
        valid = (len(p['orders']) == 1 and bool(p['orders'][0]['order_id'])
                 and type(p['orders'][0]['total_cents']) is int
                 and p['orders'][0]['total_cents'] == (p.get('cart') or {}).get('total_cents'))
        p['phase'] = 'placed' if valid and all(o['status'] == 'settled' for o in p['orders']) else 'reconciling'
        p['approval_url'] = None
    else:
        last = result.get('last_checkout') or {}
        if p['phase'] == 'preparing' and not last:
            apply_cart(p, result)
        if (last.get('code') == 'vault_approval_required' and last.get('charge_status') == 'none'
                and provider.safe_url(last.get('approval_url'), 'approve')):
            if approval_id(last['approval_url']) not in p.get('used_approval_ids', []):
                p.update(phase='approval', approval_url=last['approval_url'])
        elif last.get('status') in {'denied', 'error'} and last.get('charge_status') == 'none':
            p.update(phase='declined', message='Payment was not completed. Review the request before starting a new purchase.')
        # An absent or ambiguous response stays locked, even after a restart.
    wallet.save()


def refresh(wallet, *, resume=True):
    enrollment = wallet.state.get('enrollment') or {}
    if enrollment.get('status') == 'pending':
        result = provider.call('GET', '/api/v2/vault_sessions/' + provider.identifier(enrollment['id'], 'vs_'))
        uid = (wallet.state.get('connection') or {}).get('user_id')
        if result.get('id') != enrollment['id'] or result.get('user_id') not in (None, uid):
            raise provider.AgentcardError('Wallet setup belongs to another connection.')
        if result.get('test_mode') is not (provider.mode() == 'sandbox'):
            raise provider.AgentcardError('Wallet setup mode does not match.')
        enrollment['status'] = result.get('status')
        wallet.save()
    refresh_cards(wallet)
    reconcile(wallet)
    p = wallet.state.get('purchase') or {}
    if (resume and p.get('phase') == 'approval' and p.get('confirmed_hash') == (p.get('cart') or {}).get('hash')
            and p.get('confirmed_hash') and os.getenv('AGENTCARD_CHECKOUT_ENABLED') == 'true'):
        auth_id = approval_id(p.get('approval_url'))
        auth = provider.call('GET', '/api/v2/checkout/authorizations/' + auth_id)
        if auth.get('id') != auth_id:
            raise provider.AgentcardError()
        if auth.get('status') == 'approved':
            checkout(wallet, Confirm(purchase_id=p['id'], cart_hash=p['confirmed_hash']), approved=auth)
        elif auth.get('status') in {'declined', 'expired'} and auth.get('replay_attempted') is False:
            p.update(phase='declined', approval_url=None, message='The secure approval was declined or expired. No purchase is confirmed.')
            wallet.save()


class StrictBody(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Code(StrictBody):
    code: str = Field(min_length=4, max_length=12, pattern=r'^\d+$')


class Ask(StrictBody):
    request_id: str = Field(pattern=r'^[0-9a-fA-F-]{36}$')
    ask: str = Field(min_length=3, max_length=3000)


class Confirm(StrictBody):
    purchase_id: str
    cart_hash: str = Field(min_length=1, max_length=256)


def perform(bid, uid, operation):
    try:
        with Wallet(bid, uid) as wallet:
            operation(wallet)
            return snapshot(wallet)
    except provider.AgentcardError as exc:
        raise HTTPException(exc.status if exc.status in (403, 409, 429, 503) else 502, str(exc), headers=NO_STORE) from None


@router.get('/wallet/{business_id}')
def status(business_id: str, response: Response, session: UserSession = Depends(sb_clients.authed_request)):
    response.headers.update(NO_STORE)
    business_access.assert_access(business_id, session.user, 'owner')
    if not enabled():
        return {'available': False, 'mode': provider.mode(), 'checkout_enabled': False, 'connected': False,
                'cards': [], 'purchase': None, 'history': []}
    bid, uid = owner(business_id, session)
    return perform(bid, uid, lambda w: None)


@router.post('/wallet/{business_id}/refresh')
def refresh_route(business_id: str, response: Response, session: UserSession = Depends(sb_clients.authed_request)):
    response.headers.update(NO_STORE)
    return perform(*owner(business_id, session), refresh)


@router.post('/wallet/{business_id}/connect')
def connect(business_id: str, response: Response, session: UserSession = Depends(sb_clients.authed_request)):
    response.headers.update(NO_STORE)
    bid, uid = owner(business_id, session)
    email = session.user.email
    if not email:
        raise HTTPException(409, 'Add a verified email to your Solutionist account first.', headers=NO_STORE)
    def start(w):
        if time.time() - w.state.get('last_connect', 0) < 60:
            raise provider.AgentcardError('Wait one minute before requesting another code.', status=429)
        if (w.state.get('purchase') or {}).get('phase') in {'submitting', 'approval', 'reconciling'}:
            raise provider.AgentcardError('Finish or reconcile the current purchase before reconnecting.', status=409)
        w.state['last_connect'] = time.time()
        w.save()
        r = provider.call('POST', '/api/v2/connect/start', {'email': email, 'external_user_id': uid})
        w.state['attempt'] = {'id': provider.identifier(r.get('id'), 'ca_'), 'expires_at': r.get('expires_at'), 'tries': 0}
        w.save()
    return perform(bid, uid, start)


@router.post('/wallet/{business_id}/verify')
def verify(business_id: str, body: Code, response: Response, session: UserSession = Depends(sb_clients.authed_request)):
    response.headers.update(NO_STORE)
    def complete(w):
        a = w.state.get('attempt') or {}
        if not a.get('id') or not future(a.get('expires_at')) or a.get('tries', 0) >= 5:
            raise provider.AgentcardError('Request a new connection code.', status=409)
        a['tries'] = a.get('tries', 0) + 1
        w.save()
        r = provider.call('POST', '/api/v2/connect/verify', {'connect_id': a['id'], 'code': body.code})
        uid = provider.identifier((r.get('user') or {}).get('id'), 'usr_')
        previous = (w.state.get('connection') or {}).get('user_id')
        if previous and previous != uid:
            raise provider.AgentcardError('This connection does not match your saved wallet.', status=409)
        if not all(isinstance(r.get(k), str) and r[k] for k in ('access_token', 'refresh_token')):
            raise provider.AgentcardError()
        w.state['connection'] = {'user_id': uid, 'access_token': r['access_token'], 'refresh_token': r['refresh_token'],
                                  'expires_at': time.time() + int(r.get('expires_in', 3600))}
        w.state.pop('attempt', None)
        w.save()
        refresh_cards(w)
    return perform(*owner(business_id, session), complete)


@router.post('/wallet/{business_id}/enroll')
def enroll(business_id: str, response: Response, session: UserSession = Depends(sb_clients.authed_request)):
    response.headers.update(NO_STORE)
    def create(w):
        uid = (w.state.get('connection') or {}).get('user_id')
        if not uid:
            raise provider.AgentcardError('Verify your wallet connection first.', status=409)
        old = w.state.get('enrollment') or {}
        if old.get('status') == 'pending' and future(old.get('expires_at')):
            return
        r = provider.call('POST', '/api/v2/vault_sessions', {'user_id': uid, 'expires_in': 3600})
        url = provider.safe_url(r.get('url'), 'enroll')
        if not url or r.get('user_id') != uid or r.get('test_mode') is not (provider.mode() == 'sandbox'):
            raise provider.AgentcardError()
        w.state['enrollment'] = {'id': provider.identifier(r.get('id'), 'vs_'), 'url': url,
                                 'status': 'pending', 'expires_at': r.get('expires_at')}
        w.save()
    return perform(*owner(business_id, session), create)


def prepare(w, request_id, ask):
    if re.search(r'(?:\d[ -]?){13,19}', ask):
        raise provider.AgentcardError('Keep card numbers out of purchase requests. Use secure card setup.', status=409)
    p = w.state.get('purchase')
    if p and p.get('last_request_id') == request_id:
        return
    if p and p['phase'] not in {'draft', 'cart', 'closed', 'placed', 'declined'}:
        raise provider.AgentcardError('Check the current purchase before creating another request.', status=409)
    token = user_token(w)
    if not w.state.get('cards'):
        raise provider.AgentcardError('Add your card in the secure wallet first.', status=409)
    continuing = p and p['phase'] in {'draft', 'cart'}
    body = {'ask': ask}
    if continuing:
        body['conversation_id'] = p['conversation_id']
        p['request'] = (p.get('request', '') + '\n\n' + ask)[-12000:]
    else:
        if p:
            w.state['history'] = (w.state.get('history', []) + [p])[-20:]
        p = {'id': request_id, 'request': ask, 'phase': 'draft'}
        w.state['purchase'] = p
    p.update(phase='preparing', last_request_id=request_id)
    w.save()
    r = provider.request('POST', '/buy', body, token=token, timeout=130)
    p['conversation_id'] = provider.identifier(r.get('conversation_id'), 'conv_')
    apply_cart(p, r)
    w.save()


def apply_cart(p, r):
    carts = r.get('carts') or ([r['cart']] if r.get('cart') else [])
    cart = cart_view(carts[0]) if len(carts) == 1 else None
    p.update(phase='cart' if cart else 'draft', cart=cart, reply=text(r.get('reply'), 4000),
             unmatched=[{'requested': text(x.get('requested'), 300), 'reason': text(x.get('reason'), 200)}
                        for x in (r.get('unmatched') or []) if isinstance(x, dict)], approval_url=None)
    if len(carts) > 1:
        p.update(phase='draft', reply='Please choose one merchant and one cart for this purchase.')


@router.post('/wallet/{business_id}/ask')
def ask_route(business_id: str, body: Ask, response: Response, session: UserSession = Depends(sb_clients.authed_request)):
    response.headers.update(NO_STORE)
    return perform(*owner(business_id, session), lambda w: prepare(w, str(UUID(body.request_id)), body.ask))


def checkout(w, body, *, approved=None):
    if os.getenv('AGENTCARD_CHECKOUT_ENABLED') != 'true':
        raise provider.AgentcardError('Checkout is not enabled yet. Your cart is saved for review.', status=409)
    p = w.state.get('purchase') or {}
    cart = p.get('cart') or {}
    if p.get('id') != body.purchase_id or cart.get('hash') != body.cart_hash:
        raise provider.AgentcardError('This cart changed. Review the current cart before continuing.', status=409)
    auth_id = None
    if p.get('phase') == 'approval':
        # Only a provider-confirmed approval permits the documented second confirm.
        auth_id = approval_id(p.get('approval_url'))
        if auth_id in p.get('used_approval_ids', []):
            raise provider.AgentcardError('This approval has already been submitted. Check purchase status.', status=409)
        auth = approved or provider.call('GET', '/api/v2/checkout/authorizations/' + auth_id)
        if auth.get('id') != auth_id or auth.get('currency', '').lower() != 'usd' or auth.get('amount') != cart['total_cents']:
            raise provider.AgentcardError('The approval does not match the reviewed total.', status=409)
        if auth.get('status') != 'approved':
            raise provider.AgentcardError('Complete the secure approval first, then check again.', status=409)
    elif p.get('phase') != 'cart':
        raise provider.AgentcardError('Check the purchase status before continuing. Checkout cannot be repeated.', status=409)
    cap = int(os.getenv('AGENTCARD_MAX_PURCHASE_CENTS', '15000'))
    if type(cart.get('total_cents')) is not int or not 0 < cart['total_cents'] <= cap:
        raise provider.AgentcardError('This total exceeds the current wallet purchase limit.', status=409)
    token = user_token(w)
    if auth_id:
        p['used_approval_ids'] = p.get('used_approval_ids', []) + [auth_id]
    p.update(phase='submitting', confirmed_hash=body.cart_hash, approval_url=None)
    w.save()  # Durable claim before a money-moving call. Never retry on transport error.
    try:
        r = provider.request('POST', '/buy', {'conversation_id': p['conversation_id'],
            'confirm': body.cart_hash, 'payment_source': 'vault'}, token=token, timeout=130)
    except provider.AgentcardError as exc:
        if (exc.status == 409 and exc.data.get('code') != 'turn_in_progress'
                and exc.data.get('conversation_id') == p['conversation_id'] and exc.data.get('carts')):
            apply_cart(p, exc.data)
            p['message'] = 'The cart changed. Review the new total before confirming.'
            w.save()
            return
        raise
    if r.get('conversation_id') != p['conversation_id']:
        raise provider.AgentcardError()
    if (r.get('decline_code') == 'vault_approval_required' and r.get('charge_status') == 'none'
            and provider.safe_url(r.get('approval_url'), 'approve')):
        if approval_id(r['approval_url']) in p.get('used_approval_ids', []):
            p.update(phase='reconciling', approval_url=None)
        else:
            p.update(phase='approval', approval_url=r['approval_url'])
    elif r.get('status') == 'declined' and r.get('charge_status') == 'none':
        p.update(phase='declined', message='Sandbox rehearsal finished; no payment was made.' if r.get('decline_code') == 'sandbox_mode'
                 else 'Payment was declined. No order is confirmed. Review the purchase before trying again.')
    else:
        p['phase'] = 'reconciling'
    w.save()
    if p['phase'] == 'reconciling':
        reconcile(w)


@router.post('/wallet/{business_id}/confirm')
def confirm_route(business_id: str, body: Confirm, request: Request, response: Response,
                  session: UserSession = Depends(sb_clients.authed_request)):
    response.headers.update(NO_STORE)
    bid, uid = owner(business_id, session)
    require_unlock(request, uid, SCOPE_DANGER)
    return perform(bid, uid, lambda w: checkout(w, body))


@router.post('/wallet/{business_id}/close')
def close_route(business_id: str, response: Response, session: UserSession = Depends(sb_clients.authed_request)):
    response.headers.update(NO_STORE)
    def close(w):
        p = w.state.get('purchase') or {}
        if p.get('phase') not in {'draft', 'cart', 'declined', 'placed', 'closed', 'preparing'}:
            raise provider.AgentcardError('This purchase may still be processing. Check its status; it cannot be dismissed.', status=409)
        if p:
            w.state['history'] = (w.state.get('history', []) + [p])[-20:]
            w.state.pop('purchase', None)
            w.save()
    return perform(*owner(business_id, session), close)


def verify_signature(raw, signature, secret, now=None):
    if not secret or not signature or len(raw) > 1_000_000:
        return False
    try:
        parts = dict(p.strip().split('=', 1) for p in signature.split(','))
        stamp = parts['t']
        if not stamp.isdigit() or abs((time.time() if now is None else now) - int(stamp)) > 300:
            return False
        expected = hmac.new(secret.encode(), stamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, parts.get('v1', ''))
    except (ValueError, KeyError, TypeError):
        return False


@router.post('/webhooks')
async def webhook(request: Request):
    raw = b''
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > 1_000_000:
            raise HTTPException(413, 'Webhook too large.')
    if not verify_signature(raw, request.headers.get('AgentCard-Signature'), os.getenv('AGENTCARD_WEBHOOK_SECRET')):
        raise HTTPException(401, 'Invalid webhook signature.')
    try:
        event = json.loads(raw)
        event_id = provider.identifier(event.get('id'), 'evt_')
        if event.get('livemode') is not (provider.mode() == 'production'):
            raise ValueError()
        typ = event.get('type')
        if not isinstance(typ, str) or not re.fullmatch(r'[a-z_.]{1,100}', typ):
            raise ValueError()
    except (ValueError, AttributeError, provider.AgentcardError):
        raise HTTPException(400, 'Invalid webhook event.') from None
    # Durable inbox; UI refresh reads authoritative provider state. No webhook can initiate a purchase.
    encrypted = cipher().encrypt(raw).decode()
    import httpx
    key = sb_clients.sb_service_role()
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(sb_clients.sb_url() + '/rest/v1/agentcard_events?on_conflict=id',
            headers={'apikey': key, 'Authorization': 'Bearer ' + key, 'Prefer': 'resolution=ignore-duplicates'},
            json={'id': event_id, 'event_type': typ, 'livemode': event['livemode'], 'encrypted_payload': encrypted})
    if r.status_code >= 300:
        raise HTTPException(503, 'Webhook storage unavailable.')
    return {'received': True}
