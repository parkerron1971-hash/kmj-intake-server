import asyncio
import copy
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException, FastAPI
from fastapi.testclient import TestClient
from PIL import Image

import creative_director as d
import image_studio as images
from creative_director_models import Plan, Review


def run(coro): return asyncio.run(coro)


def png(color=(12, 20, 36, 255), size=(1024, 1536)):
    out = io.BytesIO(); Image.new('RGBA', size, color).save(out, 'PNG'); return out.getvalue()


def plan(**kw):
    return Plan(concept='Dimensional editorial typography', reference_analysis='Oversized dimensional headline with grain',
        typography='Bold condensed headline', composition='Headline upper third, price lower third', palette='Navy violet cyan',
        materials_light='Paper grain and soft directional light', **kw)


def spec(refs=None):
    return dict(version=1, goal='Create a founding flyer', copy=['Founding seats', '$99 / month', 'mysolutionist.app'],
        references=refs or [], owner_request='Use the style reference', owner_context='', facts={}, preferences={},
        max_renders=2, phase='queued', attempts=0, review=None)


def row(s=None):
    return dict(id=str(uuid4()), business_id=str(uuid4()), director=s or spec(), model=images.MODELS[0], quality='high', size='1024x1536')


def test_plan_rejects_foreign_missing_clipped_and_overlapping_assets():
    a, b = str(uuid4()), str(uuid4())
    s = spec([{'id': a, 'role': 'logo'}, {'id': b, 'role': 'product'}])
    placements = [dict(image_id=a,x=.1,y=.1,width=.2,height=.2),dict(image_id=b,x=.5,y=.5,width=.4,height=.4)]
    d.validate_plan(plan(placements=placements), s)
    for wrong in [[], placements[:1], [*placements, placements[0]],
                  [dict(placements[0], image_id=str(uuid4())), placements[1]],
                  [placements[0], dict(placements[1], x=.9)],
                  [placements[0], dict(placements[1], x=.1, y=.1)]]:
        with pytest.raises(HTTPException): d.validate_plan(plan(placements=wrong), s)


def test_price_substring_is_not_a_pass_and_flags_have_issues():
    review = Review(observed_text='Founding seats $199 / month mysolutionist.app', reference_match=True,
        readable=True, composition_coherent=True, brand_assets_clean=True)
    assert not d.review_verdict(review, spec())['passed']
    assert d.review_verdict(review.model_copy(update={'observed_text':'Founding seats\n$99 / month\nmysolutionist.app'}), spec())['passed']
    result = d.review_verdict(review.model_copy(update={'readable':False}), spec())
    assert result['issues']


@pytest.fixture
def pipeline(monkeypatch):
    s = SimpleNamespace(writes=[], renders=[], reviews=[], saved={}, fail_render=None, fail_review=False, fail_store=False)
    async def db(client, method, path, body=None, **kw):
        s.writes.append(copy.deepcopy(body)); return [body]
    async def render(client, record, prompt, refs):
        s.renders.append(refs)
        if s.fail_render == len(s.renders): raise httpx.ReadTimeout('uncertain')
        return png(), {'output_tokens':10}, .05
    async def review(*args):
        if s.fail_review: raise RuntimeError('review unavailable')
        return s.reviews.pop(0) if s.reviews else dict(passed=False, issues=['Title clipped'], repair_instruction='Fit the title')
    async def store(client, path, raw, mime):
        if s.fail_store and path.endswith(('-2.png', '-2-art.png')): raise HTTPException(502, 'storage unavailable')
        s.saved[path] = raw
    monkeypatch.setattr(images, 'db', db); monkeypatch.setattr(images, 'store', store)
    monkeypatch.setattr(d, 'references', AsyncMock(return_value={}))
    monkeypatch.setattr(d, 'make_plan', AsyncMock(return_value=plan()))
    monkeypatch.setattr(d, 'render', render); monkeypatch.setattr(d, 'review', review)
    return s


def test_pipeline_has_two_render_ceiling_and_preserves_review_findings(pipeline):
    run(d.run(None, row()))
    assert len(pipeline.renders) == 2
    assert pipeline.writes[-1]['director']['phase'] == 'needs_review'
    assert pipeline.writes[-1]['director']['review']['issues'] == ['Title clipped']
    assert len(pipeline.saved) == 4


def test_pass_stops_after_one_render(pipeline):
    pipeline.reviews = [dict(passed=True, issues=[], repair_instruction='')]
    run(d.run(None, row()))
    assert len(pipeline.renders) == 1
    assert pipeline.writes[-1]['director']['phase'] == 'complete'


def test_uncertain_first_render_never_retries(pipeline):
    pipeline.fail_render = 1
    with pytest.raises(httpx.ReadTimeout): run(d.run(None, row()))
    assert len(pipeline.renders) == 1 and not pipeline.saved


@pytest.mark.parametrize('failure', ['render', 'store'])
def test_failed_repair_keeps_first_saved_draft(pipeline, failure):
    pipeline.fail_render = 2 if failure == 'render' else None
    pipeline.fail_store = failure == 'store'
    run(d.run(None, row()))
    paths = [v['storage_path'] for v in pipeline.writes if 'storage_path' in v]
    assert len(paths) == 1 and paths[0].endswith('-1.png')
    assert pipeline.writes[-1]['director']['warning']


def test_review_outage_does_not_trigger_paid_retry(pipeline):
    pipeline.fail_review = True
    run(d.run(None, row()))
    assert len(pipeline.renders) == 1
    assert pipeline.writes[-1]['director']['review'] is None


def test_logo_is_composited_with_original_alpha():
    logo = str(uuid4()); original = Image.new('RGBA', (200,200), (0,0,0,0))
    original.paste((135, 67, 200, 255), (50,50,150,150)); out=io.BytesIO();original.save(out,'PNG')
    p = plan(placements=[dict(image_id=logo,x=0,y=0,width=200/1024,height=200/1536)])
    rendered, svg = run(d.compose(png(), p, {logo:out.getvalue()}, '1024x1536'))
    with Image.open(io.BytesIO(rendered)) as im:
        assert im.convert('RGB').getpixel((0,0)) == (12,20,36)
        assert im.convert('RGB').getpixel((100,100)) == (135,67,200)
    assert svg.count('<image ') == 2


def test_protected_assets_never_sent_to_image_generator(pipeline, monkeypatch):
    ids=[str(uuid4()) for _ in range(3)]
    refs=[dict(id=i,role=role,use='Reference') for i,role in zip(ids,['logo','product','style'])]
    loaded={ids[0]:b'original-logo',ids[1]:b'original-ui',ids[2]:png()}
    monkeypatch.setattr(d,'references',AsyncMock(return_value=loaded))
    pipeline.reviews=[dict(passed=True,issues=[],repair_instruction='')]
    run(d.run(None,row(spec(refs))))
    assert pipeline.renders == [[loaded[ids[2]]]]


def test_bind_director_same_request_replays_but_different_copy_conflicts(monkeypatch):
    s=spec(); r=row(s); r['director']['request_hash']=d.request_hash(s)
    original=copy.deepcopy(s); original.pop('request_hash')
    assert run(images.bind_director(None,r,original)) == r
    with pytest.raises(HTTPException) as e: run(images.bind_director(None,r,{**original,'copy':['changed']}))
    assert e.value.status_code == 409


def test_public_status_does_not_expose_owner_context_or_reference_ids():
    s=spec();s.update(owner_context='private context',plan=plan().model_dump(),request_hash='secret')
    result=d.public_state(s)
    assert 'private context' not in str(result) and 'request_hash' not in result and 'plan' not in result


def test_remember_requires_owner():
    app=FastAPI();app.include_router(d.router)
    assert TestClient(app).post(f'/platform/chief/director/{uuid4()}/remember').status_code in (401,403)


def test_foreign_reference_rejected_before_saving_attachments(monkeypatch):
    import platform_chief_creative as creative
    import chief_flyer_direction as direction
    from platform_chief_marketing import ChiefMessageBody
    biz={'id':str(uuid4()),'owner_id':str(uuid4())}
    monkeypatch.setattr(creative,'platform_business',AsyncMock(return_value=biz))
    monkeypatch.setattr(images,'business',AsyncMock(return_value=biz))
    monkeypatch.setattr(d,'profile',AsyncMock(return_value={}))
    monkeypatch.setattr(images,'artwork',AsyncMock(side_effect=HTTPException(404,'Foreign reference')))
    upload=AsyncMock();monkeypatch.setattr(direction,'save_chat_reference',upload)
    action={'type':'design_flyer','goal':'Create a poster','exact_copy':['A useful headline'],
        'reference_inputs':[{'source':'artwork:'+str(uuid4()),'role':'style','use':'Type treatment'}]}
    with pytest.raises(HTTPException) as exc: run(d.prepare(action,ChiefMessageBody(message='Create it'),SimpleNamespace(id=biz['owner_id'])))
    assert exc.value.status_code==404
    upload.assert_not_called()


def test_worker_marks_ready_only_after_director_finishes(monkeypatch):
    r=row();r.update(reference_ids=[],status='queued')
    events=[]
    async def db(client,method,path,body=None,**kwargs):
        events.append(body.get('status'));return [{**r,**body}]
    async def execute(client,record): events.append('review-finished')
    monkeypatch.setattr(images,'db',db);monkeypatch.setattr(d,'run',execute)
    run(images.generate_worker(r))
    assert events==['working','review-finished','ready']


def test_worker_duplicate_claim_does_not_render(monkeypatch):
    monkeypatch.setattr(images,'db',AsyncMock(return_value=[]))
    render=AsyncMock();monkeypatch.setattr(d,'run',render)
    run(images.generate_worker(row()))
    render.assert_not_called()


def test_planner_receives_actual_pixels_and_validates_before_render(monkeypatch):
    iid=str(uuid4());s=spec([dict(id=iid,role='style',use='Type and texture')]);r=row(s)
    calls=AsyncMock(return_value=plan());monkeypatch.setattr(d,'structured',calls)
    run(d.make_plan(None,r,s,{iid:png()}))
    blocks=calls.call_args.args[-1]
    assert any(x['type']=='image' for x in blocks)
    assert 'Current owner instructions' in calls.call_args.args[-2]


def test_remember_saves_only_style_and_checks_owned_asset(monkeypatch):
    import platform_chief_creative as creative
    biz={'id':str(uuid4()),'owner_id':str(uuid4())};s=spec();s['plan']=plan().model_dump(mode='json')
    record={**row(s),'status':'ready'}
    monkeypatch.setattr(creative,'platform_business',AsyncMock(return_value=biz))
    monkeypatch.setattr(images,'business',AsyncMock(return_value=biz))
    lookup=AsyncMock(return_value=record);monkeypatch.setattr(images,'artwork',lookup)
    calls=[]
    def respond(req):
        import json
        calls.append(json.loads(req.content));return httpx.Response(201,json=[{}])
    factory=httpx.AsyncClient
    monkeypatch.setattr(d.httpx,'AsyncClient',lambda **kw: factory(transport=httpx.MockTransport(respond),**kw))
    monkeypatch.setattr(d.sb_clients,'sb_url',lambda:'https://storage.test')
    monkeypatch.setattr(d.sb_clients,'sb_headers_service',lambda **kw:{})
    result=run(d.remember(uuid4(),SimpleNamespace(id=biz['owner_id'])))
    assert result['ok'] and calls[0]['owner_id']==biz['owner_id']
    assert 'copy' not in calls[0]['preferences'] and 'facts' not in calls[0]['preferences']
    assert lookup.call_args.args[1]==biz['id']


def test_native_creation_uses_director_contract():
    from chief_creative_execution import tool_specs
    names={x['name'] for x in tool_specs()}
    assert 'design_flyer' in names
    assert not names & {'generate_image','compose_flyer','publish','approve'}


def test_verbose_art_direction_is_bounded_without_changing_protected_fields():
    value=plan().model_dump(mode='json')
    value.update(typography='Use tightly stacked dimensional typography. '*100,
        materials_light='Use subtle grain with deliberate directional light. '*100,
        copy_concerns=['Confirm this unverified claim.'])
    original=copy.deepcopy(value)
    compact=d.compact_art_direction(value)
    result=Plan.model_validate(compact)
    assert len(result.typography)<=900 and len(result.materials_light)<=800
    assert compact['placements']==original['placements']
    assert compact['copy_concerns']==original['copy_concerns']
    assert value==original
    with pytest.raises(HTTPException): d.validate_plan(result,spec())


def test_platform_resolver_returns_verified_owner_for_subscription_context(monkeypatch):
    import platform_console as console
    owner=str(uuid4());biz={'id':str(uuid4()),'owner_id':owner};seen=[]
    def respond(req):
        seen.append(req); return httpx.Response(200,json=[biz])
    monkeypatch.setattr(console,'SUPABASE_URL','https://storage.test')
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await console._find_platform_business(client,{},owner)
    assert run(exercise())['owner_id']==owner
    assert seen[0].url.params['owner_id']=='eq.'+owner
    assert 'owner_id' in seen[0].url.params['select'].split(',')


def test_planner_and_image_render_each_meter_once(monkeypatch):
    import base64
    import api_usage_logger
    from creative_director_render import render
    r=row(); billed=[]
    monkeypatch.setattr(d,'guard',AsyncMock())
    monkeypatch.setattr(api_usage_logger,'log_api_usage_sync',lambda **kw:billed.append(kw))
    async def record(**kw): billed.append(kw)
    monkeypatch.setattr(images,'log_api_usage',record)
    monkeypatch.setenv('ANTHROPIC_API_KEY','fake-test-key')
    def respond(req):
        if '/images/' in str(req.url):
            return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(png()).decode()}],
                'usage':{'input_tokens':10,'output_tokens':20}})
        verbose={**plan().model_dump(mode='json'),'typography':'Dimensional type with restrained highlights. '*100}
        return httpx.Response(200,json={'model':'claude-sonnet-5','usage':{'input_tokens':10,'output_tokens':20},
            'content':[{'type':'tool_use','name':'return_result','input':verbose}]})
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            await d.structured(client,r,Plan,'Plan this design',[{'type':'text','text':'owner brief'}])
            await render(client,r,'approved art direction',[])
    run(exercise())
    assert len(billed)==2
    assert all(x['business_id']==r['business_id'] for x in billed)
    assert billed[0]['endpoint'] != billed[1]['endpoint']


@pytest.mark.parametrize('status,body,expected', [(400,{'statusCode':'413','message':'exceeds maximum allowed size'},413),
    (400,{'code':'EntityTooLarge'},413),(413,{},413),(415,{},415),(400,{'code':'InvalidMimeType'},415),
    (403,{'message':'secret details'},503),(500,{},503)])
def test_storage_errors_are_actionable_and_do_not_leak_provider_details(status,body,expected):
    from platform_marketing import storage_upload_error
    error=storage_upload_error(httpx.Response(status,json=body),60*1024*1024,'video/mp4')
    assert error.status_code==expected and 'secret details' not in error.detail
