"""Loopback-only QA server. Synthetic in-memory DB; real Growth routes/cores.
Run from backend: python __tests__/growth_preview_server.py
No credentials, no external network, no persistent business mutations.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from urllib.parse import parse_qs, urlparse
import json
import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from auth_supabase import AuthedUser, require_user
import growth_intelligence_router as api
import chief_growth_intelligence_actions as chief

BID='10000000-0000-4000-8000-000000000001'
now=datetime.now(timezone.utc)
month=now.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
db={name:[] for name in ('contacts','invoices','sessions','campaigns','growth_records','growth_events','custom_modules','module_entries')}
db['businesses']=[{'id':BID,'owner_id':'fixture-owner','settings':{}}]
def row(table, **kw):
    r={'id':str(uuid4()),'business_id':BID,**kw}; db[table].append(r); return r
campaign=row('campaigns',name='September return visits',status='running')
for n in range(45):
    created=month-timedelta(days=20+n*4)
    person=row('contacts',name=f'Demo customer {n+1:02}',status='active',created_at=created.isoformat(),source=['Referral','Search','Instagram'][n%3])
    for visit in range(1+n%5):
        paid=created+timedelta(days=visit*22+2)
        if paid>=now: continue
        row('invoices',contact_id=person['id'],status='paid',paid_at=paid.isoformat(),created_at=paid.isoformat(),total=150+(n%7)*45,category=['Strategy','Coaching','Workshop'][n%3])
    if n%2==0:
        paid=month+timedelta(hours=12+n%48)
        row('invoices',contact_id=person['id'],status='paid',paid_at=paid.isoformat(),created_at=paid.isoformat(),total=240+(n%5)*60,category=['Strategy','Coaching','Workshop'][n%3])
    for day in (-6, n%12+1):
        row('sessions',contact_id=person['id'],scheduled_for=(now+timedelta(days=day)).isoformat(),duration_minutes=45+(n%3)*15,status='completed' if day<0 else 'scheduled')
    row('growth_events',contact_id=person['id'],kind='interaction',occurred_at=(now-timedelta(days=n%12)).isoformat())
def record(kind,data): return row('growth_records',kind=kind,data=data,revision=1)
record('preferences',{'timezone':'America/New_York','currency':'USD','weekly_hours':32,'history_since':(now-timedelta(days=90)).isoformat()})
record('costs',{'description':'September search campaign','date':month.date().isoformat(),'amount':420,'kind':'marketing','source':'Search','campaign_id':campaign['id'],'contact_id':None,'offering':'','hours':0})
record('costs',{'description':'Strategy delivery time','date':month.date().isoformat(),'amount':780,'kind':'direct','source':'','offering':'Strategy','hours':12,'contact_id':None,'campaign_id':None})
record('actions',{'title':'Bring returning customers back into the calendar','owner':'Alex','start_date':month.date().isoformat(),'due_date':(month+timedelta(days=27)).date().isoformat(),'metric':'revenue','target':10000,'status':'active','notes':'Follow up with the people who asked about a September session. Review the bookings and collected payments at month end.','contact_ids':[]})
record('attributions',{'invoice_id':db['invoices'][-1]['id'],'campaign_id':campaign['id'],'evidence':'Synthetic fixture: buyer provided the campaign code.','archived':False})

async def fake_db(client,method,path,body=None):
    parts=urlparse(path); table=parts.path.strip('/'); params=parse_qs(parts.query)
    selected=list(db.get(table,[]))
    for key,vals in params.items():
        if key in ('select','order','offset','limit'): continue
        value=vals[-1]
        if value.startswith('eq.'): selected=[r for r in selected if str(r.get(key))==value[3:]]
        elif value=='not.is.null': selected=[r for r in selected if r.get(key) is not None]
    if method=='GET':
        selected.sort(key=lambda r:r['id']); offset=int(params.get('offset',['0'])[0]); limit=int(params.get('limit',['1000'])[0]); return json.loads(json.dumps(selected[offset:offset+limit]))
    if method=='POST':
        created={'revision':1,**body}; db[table].append(created); return [created.copy()]
    if method=='PATCH':
        for item in selected: item.update(body)
        return [item.copy() for item in selected]
    raise AssertionError(method)
api.db=fake_db
app=FastAPI()
app.add_middleware(CORSMiddleware,allow_origins=['http://127.0.0.1:5192'],allow_methods=['GET','POST'],allow_headers=['Content-Type'])
app.dependency_overrides[require_user]=lambda:AuthedUser(id='fixture-owner',email=None,role='authenticated')
app.include_router(api.router)
@app.post('/fixture/chief')
async def recall():
    async with httpx.AsyncClient() as client:
        return await chief.handle_growth_report(client,{'id':BID},{'period':'mtd'})
if __name__=='__main__': uvicorn.run(app,host='127.0.0.1',port=5193,log_level='warning')
