from __future__ import annotations
import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID
import pytest

import chief_event_delivery as delivery
import chief_responsibilities as responsibilities
import chief_business_responsibilities as workflows
import chief_operating_context as operating
import chief_assignments as assignments
import chief_jobs

BID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
UID = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
IID = 'cccccccc-cccc-cccc-cccc-cccccccccccc'
BIZ = {'id': BID, 'owner_id': UID, 'name': 'Fixture business', 'settings': {}}


def run(value):
    return asyncio.run(value)


@pytest.fixture
def event_store(monkeypatch):
    calls = []
    def rpc(name, args):
        calls.append((name, args))
        if name == 'claim':
            return [{'event_id': 'one'}]
        return True
    monkeypatch.setattr(delivery, 'rpc', rpc)
    return calls


def test_delivery_checkpoints_before_effects_and_after_completion(event_store):
    async def runner(biz, events):
        assert [e['id'] for e in events] == ['one']
        await delivery.before_actions()
        assert event_store[-1][1]['p_phase'] == 'acting'
        return {'recap': 'Prepared a draft.', 'failed': []}
    result = run(delivery.execute(BIZ, [{'id':'one','business_id':BID}, {'id':'other','business_id':UID}], runner))
    assert result['recap'] == 'Prepared a draft.'
    assert event_store[0][1]['p_ids'] == ['one']
    assert event_store[-1][1]['p_phase'] == 'completed'
    assert delivery._delivery.get() is None


@pytest.mark.parametrize('acting', [False, True])
def test_crash_preserves_last_durable_boundary(event_store, acting):
    async def runner(*args):
        if acting:
            await delivery.before_actions()
        raise RuntimeError('worker stopped')
    with pytest.raises(RuntimeError, match='worker stopped'):
        run(delivery.execute(BIZ, [{'id':'one','business_id':BID}], runner))
    assert not any(a.get('p_phase') == 'completed' for _, a in event_store)
    assert event_store[-1][0] == ('checkpoint' if acting else 'claim')
    assert delivery._delivery.get() is None


def test_lost_claim_never_exposes_write_tools(monkeypatch):
    def rpc(name, args):
        return [{'event_id':'one'}] if name == 'claim' else False
    monkeypatch.setattr(delivery, 'rpc', rpc)
    async def runner(*args):
        await delivery.before_actions()
        pytest.fail('stale worker acted')
    with pytest.raises(RuntimeError, match='lease'):
        run(delivery.execute(BIZ, [{'id':'one','business_id':BID}], runner))


def test_failed_action_becomes_review_not_success(event_store):
    async def runner(*args):
        await delivery.before_actions()
        return {'failed':['create_task'], 'recap':'Finished'}
    run(delivery.execute(BIZ, [{'id':'one','business_id':BID}], runner))
    assert event_store[-1][1]['p_phase'] == 'needs_review'


def test_snapshot_keeps_errors_and_deduplicates_errand_jobs(monkeypatch):
    seen = []
    def read(query):
        seen.append(query)
        if query.startswith('/chief_missions'):
            return None
        if query.startswith('/chief_errands'):
            return [{'id':'errand','job_id':'job','status':'interrupted','title':'Supplier order'}]
        if query.startswith('/chief_jobs'):
            return [{'id':'job','kind':'errand','status':'failed'}]
        return []
    monkeypatch.setattr(responsibilities.sb_clients, 'sb_get_as_service', read)
    monkeypatch.setenv('CHIEF_DURABLE_EVENTS', 'off')
    report = run(responsibilities.snapshot(BID))
    assert report['partial'] and len(report['items']) == 1 and report['needs_you'] == 1
    assert not report['sources']['missions']['available']
    assert all(f'business_id=eq.{BID}' in q for q in seen)
    assert 'supplier' in report['items'][0]['summary']


def test_cross_business_request_stops_before_work_reads(monkeypatch):
    seen = []
    def read(query):
        seen.append(query)
        return [{'id':BID, 'owner_id':UID}]
    monkeypatch.setattr(responsibilities.sb_clients, 'sb_get_as_service', read)
    with pytest.raises(responsibilities.HTTPException) as exc:
        run(responsibilities.get_responsibilities(UUID(BID), SimpleNamespace(id=IID)))
    assert exc.value.status_code == 403 and len(seen) == 1


def test_held_build_does_not_read_as_completed():
    item = responsibilities.normalize('jobs', {'id':'one','status':'done','kind':'build',
        'params':{'conversation_id':IID}, 'result':{'status':'held','held':{'label':'Approve outreach'}}})
    assert item['status'] == 'held' and item['needs_you']
    assert item['conversation_id'] == IID


@pytest.mark.parametrize('kind,label', [('author_spec','Blueprint'),('revise_spec','Blueprint revision'),('unknown_internal_kind','Background work')])
def test_report_uses_user_facing_job_labels(kind,label):
    item=responsibilities.normalize('jobs', {'id':'one','kind':kind,'status':'done'})
    assert item['title']==label


def test_report_reads_real_draft_approval_state_and_preserves_failed_errands(monkeypatch):
    def read(query):
        if query.startswith('/agent_queue'):
            assert 'status=eq.draft' in query
            return [{'id':'approval','subject':'Review reminder','created_at':'2026-10-03T12:00:00Z'}]
        if query.startswith('/chief_errands'):
            assert 'interrupted,failed)' in query
            return [{'id':'errand','status':'failed','title':'Supplier order'}]
        return []
    monkeypatch.setattr(responsibilities.sb_clients,'sb_get_as_service',read)
    result=run(responsibilities.snapshot(BID))
    assert result['needs_you']==2
    assert {i['status'] for i in result['items']}=={'awaiting_approval','failed'}


def test_saved_measurement_is_not_causal_credit():
    item = responsibilities.normalize('assignments', {'id':'one','status':'completed',
        'progress':{'value':6, 'target':6, 'label':'6 appointments'}, 'next_check_at':None})
    assert item['measurement']['value'] == 6
    assert 'not proof' in item['attribution'] and item['next_check_at'] is None


def profile(revision, statement):
    return {'revision':revision, 'profile':{'schema_version':1,'trade_label':'Coaching',
        'summary':'Owner rules', 'facts':[{'key':'fridays','kind':'workflow','content':statement,
        'basis':'owner','owner_quote':statement,'evidence_ids':[]}], 'gaps':[], 'evidence':[]}}


def test_correction_is_fresh_on_next_background_read(monkeypatch):
    rows = iter([profile(1,'Fridays are open.'), profile(2,'We no longer offer Friday appointments.')])
    monkeypatch.setattr(operating.business_learning, 'load', lambda bid: next(rows))
    first, second = operating.current_context(BIZ), operating.current_context(BIZ)
    assert 'Fridays are open.' in first
    assert 'revision 2' in second and 'no longer offer Friday' in second
    assert 'Fridays are open.' not in second and 'does not prove' in second


def test_missing_knowledge_read_blocks_unattended_work(monkeypatch):
    def missing(*a):
        raise RuntimeError('unavailable')
    monkeypatch.setattr(operating.business_learning, 'load', missing)
    with pytest.raises(RuntimeError):
        operating.current_context(BIZ)


@pytest.mark.parametrize('workflow,kind', [('fill_appointments','sessions_scheduled'),('collect_invoice','invoice_paid'),('grow_contacts','new_contacts')])
def test_three_workflows_use_existing_assignment_permissions(monkeypatch, workflow, kind):
    seen = []
    monkeypatch.setattr(workflows.sb_clients, 'sb_get_as_service', lambda q: [{'id':IID,'status':'sent'}])
    monkeypatch.setattr(assignments, 'measure', lambda *a: {'value':0,'target':2,'met':False})
    async def create(client,biz,action):
        seen.append(action)
        return {'type':'create_assignment','result':'Recorded','label':'Recorded','assignment_id':IID, 'agent_enabled':False}
    monkeypatch.setattr(assignments, 'handle_create_assignment', create)
    result = run(workflows.handle_start_business_responsibility(None,BIZ,{
        'workflow':workflow,'invoice_id':IID,'from':'2026-10-04','to':'2026-10-05','count':2}))
    assert seen[0]['target']['kind'] == kind
    assert 'owner review' in seen[0]['ask'] or 'approval queue' in seen[0]['ask']
    assert result['baseline']['value'] == 0 and not result['agent_enabled']


def test_foreign_invoice_cannot_start_collection(monkeypatch):
    seen = []
    monkeypatch.setattr(workflows.sb_clients, 'sb_get_as_service', lambda q: seen.append(q) or [])
    result = run(workflows.handle_start_business_responsibility(None,BIZ,{'workflow':'collect_invoice','invoice_id':IID}))
    assert result['failed'] and f'business_id=eq.{BID}' in seen[0]


@pytest.mark.parametrize('rows', [None, [{'id':str(i)} for i in range(1000)]])
def test_unavailable_or_truncated_measurement_is_not_zero(monkeypatch, rows):
    monkeypatch.setattr(assignments.sb_clients, 'sb_get_as_service', lambda q: rows)
    with pytest.raises(RuntimeError):
        assignments.measure(BID, {'kind':'new_contacts','from':'2026-10-04','to':'2026-10-05','count':5}, tz=timezone.utc)


def test_measurement_failure_keeps_last_progress_and_rechecks(monkeypatch):
    import chief_agent
    patches = []
    monkeypatch.setattr(chief_agent, '_business', lambda bid:BIZ)
    monkeypatch.setattr(assignments, 'measure', lambda *a: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(assignments, 'save', lambda rid,p: patches.append(p) or True)
    result = run(assignments.check_one({'id':IID,'business_id':BID,'target':{},'progress':{'value':4}}))
    assert result['did'] == 'skipped'
    assert 'progress' not in patches[0] and patches[0]['next_check_at']


@pytest.mark.parametrize('kind,status', [('errand','failed'),('rebuild_site','running'),('build','failed')])
def test_generic_retry_cannot_replay_uncertain_or_running_work(monkeypatch, kind, status):
    calls=[]
    async def db(client,method,path,body=None):
        calls.append(method)
        return [{'id':IID,'user_id':UID,'business_id':BID,'kind':kind,'status':status}]
    monkeypatch.setattr(chief_jobs,'_sb',db)
    with pytest.raises(chief_jobs.HTTPException) as exc:
        run(chief_jobs.retry_job(chief_jobs._RetryReq(job_id=IID),SimpleNamespace(user=SimpleNamespace(id=UID))))
    assert exc.value.status_code==409 and calls==['GET']


def test_native_report_pages_whole_json_within_transport_budget(monkeypatch):
    async def snapshot(bid):
        items = [responsibilities.normalize('jobs', {'id':str(i),'kind':'x'*160,'status':'failed',
                 'result':{'summary_label':'\u2603'*240}}) for i in range(40)]
        return {'items':items,'needs_you':40,'partial':False,'sources':{},'errors':[]}
    monkeypatch.setattr(responsibilities,'snapshot',snapshot)
    first=run(responsibilities.handle_responsibility_status(None,BIZ,{}))
    assert len(json.dumps(first)) < responsibilities.REPORT_MAX_RESULT_CHARS
    offset=first['responsibilities']['next_offset']
    assert 0 < offset < 40
    second=run(responsibilities.handle_responsibility_status(None,BIZ,{'offset':offset}))
    assert first['responsibilities']['items'][-1]['id'] != second['responsibilities']['items'][0]['id']


@pytest.mark.parametrize('owner',[True,False])
def test_follow_up_acknowledgement_requires_owner_and_current_revision(monkeypatch,owner):
    import chief_of_staff as cos
    calls=[]
    monkeypatch.setattr(delivery,'rpc',lambda name,args:calls.append((name,args)) or True)
    token=cos._TURN_USER_ID.set(UID if owner else IID)
    try:
        result=run(responsibilities.handle_acknowledge_follow_up(None,BIZ,{
            'event_id':IID,'observed_at':'2026-10-03T12:00:00Z'}))
    finally:
        cos._TURN_USER_ID.reset(token)
    assert result['failed'] is not owner
    assert len(calls)==int(owner)
    if owner:
        assert calls[0][0]=='resolve' and calls[0][1]['p_business']==BID
        assert 'No actions were replayed' in result['result']


def test_only_the_winner_of_atomic_retry_starts_a_worker(monkeypatch):
    claimed=False
    runs=[]
    async def db(client,method,path,body=None):
        nonlocal claimed
        if method=='GET':
            return [{'id':IID,'business_id':BID,'user_id':UID,'kind':'draft_campaign','status':'failed'}]
        assert 'user_id=eq.'+UID in path and 'status=eq.failed' in path
        if claimed:
            return []
        claimed=True
        return [{'id':IID}]
    async def worker(*args):
        runs.append(args)
    monkeypatch.setattr(chief_jobs,'_sb',db)
    monkeypatch.setattr(chief_jobs,'_run',worker)
    async def race():
        user=SimpleNamespace(user=SimpleNamespace(id=UID))
        results=await asyncio.gather(*(chief_jobs.retry_job(chief_jobs._RetryReq(job_id=IID),user) for _ in range(2)),return_exceptions=True)
        await asyncio.sleep(0)
        return results
    results=run(race())
    assert len(runs)==1
    assert sum(isinstance(r,chief_jobs.HTTPException) and r.status_code==409 for r in results)==1
