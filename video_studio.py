"""Video Studio application service. All public operations require a manager seat.

Private rows follow media_library's server-only storage boundary. Worker calls
are explicitly separate from request handlers and recheck the creator's seat.
"""
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from uuid import UUID,uuid4
import httpx
from fastapi import HTTPException
import sb_clients
import storage_links
import media_library as media
from video_studio_models import Composition, validate_assets

BUCKET='video-studio'
MAX_UPLOAD=100*1024*1024
MIMES={'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp','video/mp4':'.mp4',
       'video/webm':'.webm','video/quicktime':'.mov','audio/mpeg':'.mp3','audio/wav':'.wav','audio/x-wav':'.wav'}
JOB_FIELDS='id,project_id,kind,revision_id,expected_revision,status,stage,progress,attempt,error,duration_seconds,created_at,finished_at'

def key(x): return str(UUID(str(x)))
def rows(path): return media.read(path)
def one(x): return media.one(x)
def rpc(name,data):
    result=one(sb_clients.sb_post_as_service('/rpc/'+name,data))
    if result.get('conflict'): raise HTTPException(409,'Your project changed. Refresh before continuing.')
    if result.get('refused'): raise HTTPException(409,result['refused'])
    return result
def access(b,user):
    from business_access import assert_access
    return assert_access(key(b),user,'manager')
def project(b,p,user):
    access(b,user)
    found=rows(f'/video_projects?id=eq.{key(p)}&business_id=eq.{key(b)}&select=*&limit=1')
    if not found: raise HTTPException(404,'Video project not found.')
    return found[0]
def assets(b,p): return rows(f'/video_assets?business_id=eq.{key(b)}&project_id=eq.{key(p)}&select=*&order=created_at')
def public_asset(a): return {k:v for k,v in a.items() if k not in ('object_path','created_by')}
def public_revision(r):
    return {k:v for k,v in r.items() if k!='assets'}|{'composition_hash':Composition.model_validate(r['composition']).digest()}
def configuration():
    return {'planning_available':os.getenv('VIDEO_STUDIO_ENABLED')=='on',
        'rendering_available':os.getenv('VIDEO_RENDER_ENABLED')=='on',
        'narration_available':bool(os.getenv('OPENAI_API_KEY')), 'max_upload_bytes':MAX_UPLOAD,
        'max_seconds':180,'daily_render_seconds':1800,'render_price_label':'Included during early access',
        'planning_price_label':'Uses your existing AI allowance','renderer':'hyperframes'}
def listing(b,user):
    access(b,user)
    return {'projects':rows(f'/video_projects?business_id=eq.{key(b)}&select=*&order=updated_at.desc&limit=100'),'configuration':configuration()}
def detail(b,p,user):
    saved=project(b,p,user)
    return {'project':saved,'assets':[public_asset(a) for a in assets(b,p)],
        'revisions':[public_revision(r) for r in rows(f'/video_revisions?business_id=eq.{key(b)}&project_id=eq.{key(p)}&select=*&order=revision.desc&limit=100')],
        'messages':rows(f'/video_messages?business_id=eq.{key(b)}&project_id=eq.{key(p)}&select=*&order=created_at.desc&limit=200')[::-1],
        'jobs':rows(f'/video_jobs?business_id=eq.{key(b)}&project_id=eq.{key(p)}&select={JOB_FIELDS}&order=created_at.desc&limit=50'),
        'configuration':configuration()}
def create(b,body,user):
    access(b,user)
    return one(sb_clients.sb_post_as_service('/video_projects',body.model_dump()|{'business_id':key(b),'created_by':str(user.id)}))
def no_active(b,p):
    if rows(f'/video_jobs?business_id=eq.{key(b)}&project_id=eq.{key(p)}&status=in.(queued,working)&select=id&limit=1'):
        raise HTTPException(409,'Wait for Chief to finish or cancel this job before changing the project.')
def check_composition(b,p,composition):
    try: validate_assets(composition,assets(b,p))
    except ValueError as e: raise HTTPException(422,str(e)) from e
    if composition.voice!='none' and not configuration()['narration_available']:
        raise HTTPException(409,'Narration is not configured. Choose No voice or ask your administrator to enable it.')
def save(b,p,body,user):
    project(b,p,user);no_active(b,p);check_composition(b,p,body.composition)
    return public_revision(rpc('save_video_revision',{'p_business_id':key(b),'p_project_id':key(p),'p_actor_id':str(user.id),
      'p_expected':body.expected_revision,'p_composition':body.composition.model_dump(mode='json'),'p_label':body.label}))
def enqueue(b,p,body,user,kind):
    saved=project(b,p,user)
    if not configuration()['planning_available' if kind=='plan' else 'rendering_available']:
        raise HTTPException(503,'Video '+('planning' if kind=='plan' else 'rendering')+' is not available yet.')
    import spend_guard,usage_metering
    if spend_guard.over_budget(key(b)): raise HTTPException(429,spend_guard.block_message())
    if kind=='plan' and not usage_metering.can_interact(key(b)):raise HTTPException(429,'Your AI allowance is used up. Add credits to continue with Chief.')
    revision=None
    if kind=='render':
        found=rows(f'/video_revisions?business_id=eq.{key(b)}&project_id=eq.{key(p)}&id=eq.{body.revision_id}&select=*&limit=1')
        if not found or found[0]['revision']!=saved['revision']: raise HTTPException(409,'Choose the current saved revision.')
        composition=Composition.model_validate(found[0]['composition'])
        if composition.digest()!=body.composition_hash: raise HTTPException(409,'Review the current scene plan before rendering.')
        check_composition(b,p,composition);revision=str(body.revision_id)
    result=rpc('enqueue_video_job',{'p_business_id':key(b),'p_project_id':key(p),'p_actor_id':str(user.id),'p_kind':kind,
      'p_revision_id':revision,'p_expected':body.expected_revision,'p_request_id':str(body.request_id),'p_request':body.model_dump(mode='json')})
    return {k:result.get(k) for k in JOB_FIELDS.split(',')}
def cancel(b,p,j,user):
    project(b,p,user)
    result=sb_clients.sb_patch_as_service(f'/video_jobs?id=eq.{key(j)}&business_id=eq.{key(b)}&project_id=eq.{key(p)}&status=in.(queued,working)',
      {'status':'cancelled','stage':'cancelled'})
    return {'cancelled':bool(result)}
def signed(b,p,item,user,asset=False,download=False):
    project(b,p,user)
    table='video_assets' if asset else 'video_jobs'
    found=rows(f'/{table}?id=eq.{key(item)}&business_id=eq.{key(b)}&project_id=eq.{key(p)}&select=*&limit=1')
    if not found: raise HTTPException(404,'Video file not found.')
    row=found[0]
    if not asset and (row['status']!='completed' or not row.get('output_path')): raise HTTPException(409,'This render is not finished.')
    path=row['object_path'] if asset else row['output_path']
    url=storage_links.signed_url_sync(BUCKET,path,ttl=900,download_as='video.mp4' if download and not asset else None)
    if not url: raise HTTPException(503,'The private playback link is unavailable.')
    return {'url':url,'expires_in':900}
def put_file(path,target,mime):
    with httpx.Client(timeout=120,follow_redirects=False) as client,Path(path).open('rb') as stream:
        response=client.post(os.environ['SUPABASE_URL'].rstrip('/')+'/storage/v1/object/'+BUCKET+'/'+target,
            headers={**storage_links.service_headers(),'Content-Type':mime,'Content-Length':str(Path(path).stat().st_size),'x-upsert':'false'},
            content=media.upload_chunks(stream))
        if response.status_code>=400: raise RuntimeError('The private video file could not be stored.')
def remove_objects(paths):
    if not paths:return
    response=httpx.request('DELETE',os.environ['SUPABASE_URL'].rstrip('/')+'/storage/v1/object/'+BUCKET,
        headers=storage_links.service_headers(),json={'prefixes':paths},timeout=60)
    response.raise_for_status()
def store_upload(b,p,user,path,name,mime,purpose):
    project(b,p,user);no_active(b,p)
    if mime not in MIMES: raise HTTPException(422,'Use PNG, JPG, WebP, MP4, MOV, WebM, MP3 or WAV.')
    if not 0<Path(path).stat().st_size<=MAX_UPLOAD: raise HTTPException(413,'Files can be up to 100 MB.')
    # Decode the actual file; neither its extension nor the browser MIME is trusted.
    duration=None
    if mime.startswith('image/'):
        from PIL import Image
        try:
            with Image.open(path) as im:
                if im.format not in ('PNG','JPEG','WEBP') or im.width*im.height>30000000: raise ValueError()
                im.verify()
        except Exception as e: raise HTTPException(422,'This image could not be read safely.') from e
    else:
        try:
            info=json.loads(subprocess.check_output(['ffprobe','-v','error','-protocol_whitelist','file,pipe','-show_streams','-show_format','-of','json',str(path)],timeout=20))
            formats=set(info['format'].get('format_name','').split(','))
            if not formats & {'mov','mp4','matroska','webm','mp3','wav'}:raise ValueError()
            duration=float(info['format']['duration'])
            if not 0<duration<=7200: raise ValueError()
            expected='video' if mime.startswith('video/') else 'audio'
            if not any(x['codec_type']==expected for x in info['streams']): raise ValueError()
            if any(x.get('width',0)*x.get('height',0)>3840*2160 for x in info['streams']): raise ValueError()
        except Exception as e: raise HTTPException(422,'Choose a readable recording up to two hours and 4K.') from e
    existing=assets(b,p)
    if len(existing)>=12 or sum(a['byte_size'] for a in existing)+Path(path).stat().st_size>300*1024*1024:
        raise HTTPException(409,'Use up to 12 files and 300 MB in one project.')
    aid=str(uuid4());target=f'{key(b)}/{key(p)}-{aid}{MIMES[mime]}'
    with Path(path).open('rb') as stream: sha=hashlib.file_digest(stream,'sha256').hexdigest()
    put_file(path,target,mime)
    try:
        result=one(sb_clients.sb_post_as_service('/video_assets',{'id':aid,'business_id':key(b),'project_id':key(p),'created_by':str(user.id),
            'name':name[:160],'mime_type':mime,'purpose':purpose,'byte_size':Path(path).stat().st_size,'sha256':sha,'duration_seconds':duration,'object_path':target}))
    except Exception:
        remove_objects([target]);raise
    return public_asset(result)
def set_purpose(b,p,a,body,user):
    project(b,p,user);no_active(b,p)
    return public_asset(one(sb_clients.sb_patch_as_service(f'/video_assets?id=eq.{key(a)}&business_id=eq.{key(b)}&project_id=eq.{key(p)}',body.model_dump())))
def delete_asset(b,p,a,user):
    project(b,p,user);no_active(b,p)
    found=rows(f'/video_assets?id=eq.{key(a)}&business_id=eq.{key(b)}&project_id=eq.{key(p)}&select=*&limit=1')
    if not found: raise HTTPException(404,'File not found.')
    sb_clients.sb_delete_as_service(f'/video_assets?id=eq.{key(a)}&business_id=eq.{key(b)}&project_id=eq.{key(p)}')
    remove_objects([found[0]['object_path']])
    return {'deleted':True}

def library(b,p,user):
    project(b,p,user)
    return {'assets':rows(f'/media_assets?business_id=eq.{key(b)}&status=eq.ready&select=id,name,kind,duration_seconds,byte_size&order=created_at.desc&limit=100')}

def import_library(b,p,source_id,user):
    project(b,p,user);no_active(b,p)
    source=media.asset(b,source_id,user)
    if source['status']!='ready':raise HTTPException(409,'Wait for this recording to finish processing.')
    if (source.get('byte_size') or 0)>MAX_UPLOAD:raise HTTPException(413,'Create a shorter clip in the media library first. Video Studio accepts files up to 100 MB.')
    url=storage_links.signed_url_sync(media.BUCKET,media.object_path(source),ttl=900)
    if not url:raise HTTPException(503,'The source recording is unavailable.')
    with tempfile.TemporaryDirectory(prefix='video-library-') as folder:
        target=Path(folder)/'source.mp4'
        with httpx.Client(timeout=120,follow_redirects=False) as client:
            media.transfer_to_file(client,url,{},target,MAX_UPLOAD)
        # A private copy makes future source-library edits independent of this project.
        return store_upload(b,p,user,target,source['name'],'video/mp4','reference')
