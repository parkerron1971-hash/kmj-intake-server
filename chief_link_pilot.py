"""Private Link device-flow rehearsal. No live spending or merchant execution.

Protocol follows stripe/link-cli (CLI 0.19.1 / SDK 0.4.1). The public client
is used only for the owner's private pilot, not offered as a customer product.
All provider bodies are private; only explicit status fields leave this module.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import os
import re
import time
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from cryptography.fernet import Fernet

CLIENT_ID = 'lwlpk_U7Qy7ThG69STZk'  # Stripe's published public device client ID
SCOPE = 'payment_methods.agentic userinfo:read'
LOGIN = 'https://login.link.com'
API = 'https://api.link.com'
OPERATIONS = ('connect', 'status', 'rehearse', 'check', 'cancel', 'disconnect')
STATUSES = {'pending', 'pending_approval', 'approved', 'declined', 'canceled',
            'expired', 'completed', 'failed', 'requires_approval', 'created',
            'denied', 'succeeded', 'requires_action'}
TERMINAL = {'canceled', 'expired', 'declined', 'denied', 'completed', 'succeeded', 'failed'}
REQUEST_ID = re.compile(r'lsrq_[A-Za-z0-9]{1,100}')
_CHAT_AUTHORIZED = contextvars.ContextVar('chief_link_pilot.chat_authorized', default=False)


class PilotError(Exception):
    """Only application-authored, credential-free messages belong here."""


def allowed(business_id, user_id):
    return bool(os.getenv('CHIEF_LINK_PILOT_ENABLED') == 'true'
                and user_id and business_id
                and str(user_id) == os.getenv('CHIEF_LINK_PILOT_USER_ID')
                and str(business_id) == os.getenv('CHIEF_LINK_PILOT_BUSINESS_ID'))


def cipher():
    try:
        return Fernet(os.environ['CHIEF_LINK_PILOT_ENCRYPTION_KEY'].encode())
    except Exception:
        raise PilotError('The private Link pilot is not configured yet.') from None


def rpc(name, **args):
    from chief_errands import rpc as call
    return call(name, **args)


class Session:
    """Database lease serializes token rotation and retries across workers/deploys."""
    def __init__(self, business_id, user_id):
        self.binding = {'business_id': str(UUID(business_id)), 'user_id': str(UUID(user_id)), 'version': 1}
        self.args = {'p_business_id': business_id, 'p_user_id': user_id, 'p_lease_id': str(uuid4())}
        self.state = {}

    def __enter__(self):
        key = cipher()  # fail before acquiring a lease if configuration is incomplete
        result = rpc('chief_link_pilot_acquire', **self.args)
        if not result or not result.get('acquired'):
            raise PilotError('Another Link operation is running. Try again shortly.')
        try:
            if result.get('encrypted_state'):
                value = json.loads(key.decrypt(result['encrypted_state'].encode()))
                if value['binding'] != self.binding or not isinstance(value['state'], dict):
                    raise ValueError()
                self.state = value['state']
        except Exception:
            self.__exit__(None, None, None)
            raise PilotError('The private Link session could not be opened safely.') from None
        return self

    def save(self):
        value = cipher().encrypt(json.dumps({'binding': self.binding, 'state': self.state}).encode()).decode()
        if rpc('chief_link_pilot_save', **self.args, p_encrypted_state=value) is not True:
            raise PilotError('The Link session changed. Check its status before retrying.')

    def __exit__(self, *_):
        try:
            rpc('chief_link_pilot_release', **self.args)
        except Exception:
            pass  # lease expires; never log the encrypted session or exception context


def request(method, path, *, token=None, form=None, body=None):
    """Fixed provider hosts, no redirects, bounded timeout, no provider text errors."""
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            response = client.request(method, (API if token else LOGIN) + path,
                                      headers={'Authorization': 'Bearer ' + token} if token else {},
                                      data=form, json=body)
            data = response.json()
            return response.status_code, data if isinstance(data, dict) else {}
    except Exception:
        raise PilotError('Link could not be reached. Check status before retrying.') from None


def require_success(code):
    if not 200 <= code < 300:
        raise PilotError('Link did not complete this step. Check status or reconnect; no order was placed.')


def safe_url(value, purpose):
    try:
        parsed = urlsplit(value)
        prefix = '/device/' if purpose == 'connect' else '/activity/approve/'
        if (parsed.scheme == 'https' and parsed.hostname == 'app.link.com'
                and parsed.netloc == 'app.link.com' and parsed.path.startswith(prefix)
                and not parsed.fragment):
            return value
    except Exception:
        pass
    raise PilotError('Link did not return a valid approval link.')


def tokens(data, previous=None):
    access = data.get('access_token')
    refresh = data.get('refresh_token') or (previous or {}).get('refresh_token')
    scope = set(str(data.get('scope') or (previous or {}).get('scope') or '').split())
    if (not isinstance(access, str) or not 1 <= len(access) <= 8192
            or not isinstance(refresh, str) or not 1 <= len(refresh) <= 8192
            or scope != set(SCOPE.split())):
        raise PilotError('Link authorization was incomplete or had unexpected permissions. Reconnect in Link.')
    return {'access_token': access, 'refresh_token': refresh, 'scope': SCOPE,
            'expires_at': time.time() + max(1, min(int(data.get('expires_in', 0)), 86400))}


def access(session, force=False):
    auth = session.state.get('auth')
    if not auth:
        raise PilotError('Connect your Link account first, then ask Chief to check the connection.')
    if force or auth['expires_at'] <= time.time() + 60:
        code, data = request('POST', '/device/token', form={
            'client_id': CLIENT_ID, 'grant_type': 'refresh_token', 'refresh_token': auth['refresh_token']})
        if code == 400 and data.get('error') in ('invalid_grant', 'access_denied', 'expired_token'):
            session.state.pop('auth', None)
            session.save()
            raise PilotError('This Link connection is no longer authorized. Ask to connect again.')
        require_success(code)
        auth = tokens(data, auth)
        session.state['auth'] = auth
        session.save()  # persist the rotated token before using it anywhere
    return auth['access_token']


def provider(session, method, path, body=None):
    code, data = request(method, path, token=access(session), body=body)
    # An explicit 401 means no operation was authorized. Refresh once; never
    # retry a timeout/5xx or other ambiguous mutation automatically.
    if code == 401:
        code, data = request(method, path, token=access(session, force=True), body=body)
    require_success(code)
    return data


def poll_connection(session):
    pending = session.state.get('pending')
    if not pending or session.state.get('auth'):
        return
    if pending['expires_at'] <= time.time():
        session.state.pop('pending', None)
        session.save()
        return
    if pending['next_poll'] > time.time():
        return
    pending['next_poll'] = time.time() + pending['interval']
    session.save()
    code, data = request('POST', '/device/token', form={
        'client_id': CLIENT_ID, 'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
        'device_code': pending['device_code']})
    if code == 400 and data.get('error') in ('authorization_pending', 'slow_down'):
        if data['error'] == 'slow_down':
            pending['interval'] = min(pending['interval'] + 5, 120)
            pending['next_poll'] = time.time() + pending['interval']
            session.save()
        return
    if code == 400 and data.get('error') in ('expired_token', 'access_denied', 'authorization_failed'):
        session.state.pop('pending', None)
        session.save()
        raise PilotError('Link authorization expired or was declined. Ask to connect again.')
    require_success(code)
    session.state['auth'] = tokens(data)
    session.state.pop('pending', None)
    session.save()


def snapshot(session, note=None):
    state = session.state
    trial = state.get('trial', {})
    pending = state.get('pending', {})
    result = {'type': 'link_wallet_pilot', 'label': 'Link private test', 'test_mode': True,
              'connected': bool(state.get('auth')), 'status': trial.get('status') or (
                  'connected' if state.get('auth') else 'awaiting_connection' if pending else 'disconnected'),
              'test_credential_verified': trial.get('verified') is True,
              'result': note or 'Private Link rehearsal only. No merchant order or real charge has been made.'}
    if pending and not state.get('auth'):
        result['connection_url'] = safe_url(pending['url'], 'connect')
    if trial.get('approval_url') and trial.get('status') not in TERMINAL:
        result['approval_url'] = safe_url(trial['approval_url'], 'approve')
    if trial.get('id'):
        result['test_request_id'] = trial['id']
    return result


def trial_id(trial):
    value = trial.get('id', '')
    if not REQUEST_ID.fullmatch(value):
        raise PilotError('The test request is not ready. Ask to rehearse again to recover the same request.')
    return value


def record_trial(session, data):
    status = data.get('status')
    if not REQUEST_ID.fullmatch(str(data.get('id', ''))) or status not in STATUSES:
        raise PilotError('Link returned an unrecognized test status. No checkout was attempted.')
    trial = session.state['trial']
    if trial.get('id') and data['id'] != trial['id']:
        raise PilotError('Link returned a different request. The test was stopped.')
    trial.update(id=data['id'], status=status)
    session.save()


def create_trial(session, approval=True):
    access(session)
    if not session.state.get('trial'):
        session.state['trial'] = {'key': str(uuid4()), 'status': 'creating', 'verified': False}
        session.save()  # journal stable idempotency key BEFORE any provider write
    trial = session.state['trial']
    if not trial.get('id'):
        # None of these values can come from the model, client, business settings or env.
        code, data = request('POST', '/spend_requests', token=access(session), body={
            'idempotency_key': 'chief-link-pilot-' + trial['key'], 'test': True,
            'credential_type': 'card', 'amount': 100, 'currency': 'usd',
            'merchant_name': 'Stripe Press', 'merchant_url': 'https://press.stripe.com',
            'context': 'Solutionist Chief PRIVATE TEST ONLY: simulated $1 approval. No item will be ordered.',
        })
        if code == 409:
            data = (data.get('error') or {}).get('duplicate_spend_request') or {}
        else:
            require_success(code)
        record_trial(session, data)
    if trial['status'] in TERMINAL:
        return
    if approval and not trial.get('approval_url') and trial['status'] != 'approved':
        data = provider(session, 'POST', '/spend_requests/' + trial_id(trial) + '/request_approval')
        if data.get('id') != trial['id']:
            raise PilotError('Link returned a different approval request. The test was stopped.')
        trial['approval_url'] = safe_url(data.get('approval_link'), 'approve')
        session.save()


def cancel_trial(session):
    trial = session.state.get('trial')
    if not trial or trial.get('status') in TERMINAL:
        return
    if not trial.get('id'):
        create_trial(session, approval=False)  # recover the journaled request before cancellation
    data = provider(session, 'POST', '/spend_requests/' + trial_id(trial) + '/cancel')
    record_trial(session, data)
    if trial['status'] != 'canceled':
        raise PilotError('Link has not confirmed cancellation yet. Ask to cancel the test again.')


def check_trial(session):
    trial = session.state.get('trial')
    if not trial:
        return
    path = '/spend_requests/' + trial_id(trial)
    record_trial(session, provider(session, 'GET', path))
    if trial['status'] == 'approved':
        if not trial.get('verified'):
            data = provider(session, 'GET', path + '?include=card')
            # The sole credential read: fake test credential validation in memory.
            # Never return, persist, log, or supply this body to Chief/browser/Sentry.
            card = data.get('card') or {}
            valid = (data.get('id') == trial['id'] and data.get('status') == 'approved'
                     and card.get('number') == '4242424242424242'
                     and bool(card.get('cvc')) and bool(card.get('exp_month')) and bool(card.get('exp_year')))
            del data, card
            trial['verified'] = bool(valid)
            session.save()
            if not valid:
                cancel_trial(session)
                raise PilotError('The test credential did not match the expected fake card. The request was canceled.')
        cancel_trial(session)  # no merchant ever receives even the fake credential


def run(business_id, user_id, operation):
    if not allowed(business_id, user_id):
        raise PilotError('This private Link test is available only to its configured owner and business.')
    if operation not in OPERATIONS:
        raise PilotError('Choose connect, status, rehearse, check, cancel or disconnect.')
    import business_access
    business_access.assert_access(business_id, SimpleNamespace(id=user_id), 'owner')
    with Session(business_id, user_id) as session:
        if operation == 'connect':
            if not session.state.get('auth') and not (session.state.get('pending', {}).get('expires_at', 0) > time.time()):
                code, data = request('POST', '/device/code', form={
                    'client_id': CLIENT_ID, 'scope': SCOPE,
                    'connection_label': 'Chief Private Test on Solutionist', 'client_hint': 'Chief Private Test'})
                require_success(code)
                device = data.get('device_code')
                if not isinstance(device, str) or not 1 <= len(device) <= 8192:
                    raise PilotError('Link did not start authorization. Try again.')
                interval = max(5, min(int(data.get('interval', 5)), 120))
                session.state['pending'] = {'device_code': device,
                    'url': safe_url(data.get('verification_uri_complete'), 'connect'),
                    'expires_at': time.time() + max(1, min(int(data.get('expires_in', 0)), 3600)),
                    'interval': interval, 'next_poll': time.time() + interval}
                session.save()
        elif operation == 'status':
            poll_connection(session)
            if session.state.get('auth'):
                provider(session, 'GET', '/userinfo')  # verify the connection; discard all profile fields
        elif operation == 'rehearse':
            create_trial(session)
        elif operation == 'check':
            poll_connection(session)
            check_trial(session)
        elif operation == 'cancel':
            cancel_trial(session)
        elif operation == 'disconnect':
            cancel_trial(session)
            auth = session.state.get('auth')
            if auth:
                code, _ = request('POST', '/device/revoke', form={
                    'client_id': CLIENT_ID, 'token': auth['refresh_token']})
                require_success(code)
            session.state = {}
            session.save()
            return snapshot(session, 'Private Link connection removed. Pending test requests were canceled first.')
        return snapshot(session)


async def handle_link_wallet_pilot(client, biz, action):
    from chief_of_staff import _TURN_USER_ID
    from chief_host import _fail
    # Reject all undeclared knobs, including identity, card, amount and live mode.
    if not _CHAT_AUTHORIZED.get():
        return _fail('link_wallet_pilot', 'The private Link pilot requires your current Chief chat turn.')
    if set(action) - {'type', 'operation'}:
        return _fail('link_wallet_pilot', 'This pilot accepts only an operation; it cannot make live purchases.')
    try:
        return await asyncio.to_thread(run, str(biz['id']), _TURN_USER_ID.get(), action.get('operation', 'status'))
    except PilotError as exc:
        return _fail('link_wallet_pilot', str(exc))
    except Exception:
        return _fail('link_wallet_pilot', 'The private Link test could not complete safely. No merchant checkout was attempted.')


async def dispatch(client, biz, action, *, surface, prompted, user_id):
    """Called only by Chief's central action door; direct handler calls fail closed."""
    from chief_of_staff import _TURN_USER_ID
    from chief_host import _fail
    if surface != 'chat' or not prompted or not user_id or user_id != _TURN_USER_ID.get():
        return _fail('link_wallet_pilot', 'The private Link pilot requires your current Chief chat turn.')
    token = _CHAT_AUTHORIZED.set(True)
    try:
        return await handle_link_wallet_pilot(client, biz, action)
    finally:
        _CHAT_AUTHORIZED.reset(token)


def tool_definition():
    return {'name': 'link_wallet_pilot', 'description': (
        'Run the configured owner\'s private Link TEST pilot. connect returns a Link connection URL; '
        'status polls authorization after the owner finishes at Link; rehearse creates one simulated $1 '
        'Stripe Press approval; check verifies its fake credential after approval and cancels the test; '
        'cancel stops the test; disconnect revokes this pilot connection. No real purchase is possible. '
        'Call the tool before claiming anything connected or succeeded. Share returned links exactly. '
        'Never ask for cards, tokens, codes or passwords. Do not emit a duplicate ACTION tag.'),
        'input_schema': {'type': 'object', 'properties': {'operation': {'type': 'string', 'enum': list(OPERATIONS)}},
                         'required': ['operation'], 'additionalProperties': False}}
