"""Owner-scoped native-account pilot: durable Chief jobs, never hosted OAuth.

Provider credentials remain in the customer's native CLI. Database transitions
serialize pairing, leases, completion and approval across server processes.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import os
import secrets
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from auth_supabase import AuthedUser, require_user
from connected_agents.contracts import Draft, RehearsalError
import feature_gates
import sb_clients

def _no_store(response: Response):
    response.headers['Cache-Control'] = 'no-store'


router = APIRouter(prefix="/connected-ai", tags=["connected-ai"], dependencies=[Depends(_no_store)])
ProviderName = Literal['chatgpt', 'claude']
DeviceState = Literal['signed_in', 'login_required', 'usage_limits', 'provider_not_installed', 'provider_unavailable']
Failure = Literal['usage_limits', 'login_required', 'provider_failed', 'provider_unavailable',
                  'invalid_output', 'incomplete_output', 'provider_timeout', 'provider_output_too_large']
ERRORS = {'owner_required', 'pairing_limit', 'pairing_expired', 'device_limit', 'device_revoked',
          'request_conflict', 'device_unavailable', 'job_already_active', 'lease_invalid', 'lease_expired',
          'already_reviewed', 'invoice_changed', 'invoice_not_overdue', 'invoice_contact_required'}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _rows(path: str) -> list:
    value = sb_clients.sb_get_as_service(path)
    if not isinstance(value, list):
        raise HTTPException(503, 'connection_service_unavailable')
    return value


def _owner(business_id: UUID, user: AuthedUser) -> dict:
    rows = _rows(f'/businesses?id=eq.{business_id}&select=*&limit=1')
    if not rows:
        raise HTTPException(404, 'business_not_found')
    if str(rows[0].get('owner_id')) != str(user.id):
        raise HTTPException(403, 'owner_required')
    return rows[0]


def enabled(business: dict) -> bool:
    # Server-controlled pilot eligibility; editable business settings grant none.
    allowlist = {v.strip() for v in os.getenv('CONNECTED_AI_PILOT_BUSINESSES', '').split(',') if v.strip()}
    return (os.getenv('CONNECTED_AI_ENABLED', '').lower() == 'on'
            and str(business['id']) in allowlist
            and feature_gates.has_feature(business, 'agent_connector_write'))


def _require_enabled(business: dict) -> None:
    if not enabled(business):
        raise HTTPException(403, 'connected_ai_not_enabled')


def transition(op: str, business_id: str, actor: str, data: dict | None = None) -> dict:
    base = os.getenv('SUPABASE_URL', '').rstrip('/')
    if not base or not os.getenv('SUPABASE_SERVICE_ROLE_KEY'):
        raise HTTPException(503, 'connection_service_unavailable')
    try:
        response = httpx.post(f'{base}/rest/v1/rpc/connected_ai_transition',
            headers=sb_clients.sb_headers_service(), timeout=20,
            json={'p_op': op, 'p_business': str(business_id), 'p_actor': str(actor), 'p_data': data or {}})
        if response.is_error:
            try:
                reason = response.json().get('message')
            except (ValueError, AttributeError):
                reason = None
            if reason in ERRORS:
                raise HTTPException(403 if reason in {'owner_required','device_revoked'} else 409, reason)
            raise HTTPException(503, 'connection_service_unavailable')
        result = response.json()
        if not isinstance(result, dict):
            raise HTTPException(503, 'connection_service_unavailable')
        return result
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, 'connection_service_unavailable') from None


def _worker(authorization: str | None) -> dict:
    if not authorization or not authorization.startswith('Bearer sol_device_'):
        raise HTTPException(401, 'device_auth_required')
    token = authorization[7:]
    if len(token) != 54:
        raise HTTPException(401, 'device_auth_required')
    rows = _rows(f'/connected_ai_devices?token_hash=eq.{digest(token)}&revoked_at=is.null&select=*&limit=1')
    if not rows:
        raise HTTPException(401, 'device_revoked')
    device = rows[0]
    try:
        if datetime.fromisoformat(device['expires_at'].replace('Z','+00:00')) <= datetime.now(timezone.utc):
            raise ValueError('expired')
    except (ValueError, KeyError, TypeError):
        raise HTTPException(401, 'device_revoked') from None
    business = _rows(f"/businesses?id=eq.{UUID(device['business_id'])}&select=*&limit=1")
    if not business or str(business[0].get('owner_id')) != str(device['owner_id']):
        raise HTTPException(403, 'device_revoked')
    _require_enabled(business[0])
    return device


class PairRequest(BaseModel):
    provider: ProviderName


class ClaimRequest(BaseModel):
    code: str = Field(min_length=43, max_length=43, pattern=r'^[A-Za-z0-9_-]+$')
    label: str = Field(min_length=1, max_length=80)


class Heartbeat(BaseModel):
    state: DeviceState
    job_id: UUID | None = None
    lease: str | None = Field(default=None, min_length=43, max_length=43)


class NewJob(BaseModel):
    device_id: UUID
    invoice_id: UUID
    request_id: UUID


class Completion(BaseModel):
    lease: str = Field(min_length=43, max_length=43)
    subject: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=20, max_length=4000)


class FailedJob(BaseModel):
    lease: str = Field(min_length=43, max_length=43)
    error: Failure


class Review(BaseModel):
    subject: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=20, max_length=4000)


@router.get('/status')
def status(business_id: UUID, user: AuthedUser = Depends(require_user)):
    business = _owner(business_id, user)
    if not enabled(business):
        return {'enabled': False, 'devices': [], 'jobs': [], 'reason': 'connected_ai_not_enabled'}
    result = transition('status', str(business_id), user.id)
    now = datetime.now(timezone.utc)
    for device in result.get('devices', []):
        try:
            seen = datetime.fromisoformat(device['last_seen_at'].replace('Z','+00:00'))
            expiry = datetime.fromisoformat(device['expires_at'].replace('Z','+00:00'))
            device['online'] = 0 <= (now-seen).total_seconds() < 90 and expiry > now
        except (KeyError, TypeError, ValueError, AttributeError):
            device['online'] = False
    return {'enabled': True, **result}


@router.post('/pairings')
def pair(payload: PairRequest, business_id: UUID, user: AuthedUser = Depends(require_user)):
    _require_enabled(_owner(business_id, user))
    code = secrets.token_urlsafe(32)
    result = transition('pair', str(business_id), user.id,
                        {'provider': payload.provider, 'secret_hash': digest(code)})
    return {**result, 'code': code, 'provider': payload.provider}


@router.post('/claim')
def claim(payload: ClaimRequest):
    if not payload.label.strip():
        raise HTTPException(422, 'device_label_required')
    hashed = digest(payload.code)
    rows = _rows(f'/connected_ai_pairings?secret_hash=eq.{hashed}&select=business_id,owner_id&limit=1')
    if not rows:
        raise HTTPException(409, 'pairing_expired')
    row = rows[0]
    business = _rows(f"/businesses?id=eq.{UUID(row['business_id'])}&select=*&limit=1")
    if not business or str(business[0]['owner_id']) != str(row['owner_id']):
        raise HTTPException(409, 'pairing_expired')
    _require_enabled(business[0])
    token = 'sol_device_' + secrets.token_urlsafe(32)
    device = transition('claim', row['business_id'], row['owner_id'],
                        {'secret_hash': hashed, 'token_hash': digest(token), 'label': payload.label.strip()})
    return {'device': device, 'device_token': token}


def _device_data(device: dict, **extra) -> dict:
    return {'device_id': device['id'], 'token_hash': device['token_hash'], **extra}


@router.post('/heartbeat')
def heartbeat(payload: Heartbeat, authorization: str | None = Header(default=None)):
    device = _worker(authorization)
    return transition('heartbeat', device['business_id'], device['owner_id'], _device_data(device,
        state=payload.state, job_id=str(payload.job_id) if payload.job_id else None,
        lease_hash=digest(payload.lease) if payload.lease else None))


@router.post('/lease')
def lease(authorization: str | None = Header(default=None)):
    device = _worker(authorization)
    secret = secrets.token_urlsafe(32)
    result = transition('lease', device['business_id'], device['owner_id'],
                        _device_data(device, lease_hash=digest(secret)))
    if result.get('job'):
        result['job']['lease'] = secret
    return result


@router.post('/jobs')
def enqueue(payload: NewJob, business_id: UUID, user: AuthedUser = Depends(require_user)):
    _require_enabled(_owner(business_id, user))
    return transition('enqueue', str(business_id), user.id,
                      {key: str(value) for key, value in payload.model_dump().items()})


@router.post('/jobs/{job_id}/complete')
def complete(job_id: UUID, payload: Completion, authorization: str | None = Header(default=None)):
    device = _worker(authorization)
    try:
        draft = Draft.parse({'subject': payload.subject, 'body': payload.body})
    except RehearsalError:
        raise HTTPException(422, 'invalid_output') from None
    return transition('complete', device['business_id'], device['owner_id'], _device_data(device,
        job_id=str(job_id), lease_hash=digest(payload.lease), subject=draft.subject, body=draft.body))


@router.post('/jobs/{job_id}/fail')
def fail(job_id: UUID, payload: FailedJob, authorization: str | None = Header(default=None)):
    device = _worker(authorization)
    return transition('fail', device['business_id'], device['owner_id'], _device_data(device,
        job_id=str(job_id), lease_hash=digest(payload.lease), error=payload.error))


@router.delete('/devices/{device_id}')
def revoke(device_id: UUID, business_id: UUID, user: AuthedUser = Depends(require_user)):
    _owner(business_id, user)
    return transition('revoke', str(business_id), user.id, {'device_id': str(device_id)})


@router.post('/jobs/{job_id}/cancel')
def cancel(job_id: UUID, business_id: UUID, user: AuthedUser = Depends(require_user)):
    _owner(business_id, user)
    return transition('cancel', str(business_id), user.id, {'job_id': str(job_id)})


@router.get('/invoices')
def invoices(business_id: UUID, user: AuthedUser = Depends(require_user)):
    _require_enabled(_owner(business_id, user))
    # Canonical invoices store decimal `total`, not the abandoned Stripe
    # mirror's amount_due_cents/customer_email columns. No cross-tenant join.
    rows = _rows(f'/invoices?business_id=eq.{business_id}&status=in.(sent,viewed,overdue)'
                 f'&due_date=lt.{date.today().isoformat()}&total=gt.0&archived_at=is.null&paid_at=is.null'
                 '&select=id,invoice_number,total,currency,due_date&order=due_date.asc&limit=100')
    return {'invoices': [{'id': row['id'], 'invoice_number': row['invoice_number'],
        'amount_due_cents': int((Decimal(str(row['total']))*100).quantize(Decimal('1'), rounding=ROUND_HALF_UP)),
        'currency': row['currency'], 'due_date': row['due_date']} for row in rows]}


@router.get('/jobs/{job_id}/draft')
def draft_for_review(job_id: UUID, business_id: UUID, user: AuthedUser = Depends(require_user)):
    _owner(business_id, user)
    rows = _rows(f'/agent_queue?connected_ai_job_id=eq.{job_id}&business_id=eq.{business_id}'
                 '&select=id,subject,body,status,contact_id&limit=1')
    if not rows:
        raise HTTPException(404, 'draft_not_found')
    contacts = _rows(f"/contacts?id=eq.{UUID(rows[0]['contact_id'])}&business_id=eq.{business_id}&select=name,email&limit=1")
    return {**rows[0], 'recipient': contacts[0] if contacts else None}


async def approve_connected(business: dict, item: dict, actor: str | None, edits: dict | None = None) -> dict:
    """Only an explicit, owner-authenticated review may claim the single send.

    An uncertain send is never automatically retried. Its durable 'sending'
    marker survives a server crash and prevents a second delivery attempt.
    """
    if not actor or str(business.get('owner_id')) != str(actor):
        return {'ok': False, 'sent': False, 'reason': 'human_review_required',
                'message': 'The business owner must review this in Connect your AI before sending.'}
    _require_enabled(business)
    job_id = str(UUID(str(item['connected_ai_job_id'])))
    try:
        draft = Draft.parse(edits or {'subject': item['subject'], 'body': item['body']})
    except RehearsalError:
        raise HTTPException(422, 'invalid_output') from None
    claimed = await asyncio.to_thread(transition, 'claim_send', business['id'], actor,
                                     {'job_id': job_id, 'subject': draft.subject, 'body': draft.body})
    import chief_of_staff
    try:
        async with httpx.AsyncClient() as client:
            delivery = await chief_of_staff._send_queued_email(client, business, claimed['item'],
                connected_delivery=True, expected_email=claimed['expected_email'])
    except Exception:
        delivery = {'sent': False, 'reason': 'delivery_needs_check'}
    await asyncio.to_thread(transition, 'settle_send', business['id'], actor,
        {'job_id': job_id, 'sent': bool(delivery.get('sent')), 'provider_id': delivery.get('provider_id')})
    return {'ok': bool(delivery.get('sent')), 'sent': bool(delivery.get('sent')),
            'reason': 'sent' if delivery.get('sent') else 'delivery_needs_check',
            'provider_id': delivery.get('provider_id')}


@router.post('/jobs/{job_id}/approve')
async def approve(job_id: UUID, payload: Review, business_id: UUID, user: AuthedUser = Depends(require_user)):
    business = await asyncio.to_thread(_owner, business_id, user)
    rows = await asyncio.to_thread(_rows, f'/agent_queue?connected_ai_job_id=eq.{job_id}&business_id=eq.{business_id}&select=*&limit=1')
    if not rows:
        raise HTTPException(404, 'draft_not_found')
    return await approve_connected(business, rows[0], user.id, payload.model_dump())


@router.get('/companion.zip')
def companion_download(business_id: UUID, user: AuthedUser = Depends(require_user)):
    _require_enabled(_owner(business_id, user))
    buffer = io.BytesIO()
    root = Path(__file__).parent
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in ('__init__.py','contracts.py','runtime.py','companion.py'):
            archive.write(root / 'connected_agents' / name, 'connected_agents/' + name)
        archive.writestr('Start Solutionist.cmd', '@echo off\r\ncd /d "%~dp0"\r\npy -3 -m connected_agents.companion\r\npause\r\n')
        archive.writestr('README.txt', 'Solutionist desktop connection pilot\n\nRequires Python 3.11+ and the native Claude or Codex app/CLI.\nExtract the ZIP, then open Start Solutionist.cmd on Windows.\nOn macOS/Linux run: python3 -m connected_agents.companion\nPaste the one-use code from Connect your AI when asked.\nSign in directly with your provider. Keep this window running.\nClose it to stop work. Disconnect in Solutionist to revoke access.\nNo automatic installation, startup service, or provider credentials are uploaded.\n')
    return Response(buffer.getvalue(), media_type='application/zip',
                    headers={'Content-Disposition': 'attachment; filename="Solutionist-Desktop-Connection.zip"',
                             'Cache-Control': 'no-store'})
