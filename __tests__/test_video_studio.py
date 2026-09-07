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
