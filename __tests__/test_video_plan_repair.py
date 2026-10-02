"""Exercise the actual planning path with deterministic provider responses."""
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
import llm_call
import spend_guard
import usage_metering
import video_studio_worker as worker


def reply(layout='title', asset_id=None):
    scene={'id':'product-window','title':'Your business, together','seconds':6,'layout':layout}
    if asset_id:scene['asset_id']=asset_id
    return {'message':'Review this scene.','composition':{'title':'Promo','scenes':[scene]}}


@pytest.fixture
def planner(monkeypatch,tmp_path):
    saved=[];calls=[];budgets=[]
    monkeypatch.setattr(worker,'progress',lambda *a:None)
    monkeypatch.setattr(worker.studio,'project',lambda *a:{'title':'Promo','brief':'Use my style reference for a product video.','format':'landscape'})
    monkeypatch.setattr(worker.studio,'assets',lambda *a:[])
    monkeypatch.setattr(worker.studio,'rows',lambda *a:[])
    monkeypatch.setattr(worker.studio,'rpc',lambda name,body:saved.append(body))
    monkeypatch.setattr(spend_guard,'over_budget',lambda bid:budgets.append(bid) or False)
    monkeypatch.setattr(usage_metering,'can_interact',lambda bid:True)
    job={k:str(uuid4()) for k in ('id','created_by','business_id','project_id')}
    job['lease_id']=str(uuid4())
    def run(responses):
        answers=iter(responses)
        def post(payload,**kwargs):
            calls.append((payload,kwargs));value=next(answers)
            data=value if 'stop_reason' in value else {'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(value)}]}
            return SimpleNamespace(raise_for_status=lambda:None,json=lambda:data)
        monkeypatch.setattr(llm_call,'post',post)
        worker.plan(job,tmp_path)
    return SimpleNamespace(run=run,saved=saved,calls=calls,budgets=budgets,job=job)


def test_missing_media_layout_is_repaired_before_saving(planner):
    planner.run([reply('split'),reply()])
    assert len(planner.calls)==2 and len(planner.saved)==1
    assert planner.saved[0]['p_composition']['scenes'][0]['layout']=='title'
    assert len(planner.budgets)==2
    for payload,options in planner.calls:
        assert options['business_id']==planner.job['business_id'] and options['task']=='video_studio'
    assert 'Choose media for this layout' in planner.calls[1][0]['messages'][-1]['content']


def test_missing_assets_can_become_a_question_without_a_fake_plan(planner):
    planner.run([reply('image'),{'message':'Please add a product screenshot as Use in video.','composition':None}])
    assert planner.saved[0]['p_composition'] is None
    assert 'screenshot' in planner.saved[0]['p_message']


def test_second_invalid_plan_stops_without_saving(planner):
    with pytest.raises(RuntimeError,match='Style reference files only guide'):
        planner.run([reply('split'),reply('image')])
    assert len(planner.calls)==2 and not planner.saved


def test_repair_cannot_invent_or_promote_an_asset(planner):
    with pytest.raises(RuntimeError,match='valid scene plan'):
        planner.run([reply('split'),reply('image',str(uuid4()))])
    assert not planner.saved


def test_budget_exhaustion_prevents_a_repair_call(planner,monkeypatch):
    answers=iter([False,True])
    monkeypatch.setattr(spend_guard,'over_budget',lambda bid:next(answers))
    monkeypatch.setattr(spend_guard,'block_message',lambda:'Budget exhausted')
    with pytest.raises(RuntimeError,match='Budget exhausted'):planner.run([reply('split')])
    assert len(planner.calls)==1 and not planner.saved


def test_valid_plan_needs_no_second_provider_call(planner):
    planner.run([reply()])
    assert len(planner.calls)==1 and len(planner.saved)==1


def test_truncated_repair_never_saves_a_partial_plan(planner):
    with pytest.raises(RuntimeError,match='corrected plan was cut short'):
        planner.run([reply('split'),{'stop_reason':'max_tokens','content':[]}])
    assert len(planner.calls)==2 and not planner.saved
