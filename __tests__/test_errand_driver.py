"""Scripted Anthropic responses against real Chromium fixture pages."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from playwright.sync_api import sync_playwright

import chief_errands as ce
import errand_driver as ed
from browser_controller import VIEWPORT

BID='00000000-0000-4000-8000-000000000001'
UID='00000000-0000-4000-8000-000000000002'
EID='00000000-0000-4000-8000-000000000003'
OID='00000000-0000-4000-8000-000000000004'
JOB='00000000-0000-4000-8000-000000000005'
FIXTURES=Path(__file__).parent/'fixtures'/'computer'


class Store:
    def __init__(self,secret=False,total=200):
        self.row={'id':EID,'business_id':BID,'user_id':UID,'approved_by':UID,'job_id':JOB,
            'status':'approved','kind':'reorder','title':'Paper clips','hosts':['supplier.test'],
            'spend_limit_cents':15000,'planned_total_cents':total,'hold':None,
            'plan':{'supplier':{'id':JOB,'name':'Supplier','host':'supplier.test'},
                'items':[{'offering_id':OID,'name':'Paper clips','qty':1,'unit_cents':200,'line_cents':200}],
                '__start_url':'https://supplier.test/checkout' if secret else 'https://supplier.test/'}}
        self.events=[]
        self.holds=[]
        self.on_hold=None
        self.settings={}

    def get_row(self,eid):
        assert eid==EID
        return copy.deepcopy(self.row)

    def db(self,method,path,body=None):
        if path.startswith('/businesses'):
            return [{'id':BID,'settings':copy.deepcopy(self.settings)}]
        if path.startswith('/business_secrets'):
            return []
        raise AssertionError('Unexpected storage call')

    def transition(self,row,expected,patch,kind=None,note=None,hold_id=None):
        assert self.row['status'] in expected
        if hold_id:
            assert self.row['hold']['id']==hold_id
        self.row.update(copy.deepcopy(patch))
        if kind:
            self.event(self.row,kind,note)
        if patch.get('status')=='needs_you':
            self.holds.append(copy.deepcopy(self.row['hold']))
            if self.on_hold:
                self.on_hold(self.row['hold'])
        return copy.deepcopy(self.row)

    def event(self,row,kind,note,**extra):
        self.events.append({'n':len(self.events)+1,'kind':kind,'note':note,**extra})


class Backend:
    blocked=False
    def __init__(self,browser):
        self.browser=browser
        self.context=None
        self.final_quantity=None
    def open(self):
        self.context=self.browser.new_context(viewport=VIEWPORT,service_workers='block')
        self.context.set_default_timeout(1000)
        self.context.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',
            body=(FIXTURES/('cancellation.html' if '/cancel' in route.request.url else 'checkout.html' if '/checkout' in route.request.url else 'supplier.html')).read_text()))
    def page(self):
        return self.context.new_page()
    def close(self):
        if self.context:
            pages=self.context.pages
            if pages and pages[0].locator('[name="quantity"]').count():
                self.final_quantity=pages[0].locator('[name="quantity"]').input_value()
            self.context.close()


class ScriptedClient:
    def __init__(self,mode='happy'):
        self.messages=self
        self.mode=mode
        self.requests=[]
        self.refs={}
    def create(self,**request):
        self.requests.append(copy.deepcopy(request))
        turn=len(self.requests)
        for message in request['messages']:
            if not isinstance(message['content'],list):
                continue
            for block in message['content']:
                if block.get('type')!='tool_result':
                    continue
                content=block.get('content')
                if not isinstance(content,list):
                    continue
                for item in content:
                    if item.get('type')!='text':
                        continue
                    for line in item.get('text','').splitlines():
                        if not line.startswith('ref_'):
                            continue
                        ref=line.split()[0]
                        if ' article ' in line and 'Paper clips' in line: self.refs['row']=ref
                        if ' input number Quantity' in line: self.refs['qty']=ref
                        if ' p ' in line and 'Total $2.00' in line: self.refs['total']=ref
                        if ' button ' in line and ('Place order' in line or 'Pay $2.00' in line): self.refs['buy']=ref
                        if 'Card number' in line and ' input ' in line: self.refs['card']=ref
                        if ' article ' in line and 'TEST-1' in line: self.refs['cancel_row']=ref
                        if ' button ' in line and 'Cancel order' in line: self.refs['cancel']=ref
        def use(name,args=None,browser=True):
            return {'content':[{'type':'tool_use','id':'tool_'+str(turn),'name':name,'input':args or {},
                               **({'toolset_name':'browser'} if browser else {})}],
                    'usage':{'input_tokens':10,'output_tokens':10}}
        if self.mode=='budget':
            return use('read_page',{'filter':'interactive'})
        if turn==1:
            return use('read_page',{'filter':'all'})
        if self.mode=='portal':
            return {'content':[{'type':'text','text':json.dumps({'evidence':'Test supply shop'})}]}
        if self.mode=='cancel':
            if turn==2:
                return use('review_cancellation',{'submit_ref':self.refs['cancel'],'order_ref':self.refs['cancel_row']},False)
            if turn==3:
                return use('left_click',{'target':{'type':'ref','ref':self.refs['cancel']}})
            return {'content':[{'type':'text','text':json.dumps({'cancelled_order_number':'TEST-1'})}]}
        if self.mode=='injection':
            return use('form_input',{'target':{'type':'ref','ref':self.refs['qty']},'value':40})
        if self.mode=='offdomain':
            return use('navigate',{'url':'https://evil.test/steal'})
        if self.mode=='skip_review':
            return use('left_click',{'target':{'type':'ref','ref':self.refs['buy']}})
        if self.mode=='secret':
            if turn==2:
                return use('form_input',{'target':{'type':'ref','ref':self.refs['card']},'value':'MODEL-GUESS'})
            if turn==3:
                return use('read_page',{'filter':'all'})
            turn-=2
        if turn==2:
            return use('review_checkout',{'submit_ref':self.refs['buy'],'total_ref':self.refs['total'],
                'items':[{'offering_id':OID,'item_ref':self.refs['row'],'quantity_ref':self.refs['qty']}]},False)
        if turn==3:
            return use('left_click',{'target':{'type':'ref','ref':self.refs['buy']}})
        if self.mode=='retry_submit':
            return use('left_click',{'target':{'type':'ref','ref':self.refs['buy']}})
        return {'content':[{'type':'text','text':json.dumps({'order_number':'TEST-1' if self.mode!='invent_confirmation' else 'MADE-UP',
            'charged_cents':200,'confirmation_url_host':'supplier.test'})}]}


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as p:
        b=p.chromium.launch(headless=True)
        yield b
        b.close()


def setup_driver(browser,monkeypatch,mode='happy',total=200,**extra):
    store=Store(mode=='secret',total)
    backend=Backend(browser)
    client=ScriptedClient(mode)
    frames=[]
    def frame(bid,eid,n,jpeg):
        assert bid==BID and eid==EID
        frames.append(jpeg)
        return f'{bid}/errand/{eid}/{n:03d}.jpg'
    monkeypatch.setattr(ed,'store_frame',frame)
    writer=Mock(return_value={'document_id':JOB,'document_path':f'{BID}/general/Receipt-{EID}.pdf'})
    driver=ed.Driver(BID,EID,job_id=JOB,store=store,backend=backend,client=client,
        authorize=Mock(),receipt_writer=writer,model='fixture-model',meter=Mock(),**extra)
    return driver,store,backend,client,writer,frames


def test_happy_path_requires_dom_review_then_confirmed_receipt(browser,monkeypatch):
    driver,store,backend,client,writer,frames=setup_driver(browser,monkeypatch)
    result=driver.run()
    assert result['ok'],result
    assert store.row['status']=='done'
    assert store.row['receipt']['order_number']=='TEST-1'
    assert store.row['receipt']['document_id']==JOB
    assert store.row['plan']['__submission_attempted_at']
    assert backend.final_quantity=='1'
    assert len(frames)>=4
    writer.assert_called_once()


def test_secure_entry_fill_resume_keeps_every_model_request_secret_free(browser,monkeypatch):
    # A random reference UUID can coincidentally contain the three CVC digits.
    # Keep opaque references deterministic; still inspect every model request.
    import browser_controller
    import itertools
    from uuid import UUID
    sequence=itertools.count(1)
    monkeypatch.setattr(browser_controller,'uuid4',lambda:UUID('aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaa'+format(next(sequence),'02x')))
    driver,store,backend,client,writer,frames=setup_driver(browser,monkeypatch,'secret')
    fields={'name':'PRIVATE OWNER','number':'4242424242424242','exp':'12/30','cvc':'789'}
    commands=[]
    def answer(hold):
        command=ce.Command('secret',UID,hold_id=hold['id'],fields=dict(fields))
        commands.append(command)
        driver.mailbox.put(command)
    store.on_hold=answer
    result=driver.run()
    assert result['ok'],result
    assert store.holds[0]['field_kind']=='card' and not store.holds[0]['allow_save']
    sent=json.dumps(client.requests)
    assert all(v not in sent for v in fields.values()), [(k, sent[max(0,sent.find(v)-70):sent.find(v)+100]) for k,v in fields.items() if v in sent]
    assert '4242' not in sent
    assert 'filled' in sent
    assert not commands[0].fields
    assert store.row['receipt']['paid_with']=='card •••• 4242'
    assert all(v not in json.dumps(store.events) for v in fields.values())


def test_total_drift_waits_for_hold_approval(browser,monkeypatch):
    driver,store,backend,client,writer,frames=setup_driver(browser,monkeypatch,total=100)
    store.on_hold=lambda hold:driver.mailbox.put(ce.Command('continue',UID,hold_id=hold['id']))
    result=driver.run()
    assert result['ok'],result
    assert store.holds[0]['kind']=='approval'
    assert store.holds[0]['planned_total_cents']==100
    assert store.holds[0]['observed_total_cents']==200
    assert any(e['kind']=='approved' for e in store.events)


@pytest.mark.parametrize('mode',['injection','offdomain','skip_review','invent_confirmation','retry_submit'])
def test_model_cannot_change_quantity_escape_skip_review_invent_or_resubmit(browser,monkeypatch,mode):
    driver,store,backend,client,writer,frames=setup_driver(browser,monkeypatch,mode)
    result=driver.run()
    assert not result['ok']
    assert backend.final_quantity=='1'
    writer.assert_not_called()
    if mode in ('injection','offdomain','skip_review'):
        assert not driver.submitted


def test_time_budget_stops_before_any_action_after_slow_model(browser,monkeypatch):
    clock=[0.0]
    driver,store,backend,client,writer,frames=setup_driver(browser,monkeypatch,clock=lambda:clock[0])
    original=client.create
    def slow(**kwargs):
        clock[0]=481
        return original(**kwargs)
    client.create=slow
    result=driver.run()
    assert not result['ok']
    assert not driver.submitted
    assert len(frames)==1


def test_action_budget_does_not_execute_the_sixty_first_tool(browser,monkeypatch):
    driver,store,backend,client,writer,frames=setup_driver(browser,monkeypatch,'budget')
    result=driver.run()
    assert not result['ok']
    assert driver.calls==60
    assert len(frames)==61  # opening the supplier + 60 model tools


def test_receipt_storage_failure_does_not_make_confirmed_purchase_retryable(browser,monkeypatch):
    driver,store,backend,client,writer,frames=setup_driver(browser,monkeypatch)
    writer.side_effect=RuntimeError('storage down')
    result=driver.run()
    assert result['ok'] and result['warning']
    assert store.row['status']=='done'
    assert store.row['receipt']['order_number']=='TEST-1'
    assert store.row['plan']['__confirmation_text']


def test_restart_state_is_preserved_and_never_auto_retried(browser,monkeypatch):
    driver,store,backend,client,writer,frames=setup_driver(browser,monkeypatch)
    original=client.create
    def interrupted(**kwargs):
        response=original(**kwargs)
        store.row.update(status='interrupted',error=ce.INTERRUPTED)
        return response
    client.create=interrupted
    result=driver.run()
    assert not result['ok'] and result['status']=='interrupted'
    assert not driver.submitted
    writer.assert_not_called()


@pytest.mark.parametrize('change',['quantity','total','stop','permission'])
def test_changed_checkout_or_authority_cannot_use_previous_review(browser,monkeypatch,change):
    driver,store,backend,client,writer,frames=setup_driver(browser,monkeypatch)
    original=client.create
    def changed(**kwargs):
        response=original(**kwargs)
        if len(client.requests)==3:
            page=backend.context.pages[0]
            if change=='quantity': page.locator('[name=quantity]').fill('40')
            elif change=='total': page.locator('p').first.evaluate("el=>el.textContent='Total $999.00'")
            elif change=='stop': store.row['status']='stopped'
            else: driver.authorize.side_effect=RuntimeError('access revoked')
        return response
    client.create=changed
    result=driver.run()
    assert not result['ok'] and not driver.submitted
    writer.assert_not_called()


def test_pause_after_model_response_prevents_action_until_resume(browser,monkeypatch):
    driver,store,backend,client,writer,frames=setup_driver(browser,monkeypatch)
    original=client.create
    def paused(**kwargs):
        response=original(**kwargs)
        if len(client.requests)==2: store.row['status']='paused'
        return response
    client.create=paused
    def resume(_):
        assert not driver.submitted
        store.row['status']='stopped'
    driver.sleeper=resume
    result=driver.run()
    assert not result['ok'] and store.row['status']=='stopped'
    writer.assert_not_called()


def test_portal_finishes_with_visible_evidence_and_no_purchase_receipt(browser,monkeypatch):
    driver,store,backend,client,writer,frames=setup_driver(browser,monkeypatch,'portal')
    store.row['kind']='portal'
    driver.row['kind']='portal'
    result=driver.run()
    assert result['ok'] and result['report']=='Test supply shop'
    assert '"kind": "portal"' in client.requests[0]['messages'][0]['content']
    assert not driver.submitted and not store.row.get('receipt')
    writer.assert_not_called()


@pytest.mark.parametrize('mode',['happy','secret'])
def test_portal_cannot_purchase_or_enter_card(browser,monkeypatch,mode):
    driver,store,backend,client,writer,frames=setup_driver(browser,monkeypatch,mode)
    store.row['kind']='portal'
    driver.row['kind']='portal'
    result=driver.run()
    assert not result['ok'] and not driver.submitted
    assert not store.holds
    writer.assert_not_called()


@pytest.mark.parametrize('expired',[False,True])
def test_cancellation_requires_original_order_and_live_window(browser,monkeypatch,expired):
    driver,store,backend,client,writer,frames=setup_driver(browser,monkeypatch,'cancel')
    store.row.update(kind='cancel_order')
    store.row['plan'].update(original_errand_id=OID,order_number='TEST-1',__start_url='https://supplier.test/cancel')
    driver.row=store.get_row(EID)
    original_get=store.get_row
    store.get_row=lambda eid: {'id':OID,'business_id':BID,'status':'done','cancel_until':
        '2000-01-01T00:00:00Z' if expired else '2099-01-01T00:00:00Z',
        'receipt':{'order_number':'TEST-1'}} if eid==OID else original_get(eid)
    result=driver.run()
    assert result['ok'] is (not expired),result
    assert driver.cancel_submitted is (not expired)
    assert not driver.submitted
    writer.assert_not_called()


def test_spend_limit_drop_while_continue_is_queued_requires_fresh_stepup(browser,monkeypatch):
    driver,store,backend,client,writer,frames=setup_driver(browser,monkeypatch,total=100)
    commands=[]
    def approve_at_old_limit(hold):
        assert not hold['needs_stepup']
        command=ce.Command('continue',UID,hold_id=hold['id'])
        commands.append(command)
        store.settings={'computer':{'spend_limit_cents':1}}
        driver.mailbox.put(command)
    store.on_hold=approve_at_old_limit
    driver.sleeper=lambda _:store.row.update(status='stopped')
    result=driver.run()
    assert not result['ok'] and not driver.submitted
    assert commands[0].result.exception().status_code==409
    writer.assert_not_called()
