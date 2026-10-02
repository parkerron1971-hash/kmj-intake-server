"""Chief uses the same scoped Video Studio service as the direct editor."""
import asyncio
import json
from uuid import uuid4
from auth_supabase import AuthedUser
import video_studio as studio
from video_studio_models import CreateProject,Message,RenderRequest

PROMPT='''
VIDEO CREATION: You can start a saved Video Studio project and work on it conversationally.
Use [ACTION:{"type":"create_video","brief":"the user's request","title":"short title","format":"landscape"}]. This queues a planning job; it does not immediately finish a video. The result opens Video Studio where uploads, revisions, narration, rendering and downloads live.
Use [ACTION:{"type":"inspect_video","project_id":"UUID"}] to see saved scenes, real job status and the exact composition hash.
Use [ACTION:{"type":"revise_video","project_id":"UUID","message":"requested change","expected_revision":1}] for a saved project.
Only after the user explicitly asks to render their reviewed current plan, use [ACTION:{"type":"render_video","project_id":"UUID","revision_id":"UUID","expected_revision":1,"composition_hash":"hash from inspect_video","approved":true}]. A render creates a PRIVATE video, never a post. If the requested facts are missing, the video director asks in that project's conversation. Never claim a queued job is completed. Never claim a reference recording has been transcribed unless a transcript exists.
'''
def actor():
    import chief_of_staff as chief
    uid=chief._TURN_USER_ID.get()
    if not uid:raise ValueError('Open Chief in your signed-in business to create a video.')
    return AuthedUser(id=str(uid),email='',role='authenticated')
def result(kind,label,pid,**extra):
    return {'type':kind,'result':label,'label':label,'nav':{'tab':'grow','sub':'video-studio'},
        'frontend_event':{'name':'solutionist-video-project','detail':{'project_id':pid}},**extra}
async def handle_create_video(client,biz,action):
    try:
        user=actor();body=CreateProject(brief=action.get('brief') or action.get('_owner_text') or '',title=action.get('title') or 'New video',format=action.get('format') or 'landscape')
        row=await asyncio.to_thread(studio.create,biz['id'],body,user)
        job=await asyncio.to_thread(studio.enqueue,biz['id'],row['id'],Message(message=body.brief,expected_revision=0,request_id=uuid4()),user,'plan')
        return result('create_video','Your video project is saved. Chief is preparing the scene plan.',row['id'],job_id=job['id'],project_id=row['id'])
    except Exception as e:return {'type':'create_video','failed':True,'result':getattr(e,'detail',str(e))}
async def handle_inspect_video(client,biz,action):
    try:
        data=await asyncio.to_thread(studio.detail,biz['id'],action['project_id'],actor())
        data['revisions']=data['revisions'][:1];data['jobs']=data['jobs'][:2];data['messages']=data['messages'][-4:]
        return {'type':'inspect_video','result':json.dumps(data,default=str)}
    except Exception as e:return {'type':'inspect_video','failed':True,'result':getattr(e,'detail',str(e))}
async def handle_revise_video(client,biz,action):
    try:
        body=Message(message=action.get('message') or action.get('_owner_text') or '',expected_revision=action['expected_revision'],request_id=uuid4())
        job=await asyncio.to_thread(studio.enqueue,biz['id'],action['project_id'],body,actor(),'plan')
        return result('revise_video','Chief is working on your requested revision.',action['project_id'],job_id=job['id'])
    except Exception as e:return {'type':'revise_video','failed':True,'result':getattr(e,'detail',str(e))}
async def handle_render_video(client,biz,action):
    try:
        body=RenderRequest(**{k:action[k] for k in ['revision_id','expected_revision','composition_hash','approved']},request_id=uuid4())
        job=await asyncio.to_thread(studio.enqueue,biz['id'],action['project_id'],body,actor(),'render')
        return result('render_video','Your approved video is queued for rendering. I will show its real status in Video Studio.',action['project_id'],job_id=job['id'])
    except Exception as e:return {'type':'render_video','failed':True,'result':getattr(e,'detail',str(e))}
