"""Chief Computer API, durable state and thread mailbox (arc PR3).

Plaintext Secure Entry bodies never reach chat, the database, logs or model
tools. A per-run worker mailbox is the only bridge to Playwright's owning thread.
All DB RPCs are service-only, with tenant/role checks at each HTTP boundary.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from concurrent.futures import Future, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
import queue
import re
import threading
import time
from urllib.parse import quote, urlsplit
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from auth_supabase import UserSession
import business_access
import sb_clients
from ledger_unlock import require_unlock, SCOPE_DANGER
import secret_vault

router = APIRouter(prefix='/agents/chief', tags=['chief-computer'])
ACTIVE = ('planned','approved','running','needs_you','paused')
LIVE = ('approved','running','needs_you','paused')
TERMINAL = ('done','failed','stopped','cancelled','interrupted')
INTERRUPTED = 'The server restarted. Check the supplier before trying again; an order may already have been placed.'
DEFAULT_SETTINGS = {'allowed_hosts': [], 'deny_hosts': ['amazon.com'],
    'spend_limit_cents': 15000, 'require_stepup_unpriced': True,
    'save_cards': False, 'prefer_virtual_card': False, 'max_minutes': 8}
ERRAND_COLUMNS = ('id,business_id,user_id,job_id,kind,status,title,plan,hosts,spend_limit_cents,'
    'planned_total_cents,observed_total_cents,approved_at,approved_by,approval_scope,hold,receipt,'
    'idempotency_key,cancel_until,error,created_at,started_at,finished_at')
EVENT_COLUMNS = 'n,at,kind,note,frame_path,url_host,meta'
_attempts = defaultdict(deque)
_attempt_lock = threading.Lock()
_mailboxes = {}
_mailbox_lock = threading.Lock()


def now():
    return datetime.now(timezone.utc).isoformat()


def uid(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, 'A valid identifier is required.') from None


def db(method, path, body=None):
    """Dedicated service transport: never log response text, bodies or headers."""
    key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
    try:
        response = httpx.request(method, os.environ['SUPABASE_URL'].rstrip('/') + '/rest/v1' + path,
            headers={'apikey':key,'Authorization':'Bearer '+key,'Prefer':'return=representation'},
            json=body, timeout=15)
    except Exception:
        raise HTTPException(503, 'Chief computer storage is unavailable.') from None
    if response.status_code >= 400:
        if response.status_code in (400,409):
            raise HTTPException(409, 'The errand changed or another errand is already running. Refresh and try again.')
        raise HTTPException(503, 'Chief computer storage is unavailable.')
    return response.json() if response.content else None


def rpc(name, **body):
    return db('POST', '/rpc/'+name, body)


def get_row(errand_id):
    rows=db('GET',f'/chief_errands?id=eq.{uid(errand_id)}&select={ERRAND_COLUMNS}&limit=1') or []
    if not rows:
        raise HTTPException(404, 'Errand not found.')
    return rows[0]


def business(business_id, user, min_role='viewer'):
    bid=uid(business_id)
    business_access.assert_access(bid, user, min_role)
    rows=db('GET', f'/businesses?id=eq.{bid}&select=id,name,settings&limit=1') or []
    if not rows:
        raise HTTPException(404, 'Business not found.')
    return rows[0]


def authorized(errand_id, user, min_role='viewer'):
    row=get_row(errand_id)
    business_access.assert_access(row['business_id'], user, min_role)
    return row


def settings_of(biz):
    stored=(biz.get('settings') or {}).get('computer') or {}
    result={**DEFAULT_SETTINGS, **{k:v for k,v in stored.items() if k in DEFAULT_SETTINGS}}
    result['deny_hosts']=sorted(set(['amazon.com', *result.get('deny_hosts',[]), *stored.get('deny_hosts_extra',[])]))
    result['save_cards']=False
    result['prefer_virtual_card']=False
    result['max_minutes']=min(8,max(1,int(result.get('max_minutes',8))))
    return result


def validate_settings(raw):
    if not isinstance(raw,dict) or set(raw)-set(DEFAULT_SETTINGS):
        raise HTTPException(422,'Invalid computer settings.')
    result={**DEFAULT_SETTINGS,**raw}
    for key in ('allowed_hosts','deny_hosts'):
        if not isinstance(result[key],list) or len(result[key])>20:
            raise HTTPException(422,'Choose at most 20 exact hosts.')
        result[key]=sorted(set(secret_vault.normalize_host(h) for h in result[key]))
    result['deny_hosts']=sorted(set(['amazon.com',*result['deny_hosts']]))
    if type(result['spend_limit_cents']) is not int or not 0<=result['spend_limit_cents']<=10000000:
        raise HTTPException(422,'Invalid spend limit.')
    if type(result['max_minutes']) is not int or not 1<=result['max_minutes']<=8:
        raise HTTPException(422,'Errands can run for 1 to 8 minutes.')
    for key in ('require_stepup_unpriced','save_cards','prefer_virtual_card'):
        if type(result[key]) is not bool:
            raise HTTPException(422,'Invalid computer setting.')
    if result['save_cards'] or result['prefer_virtual_card']:
        raise HTTPException(422,'Saved cards and virtual card issuing are not enabled.')
    return result


def needs_stepup(total, limit, settings):
    return (total is None and bool(settings['require_stepup_unpriced'])) or (total is not None and total>limit)


def outward(row, steps=0):
    allowed=('id','business_id','kind','status','title','plan','hosts','spend_limit_cents',
        'planned_total_cents','observed_total_cents','approved_at','approval_scope','hold','receipt',
        'cancel_until','error','created_at','started_at','finished_at')
    result={k:row.get(k) for k in allowed}
    result['plan']={k:v for k,v in (row.get('plan') or {}).items() if not k.startswith('__')}
    result['steps_done']=steps
    result['steps_total_hint']=60
    return result


def card(row, *, planned=False, replay=False):
    return {'type':'errand_plan' if planned else 'errand_status','errand_id':row['id'],
        'errand':outward(row),'label':row['title'],'result':f"Errand {row['status']}.",
        'nav':{'room':'operate','panel':'computer'}, **({'replay':True} if replay else {})}


def event(row, kind, note, **extra):
    # Extra is produced by the controller/driver, never arbitrary API/model JSON.
    return rpc('chief_errand_event',p_business_id=row['business_id'],p_id=row['id'],
               p_event={'kind':kind,'note':note,**extra})


def transition(row, expected, patch, kind=None, note=None, hold_id=None):
    return rpc('chief_errand_transition',p_business_id=row['business_id'],p_id=row['id'],
        p_expected=list(expected),p_patch=patch,p_hold_id=hold_id,
        p_event={'kind':kind,'note':note} if kind else None)


def rate_limit(user_id, errand_id):
    timestamp=time.monotonic()
    with _attempt_lock:
        for key in list(_attempts):
            if not _attempts[key] or _attempts[key][-1]<timestamp-60:
                del _attempts[key]
        key=(user_id,errand_id)
        recent=_attempts[key]
        while recent and recent[0]<timestamp-60:
            recent.popleft()
        if len(recent)>=6:
            raise HTTPException(429,'Too many Secure Entry attempts. Wait a minute.')
        recent.append(timestamp)


async def json_body(request, maximum=16384):
    # Avoid model-validation errors that echo bad plaintext inputs in a 422.
    data=bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data)>maximum:
            raise HTTPException(413,'Request is too large.')
    try:
        body=json.loads(data)
    except Exception:
        raise HTTPException(422,'Invalid request body.') from None
    if not isinstance(body,dict):
        raise HTTPException(422,'Invalid request body.')
    return body


def _price(value):
    if value is None:
        return None
    try:
        cents=int((Decimal(str(value))*100).quantize(Decimal('1')))
        return cents if 0<=cents<=10000000 else None
    except (InvalidOperation,ValueError,OverflowError):
        return None


async def plan(biz, user_id, body, client=None):
    from browser_controller import host_allowed
    from chief_inventory_actions import _primary_supplier, handle_draft_purchase_order
    from reorder_engine import compose_purchase_order, REORDER_DEDUP_HOURS
    settings=settings_of(biz)
    kind=body.get('kind','reorder')
    if kind!='reorder':
        raise HTTPException(422,'This endpoint currently plans inventory reorders.')
    ids=body.get('offering_ids')
    quantities=body.get('qty') or {}
    if not isinstance(ids,list) or not 1<=len(ids)<=20 or not isinstance(quantities,dict):
        raise HTTPException(422,'Choose 1 to 20 inventory items and quantities.')
    ids=sorted(set(uid(i) for i in ids))
    if set(quantities)-set(ids):
        raise HTTPException(422,'Quantities must belong to the selected items.')
    items=[]
    supplier=None
    host=None
    for oid in ids:
        rows=await asyncio.to_thread(db,'GET',f'/offerings?id=eq.{oid}&business_id=eq.{biz["id"]}'
            '&is_active=eq.true&archived_at=is.null&select=*&limit=1') or []
        if not rows:
            raise HTTPException(404,'Inventory item not found.')
        offering=rows[0]
        qty=quantities.get(oid,offering.get('reorder_qty'))
        if type(qty) is not int or not 1<=qty<=10000:
            raise HTTPException(422,'Each item needs a quantity from 1 to 10000.')
        pending=offering.get('reorder_pending_at')
        if pending:
            try:
                age=(datetime.now(timezone.utc)-datetime.fromisoformat(pending.replace('Z','+00:00'))).total_seconds()/3600
            except Exception:
                age=0
            if age<REORDER_DEDUP_HOURS:
                raise HTTPException(409,'This item already has a pending reorder.')
        candidate=await asyncio.to_thread(_primary_supplier,biz['id'],oid)
        if candidate and str(candidate.get('business_id'))!=str(biz['id']):
            raise HTTPException(404,'Supplier not found.')
        website=(candidate or {}).get('website')
        if not website and offering.get('supplier_email') and len(ids)==1:
            async with httpx.AsyncClient() as email_client:
                draft=await handle_draft_purchase_order(client or email_client,biz,
                    {'type':'draft_purchase_order','offering_id':oid,'qty':qty})
            return {'errand':None,'action':draft,'door':'email'}
        if not website:
            raise HTTPException(422,'Add the supplier website to this item first.')
        if not str(website).startswith('https://'):
            website='https://'+str(website)
        try:
            candidate_host=secret_vault.normalize_host(urlsplit(website).hostname or '')
        except Exception:
            raise HTTPException(422,'The supplier needs a valid HTTPS website.') from None
        if not host_allowed(website,[candidate_host],settings['deny_hosts']):
            raise HTTPException(422,'This supplier website is not allowed.')
        if host and (host!=candidate_host or supplier['id']!=candidate['id']):
            raise HTTPException(422,'Each errand can order from one supplier only.')
        host,supplier=candidate_host,candidate
        unit=_price(offering.get('price'))
        # Reuse the existing PO composition/number sequence; never copy its full
        # supplier account-number field into model-facing errand data.
        po=await asyncio.to_thread(compose_purchase_order,biz,offering,qty,supplier=candidate)
        items.append({'offering_id':oid,'name':str(offering.get('name') or 'Item')[:200],
            'sku':str(offering.get('sku') or '')[:100], 'qty':qty,'unit_cents':unit,
            'line_cents':unit*qty if unit is not None else None,'po_number':po['po_number']})
    total=sum(i['line_cents'] for i in items) if all(i['line_cents'] is not None for i in items) else None
    if total is not None and total>2147483647:
        raise HTTPException(422,'Planned order exceeds the supported total.')
    hosts=sorted(set([host,*settings['allowed_hosts']]))
    if len(hosts)>20 or any(not host_allowed('https://'+h,hosts,settings['deny_hosts']) for h in hosts):
        raise HTTPException(422,'Review the allowed supplier hosts in computer settings.')
    plan_data={'supplier':{'id':supplier['id'],'name':str(supplier.get('name') or host)[:200],'host':host},
        'items':items,'ship_to':None,'planned_total_cents':total,'priced':total is not None,
        'notes':['Final tax, delivery charges, quantities and total require checkout verification.'],
        'door':'browser','__start_url':website,'__require_stepup_unpriced':settings['require_stepup_unpriced']}
    key='reorder:'+(':'.join(ids) if len(ids)==1 else hashlib.sha256(':'.join(ids).encode()).hexdigest())+':'+now()[:10]
    row=await asyncio.to_thread(rpc,'chief_errand_plan',p_row={'business_id':biz['id'],'user_id':uid(user_id),
        'kind':'reorder','title':('Reorder from '+str(supplier.get('name') or host))[:200],
        'plan':plan_data,'hosts':hosts,'spend_limit_cents':settings['spend_limit_cents'],
        'planned_total_cents':total,'idempotency_key':key})
    return {'errand':outward(row)}


@dataclass(repr=False)
class Command:
    action: str
    user_id: str
    hold_id: str | None = None
    fields: dict = field(default_factory=dict,repr=False)
    save_row: dict | None = field(default=None,repr=False)
    saved_id: str | None = None
    expires: float = field(default_factory=lambda:time.monotonic()+25)
    result: Future = field(default_factory=Future,repr=False)
    cancelled: bool = False


def register_worker(errand_id):
    with _mailbox_lock:
        if errand_id in _mailboxes:
            raise RuntimeError('This errand already has a worker.')
        mailbox=queue.Queue(maxsize=5)
        _mailboxes[errand_id]=mailbox
        return mailbox


def unregister_worker(errand_id):
    with _mailbox_lock:
        mailbox=_mailboxes.pop(errand_id,None)
    if mailbox:
        while not mailbox.empty():
            command=mailbox.get_nowait()
            command.fields.clear()
            command.save_row=None
            if not command.result.done():
                command.result.set_exception(HTTPException(409,'The errand worker stopped.'))


async def send_command(errand_id, command):
    with _mailbox_lock:
        mailbox=_mailboxes.get(errand_id)
        if mailbox is None:
            command.fields.clear()
            raise HTTPException(409,'This errand has no live browser. Refresh its status.')
        try:
            mailbox.put_nowait(command)
        except queue.Full:
            command.fields.clear()
            raise HTTPException(429,'The browser is busy. Try again shortly.') from None
    try:
        return await asyncio.wait_for(asyncio.wrap_future(command.result),timeout=30)
    except (TimeoutError,FutureTimeout):
        command.cancelled=True
        raise HTTPException(409,'The browser did not confirm this action. Refresh before retrying.') from None


def interrupt_job(job_id):
    rows=db('GET',f'/chief_errands?job_id=eq.{uid(job_id)}&status=in.({",".join(LIVE)})&select={ERRAND_COLUMNS}') or []
    for row in rows:
        transition(row,LIVE,{'status':'interrupted','hold':None,'error':INTERRUPTED,'finished_at':now()},
                   'failed',INTERRUPTED)


async def approve(row, user, request, *, via_chat=False):
    if row['status']!='planned':
        raise HTTPException(409,'This errand is no longer awaiting approval.')
    biz=await asyncio.to_thread(business,row['business_id'],user,'manager')
    settings=settings_of(biz)
    stepup=needs_stepup(row.get('planned_total_cents'),min(row['spend_limit_cents'],settings['spend_limit_cents']),settings)
    if via_chat and stepup:
        raise HTTPException(403,{'code':'ledger_locked','scope':'danger','message':'Approve this errand on its card.'})
    if stepup:
        require_unlock(request,str(user.id),SCOPE_DANGER)
    if os.environ.get('ERRANDS_ENABLED','off').lower()!='on':
        raise HTTPException(503,'Chief computer execution is not enabled yet. Your plan is saved.')
    prepared=await asyncio.to_thread(rpc,'chief_errand_approve',p_business_id=row['business_id'],
        p_id=row['id'],p_user_id=str(user.id),p_scope='stepup:danger' if stepup else ('chat' if via_chat else 'button'))
    import chief_jobs
    async with httpx.AsyncClient() as client:
        await chief_jobs.enqueue(client,user_id=str(user.id),business_id=row['business_id'],kind='errand',
            params={'errand_id':row['id']},source='approval',prepared_job=prepared['job'])
    return prepared['errand']


@router.post('/errands')
async def create_errand(request:Request, session:UserSession=Depends(sb_clients.authed_request)):
    body=await json_body(request)
    biz=await asyncio.to_thread(business,body.get('business_id'),session.user,'manager')
    return await plan(biz,str(session.user.id),body)


@router.get('/errands')
async def list_errands(business_id:str,status:str='active',limit:int=Query(10,ge=1,le=50),
                       session:UserSession=Depends(sb_clients.authed_request)):
    biz=await asyncio.to_thread(business,business_id,session.user)
    if status not in ('active','all'):
        raise HTTPException(422,'Choose active or all errands.')
    condition=f'&status=in.({",".join(ACTIVE)})' if status=='active' else ''
    rows=await asyncio.to_thread(db,'GET',f'/chief_errands?business_id=eq.{biz["id"]}{condition}'
        f'&select={ERRAND_COLUMNS}&order=created_at.desc&limit={limit}') or []
    return {'errands':[outward(r) for r in rows]}


@router.get('/errands/{errand_id}')
async def errand_status(errand_id:str,since:int=Query(0,ge=0),session:UserSession=Depends(sb_clients.authed_request)):
    row=await asyncio.to_thread(authorized,errand_id,session.user)
    # Worker-side capture throttling coalesces these requests; never access a
    # Playwright page from the API event loop or an unrelated thread.
    if row['status']=='running':
        with _mailbox_lock:
            mailbox=_mailboxes.get(row['id'])
            if mailbox and mailbox.empty():
                try:
                    mailbox.put_nowait(Command('frame',str(session.user.id)))
                except queue.Full:
                    pass
    rows=await asyncio.to_thread(db,'GET',f'/chief_errand_events?errand_id=eq.{row["id"]}'
        f'&business_id=eq.{row["business_id"]}&n=gt.{since}&select={EVENT_COLUMNS}&order=n.asc&limit=200') or []
    latest=await asyncio.to_thread(db,'GET',f'/chief_errand_events?errand_id=eq.{row["id"]}'
        f'&business_id=eq.{row["business_id"]}&frame_path=not.is.null&select=n,at,frame_path&order=n.desc&limit=1') or []
    last=latest[0] if latest else {}
    from storage_links import signed_url_sync
    url=await asyncio.to_thread(signed_url_sync,'proposals',last['frame_path'],ttl=60) if last.get('frame_path') else None
    return {'errand':outward(row,max([r['n'] for r in rows]+[last.get('n',0)])),
        'events':[{**{k:v for k,v in r.items() if k!='frame_path'},'has_frame':bool(r.get('frame_path'))} for r in rows],
        'frame_url':url,'frame_at':last.get('at')}


@router.post('/errands/{errand_id}/approve')
async def approve_errand(errand_id:str,request:Request,session:UserSession=Depends(sb_clients.authed_request)):
    row=await asyncio.to_thread(authorized,errand_id,session.user,'manager')
    return {'errand':outward(await approve(row,session.user,request))}


@router.post('/errands/{errand_id}/secret')
async def secure_entry(errand_id:str,request:Request,session:UserSession=Depends(sb_clients.authed_request)):
    row=await asyncio.to_thread(authorized,errand_id,session.user,'manager')
    rate_limit(str(session.user.id),row['id'])
    body=await json_body(request)
    hold=row.get('hold') or {}
    if (row['status']!='needs_you' or hold.get('kind')!='secret' or body.get('hold_id')!=hold.get('id')
            or not hold.get('expires_at') or hold['expires_at']<=now()):
        raise HTTPException(409,'Secure Entry no longer matches the current hold.')
    if set(body)-{'hold_id','fields','save','label','use_saved'} or type(body.get('save',False)) is not bool:
        raise HTTPException(422,'Invalid Secure Entry request.')
    if body.get('use_saved')=='virtual':
        raise HTTPException(400,'Virtual card issuing is not enabled yet.')
    save=body.get('save',False)
    saved=body.get('use_saved')
    if save or saved:
        require_unlock(request,str(session.user.id),SCOPE_DANGER)
    if saved and (body.get('fields') or save):
        raise HTTPException(422,'Choose saved credentials or new fields.')
    command=Command('secret',str(session.user.id),hold_id=hold['id'])
    if saved:
        command.saved_id=uid(saved)
    else:
        fields=body.get('fields')
        expected={'login':{'username','password'},'card':{'name','number','exp','cvc'},'otp':{'code'}}.get(hold.get('field_kind'))
        if (not isinstance(fields,dict) or set(fields)!=expected
                or any(not isinstance(v,str) or not v or len(v)>4096 for v in fields.values())):
            raise HTTPException(422,'The fields do not match this Secure Entry request.')
        if hold['field_kind']=='otp' and not re.fullmatch(r'\d{4,10}',fields['code']):
            raise HTTPException(422,'Enter the verification code in Secure Entry.')
        if save and hold['field_kind']!='login':
            raise HTTPException(422,'Only logins can be saved. Cards and codes are never saved.')
        if save:
            sid=str(uuid4())
            label=body.get('label') or hold['host']+' login'
            if not isinstance(label,str) or not 1<=len(label)<=120 or any(v in label for v in fields.values()):
                raise HTTPException(422,'Choose a label that does not contain a credential.')
            ciphertext=secret_vault.encrypt(fields,business_id=row['business_id'],secret_id=sid,host=hold['host'])
            command.save_row={'id':sid,'business_id':row['business_id'],'kind':'login','host':hold['host'],
                'label':label,'fields_ciphertext':ciphertext,'display':{'username_hint':'••••'},'created_by':str(session.user.id)}
        command.fields=dict(fields)
    await send_command(row['id'],command)
    return {'ok':True}


@router.post('/errands/{errand_id}/continue')
async def continue_errand(errand_id:str,request:Request,session:UserSession=Depends(sb_clients.authed_request)):
    row=await asyncio.to_thread(authorized,errand_id,session.user,'manager')
    body=await json_body(request)
    hold=row.get('hold') or {}
    if row['status']!='needs_you' or hold.get('kind')!='approval' or body.get('hold_id')!=hold.get('id') or hold.get('expires_at','')<=now():
        raise HTTPException(409,'The checkout approval has expired or changed.')
    biz=await asyncio.to_thread(business,row['business_id'],session.user,'manager')
    settings=settings_of(biz)
    if needs_stepup(hold.get('observed_total_cents'),min(row['spend_limit_cents'],settings['spend_limit_cents']),settings):
        require_unlock(request,str(session.user.id),SCOPE_DANGER)
    await send_command(row['id'],Command('continue',str(session.user.id),hold_id=hold['id']))
    return {'errand':outward(await asyncio.to_thread(get_row,row['id']))}


@router.post('/errands/{errand_id}/pause')
async def pause_errand(errand_id:str,session:UserSession=Depends(sb_clients.authed_request)):
    row=await asyncio.to_thread(authorized,errand_id,session.user,'manager')
    # Preserve an existing secret/approval hold across a user pause. Resume must
    # return to that hold; pausing cannot be used to skip Secure Entry/approval.
    updated=await asyncio.to_thread(transition,row,('approved','running','needs_you'),
        {'status':'paused'},'paused','Paused by the owner or manager.')
    return {'errand':outward(updated)}


@router.post('/errands/{errand_id}/resume')
async def resume_errand(errand_id:str,session:UserSession=Depends(sb_clients.authed_request)):
    row=await asyncio.to_thread(authorized,errand_id,session.user,'manager')
    with _mailbox_lock:
        if row['id'] not in _mailboxes:
            raise HTTPException(409,'There is no live browser to resume. Check the supplier before replanning.')
    status='needs_you' if row.get('hold') else 'running'
    updated=await asyncio.to_thread(transition,row,('paused',),{'status':status},'resumed','Resumed by the owner or manager.')
    return {'errand':outward(updated)}


@router.post('/errands/{errand_id}/stop')
async def stop_errand(errand_id:str,session:UserSession=Depends(sb_clients.authed_request)):
    row=await asyncio.to_thread(authorized,errand_id,session.user,'manager')
    if row['status'] in TERMINAL:
        return {'errand':outward(row)}
    updated=await asyncio.to_thread(transition,row,ACTIVE,{'status':'stopped','hold':None,'finished_at':now()},
        'stopped','Stopped by the owner or manager. A submitted order may still need cancellation.')
    return {'errand':outward(updated)}


@router.get('/computer/settings')
async def get_settings(business_id:str,session:UserSession=Depends(sb_clients.authed_request)):
    biz=await asyncio.to_thread(business,business_id,session.user)
    rows=await asyncio.to_thread(db,'GET',f'/business_secrets?business_id=eq.{biz["id"]}'
        f'&status=eq.active&select={secret_vault.METADATA_COLUMNS}&order=created_at.desc&limit=100') or []
    return {'settings':settings_of(biz),'secrets':[secret_vault.secret_metadata(r) for r in rows]}


@router.put('/computer/settings')
async def put_settings(request:Request,session:UserSession=Depends(sb_clients.authed_request)):
    body=await json_body(request)
    biz=await asyncio.to_thread(business,body.get('business_id'),session.user,'owner')
    require_unlock(request,str(session.user.id),SCOPE_DANGER)
    settings=validate_settings(body.get('settings'))
    await asyncio.to_thread(rpc,'chief_computer_settings',p_business_id=biz['id'],p_settings=settings)
    return {'settings':settings}


@router.delete('/computer/secrets/{secret_id}')
async def revoke_secret(secret_id:str,session:UserSession=Depends(sb_clients.authed_request)):
    rows=await asyncio.to_thread(db,'GET',f'/business_secrets?id=eq.{uid(secret_id)}&select=id,business_id&limit=1') or []
    if not rows:
        raise HTTPException(404,'Saved login not found.')
    await asyncio.to_thread(business,rows[0]['business_id'],session.user,'owner')
    await asyncio.to_thread(db,'PATCH',f'/business_secrets?id=eq.{uid(secret_id)}&business_id=eq.{rows[0]["business_id"]}',
        {'status':'revoked','fields_ciphertext':''})
    return {'ok':True}


@router.get('/errands/{errand_id}/frames')
async def get_frame(errand_id:str,n:int=Query(...,ge=1),session:UserSession=Depends(sb_clients.authed_request)):
    row=await asyncio.to_thread(authorized,errand_id,session.user)
    rows=await asyncio.to_thread(db,'GET',f'/chief_errand_events?errand_id=eq.{row["id"]}&business_id=eq.{row["business_id"]}'
        f'&n=eq.{n}&select=frame_path&limit=1') or []
    path=rows[0].get('frame_path') if rows else None
    from storage_links import signed_url_sync
    return {'frame_url':await asyncio.to_thread(signed_url_sync,'proposals',path,ttl=60) if path else None}
