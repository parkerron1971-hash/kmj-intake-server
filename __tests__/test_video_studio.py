import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
import video_studio as service
from video_studio_models import Composition,Scene,validate_assets,RenderRequest
import video_studio_worker as worker
from video_hyperframes import compile_project,RUNTIME

def composition(**kw):return Composition(title='Studio test',scenes=[Scene(id='opening',title='A clear idea',seconds=6)],**kw)
def test_untrusted_fields_and_timings_rejected():
    for patch in [{'html':'<script/>'},{'accent':'red;url(https://evil)'},{'voice':'../../secret'}]:
        with pytest.raises(ValidationError):composition(**patch)
    with pytest.raises(ValidationError):Scene(id='x',title='test',seconds=float('nan'))
    with pytest.raises(ValidationError):Composition(title='x',scenes=[Scene(id='same',title='x',seconds=4)]*2)
def test_reference_and_foreign_assets_cannot_render():
    asset=str(uuid4());spec=Composition(title='x',scenes=[Scene(id='x',title='x',seconds=6,layout='image',asset_id=asset)])
    for assets in [[],[{'id':asset,'purpose':'reference','mime_type':'image/png'}]]:
        with pytest.raises(ValueError):validate_assets(spec,assets)
    validate_assets(spec,[{'id':asset,'purpose':'include','mime_type':'image/png'}])
def test_trim_cannot_overrun_source():
    asset=str(uuid4());spec=Composition(title='x',scenes=[Scene(id='x',title='x',seconds=6,asset_id=asset,source_start=8)])
    with pytest.raises(ValueError):validate_assets(spec,[{'id':asset,'purpose':'include','mime_type':'video/mp4','duration_seconds':10}])
def test_project_lookup_is_tenant_scoped(monkeypatch):
    b,p=uuid4(),uuid4();paths=[]
    monkeypatch.setattr(service,'access',lambda *a:None)
    monkeypatch.setattr(service,'rows',lambda path:paths.append(path) or [])
    with pytest.raises(HTTPException) as err:service.project(b,p,SimpleNamespace(id=uuid4()))
    assert err.value.status_code==404
    assert f'business_id=eq.{b}' in paths[0] and f'id=eq.{p}' in paths[0]
def test_role_denial_happens_before_project_read(monkeypatch):
    def deny(*a):raise HTTPException(403,'denied')
    monkeypatch.setattr(service,'access',deny)
    monkeypatch.setattr(service,'rows',lambda *a:pytest.fail('unauthorized read'))
    with pytest.raises(HTTPException):service.detail(uuid4(),uuid4(),SimpleNamespace(id=uuid4()))
def test_render_approval_hash_is_required():
    with pytest.raises(ValidationError):RenderRequest(revision_id=uuid4(),expected_revision=1,request_id=uuid4(),composition_hash='a'*64,approved=False)
    spec=composition();edited=spec.model_copy(deep=True);edited.scenes[0].title='Different text'
    assert spec.digest()!=edited.digest()
def test_cancelled_lease_cannot_continue(monkeypatch):
    monkeypatch.setattr(service,'access',lambda *a:None)
    monkeypatch.setattr(worker.sb_clients,'sb_patch_as_service',lambda *a:[])
    job={'id':str(uuid4()),'lease_id':str(uuid4()),'business_id':str(uuid4()),'created_by':str(uuid4())}
    with pytest.raises(worker.Cancelled):worker.progress(job,'rendering',12)
def test_renderer_does_not_inherit_credentials(monkeypatch):
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY','private');monkeypatch.setenv('ANTHROPIC_API_KEY','private')
    monkeypatch.setenv('NODE_OPTIONS','--require /evil.js');monkeypatch.setenv('AWS_SECRET_ACCESS_KEY','private')
    env=worker.child_env()
    assert not {'SUPABASE_SERVICE_ROLE_KEY','ANTHROPIC_API_KEY','NODE_OPTIONS','AWS_SECRET_ACCESS_KEY'} & env.keys()
def test_compiler_treats_text_as_text(tmp_path):
    spec=Composition(title='Literal <title>',scenes=[Scene(id='intro',title='</h1><script>alert(1)</script>',subtitle='<img src=x onerror=alert(1)>',seconds=6)])
    compile_project(spec,tmp_path,{},{});html=(tmp_path/'index.html').read_text()
    assert '<script>alert(1)' not in html and '&lt;script&gt;' in html
    assert 'window.__timelines.main=tl' in html and 'paused:true' in html
def test_asset_signed_link_cannot_read_another_project(monkeypatch):
    monkeypatch.setattr(service,'project',lambda *a:{})
    seen=[];monkeypatch.setattr(service,'rows',lambda p:seen.append(p) or [])
    b,p,a=uuid4(),uuid4(),uuid4()
    with pytest.raises(HTTPException):service.signed(b,p,a,SimpleNamespace(id=uuid4()),asset=True)
    assert f'business_id=eq.{b}' in seen[0] and f'project_id=eq.{p}' in seen[0]

def test_renderer_bundle_rejects_traversal(tmp_path):
    import zipfile
    from video_cloud_renderer import extract_bundle
    archive=tmp_path/'bundle.zip'
    for name in ('../escape.txt','/absolute.txt','assets/../../escape.txt','assets\\escape.txt','secrets.env'):
        with zipfile.ZipFile(archive,'w') as z:z.writestr(name,'untrusted')
        with pytest.raises(ValueError):extract_bundle(archive,tmp_path/'render')

def test_renderer_token_and_clean_environment(monkeypatch):
    import video_cloud_renderer as cloud
    monkeypatch.setenv('VIDEO_RENDER_TOKEN','x'*48)
    with pytest.raises(HTTPException):cloud.authorized('Bearer wrong')
    cloud.authorized('Bearer '+'x'*48)
    assert 'VIDEO_RENDER_TOKEN' not in cloud.clean_env()

def test_library_import_checks_source_tenant_before_downloading(monkeypatch):
    monkeypatch.setattr(service,'project',lambda *a:{})
    monkeypatch.setattr(service,'no_active',lambda *a:None)
    def denied(*a):raise HTTPException(404,'Source not found')
    monkeypatch.setattr(service.media,'asset',denied)
    monkeypatch.setattr(service.storage_links,'signed_url_sync',lambda *a,**k:pytest.fail('foreign source signed'))
    with pytest.raises(HTTPException):service.import_library(uuid4(),uuid4(),uuid4(),SimpleNamespace(id=uuid4()))

def test_chief_reply_accepts_prose_and_fences_without_weakening_schema():
    import json
    data={'message':'I made a two-scene story.','composition':composition().model_dump(mode='json')}
    for reply in (json.dumps(data),'A warm opening.\n```json\n'+json.dumps(data)+'\n```'):
        result=worker.parse_plan_reply(reply,[])
        assert result.composition.title==data['composition']['title']
    with pytest.raises(RuntimeError):worker.parse_plan_reply('I have no scene plan yet.',[])
    data['composition']['html']='<script>evil()</script>'
    with pytest.raises(ValidationError):worker.parse_plan_reply(json.dumps(data),[])

def test_chief_reply_still_excludes_reference_assets():
    import json
    asset=str(uuid4());spec=composition().model_dump(mode='json');spec['scenes'][0]['asset_id']=asset
    with pytest.raises(ValueError):worker.parse_plan_reply('Here is the plan: '+json.dumps({'message':'Ready','composition':spec}),[{'id':asset,'purpose':'reference','mime_type':'image/png'}])

def test_source_video_has_one_absolute_timing_owner(tmp_path):
    import re
    aid=str(uuid4())
    spec=Composition(title='Video timing',scenes=[Scene(id='intro',title='Intro',seconds=5),Scene(id='footage',title='Footage',layout='split',seconds=6,asset_id=aid,source_start=10)])
    compile_project(spec,tmp_path,{aid:{'path':'assets/source.mp4','mime_type':'video/mp4'}},{})
    html=(tmp_path/'index.html').read_text()
    assert all('data-start' not in tag for tag in re.findall(r'<section[^>]+>',html))
    assert 'id="video-1" class="clip" data-start="5.0" data-duration="6.0" data-media-start="10.0"' in html
    assert "tl.fromTo('#scene-1',{opacity:0},{opacity:1,duration:0.6,ease:'power2.inOut'},5.0)" in html


def test_captions_follow_spoken_phrases_and_scenes_grow_to_fit(tmp_path):
    from video_narration import split_phrases,time_phrases,fit_scenes
    from video_audio import duck_expression
    text='Welcome to the shop. We cut hair, trim beards and talk football, every single day of the week.'
    phrases=split_phrases(text)
    assert [p[0] for p in phrases][:2]==['Welcome to the shop.','We cut hair,'] and all(p[2]-p[1]<=7 for p in phrases)
    words=[{'word':w,'start':i*.4,'end':i*.4+.35} for i,w in enumerate(text.split())]
    timed=time_phrases(text,words,10)
    assert timed[0][1]==0 and timed[1][1]>=timed[0][2] and timed[-1][2]<=10
    spec=Composition(title='Fit',voice='nova',scenes=[Scene(id='a',title='A',seconds=4,narration=text),Scene(id='b',title='B',seconds=5)])
    grown=fit_scenes(spec,{'a':{'path':'assets/voice-0.wav','duration':6.2}})
    assert grown.scenes[0].seconds==7.5 and grown.scenes[1].seconds==5 and spec.scenes[0].seconds==4
    with pytest.raises(RuntimeError):fit_scenes(spec,{'a':{'path':'x','duration':31}})
    expression=duck_expression([(2,5)])
    assert expression.startswith('0.24*') and 'clip((abs(t-3.50)-1.50)/0.45,0,1)' in expression
    compile_project(grown,tmp_path,{},{'a':{'path':'assets/voice-0.wav','duration':6.2,'phrases':timed}})
    html=(tmp_path/'index.html').read_text()
    assert 'id="caption-0-0" class="clip caption" data-layout-allow-occlusion data-layout-allow-overflow data-start="0.25"' in html and '<img class="backdrop"' not in html
    assert 'class="progress"' in html and "tl.fromTo('#scene-0 .line-in'" in html

def test_contained_photo_gets_a_blurred_fill_not_a_black_box(tmp_path):
    aid=str(uuid4())
    spec=Composition(title='Photo',scenes=[Scene(id='p',title='P',layout='split',seconds=5,asset_id=aid,fit='contain'),Scene(id='q',title='Q',layout='split',seconds=5,asset_id=aid,fit='cover')])
    compile_project(spec,tmp_path,{aid:{'path':'assets/photo.png','mime_type':'image/png'}},{})
    html=(tmp_path/'index.html').read_text()
    assert html.count('<img class="backdrop" src="assets/photo.png"')==1
    assert 'id="image-0" class="clip" data-start="0" data-duration="5.6"' in html and 'id="image-1" class="clip" data-start="5.0" data-duration="5.0"' in html


def test_logo_callouts_and_demo_layouts_compile_from_data(tmp_path):
    from video_studio_models import Demo,DemoTile,Callout
    shot=str(uuid4());mark=str(uuid4())
    spec=Composition(title='Demo',scenes=[
        Scene(id='open',layout='logo',title='Brand',subtitle='Tagline',seconds=4,asset_id=mark),
        Scene(id='shot',layout='split',title='Home',seconds=6,asset_id=shot,fit='contain',callouts=[Callout(label='Clients <b>',x=20,y=20,at=1),Callout(label='Revenue',x=70,y=20,at=2)]),
        Scene(id='chat',layout='demo',title='Say it',seconds=8,demo=Demo(kind='chat',app_name='KMJ',prompt='Invoice <Hartwell>',reply='Done.',card_title='Balance',card_value='$2,400')),
        Scene(id='dash',layout='demo',title='Run it',seconds=7,demo=Demo(kind='dashboard',greeting='Morning',tiles=[DemoTile(label='Clients',value='86'),DemoTile(label='Revenue',value='$12,480')],actions=['Draft email']))])
    compile_project(spec,tmp_path,{shot:{'path':'assets/shot.png','mime_type':'image/png'},mark:{'path':'assets/mark.png','mime_type':'image/png'}},{})
    html=(tmp_path/'index.html').read_text()
    assert 'class="scene logo"' in html and '<div class="glow" data-layout-allow-occlusion></div>' in html
    assert 'class="media device"' in html and html.count('class="callout')==2 and 'Clients &lt;b&gt;' in html and 'callout flip' in html
    assert '<span class="ch">I</span>' in html and '<Hartwell>' not in html and '<span class="ch">&lt;</span>' in html
    assert "toLocaleString('en-US')+''" in html and "'$'+Math.round" in html
    with pytest.raises(ValueError):Scene(id='x',layout='demo',title='No demo',seconds=8)
    with pytest.raises(ValueError):Demo(kind='chat',prompt='only a prompt')
    with pytest.raises(ValueError):Scene(id='x',layout='title',title='No picture',seconds=5,callouts=[Callout(label='a',x=10,y=10)])


def test_closing_pill_hides_when_chief_leaves_the_subtitle_blank(tmp_path):
    spec=Composition(title='Close',scenes=[Scene(id='end',layout='closing',title='Start free',seconds=5)])
    compile_project(spec,tmp_path,{},{})
    html=(tmp_path/'index.html').read_text()
    assert '.closing .subtitle:empty{display:none}' in html and '<div class="subtitle"></div>' in html
