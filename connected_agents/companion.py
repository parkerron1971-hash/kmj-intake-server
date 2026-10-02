"""Small, foreground desktop pilot. Standard-library only; no local web listener.

Native provider credentials are never read. The separate Solutionist device
credential is DPAPI-protected on Windows and permission-restricted on POSIX.
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import getpass
import json
import os
from pathlib import Path
import socket
import subprocess
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .contracts import Provider, RehearsalError
from .runtime import auth_status, draft_invoice, executable, login_command, provider_env

SERVER = 'https://kmj-intake-server-production.up.railway.app'
SAFE_ERRORS = {'usage_limits','login_required','provider_failed','provider_unavailable','invalid_output',
               'incomplete_output','provider_timeout','provider_output_too_large'}


class ConnectionError(Exception):
    def __init__(self, code='connection_unavailable', fatal=False):
        self.code, self.fatal = code, fatal
        super().__init__(code)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_server(server: str, allow_local=False) -> str:
    parsed = urlparse(server)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise ValueError('Use the Solutionist server origin.')
    if server.rstrip('/') != SERVER and not (allow_local and parsed.scheme=='http'
        and parsed.hostname in {'127.0.0.1','localhost','::1'}):
        raise ValueError('Only the Solutionist server or an explicitly enabled local test server is supported.')
    return server.rstrip('/')


def api(server: str, path: str, body: dict, token: str | None = None) -> dict:
    headers = {'Content-Type':'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = Request(server+'/connected-ai'+path, json.dumps(body).encode(), headers=headers, method='POST')
    try:
        with build_opener(NoRedirect()).open(request, timeout=20) as response:
            data = response.read(1_000_001)
            if len(data)>1_000_000:
                raise ConnectionError()
            result = json.loads(data)
            if not isinstance(result, dict):
                raise ConnectionError()
            return result
    except HTTPError as exc:
        # Never print server responses or credentials. Auth/revocation stops the
        # native process; a lease conflict also stops work without resubmitting.
        raise ConnectionError('connection_stopped' if exc.code in (401,403,409) else 'connection_unavailable',
                              fatal=exc.code in (401,403,409)) from None
    except (URLError, OSError, ValueError):
        raise ConnectionError() from None


def _dpapi(data: bytes, protect: bool) -> bytes:
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_char))]
    buffer=ctypes.create_string_buffer(data)
    source=Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_char)))
    output=Blob()
    fn=ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    # CRYPTPROTECT_UI_FORBIDDEN; default scope binds ciphertext to this user.
    if not fn(ctypes.byref(source),None,None,None,None,1,ctypes.byref(output)):
        raise OSError('Could not protect the local connection credential.')
    try:
        return ctypes.string_at(output.data,output.size)
    finally:
        ctypes.windll.kernel32.LocalFree(output.data)


def save_connections(state: Path, connections: list[dict]) -> None:
    state.mkdir(parents=True,exist_ok=True,mode=0o700)
    target=state/'connections.dat'
    data=json.dumps(connections).encode()
    if os.name=='nt':
        data=_dpapi(data,True)
    else:
        state.chmod(0o700)
    temporary=state/'connections.tmp'
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(data)
    temporary.replace(target)
    if os.name!='nt':
        target.chmod(0o600)


def load_connections(state: Path) -> list[dict]:
    path=state/'connections.dat'
    if not path.exists():
        return []
    data=path.read_bytes()
    if os.name=='nt':
        data=_dpapi(data,False)
    result=json.loads(data)
    if not isinstance(result,list):
        raise ValueError('Invalid saved connection.')
    return result


def find_binary(provider: Provider) -> str:
    try:
        return executable(provider)
    except RehearsalError:
        # The official desktop installation does not always add Codex to PATH.
        if provider==Provider.CHATGPT and os.name=='nt':
            candidate=Path(os.getenv('LOCALAPPDATA',''))/'Programs/OpenAI/Codex/bin/codex.exe'
            return executable(provider,str(candidate))
        raise


async def run_one(connection: dict, state: Path, once=False) -> None:
    provider=Provider(connection['provider'])
    server=connection['server']
    token=connection['token']
    last_failure=None
    while True:
        try:
            binary=find_binary(provider)
            status=await auth_status(provider,state,binary)
            expected='chatgpt' if provider==Provider.CHATGPT else 'oauth_token'
            current='signed_in' if status['authenticated'] and status['auth_method']==expected else 'login_required'
            if last_failure in {'usage_limits','login_required'}:
                current=last_failure
            await asyncio.to_thread(api,server,'/heartbeat',{'state':current},token)
            if current!='signed_in':
                if once: return
                await asyncio.sleep(20)
                continue
            leased=await asyncio.to_thread(api,server,'/lease',{},token)
            job=leased.get('job')
            if not job:
                if once: return
                await asyncio.sleep(10)
                continue
            if job.get('provider')!=provider.value:
                raise ConnectionError('connection_stopped',True)
            print(f'{provider.value}: preparing a draft for review.',flush=True)
            task=asyncio.create_task(draft_invoice(provider,state,binary,job['facts']))
            try:
                while not task.done():
                    done,_=await asyncio.wait({task},timeout=15)
                    pulse=await asyncio.to_thread(api,server,'/heartbeat',
                        {'state':current,'job_id':job['id'],'lease':job['lease']},token)
                    if not pulse.get('active'):
                        raise ConnectionError('work_cancelled')
                draft=await task
                result=await asyncio.to_thread(api,server,f"/jobs/{job['id']}/complete",
                    {'lease':job['lease'],'subject':draft.subject,'body':draft.body},token)
                print('Draft is waiting for review in Solutionist.' if result.get('ok') else
                      'The invoice changed. No draft was submitted.',flush=True)
            except RehearsalError as exc:
                last_failure=str(exc) if str(exc) in SAFE_ERRORS else 'provider_failed'
                await asyncio.to_thread(api,server,f"/jobs/{job['id']}/fail",
                    {'lease':job['lease'],'error':last_failure},token)
                print(f'{provider.value}: {last_failure}. No message was sent.',flush=True)
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task,return_exceptions=True)
            if once: return
        except ConnectionError as exc:
            print(f'{provider.value}: {exc.code}.',flush=True)
            if exc.fatal or once: return
            await asyncio.sleep(20)
        except (RehearsalError,OSError):
            try:
                await asyncio.to_thread(api,server,'/heartbeat',{'state':'provider_unavailable'},token)
            except ConnectionError:
                pass
            print(f'{provider.value}: open the native provider app and sign in, then restart this connection.',flush=True)
            return


async def serve(connections: list[dict], state: Path, once=False):
    await asyncio.gather(*(run_one(connection,state,once) for connection in connections))


def main() -> int:
    parser=argparse.ArgumentParser(description='Solutionist desktop connection')
    parser.add_argument('--state-dir',type=Path,default=Path.home()/'.solutionist'/'connected-ai')
    parser.add_argument('--server',default=SERVER)
    parser.add_argument('--allow-local',action='store_true',help='Allow an explicit localhost test server')
    parser.add_argument('--pair',action='store_true')
    parser.add_argument('--once',action='store_true',help='Run one polling cycle')
    args=parser.parse_args()
    try:
        server=validate_server(args.server,args.allow_local)
        connections=load_connections(args.state_dir)
        connections=[c for c in connections if c.get('server')==server]
        print('Solutionist desktop connection\nKeep this window open while Chief prepares your work.\n')
        if args.pair or not connections or input('Add another account? [y/N] ').strip().lower()=='y':
            code=getpass.getpass('Paste the one-use pairing code from Solutionist: ').strip()
            result=api(server,'/claim',{'code':code,'label':socket.gethostname()[:80] or 'My desktop'})
            device=result['device']
            connection={'id':device['id'],'provider':device['provider'],'server':server,'token':result['device_token']}
            connections.append(connection)
            save_connections(args.state_dir,connections)
        for connection in connections:
            provider=Provider(connection['provider'])
            binary=find_binary(provider)
            status=asyncio.run(auth_status(provider,args.state_dir,binary))
            expected='chatgpt' if provider==Provider.CHATGPT else 'oauth_token'
            if not status['authenticated'] or status['auth_method']!=expected:
                print(f'Sign in directly with {provider.value}.')
                with TemporaryDirectory(prefix='solutionist-login-') as directory:
                    subprocess.call(login_command(provider,binary),cwd=directory,env=provider_env(provider,args.state_dir))
        asyncio.run(serve(connections,args.state_dir,args.once))
        return 0
    except KeyboardInterrupt:
        print('\nConnection stopped. Unfinished work will be interrupted.')
        return 130
    except (ConnectionError,RehearsalError,OSError,ValueError,KeyError):
        print('Could not start the connection. Check the code and native provider installation, then try again.')
        return 1


if __name__=='__main__':
    raise SystemExit(main())
