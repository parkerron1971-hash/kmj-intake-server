"""Customer-owned Stripe App connection. Metadata only: never retrieve PAN/CVC.

Incoming payments, card issuance, funding and Chief execution are untouched.
OAuth completion requires the original owner AND a verifier held by the initiating
browser, separate from the state sent to Stripe. No cross-site cookie dependency.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

import business_access
import sb_clients
from auth_supabase import UserSession
from chief_errands import db, rpc, uid
from ledger_unlock import require_unlock, SCOPE_DANGER
from stripe_connect_helpers import verify_webhook_signature

router=APIRouter(prefix='/payments/card-connections',tags=['card-connections'])
CALLBACK='https://kmj-intake-server-production.up.railway.app/payments/card-connections/stripe/callback'
MODES=('test','live','sandbox')
ACCOUNT=re.compile(r'acct_[A-Za-z0-9]{1,100}')
CARD=re.compile(r'ic_[A-Za-z0-9]{1,100}')


class Selection(BaseModel):
    model_config=ConfigDict(extra='forbid')
    card_id: str = Field(pattern=r'^ic_[A-Za-z0-9]{1,100}$')


class Completion(BaseModel):
    model_config=ConfigDict(extra='forbid')
    state: str = Field(min_length=40,max_length=128,pattern=r'^[A-Za-z0-9_-]+$')
    verifier: str = Field(min_length=40,max_length=128,pattern=r'^[A-Za-z0-9_-]+$')


def clock():
    return datetime.now(timezone.utc)


def timestamp():
    return clock().strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def configuration(mode):
    if mode not in MODES:
        raise HTTPException(422,'Invalid connection environment.')
    prefix='STRIPE_CARDS_'+mode.upper()
    return {'client_id':os.getenv(prefix+'_CLIENT_ID',''),
            'authorize_url':os.getenv(prefix+'_AUTHORIZE_URL','https://marketplace.stripe.com/oauth/v2/authorize'),
            'key':os.getenv(prefix+'_DEVELOPER_KEY',''),
            'webhook':os.getenv(prefix+'_WEBHOOK_SECRET','')}


def cipher():
    try:
        return Fernet(os.environ['CARD_CONNECTION_ENCRYPTION_KEY'].encode('ascii'))
    except (KeyError,ValueError,UnicodeError):
        raise HTTPException(503,'Card connection encryption is not configured.') from None


def configured(mode):
    conf=configuration(mode)
    expected='sk_live_' if mode=='live' else 'sk_test_'
    if not (conf['client_id'].startswith('ca_') and conf['key'].startswith(expected)
            and conf['webhook'].startswith('whsec_')
            and re.fullmatch(r'https://marketplace\.stripe\.com/oauth/v2/(?:chnlink_[A-Za-z0-9]+/)?authorize',conf['authorize_url'])):
        return False
    try:
        cipher()
        return True
    except HTTPException:
        return False


def binding(row,account):
    return {k:row[k] for k in ('id','business_id','mode')} | {'account_id':account}


def encrypt(tokens,row,account):
    if not ACCOUNT.fullmatch(str(account)):
        raise HTTPException(502,'Stripe returned an invalid account.')
    values={k:tokens.get(k) for k in ('access_token','refresh_token')}
    if any(not isinstance(v,str) or not 1<=len(v)<=4096 for v in values.values()):
        raise HTTPException(502,'Stripe authorization was incomplete.')
    return cipher().encrypt(json.dumps({'binding':binding(row,account),'tokens':values}).encode()).decode()


def decrypt(value,row,account):
    try:
        data=json.loads(cipher().decrypt(value.encode()))
        if data['binding']!=binding(row,account):
            raise ValueError()
        return data['tokens']
    except (InvalidToken,ValueError,TypeError,KeyError,AttributeError):
        raise HTTPException(409,'Reconnect your card account.') from None


def owner(bid,session):
    bid=uid(bid)
    business_access.assert_access(bid,session.user,'owner')
    return bid


def connection(bid,mode):
    rows=db('GET',f'/business_card_connections?business_id=eq.{uid(bid)}&mode=eq.{mode}&limit=1') or []
    return rows[0] if rows else None


def update(row,**changes):
    data={**row,**changes}
    return rpc('card_connection_update',p_id=row['id'],p_version=row['version'],
        p_status=data['status'],p_account=data.get('account_id'),p_tokens=data.get('tokens_ciphertext'),
        p_expires=data.get('expires_at'),p_card=data.get('selected_card'))


def changed():
    raise HTTPException(409,'The connection changed. Refresh and try again.')


def safe_status(row,mode):
    selected=row.get('selected_card') if row and row['status']=='connected' else None
    selected=card_metadata({**selected,'object':'issuing.card','livemode':mode=='live'},mode) if isinstance(selected,dict) else None
    return {'provider':'stripe','mode':mode,'configured':configured(mode),
        'status':row['status'] if row else 'disconnected',
        'account_id':row.get('account_id') if row and row['status']!='disconnected' else None,
        'selected_card':selected,
        'purchasing_enabled':False}


def stripe_request(method,path,key,*,data=None,params=None):
    # Fixed origin, no redirects or expanded secrets, no raw errors or response logging.
    try:
        with httpx.Client(timeout=20,follow_redirects=False) as client:
            response=client.request(method,'https://api.stripe.com/v1'+path,
                auth=(key,''),data=data,params=params)
        if response.status_code in (401,403):
            raise HTTPException(409,'Reconnect the account and check its Issuing permissions.')
        if not 200<=response.status_code<300:
            raise HTTPException(502,'Stripe could not complete the request. Check the account in Stripe.')
        result=response.json()
        if not isinstance(result,dict):
            raise ValueError()
        return result
    except (httpx.HTTPError,ValueError):
        raise HTTPException(503,'Stripe is unavailable. Try again later.') from None


def validate_tokens(tokens,mode,account=None):
    returned=tokens.get('stripe_user_id') or tokens.get('account_id')
    if (tokens.get('livemode') is not (mode=='live') or tokens.get('scope')!='stripe_apps'
            or not ACCOUNT.fullmatch(str(returned)) or (account and returned!=account)):
        raise HTTPException(409,'Stripe authorization does not match this connection.')
    return returned


def access(row):
    if row['status']!='connected' or not configured(row['mode']):
        raise HTTPException(409,'Reconnect your card account when setup is available.')
    tokens=decrypt(row['tokens_ciphertext'],row,row['account_id'])
    if datetime.fromisoformat(row['expires_at'].replace('Z','+00:00'))>clock()+timedelta(seconds=60):
        return tokens['access_token'],row
    claimed=update(row,status='refreshing')
    if not claimed:
        changed()
    try:
        new=stripe_request('POST','/oauth/token',configuration(row['mode'])['key'],
            data={'grant_type':'refresh_token','refresh_token':tokens['refresh_token']})
        validate_tokens(new,row['mode'],row['account_id'])
        saved=update(claimed,status='connected',tokens_ciphertext=encrypt(new,row,row['account_id']),
            expires_at=(clock()+timedelta(minutes=55)).isoformat())
        if not saved:
            changed()
        return new['access_token'],saved
    except Exception:
        # Rotating refresh tokens must never be blindly replayed after an uncertain
        # response. A crashed refresh also remains blocked until owner reconnects.
        update(claimed,status='reconnect_required',tokens_ciphertext=None,selected_card=None)
        raise HTTPException(409,'Reconnect your card account to restore access.') from None


def card_metadata(card,mode):
    today=clock()
    if (card.get('object')!='issuing.card' or card.get('type')!='virtual'
            or card.get('livemode') is not (mode=='live') or card.get('status')!='active'
            or not CARD.fullmatch(str(card.get('id')))):
        return None
    month,year=card.get('exp_month'),card.get('exp_year')
    if (type(month) is not int or type(year) is not int or not 1<=month<=12
            or (year,month)<(today.year,today.month)):
        return None
    last4,currency=card.get('last4'),card.get('currency')
    if not re.fullmatch(r'[0-9]{4}',str(last4)) or not re.fullmatch(r'[a-z]{3}',str(currency)):
        return None
    return {'id':card['id'],'type':'virtual','last4':last4,'currency':currency,
        'exp_month':month,'exp_year':year,'status':'active'}


@router.get('/{business_id}/{mode}/status')
def status(business_id:str,mode:Literal['test','live','sandbox'],session:UserSession=Depends(sb_clients.authed_request)):
    bid=owner(business_id,session)
    return safe_status(connection(bid,mode),mode)


@router.post('/{business_id}/{mode}/start')
def start(business_id:str,mode:Literal['test','live','sandbox'],request:Request,session:UserSession=Depends(sb_clients.authed_request)):
    bid=owner(business_id,session)
    require_unlock(request,str(session.user.id),SCOPE_DANGER)
    if not configured(mode):
        raise HTTPException(503,'Stripe card connection setup is pending. No account was connected.')
    state,verifier=secrets.token_urlsafe(32),secrets.token_urlsafe(32)
    rpc('card_connection_begin',p_business=bid,p_mode=mode,p_user=str(session.user.id),
        p_state=digest(state),p_verifier=digest(verifier))
    url=configuration(mode)['authorize_url']+'?'+urlencode({
        'client_id':configuration(mode)['client_id'],'redirect_uri':CALLBACK,'state':state})
    return {'url':url,'state':state,'verifier':verifier}


@router.get('/stripe/callback',response_class=HTMLResponse)
def callback(request:Request):
    headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer',
        'Content-Security-Policy':"default-src 'none'; frame-ancestors 'none'; base-uri 'none'"}
    message='Authorization could not be completed. Return to Solutionist and start again.'
    state=request.query_params.get('state','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{40,128}',state):
        return HTMLResponse(message,status_code=400,headers=headers)
    rows=db('PATCH',f'/card_connection_oauth_states?state_hash=eq.{digest(state)}&status=eq.issued&expires_at=gt.{timestamp()}',{'status':'exchanging'}) or []
    if rows and not request.query_params.get('error'):
        pending=rows[0]
        try:
            code=request.query_params.get('code','')
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,512}',code):
                raise ValueError()
            records=db('GET',f'/business_card_connections?id=eq.{uid(pending["connection_id"])}&limit=1') or []
            row=records[0]
            if row['version']!=pending['version'] or not configured(row['mode']):
                changed()
            tokens=stripe_request('POST','/oauth/token',configuration(row['mode'])['key'],
                data={'grant_type':'authorization_code','code':code})
            account=validate_tokens(tokens,row['mode'])
            verified=stripe_request('GET','/account',tokens['access_token'])
            if verified.get('id')!=account:
                changed()
            db('PATCH',f'/card_connection_oauth_states?state_hash=eq.{digest(state)}&status=eq.exchanging',
                {'status':'authorized','account_id':account,'tokens_ciphertext':encrypt(tokens,row,account)})
            message='Stripe authorization received. Return to Solutionist and click Finish connection. You may close this tab.'
        except (HTTPException,KeyError,ValueError,IndexError):
            pass
    return HTMLResponse('<!doctype html><html lang="en"><meta charset="utf-8"><title>Solutionist card connection</title><h1>Card connection</h1><p>'+message+'</p></html>',headers=headers)


@router.post('/{business_id}/{mode}/complete')
def complete(business_id:str,mode:Literal['test','live','sandbox'],body:Completion,session:UserSession=Depends(sb_clients.authed_request)):
    bid=owner(business_id,session)
    row=connection(bid,mode)
    if not row:
        changed()
    # DELETE RETURNING consumes the pending credential atomically; any other
    # browser/user/business, replay or callback after disconnect fails closed.
    rows=db('DELETE',f'/card_connection_oauth_states?state_hash=eq.{digest(body.state)}&verifier_hash=eq.{digest(body.verifier)}&user_id=eq.{uid(session.user.id)}&connection_id=eq.{uid(row["id"])}&status=eq.authorized&expires_at=gt.{timestamp()}') or []
    if not rows:
        raise HTTPException(409,'Finish authorization in Stripe, then try again. If it expired, start a new connection.')
    pending=rows[0]
    if row['version']!=pending['version']:
        changed()
    decrypt(pending['tokens_ciphertext'],row,pending['account_id'])
    saved=update(row,status='connected',account_id=pending['account_id'],tokens_ciphertext=pending['tokens_ciphertext'],
        expires_at=(clock()+timedelta(minutes=45)).isoformat(),selected_card=None)
    if not saved:
        changed()
    return safe_status(saved,mode)


@router.get('/{business_id}/{mode}/cards')
def cards(business_id:str,mode:Literal['test','live','sandbox'],after:str='',session:UserSession=Depends(sb_clients.authed_request)):
    bid=owner(business_id,session)
    row=connection(bid,mode)
    if not row:
        changed()
    if after and not CARD.fullmatch(after):
        raise HTTPException(422,'Invalid card page.')
    key,row=access(row)
    data=stripe_request('GET','/issuing/cards',key,params={'limit':100,**({'starting_after':after} if after else {})})
    raw=data.get('data',[])
    if not isinstance(raw,list):
        raise HTTPException(502,'Stripe returned an invalid card list.')
    result=[item for card in raw if isinstance(card,dict) and (item:=card_metadata(card,mode))]
    current=connection(bid,mode)
    if not current or current['version']!=row['version']:
        changed()
    cursor=raw[-1].get('id') if raw and data.get('has_more') else None
    if cursor and not CARD.fullmatch(str(cursor)):
        raise HTTPException(502,'Stripe returned an invalid card page.')
    return {'cards':result,'next':cursor,'purchasing_enabled':False}


@router.post('/{business_id}/{mode}/select')
def select(business_id:str,mode:Literal['test','live','sandbox'],body:Selection,request:Request,session:UserSession=Depends(sb_clients.authed_request)):
    bid=owner(business_id,session)
    require_unlock(request,str(session.user.id),SCOPE_DANGER)
    row=connection(bid,mode)
    if not row:
        changed()
    key,row=access(row)
    card=stripe_request('GET','/issuing/cards/'+body.card_id,key)
    meta=card_metadata(card,mode)
    if not meta or meta['id']!=body.card_id:
        raise HTTPException(422,'Only active, unexpired virtual cards verified by Stripe can be selected.')
    saved=update(row,selected_card=meta)
    if not saved:
        changed()
    return safe_status(saved,mode)


@router.post('/{business_id}/{mode}/disconnect')
def disconnect(business_id:str,mode:Literal['test','live','sandbox'],session:UserSession=Depends(sb_clients.authed_request)):
    bid=owner(business_id,session)
    rpc('card_connection_disconnect',p_business=bid,p_mode=mode)
    return {'ok':True,'purchasing_enabled':False,
        'note':'Solutionist access removed. You can also uninstall the app in Stripe. Your cards were not cancelled.'}


@router.post('/stripe/webhook/{mode}')
async def webhook(mode:Literal['test','live','sandbox'],request:Request):
    payload=await request.body()
    if len(payload)>262144:
        raise HTTPException(413,'Event too large.')
    secret=configuration(mode)['webhook']
    if not secret or not verify_webhook_signature(payload,request.headers.get('stripe-signature',''),secret=secret):
        raise HTTPException(400,'Invalid Stripe signature.')
    try:
        event=json.loads(payload)
        if event.get('livemode') is not (mode=='live'):
            raise ValueError()
        if event.get('type')=='account.application.deauthorized':
            account=event.get('account')
            if not ACCOUNT.fullmatch(str(account)) or event.get('data',{}).get('object',{}).get('id')!=configuration(mode)['client_id']:
                raise ValueError()
            # Scope comes only from the signature-verified provider account.
            # Atomically erase both active and pending authorizations; there is
            # no caller-supplied business id and no read/write race in Python.
            rpc('card_connection_uninstall',p_account=account,p_mode=mode)
    except (ValueError,TypeError,AttributeError):
        raise HTTPException(400,'Invalid Stripe event.') from None
    return {'ok':True}
