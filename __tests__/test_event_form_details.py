import asyncio
from copy import deepcopy
import pytest
import chief_form_actions as forms
from chief_code import WorkOrder, question, plan
from event_form_details import event_values, details_question, date_label, flyer_url

DETAILS={'description':'A practical workshop.','starts_at':'2026-10-13T19:00:00-04:00','timezone':'America/Detroit','location':'1084 Allen Avenue, Muskegon, MI 49442','admission':'Free and open to the public','include_flyer':False}
BIZ={'id':'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'}

def test_each_event_detail_is_mandatory():
 for key in ('description','starts_at','timezone','location','admission'):
  d={**DETAILS,key:''}
  assert details_question(d)['field']==key

@pytest.mark.parametrize('stamp',['2026-10-13','not-a-date','2026-11-01T01:30','2026-03-08T02:30'])
def test_bad_or_ambiguous_date_does_not_publish(stamp):
 assert details_question({**DETAILS,'starts_at':stamp})['field']=='starts_at'

def test_explicit_flyer_choice_is_required_but_image_is_optional():
 d={**DETAILS};d.pop('include_flyer')
 assert details_question(d)['field']=='include_flyer'
 assert details_question({**DETAILS}) is None
 assert details_question({**DETAILS,'include_flyer':True})['field']=='flyer_url'
 assert details_question({**DETAILS,'include_flyer':True,'flyer_url':'https://cdn.example.org/flyer.png'}) is None
 assert event_values({'include_flyer':'No'})['include_flyer'] is False

@pytest.mark.parametrize('url',['javascript:alert(1)','http://cdn.example.org/a.png','https://localhost/a.png','https://127.0.0.1/a.png','https://10.0.0.1/a.png','https://user:pass@example.org/a.png','https://example.org/<script>'])
def test_unsafe_flyer_urls_are_rejected(url):
 assert not flyer_url(url)

def test_date_has_correct_named_timezone():
 assert date_label(DETAILS)=='Tuesday, October 13, 2026 at 7:00 PM EDT'
 assert '7:00 PM EDT' in date_label({**DETAILS,'starts_at':'2026-10-13T23:00:00Z'})

def test_chief_asks_before_saving_then_carries_all_details():
 o=WorkOrder.create({'kind':'form_and_link','facts':{'name':'Workshop','form_type':'event'}},business_id=BIZ['id'],user_id='11111111-1111-1111-1111-111111111111',turn_id='t',surface='desktop',words='Make the form')
 assert question(o)['field']=='description'
 o.facts.update(DETAILS);assert question(o) is None
 assert plan(o)[0].params['event_details']==DETAILS

def test_create_does_not_write_incomplete_event(monkeypatch):
 monkeypatch.setattr(forms.sb_clients,'sb_post_as_service',lambda *a:pytest.fail('Incomplete event was saved'))
 result=asyncio.run(forms.handle_create_client_form(None,BIZ,{'name':'Event','form_type':'event'}))
 assert result['failed'] and result['question']['field']=='description'

def test_create_persists_details_and_preserves_form_contract(monkeypatch):
 writes=[]
 def post(path,body,*args):writes.append((path,body));return [{**body,'id':'f1'}]
 monkeypatch.setattr(forms.sb_clients,'sb_post_as_service',post)
 monkeypatch.setattr(forms,'public_form_url',lambda *a:'https://example.org/form/f1')
 result=asyncio.run(forms.handle_create_client_form(None,BIZ,{'name':'Event','form_type':'event','event_details':DETAILS}))
 assert not result.get('failed')
 row=writes[0][1];assert row['settings']['event_details']==DETAILS
 assert row['fields'][0]['name']=='name' and row['fields'][0]['required']

def test_update_removes_flyer_without_losing_settings_or_fields(monkeypatch):
 row={'id':'f1','form_type':'event','fields':[{'name':'name','type':'text','label':'Name','required':True}],'settings':{'confirmation_message':'Thank you','linked_module_id':'m1','event_details':{**DETAILS,'include_flyer':True,'flyer_url':'https://cdn.example.org/a.png'}}}
 monkeypatch.setattr(forms,'_resolve_form',lambda *a:{'form':deepcopy(row)})
 writes=[];monkeypatch.setattr(forms.sb_clients,'sb_patch_as_service',lambda path,body:writes.append((path,body)))
 result=asyncio.run(forms.handle_update_client_form(None,BIZ,{'form_id':'f1','include_flyer':False,'location':'New venue'}))
 assert not result.get('failed');path,payload=writes[0]
 assert 'business_id=eq.'+BIZ['id'] in path and 'fields' not in payload
 assert payload['settings']['confirmation_message']=='Thank you' and payload['settings']['linked_module_id']=='m1'
 assert 'flyer_url' not in payload['settings']['event_details'] and payload['settings']['event_details']['location']=='New venue'

def test_update_cannot_remove_required_details_but_can_disable_legacy_form(monkeypatch):
 row={'id':'f1','form_type':'event','fields':[],'settings':{'event_details':DETAILS}}
 monkeypatch.setattr(forms,'_resolve_form',lambda *a:{'form':deepcopy(row)})
 writes=[];monkeypatch.setattr(forms.sb_clients,'sb_patch_as_service',lambda path,body:writes.append(body))
 result=asyncio.run(forms.handle_update_client_form(None,BIZ,{'form_id':'f1','description':''}))
 assert result['failed'] and not writes
 row['settings']={}
 result=asyncio.run(forms.handle_update_client_form(None,BIZ,{'form_id':'f1','is_active':False}))
 assert not result.get('failed') and writes[0]['is_active'] is False


def test_render_details_are_escaped_and_flyer_is_opt_in():
 from event_form_details import details_html
 form={'name':'Workshop','form_type':'event','settings':{'event_details':{**DETAILS,'description':'<script>alert(1)</script>','flyer_url':'https://cdn.example.org/f.png'}}}
 markup=details_html(form)
 assert '<script>' not in markup and '&lt;script&gt;' in markup
 assert 'Tuesday, October 13, 2026 at 7:00 PM EDT' in markup and 'Location' in markup
 assert '<img' not in markup
 form['settings']['event_details']['include_flyer']=True
 assert 'event-flyer' in details_html(form) and 'alt="Workshop — event flyer"' in details_html(form)
 form['settings']['event_details']['flyer_url']='javascript:alert(1)'
 assert '<img' not in details_html(form)

def test_legacy_type_fallback_still_renders_event_details():
 from event_form_details import details_html
 assert 'Event details' in details_html({'form_type':'general','settings':{'requested_form_type':'event','event_details':DETAILS}})


def test_build_verifies_saved_event_facts_and_public_page(monkeypatch):
 from chief_build_runtime import Adapter
 from chief_code import Step
 o=WorkOrder.create({'kind':'form_and_link','facts':{'name':'Workshop','form_type':'event',**DETAILS}},business_id=BIZ['id'],user_id='11111111-1111-1111-1111-111111111111',turn_id='verify',surface='desktop',words='Build registration')
 assert question(o) is None
 params=plan(o)[0].params
 row={'id':'f1','name':'Workshop','fields':forms._normalize_fields(None)[0],'is_active':True,'settings':{'event_details':dict(DETAILS)}}
 adapter=Adapter(None,{'id':o.order_id,'business_id':BIZ['id'],'user_id':o.asked_by},'lease',o)
 async def find(*args):return row
 observed=[]
 async def page(url,needles):observed.extend(needles);return True,''
 monkeypatch.setattr(adapter,'find',find);monkeypatch.setattr(adapter,'page',page)
 monkeypatch.setattr(forms,'public_form_url',lambda *a:'https://example.org/form/f1')
 result=asyncio.run(adapter.verify(plan(o)[0],params,None,{}))
 assert result['verified']['ok'] and DETAILS['description'] in observed and date_label(DETAILS) in observed
 row['settings']['event_details']={}
 assert not asyncio.run(adapter.verify(plan(o)[0],params,None,{}))['verified']['ok']
