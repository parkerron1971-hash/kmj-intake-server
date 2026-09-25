"""Solutionist Wallet v1: confidential Link OAuth and the isolated private rehearsal.

No live spend/credential/checkout endpoint exists here. OAuth protocol:
https://docs.stripe.com/agentic-commerce/link-cli/oauth
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import time
from contextlib import contextmanager
from typing import Literal
from types import SimpleNamespace
from urllib.parse import urlencode, quote
from uuid import UUID, uuid4

import httpx
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

import business_access
import chief_link_pilot as pilot
import sb_clients
from auth_supabase import UserSession
from chief_errands import rpc, uid
from ledger_unlock import require_unlock, SCOPE_DANGER

router = APIRouter(prefix='/link', tags=['wallet'])
CALLBACK = 'https://kmj-intake-server-production.up.railway.app/link/oauth/callback'
OPAQUE = re.compile(r'[A-Za-z0-9_-]{43,128}')
NO_STORE = {'Cache-Control': 'no-store', 'Pragma': 'no-cache', 'Referrer-Policy': 'no-referrer'}


class Completion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    state: str = Field(min_length=43, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    verifier: str = Field(min_length=43, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')


class PilotAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation: Literal['connect', 'status', 'rehearse', 'check', 'cancel', 'disconnect']


def owner(business_id, session):
    bid = uid(business_id)
    business_access.assert_access(bid, session.user, 'owner')
    return bid, str(session.user.id)


def configuration():
    return {name: os.getenv('LINK_WALLET_' + name.upper(), '') for name in
            ('client_id', 'client_secret', 'publishable_key')}


def cipher():
    try:
        return Fernet(os.environ['LINK_WALLET_ENCRYPTION_KEY'].encode('ascii'))
    except Exception:
        raise pilot.PilotError('Wallet connections are not available yet.') from None


def configured():
    conf = configuration()
    if (os.getenv('LINK_WALLET_ENABLED') != 'true' or not conf['client_id']
            or not conf['client_secret'] or not conf['publishable_key'].startswith('pk_live_')):
        return False
    try:
        cipher()
        return True
    except pilot.PilotError:
        return False


def require_configured():
    if not configured():
        raise HTTPException(503, 'Customer Link connections are awaiting activation.')


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Busy(pilot.PilotError):
    """A short-lived lease conflict; safe for callback receipt to retry."""


class Session:
    """Tenant-bound ciphertext and a database lease protect refresh-token rotation."""
    def __init__(self, bid, user_id):
        self.binding = {'business_id': str(UUID(bid)), 'user_id': str(UUID(user_id)), 'version': 1}
        self.args = {'p_business_id': bid, 'p_user_id': user_id, 'p_lease_id': str(uuid4())}
        self.state = {}

    def __enter__(self):
        key = cipher()
        result = rpc('link_wallet_acquire', **self.args)
        if not result or not result.get('acquired'):
            raise Busy('Another wallet operation is running. Try again shortly.')
        try:
            if result.get('encrypted_state'):
                value = json.loads(key.decrypt(result['encrypted_state'].encode()))
                if value['binding'] != self.binding or not isinstance(value['state'], dict):
                    raise ValueError()
                self.state = value['state']
        except Exception:
            self.__exit__(None, None, None)
            raise pilot.PilotError('This wallet connection could not be opened safely.') from None
        return self

    def save(self):
        value = cipher().encrypt(json.dumps({'binding': self.binding, 'state': self.state}).encode()).decode()
        if rpc('link_wallet_save', **self.args, p_encrypted_state=value,
               p_oauth_state_hash=(self.state.get('pending') or {}).get('state_hash')) is not True:
            raise pilot.PilotError('The wallet connection changed. Refresh before retrying.')

    def __exit__(self, *_):
        try:
            rpc('link_wallet_release', **self.args)
        except Exception:
            pass  # The lease expires; never print credentials or provider exceptions.


@contextmanager
def safe_operation(response):
    response.headers.update(NO_STORE)
    try:
        yield
    except HTTPException as exc:
        exc.headers = {**(exc.headers or {}), **NO_STORE}
        raise
    except pilot.PilotError as exc:
        raise HTTPException(409, str(exc), headers=NO_STORE) from None
    except Exception:
        raise HTTPException(503, 'Wallet is temporarily unavailable. Refresh before retrying.',
                            headers=NO_STORE) from None


def oauth_request(path, fields):
    """Fixed login host, bounded requests, sanitized errors, no redirects or retries."""
    conf = configuration()
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            response = client.post(pilot.LOGIN + path,
                headers={'Authorization': 'Bearer ' + conf['publishable_key']},
                data={'client_id': conf['client_id'], 'client_secret': conf['client_secret'], **fields})
            data = response.json() if response.content else {}
            return response.status_code, data if isinstance(data, dict) else {}
    except Exception:
        raise pilot.PilotError('Link could not be reached. Refresh before retrying.') from None


def save_tokens(session, data, previous=None):
    # Confidential refresh tokens rotate. Never retain the previous token if Link
    # omits a replacement, and never broaden financial-data permissions.
    if not data.get('refresh_token') or data.get('token_type', '').lower() != 'bearer':
        raise pilot.PilotError('Link returned an incomplete authorization. Reconnect your account.')
    auth = pilot.tokens(data, previous)
    session.state['auth'] = auth
    if previous is None:
        session.state['connected_at'] = time.time()
        session.state.pop('verified_at', None)
    session.save()
    return auth


def access(session, force=False):
    auth = session.state.get('auth')
    if not auth:
        raise pilot.PilotError('Connect your Link account first.')
    if force or auth['expires_at'] <= time.time() + 60:
        code, data = oauth_request('/auth/token', {'grant_type': 'refresh_token',
                                                  'refresh_token': auth['refresh_token']})
        if code == 400 and data.get('error') in ('invalid_grant', 'access_denied', 'expired_token'):
            session.state.pop('auth', None)
            session.save()
            raise pilot.PilotError('Link needs you to reconnect your account.')
        pilot.require_success(code)
        auth = save_tokens(session, data, auth)
    return auth['access_token']


def verify_connection(session):
    code, _ = pilot.request('GET', '/userinfo', token=access(session))
    if code == 401:
        code, _ = pilot.request('GET', '/userinfo', token=access(session, force=True))
    pilot.require_success(code)
    session.state['verified_at'] = time.time()
    session.save()


def customer_snapshot(session):
    state = session.state
    pending = state.get('pending', {})
    return {'connected': bool(state.get('auth')),
            'connecting': pending.get('expires_at', 0) > time.time(),
            'connected_at': state.get('connected_at') if state.get('auth') else None,
            'verified_at': state.get('verified_at') if state.get('auth') else None}


def private_snapshot(session):
    # Explicit allowlist: no auth, device codes, profile, card or raw provider data.
    result = pilot.snapshot(session)
    activity = []
    for name in ('trial', 'previous_trial'):
        trial = session.state.get(name) or {}
        if trial.get('id') and pilot.REQUEST_ID.fullmatch(str(trial['id'])):
            activity.append({'id': trial['id'], 'status': trial.get('status', 'unknown'),
                             'test_credential_verified': trial.get('verified') is True,
                             'amount': 100, 'currency': 'usd', 'merchant': 'Stripe Press'})
    result['activity'] = activity
    pending = session.state.get('pending') or {}
    result['poll_after_seconds'] = max(5, min(120, pending.get('interval', 5)))
    return result


def wallet_snapshot(bid, user_id):
    ready = configured()
    result = {'live_spending_enabled': False, 'customer_connections_available': ready,
              'customer': {'connected': False, 'connecting': False}, 'pilot': None}
    if os.getenv('LINK_WALLET_ENCRYPTION_KEY'):
        with Session(bid, user_id) as connection:
            result['customer'] = customer_snapshot(connection)
    if pilot.allowed(bid, user_id):
        with pilot.Session(bid, user_id) as connection:
            result['pilot'] = private_snapshot(connection)
    return result


@router.get('/wallet/{business_id}')
def status(business_id: str, response: Response, session: UserSession = Depends(sb_clients.authed_request)):
    bid, user_id = owner(business_id, session)
    with safe_operation(response):
        return wallet_snapshot(bid, user_id)


@router.post('/wallet/{business_id}/connect')
def connect(business_id: str, request: Request, response: Response,
            session: UserSession = Depends(sb_clients.authed_request)):
    bid, user_id = owner(business_id, session)
    require_unlock(request, user_id, SCOPE_DANGER)
    require_configured()
    with safe_operation(response), Session(bid, user_id) as connection:
        if connection.state.get('auth'):
            raise HTTPException(409, 'Disconnect the current Link account before connecting another.')
        state, pkce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        connection.state['pending'] = {'state_hash': digest(state), 'verifier_hash': digest(verifier),
                                       'pkce': pkce, 'expires_at': time.time() + 600}
        connection.save()
        conf = configuration()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(pkce.encode()).digest()).decode().rstrip('=')
        url = pilot.LOGIN + '/auth?' + urlencode({
            'key': conf['publishable_key'], 'client_id': conf['client_id'], 'redirect_uri': CALLBACK,
            'response_type': 'code', 'scope': pilot.SCOPE, 'state': state,
            'code_challenge': challenge, 'code_challenge_method': 'S256'}, quote_via=quote)
        return {'authorization_url': url, 'state': state, 'verifier': verifier, 'expires_in': 600}


@router.post('/wallet/{business_id}/complete')
def complete(business_id: str, body: Completion, response: Response,
             session: UserSession = Depends(sb_clients.authed_request)):
    bid, user_id = owner(business_id, session)
    require_configured()
    with safe_operation(response), Session(bid, user_id) as connection:
        pending = connection.state.get('pending') or {}
        if (pending.get('expires_at', 0) <= time.time()
                or not secrets.compare_digest(pending.get('state_hash', ''), digest(body.state))
                or not secrets.compare_digest(pending.get('verifier_hash', ''), digest(body.verifier))):
            raise HTTPException(400, 'This Link connection attempt expired or belongs to another session.')
        if pending.get('denied'):
            connection.state.pop('pending', None)
            connection.save()
            raise HTTPException(409, 'Link authorization was declined. You can connect again.')
        if not pending.get('code'):
            response.status_code = 202
            return {'connected': False, 'connecting': True}
        # Consume before exchange. A timeout is ambiguous: reconnect, never replay.
        connection.state.pop('pending', None)
        connection.save()
        code, data = oauth_request('/auth/token', {'grant_type': 'authorization_code',
            'code': pending['code'], 'redirect_uri': CALLBACK, 'code_verifier': pending['pkce']})
        pilot.require_success(code)
        save_tokens(connection, data)
        return customer_snapshot(connection)


@router.post('/wallet/{business_id}/refresh')
def refresh(business_id: str, response: Response, session: UserSession = Depends(sb_clients.authed_request)):
    bid, user_id = owner(business_id, session)
    require_configured()
    with safe_operation(response), Session(bid, user_id) as connection:
        verify_connection(connection)
        return customer_snapshot(connection)


@router.post('/wallet/{business_id}/disconnect')
def disconnect(business_id: str, response: Response, session: UserSession = Depends(sb_clients.authed_request)):
    bid, user_id = owner(business_id, session)
    # Revocation stays available when new connections are disabled.
    with safe_operation(response), Session(bid, user_id) as connection:
        auth = connection.state.get('auth')
        if auth:
            code, _ = oauth_request('/auth/revoke', {'token': auth['refresh_token'],
                                                    'token_type_hint': 'refresh_token'})
            pilot.require_success(code)
        connection.state = {}
        connection.save()
        return customer_snapshot(connection)


@router.post('/wallet/{business_id}/pilot')
def private_action(business_id: str, body: PilotAction, request: Request, response: Response,
                   session: UserSession = Depends(sb_clients.authed_request)):
    bid, user_id = owner(business_id, session)
    if not pilot.allowed(bid, user_id):
        raise HTTPException(403, 'The private test is available only to its configured owner.')
    if body.operation in ('connect', 'rehearse'):
        require_unlock(request, user_id, SCOPE_DANGER)
    with safe_operation(response):
        pilot.run(bid, user_id, body.operation)
        return wallet_snapshot(bid, user_id)


@router.get('/oauth/callback', response_class=HTMLResponse)
def callback(request: Request):
    # The callback records an encrypted code, never tokens. The original signed-in
    # owner must complete with a separate browser verifier. This also works when
    # Link or the browser severs window.opener (COOP, mobile tabs, popup policies).
    params = request.query_params
    state, code = params.get('state', ''), params.get('code', '')
    denied = 'error' in params
    request.scope['query_string'] = b''
    ok = False
    for attempt in range(6):
        try:
            if OPAQUE.fullmatch(state) and (denied or (0 < len(code) <= 4096 and not re.search(r'[\s<>]', code))):
                match = rpc('link_wallet_find_oauth', p_state_hash=digest(state))
                if match:
                    # Identity comes only from the server-held random-state lookup,
                    # never callback parameters. Recheck access if ownership changed.
                    business_access.assert_access(str(match['business_id']),
                        SimpleNamespace(id=str(match['user_id'])), 'owner')
                    with Session(str(match['business_id']), str(match['user_id'])) as connection:
                        pending = connection.state.get('pending') or {}
                        if (pending.get('expires_at', 0) > time.time()
                                and secrets.compare_digest(pending.get('state_hash', ''), digest(state))):
                            if not pending.get('code') and not pending.get('denied'):
                                pending.update({'denied': True} if denied else {'code': code})
                                connection.save()
                            ok = True
            break
        except Busy:
            # Completion polling can briefly own the same lease. No provider
            # call occurs here; first-callback-wins makes receipt idempotent.
            if attempt < 5:
                time.sleep(0.2)
        except Exception:
            break  # never reflect/log OAuth arguments or private state
    message = ('Return to your open Wallet page to finish connecting. You can close this window.'
               if ok else 'This connection could not be completed. Return to Wallet and start again.')
    html = ('<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Solutionist Wallet</title><body><h1>Return to Solutionist Wallet</h1><p>'
            + message + '</p></body></html>')
    return HTMLResponse(html, status_code=200 if ok else 400, headers={**NO_STORE,
        'Content-Security-Policy': "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
        'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY'})
