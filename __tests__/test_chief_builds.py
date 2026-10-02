"""Failure rehearsals for durable builds. No live services or paid calls."""
import asyncio
import copy
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
import pytest
from chief_code import WorkOrder, Step, run, receipt, question, digest, stable_id, finish
import chief_build_runtime as runtime

BIZ='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
USER='11111111-1111-1111-1111-111111111111'


def order(kind='event_setup',surface='desktop',**facts):
    base={'title':'Embrace the Shift Workshop','starts_at':'2026-10-13T19:00','timezone':'America/Detroit',
          'location':'1084 Allen Avenue, Muskegon, MI','price':0,'wants_registration_form':True,'wants_flyer':True}
    return WorkOrder.create({'kind':kind,'facts':{**base,**facts}},business_id=BIZ,user_id=USER,
                            turn_id='original-turn',surface=surface,words='Set up my workshop')


class MemoryAdapter:
    def __init__(self, fail_after_write=None, fail_verify=None, child=False):
        self.rows={};self.calls=[];self.checkpoints=[];self.fail_after_write=fail_after_write
        self.fail_verify=fail_verify;self.child=child;self.deny=False;self.checkpoint_fails=False
    async def assert_authority(self,step):
        if self.deny: raise PermissionError()
    async def parameters(self,step,state): return dict(step.params)
    async def find(self,step,params,state): return self.rows.get(step.name)
    async def confirmation(self,step,params): return 'Your flyer is waiting for your go-ahead.'
    async def save(self,state):
        if self.checkpoint_fails: raise RuntimeError('database unavailable')
        self.checkpoints.append(copy.deepcopy(state))
    def stage(self,step): return step.label
    def retry_safe(self,step): return step.name!='send'
    async def execute(self,step,params,state):
        self.calls.append(step.name)
        self.rows[step.name]={'id':step.name}
        if self.fail_after_write==step.name: raise NameError('after insert')
        return self.rows[step.name]
    async def verify(self,step,params,result,state):
        if step.name==self.fail_verify:
            return receipt(step,'failed','The page could not be verified.')
        if step.name=='flyer' and self.child:
            return receipt(step,'queued','Your flyer is generating.')
        return receipt(step,'created',verified={'ok':True,'how':'read-back'},ids={'module_id':'events','url':'https://example.mysolutionist.app/events'})


def test_work_order_authority_is_not_model_controlled():
    o=WorkOrder.create({'kind':'flyer','facts':{'prompt':'test'},'confirmed':True,'asked_by':'attacker','order_id':'forged'},
        business_id=BIZ,user_id=USER,turn_id='t',surface='voice',words='please make a flyer')
    assert o.asked_by==USER and o.approvals=={} and o.surface=='voice'
    assert o.order_id==stable_id(BIZ,'t')


def test_custom_cannot_report_empty_success():
    with pytest.raises(ValueError): order('custom')


def test_missing_question_before_any_effect():
    o=order(title='');a=MemoryAdapter()
    result=asyncio.run(run(o,a))
    assert result['status']=='needs_answer' and result['question']['field']=='title'
    assert not a.calls


def test_timezone_and_capacity_validation():
    assert question(order(timezone=''))['field']=='timezone'
    assert question(order(capacity=-1))['field']=='capacity'
    assert question(order(starts_at='2026-11-01T01:30'))['field']=='starts_at'
    o=order();assert question(o) is None;assert o.facts['starts_at'].endswith('-04:00')


def test_voice_hold_continues_independent_website_step_then_resumes_once():
    o=order(surface='voice');a=MemoryAdapter()
    held=asyncio.run(run(o,a))
    assert held['status']=='held' and len(held['receipts'])==6
    assert 'site_link' in a.calls and 'flyer' not in a.calls
    o.approvals={'flyer':held['held']['fingerprint']}
    result=asyncio.run(run(o,a,held))
    assert result['status']=='done' and a.calls.count('flyer')==1
    asyncio.run(run(o,a,result))
    assert len(a.calls)==6


def test_approval_does_not_authorize_changed_parameters():
    o=order(surface='voice');a=MemoryAdapter()
    held=asyncio.run(run(o,a));o.approvals={'flyer':'different-fingerprint'}
    assert asyncio.run(run(o,a,held))['status']=='held'
    assert 'flyer' not in a.calls


def test_write_then_exception_is_reconciled_without_duplicate():
    a=MemoryAdapter(fail_after_write='occasion')
    result=asyncio.run(run(order(),a))
    assert result['status']=='done'
    assert result['steps']['occasion']['verified']['ok']
    asyncio.run(run(order(),a,result))
    assert a.calls.count('occasion')==1


def test_existing_resource_is_verified_before_reuse():
    a=MemoryAdapter(fail_verify='events_page');a.rows['events_page']={'id':'bad-page'}
    result=asyncio.run(run(order(wants_flyer=False),a))
    assert result['status']=='done_with_gaps'
    assert not result['steps']['events_page']['verified']['ok']
    assert 'https://' not in result['summary_label']
    assert 'registration' not in a.calls


def test_queued_child_is_not_finished_and_is_not_recreated():
    a=MemoryAdapter(child=True)
    waiting=asyncio.run(run(order(),a))
    assert waiting['status']=='waiting'
    a.child=False
    done=asyncio.run(run(order(),a,waiting))
    assert done['status']=='done' and a.calls.count('flyer')==1


def test_failed_checkpoint_prevents_effects():
    a=MemoryAdapter();a.checkpoint_fails=True
    with pytest.raises(RuntimeError):asyncio.run(run(order(),a))
    assert not a.calls


def test_permission_revoked_before_step_prevents_effects():
    a=MemoryAdapter();a.deny=True
    result=asyncio.run(run(order(),a))
    assert result['status']=='failed' and not a.calls


def test_tainted_desktop_cannot_spend_without_bound_approval():
    o=order();o.untrusted_taint=True;a=MemoryAdapter()
    assert asyncio.run(run(o,a))['status']=='held'
    assert 'flyer' not in a.calls


def test_ambiguous_send_is_never_automatically_repeated():
    o=order('form_and_link',name='Registration',send_to='a@example.com');a=MemoryAdapter()
    previous={'attempted':{'send':'intent'},'steps':{}}
    result=asyncio.run(run(o,a,previous))
    assert result['steps']['send']['outcome']=='uncertain' and 'send' not in a.calls


def test_public_payload_hides_internal_checkpoint_and_diagnostics():
    payload=runtime.public_job({'id':'j','kind':'build','status':'done','build_revision':4,'params':{'secret':'private'},
        'result':{'attempted':{'x':'hash'},'receipts':[{'detail':'handler exception','label':'Ready','outcome':'created'}]}})
    assert 'params' not in payload and 'attempted' not in payload['result']
    assert 'detail' not in payload['result']['receipts'][0]


def test_page_verifier_rejects_private_hosts_and_redirects(monkeypatch):
    class Client:
        calls=0
        async def get(self,url,**kwargs):
            self.calls+=1
            return SimpleNamespace(status_code=302,text='Workshop')
    async def redirected(url): return 302,'Workshop'
    monkeypatch.setattr(runtime,'fetch_public_page',redirected)
    client=Client();o=order();adapter=runtime.Adapter(client,{'id':o.order_id,'business_id':BIZ,'user_id':USER},'lease',o)
    assert asyncio.run(adapter.page('http://127.0.0.1/admin'))==(False,'')
    assert client.calls==0
    assert asyncio.run(adapter.page('https://example.mysolutionist.app/events',['Workshop']))[0] is False


def test_submission_replays_completed_order_without_dispatch(monkeypatch):
    monkeypatch.setenv('CHIEF_BUILDS','on')
    o=order('flyer',prompt='A workshop flyer');calls=[]
    job={'id':o.order_id,'business_id':BIZ,'user_id':USER,'kind':'build','params':o.payload(),'status':'done','result':{'summary_label':'Ready'}}
    async def database(client,method,path,body=None):
        calls.append(method)
        return [{'id':BIZ,'owner_id':USER}] if path.startswith('/businesses') else [job]
    monkeypatch.setattr(runtime,'db',database)
    monkeypatch.setattr(runtime,'launch',lambda job:pytest.fail('Completed job restarted'))
    token=runtime.turn_scope.set({'user_id':USER,'turn_id':'original-turn','surface':'desktop','words':'make a flyer'})
    try:
        result=asyncio.run(runtime.submit(None,{'id':BIZ},{'kind':'flyer','facts':o.facts}))
    finally:runtime.turn_scope.reset(token)
    assert result['job_id']==o.order_id and calls==['GET','GET']


def test_cross_business_and_unknown_actor_denied(monkeypatch):
    async def empty(*args):return []
    monkeypatch.setattr(runtime,'db',empty)
    with pytest.raises(Exception) as exc:asyncio.run(runtime.owned_business(None,BIZ,USER))
    assert exc.value.status_code==403


def test_stale_review_cannot_resume(monkeypatch):
    o=order();job={'id':o.order_id,'business_id':BIZ,'user_id':USER,'params':o.payload(),
        'result':{'status':'held','held':{'step':'flyer','fingerprint':'abc'}}}
    async def database(client,method,path,body=None):
        return [{'id':BIZ,'owner_id':USER}] if path.startswith('/businesses') else [job]
    async def stale(*args):return []
    monkeypatch.setattr(runtime,'db',database);monkeypatch.setattr(runtime,'rpc',stale)
    with pytest.raises(Exception) as exc:asyncio.run(runtime.respond(None,o.order_id,USER,0,approve=True))
    assert exc.value.status_code==409


def test_adapter_executes_existing_handlers_with_trusted_scope(monkeypatch):
    import chief_of_staff as chief
    import image_studio
    import policy_engine
    import spend_guard
    import sb_clients
    o=order('flyer',surface='voice',prompt='Workshop flyer')
    adapter=runtime.Adapter(None,{'id':o.order_id,'business_id':BIZ,'user_id':USER},'lease',o)
    adapter.biz={'id':BIZ,'owner_id':USER}
    p={'prompt':'Workshop flyer','quality':'high','reference_ids':[]}
    o.approvals={'flyer':digest({'step':'flyer','params':p})}
    seen=[]
    async def handler(client,biz,action):
        assert chief._TURN_USER_ID.get()==USER
        assert chief._TURN_IS_VOICE.get() is True
        assert chief._TURN_CONFIRMED.get() is True
        assert image_studio.build_actor.get()=={'business_id':BIZ,'user_id':USER}
        assert image_studio.turn_id.get()==o.order_id
        seen.append(action)
        return {'type':'generate_image','result':'queued','label':'Creating image'}
    async def undo(*args):pass
    monkeypatch.setitem(chief.ACTION_HANDLERS,'generate_image',handler)
    monkeypatch.setattr(chief,'_record_undoable',undo)
    monkeypatch.setattr(spend_guard,'over_budget',lambda **kw:False)
    monkeypatch.setattr(policy_engine,'evaluate',lambda *a,**kw:SimpleNamespace(allowed=True,rule='test'))
    result=asyncio.run(adapter.execute(Step('flyer','generate_image','Ready',sensitive=True),p,{}))
    assert result['result']=='queued' and len(seen)==1
    assert image_studio.build_actor.get() is None


def test_background_image_db_cannot_cross_business_or_publish(monkeypatch):
    import image_studio
    import sb_clients
    calls=[]
    async def service(client,method,path,body=None):calls.append(path);return []
    monkeypatch.setattr(sb_clients,'sb_as_service',service)
    token=image_studio.build_actor.set({'business_id':BIZ,'user_id':USER})
    try:
        asyncio.run(image_studio.db(None,'GET','/image_artworks?id=eq.some-image'))
        assert calls[-1].endswith('&business_id=eq.'+BIZ)
        with pytest.raises(Exception):asyncio.run(image_studio.db(None,'POST','/image_publications',{}))
        with pytest.raises(Exception):asyncio.run(image_studio.db(None,'POST','/rpc/reserve_image_artwork',{'p_record':{'business_id':str(uuid4())}}))
    finally:image_studio.build_actor.reset(token)


def test_builds_are_not_exposed_to_external_mcp(monkeypatch):
    import action_registry
    import chief_tool_loop
    monkeypatch.setenv('CHIEF_BUILDS','on')
    assert not action_registry.may_expose_to_agent('submit_work_order',allow_writes=True)
    chief_tool_loop.reset_turn(writes_allowed=True)
    assert any(t['name']=='submit_work_order' for t in chief_tool_loop.write_tool_definitions())


def test_bound_voice_approval_refuses_bare_yes(monkeypatch):
    import chief_of_staff as chief
    assert not chief._is_voice_confirmation('yes')
    assert chief._is_voice_confirmation('go ahead')


def test_generic_enqueue_cannot_forge_worker_authority():
    import chief_jobs
    with pytest.raises(ValueError):
        asyncio.run(chief_jobs.enqueue(None,user_id=USER,business_id=BIZ,kind='build',params={'confirmed':True}))


def test_labels_are_practitioner_facing():
    import action_registry
    import re
    result=asyncio.run(run(order(surface='voice'),MemoryAdapter()))
    verbs=set(__import__('chief_of_staff').ACTION_HANDLERS)
    for r in result['receipts']:
        assert not any(v in r['label'] for v in verbs if '_' in v)
        assert not re.search(r'module_id|\bslug\b|\bemit\b|Try |[{}]',r['label'])


def test_legacy_event_batch_becomes_one_build():
    routed=runtime.route_actions([{'type':'ensure_module','archetype':'event_roster'},
        {'type':'create_module_entry','data':{'title':'Workshop','date':'2026-10-13T19:00','location':'Studio'}},
        {'type':'set_site_capability','capability':'events','on':True},{'type':'generate_image','prompt':'Workshop flyer'}])
    assert len(routed)==1 and routed[0]['kind']=='event_setup'
    assert routed[0]['facts']['title']=='Workshop' and routed[0]['facts']['wants_flyer']


def test_running_checkpoint_does_not_claim_completion():
    job=runtime.public_job({'status':'running','result':{'status':'done','summary_label':'Earlier step ready'}})
    assert job['result']['status']=='running'


def test_response_schema_rejects_invalid_identity_and_revision():
    from chief_jobs import _BuildResponseReq
    from pydantic import ValidationError
    with pytest.raises(ValidationError): _BuildResponseReq(job_id='invalid',revision=0)
    with pytest.raises(ValidationError): _BuildResponseReq(job_id=BIZ,revision=-1)


def test_pending_receipt_cannot_prove_a_write():
    import chief_truth
    sources=chief_truth.evidence_for_review({'build_jobs':[{'id':'j','result':{'receipts':[{'label':'Creating flyer','outcome':'queued','verified':{'ok':False}}]}}]},None,[])
    assert not chief_truth.wrote_anything(sources)


def test_missing_delivery_answer_preserves_verified_form():
    from chief_code import BuildQuestion
    class Questions(MemoryAdapter):
        async def parameters(self,step,state):
            if step.name=='send': raise BuildQuestion('send_to','Which saved contact should receive it?')
            return await super().parameters(step,state)
    a=Questions()
    result=asyncio.run(run(order('form_and_link',name='Registration',send_to='unknown@example.com'),a))
    assert result['status']=='needs_answer' and result['question']['field']=='send_to'
    assert result['steps']['form']['verified']['ok'] and a.calls==['form']


def test_completed_replay_survives_answered_facts(monkeypatch):
    monkeypatch.setenv('CHIEF_BUILDS','on')
    o=order('flyer',prompt='Original flyer')
    o.submission_fingerprint=digest({'kind':o.kind,'facts':o.facts})
    original=copy.deepcopy(o.facts)
    o.facts['prompt']='Clarified flyer'
    job={'id':o.order_id,'user_id':USER,'status':'done','params':o.payload(),'result':{'summary_label':'Ready'}}
    async def database(client,method,path,body=None):
        return [{'id':BIZ,'owner_id':USER}] if path.startswith('/businesses') else [job]
    monkeypatch.setattr(runtime,'db',database)
    token=runtime.turn_scope.set({'user_id':USER,'turn_id':'original-turn','surface':'desktop','words':'make a flyer'})
    try: result=asyncio.run(runtime.submit(None,{'id':BIZ},{'kind':'flyer','facts':original}))
    finally: runtime.turn_scope.reset(token)
    assert result['job_id']==o.order_id


def test_real_form_verifier_never_returns_a_404_link(monkeypatch):
    import chief_form_actions
    o=order('form_and_link',name='Registration')
    a=runtime.Adapter(None,{'id':o.order_id,'business_id':BIZ,'user_id':USER},'lease',o)
    fields,_=chief_form_actions._normalize_fields(None)
    async def found(*args): return {'id':BIZ,'name':'Registration','fields':fields,'is_active':True}
    async def missing(url): return 404,'Registration'
    monkeypatch.setattr(a,'find',found)
    monkeypatch.setattr(runtime,'fetch_public_page',missing)
    monkeypatch.setattr(chief_form_actions,'public_form_url',lambda *args:'https://example.mysolutionist.app/f/registration')
    checked=asyncio.run(a.verify(Step('form','create_client_form','Ready'),{'name':'Registration'},None,{}))
    assert checked['outcome']=='failed' and not checked['verified']['ok']
    assert 'url' not in checked['ids'] and 'https://' not in checked['label']


def test_lost_lease_stops_inflight_execution(monkeypatch):
    o=order('flyer',prompt='Flyer');cancelled=[]
    async def rpc(client,name,body):
        if name=='claim': return [{'id':o.order_id,'business_id':BIZ,'user_id':USER,'params':o.payload()}]
        if name=='renew': return False
        return []
    async def database(*args): return []
    async def execute(*args):
        try: await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise
    sleep=asyncio.sleep
    async def fast_sleep(seconds): await sleep(0)
    monkeypatch.setattr(runtime,'rpc',rpc)
    monkeypatch.setattr(runtime,'db',database)
    monkeypatch.setattr(runtime,'run',execute)
    monkeypatch.setattr(runtime.asyncio,'sleep',fast_sleep)
    asyncio.run(runtime.worker(o.order_id))
    assert cancelled==[True]


def test_build_policy_is_instruction_in_the_actual_turn_prompt(monkeypatch):
    import chief_of_staff as chief
    from scripts import chief_turn_eval as harness
    real_prompt=chief._build_system_prompt
    harness._stub_turn(monkeypatch,harness.BIZ)
    monkeypatch.setenv('CHIEF_BUILDS','on')
    prompt=real_prompt(harness._fixture_context(harness.BIZ),False)
    assert 'CURRENT BUILD ROUTING POLICY' in prompt.split('[[CHIEF_TURN_SPLIT]]')[1]
    monkeypatch.setenv('CHIEF_BUILDS','off')
    assert runtime.routing_instructions()==''


def test_build_mode_offers_work_order_instead_of_inline_image(monkeypatch):
    import chief_tool_loop
    monkeypatch.setenv('CHIEF_BUILDS','on')
    chief_tool_loop.reset_turn(writes_allowed=True)
    names={tool['name'] for tool in chief_tool_loop.tool_definitions_for_turn(writes=True)}
    assert 'submit_work_order' in names and 'generate_image' not in names


def test_pending_build_has_status_evidence_without_claiming_a_write():
    import chief_truth
    job={'id':'pending','status':'running','result':{'status':'waiting','summary_label':'Your flyer is generating.','receipts':[]}}
    sources=chief_truth.evidence_for_review({'build_jobs':[job]},None,[])
    state=sources['result:build:pending:state']
    assert state['kind']=='record' and 'Your flyer is generating.' in state['text']
    assert not chief_truth.wrote_anything(sources)


def test_receipts_keep_plan_order_after_a_database_round_trip():
    # jsonb keeps object keys shortest-first; the first live build's summary
    # read "Your workshop is saved" before "Events is ready" (2026-09-26).
    a=MemoryAdapter()
    result=asyncio.run(run(order(wants_flyer=False),a))
    names=[r['step'] for r in result['receipts']]
    assert names[0]=='events_module' and names[-1]=='site_link'
    stored=copy.deepcopy(result)
    stored['steps']=dict(sorted(stored['steps'].items(),key=lambda kv:(len(kv[0]),kv[0])))
    assert [r['step'] for r in finish(stored)['receipts']]==names
    assert finish(stored)['summary_label'].startswith('Events is ready')
    assert [r['step'] for r in asyncio.run(run(order(wants_flyer=False),a,stored))['receipts']]==names


def test_site_link_without_a_built_website_says_why_and_starts_no_edit(monkeypatch):
    import chief_jobs
    import site_adopt
    o=order(wants_flyer=False)
    a=runtime.Adapter(None,{'id':o.order_id,'business_id':BIZ,'user_id':USER},'lease',o)
    monkeypatch.setattr(site_adopt,'hand_built_block_for',lambda bid:None)
    async def database(client,method,path,body=None):
        assert path.startswith('/business_sites?business_id=eq.'+BIZ) and 'page_spec' in path
        return []
    async def enqueue(*args,**kwargs): pytest.fail('an edit was started for a website that does not exist')
    monkeypatch.setattr(runtime,'db',database)
    monkeypatch.setattr(chief_jobs,'enqueue',enqueue)
    step=Step('site_link','connect_events','Your website links to Events.')
    result=asyncio.run(a.execute(step,{},{}))
    checked=asyncio.run(a.verify(step,{},result,{}))
    assert checked['outcome']=='needs_hand' and checked['label']==runtime.NO_SITE_LABEL


def test_a_finished_website_edit_that_said_no_gives_its_reason():
    o=order(wants_flyer=False)
    a=runtime.Adapter(None,{'id':o.order_id,'business_id':BIZ,'user_id':USER},'lease',o)
    step=Step('site_link','connect_events','Your website links to Events.')
    no_page={'status':'done','result':{'ok':False,'error':'no composed page yet — compose first'}}
    checked=asyncio.run(a.verify(step,{},no_page,{}))
    assert checked['outcome']=='needs_hand' and checked['label']==runtime.NO_SITE_LABEL
    refused={'status':'done','result':{'ok':False,'error':'validator rejected section hero'}}
    checked=asyncio.run(a.verify(step,{},refused,{}))
    assert checked['outcome']=='failed' and checked['label']==runtime.SITE_LINK_REFUSED_LABEL
    assert 'validator' not in checked['label'] and not checked['verified']['ok']
