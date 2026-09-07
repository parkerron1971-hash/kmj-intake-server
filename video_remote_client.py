"""API-side dispatch to a renderer that has no tenant/provider credentials."""
import concurrent.futures
import os
from pathlib import Path
import time
import zipfile
import httpx

def render(job,folder,report):
    root=os.environ['VIDEO_RENDER_URL'].rstrip('/')
    headers={'Authorization':'Bearer '+os.environ['VIDEO_RENDER_TOKEN']}
    url=root+'/jobs/'+job['lease_id']
    bundle=folder/'bundle.zip'
    with zipfile.ZipFile(bundle,'w',compression=zipfile.ZIP_STORED) as z:
        for name in ('index.html','hyperframes.json'):z.write(folder/name,name)
        for p in (folder/'assets').iterdir():z.write(p,'assets/'+p.name)
    def request():
        with httpx.Client(timeout=httpx.Timeout(1320,connect=20),follow_redirects=False) as client,bundle.open('rb') as stream:
            with client.stream('POST',url,headers=headers,files={'file':('bundle.zip',stream,'application/zip')}) as response:
                if response.status_code>=400:
                    response.read()
                    try:message=response.json().get('detail')
                    except Exception:message=None
                    raise RuntimeError(message if isinstance(message,str) else 'The cloud renderer could not finish. Try again.')
                size=0
                with (folder/'video.mp4').open('wb') as out:
                    for chunk in response.iter_bytes(1024*1024):
                        size+=len(chunk)
                        if size>512*1024*1024:raise RuntimeError('The rendered video exceeded its file limit.')
                        out.write(chunk)
    pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future=pool.submit(request)
    try:
        while not future.done():
            state={}
            try:
                response=httpx.get(url,headers=headers,timeout=10)
                if response.status_code==200:state=response.json()
            except httpx.HTTPError:pass
            report(job,state.get('stage','rendering'),state.get('progress'))
            try:future.result(timeout=5)
            except concurrent.futures.TimeoutError:continue
        future.result()
    finally:
        if not future.done():
            try:httpx.delete(url,headers=headers,timeout=10)
            except httpx.HTTPError:pass
        pool.shutdown(wait=True,cancel_futures=True)
        bundle.unlink(missing_ok=True)
