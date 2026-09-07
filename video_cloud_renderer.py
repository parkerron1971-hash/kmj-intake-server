"""Isolated HyperFrames execution service. No database or AI credentials.

The API supplies one trusted composition and frozen assets. The shared token
authorizes rendering only; the process cannot read tenants or call AI providers.
"""
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path, PurePosixPath
import queue
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from uuid import UUID
import zipfile
from fastapi import FastAPI, File, UploadFile, Header, HTTPException, Depends
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
lock=threading.Lock();jobs={};log=logging.getLogger('renderer')
RUNTIME=Path(__file__).parent/'video_worker'

def authorized(authorization:str=Header(default='')):
    expected=os.getenv('VIDEO_RENDER_TOKEN','')
    if len(expected)<32 or not hmac.compare_digest(authorization,'Bearer '+expected):raise HTTPException(401,'Unauthorized')

def extract_bundle(archive:Path,folder:Path):
    with zipfile.ZipFile(archive) as z:
        files=z.infolist()
        if len(files)>80 or sum(f.file_size for f in files)>350*1024*1024:raise ValueError('Bundle too large')
        for item in files:
            p=PurePosixPath(item.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in item.filename or ':' in item.filename or (item.external_attr>>16)&0o170000==0o120000:
                raise ValueError('Invalid bundle path')
            if item.is_dir():continue
            if item.filename not in ('index.html','hyperframes.json') and not (len(p.parts)==2 and p.parts[0]=='assets'):
                raise ValueError('Invalid bundle file')
            target=folder.joinpath(*p.parts);target.parent.mkdir(exist_ok=True,parents=True)
            with z.open(item) as source,target.open('wb') as dest:shutil.copyfileobj(source,dest)
    if not (folder/'index.html').is_file():raise ValueError('Missing composition')

def clean_env():
    return {k:v for k,v in os.environ.items() if k in ('PATH','HOME','TMPDIR','TEMP','TMP','SYSTEMROOT','WINDIR','USERPROFILE','LOCALAPPDATA','HYPERFRAMES_BROWSER_PATH')}|{'HYPERFRAMES_NO_TELEMETRY':'1','HYPERFRAMES_SKIP_SKILLS':'1','NO_COLOR':'1','PRODUCER_ENABLE_STREAMING_ENCODE':'false'}

def child(state,args,folder,stage,limit):
    state.update(stage=stage,progress=None)
    proc=subprocess.Popen(args,cwd=folder,env=clean_env(),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',start_new_session=os.name!='nt')
    q=queue.Queue();tail=[];started=time.monotonic()
    def reader():
        for line in proc.stdout:q.put(line)
    threading.Thread(target=reader,daemon=True).start()
    try:
        while proc.poll() is None:
            while not q.empty():
                line=q.get();tail.append(line);tail=tail[-30:]
                m=re.search(r'(\d+)%',line)
                if m:state['progress']=min(99,int(m.group(1)))
            if state['cancel'].is_set():raise HTTPException(409,'Render cancelled')
            if time.monotonic()-started>limit:raise HTTPException(504,'Rendering exceeded its time limit')
            time.sleep(.5)
        if proc.returncode:
            log.error('HyperFrames %s failed: %s',stage,''.join(tail)[-6000:])
            raise HTTPException(422,'Video validation or rendering failed. Adjust the scene text or media and try again.')
    finally:
        if proc.poll() is None:
            if os.name=='nt':subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True)
            else:os.killpg(proc.pid,signal.SIGTERM)
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name!='nt':os.killpg(proc.pid,signal.SIGKILL)
                else:proc.kill()

@app.get('/health')
def health():return {'ok':True,'renderer':'hyperframes','version':'0.8.31'}

@app.get('/jobs/{job_id}',dependencies=[Depends(authorized)])
def status(job_id:UUID):
    state=jobs.get(str(job_id))
    if not state:raise HTTPException(404,'Job not running')
    return {k:state[k] for k in ('stage','progress')}

@app.delete('/jobs/{job_id}',dependencies=[Depends(authorized)])
def cancel(job_id:UUID):
    if state:=jobs.get(str(job_id)):state['cancel'].set()
    return {'cancelled':True}

@app.post('/jobs/{job_id}',dependencies=[Depends(authorized)])
def render(job_id:UUID,file:UploadFile=File(...)):
    if not lock.acquire(blocking=False):raise HTTPException(409,'Renderer busy')
    folder=Path(tempfile.mkdtemp(prefix='video-render-'));state={'stage':'validating','progress':None,'cancel':threading.Event()};jobs[str(job_id)]=state
    try:
        archive=folder/'bundle.zip';size=0
        with archive.open('wb') as out:
            while chunk:=file.file.read(1024*1024):
                size+=len(chunk)
                if size>350*1024*1024:raise HTTPException(413,'Bundle too large')
                out.write(chunk)
        try:extract_bundle(archive,folder)
        except (ValueError,zipfile.BadZipFile) as e:raise HTTPException(422,str(e)) from e
        archive.unlink()
        cli=str(RUNTIME/'node_modules/hyperframes/dist/cli.js')
        child(state,['node',cli,'check','--json'],folder,'validating',180)
        child(state,['node',cli,'render','--quality','high','--workers','1','--low-memory-mode','--experimental-fast-capture=false','--no-browser-gpu','--no-best-effort','--output','video.mp4'],folder,'rendering',1200)
        output=folder/'video.mp4'
        if not output.exists() or not 1000<output.stat().st_size<=512*1024*1024:raise HTTPException(422,'Invalid video output')
        return FileResponse(output,media_type='video/mp4',filename='video.mp4',background=BackgroundTask(shutil.rmtree,folder))
    except BaseException:
        shutil.rmtree(folder,ignore_errors=True);raise
    finally:
        jobs.pop(str(job_id),None);lock.release()

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='0.0.0.0',port=int(os.getenv('PORT','8080')),log_level='info')
