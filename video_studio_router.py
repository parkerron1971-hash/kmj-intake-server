from uuid import UUID
from typing import Literal
from pathlib import Path
import tempfile
from fastapi import APIRouter,Depends,UploadFile,File,Form,HTTPException
from auth_supabase import AuthedUser,require_user
from media_library_router import private_response
from business_access import assert_access
import video_studio as studio
from video_studio_models import CreateProject,Message,SaveRevision,RenderRequest,Purpose

router=APIRouter(prefix='/video-studio',tags=['video-studio'],dependencies=[Depends(private_response)])
@router.get('/{business_id}')
def listing(business_id:UUID,user:AuthedUser=Depends(require_user)):
    assert_access(str(business_id),user,'manager')
    return studio.listing(business_id,user)
@router.post('/{business_id}')
def create(business_id:UUID,body:CreateProject,user:AuthedUser=Depends(require_user)):
    assert_access(str(business_id),user,'manager')
    return {'project':studio.create(business_id,body,user)}
@router.get('/{business_id}/{project_id}')
def detail(business_id:UUID,project_id:UUID,user:AuthedUser=Depends(require_user)):
    assert_access(str(business_id),user,'manager')
    return studio.detail(business_id,project_id,user)
@router.post('/{business_id}/{project_id}/messages')
def message(business_id:UUID,project_id:UUID,body:Message,user:AuthedUser=Depends(require_user)):
    assert_access(str(business_id),user,'manager')
    return {'job':studio.enqueue(business_id,project_id,body,user,'plan')}
@router.post('/{business_id}/{project_id}/revisions')
def save(business_id:UUID,project_id:UUID,body:SaveRevision,user:AuthedUser=Depends(require_user)):
    assert_access(str(business_id),user,'manager')
    return {'revision':studio.save(business_id,project_id,body,user)}
@router.post('/{business_id}/{project_id}/renders')
def render(business_id:UUID,project_id:UUID,body:RenderRequest,user:AuthedUser=Depends(require_user)):
    assert_access(str(business_id),user,'manager')
    return {'job':studio.enqueue(business_id,project_id,body,user,'render')}
@router.post('/{business_id}/{project_id}/jobs/{job_id}/cancel')
def cancel(business_id:UUID,project_id:UUID,job_id:UUID,user:AuthedUser=Depends(require_user)):
    assert_access(str(business_id),user,'manager')
    return studio.cancel(business_id,project_id,job_id,user)
@router.get('/{business_id}/{project_id}/jobs/{job_id}/playback')
def playback(business_id:UUID,project_id:UUID,job_id:UUID,download:bool=False,user:AuthedUser=Depends(require_user)):
    assert_access(str(business_id),user,'manager')
    return studio.signed(business_id,project_id,job_id,user,download=download)
@router.post('/{business_id}/{project_id}/assets')
def upload(business_id:UUID,project_id:UUID,file:UploadFile=File(...),purpose:Literal['include','reference']=Form('include'),user:AuthedUser=Depends(require_user)):
    assert_access(str(business_id),user,'manager')
    studio.project(business_id,project_id,user)
    with tempfile.TemporaryDirectory(prefix='video-upload-') as folder:
        target=Path(folder)/'upload.bin';size=0
        with target.open('wb') as stream:
            while chunk:=file.file.read(1024*1024):
                size+=len(chunk)
                if size>studio.MAX_UPLOAD:raise HTTPException(413,'Files can be up to 100 MB.')
                stream.write(chunk)
        return {'asset':studio.store_upload(business_id,project_id,user,target,file.filename or 'Uploaded media',file.content_type,purpose)}
@router.get('/{business_id}/{project_id}/assets/{asset_id}/playback')
def asset_playback(business_id:UUID,project_id:UUID,asset_id:UUID,user:AuthedUser=Depends(require_user)):
    assert_access(str(business_id),user,'manager')
    return studio.signed(business_id,project_id,asset_id,user,asset=True)
@router.patch('/{business_id}/{project_id}/assets/{asset_id}')
def purpose(business_id:UUID,project_id:UUID,asset_id:UUID,body:Purpose,user:AuthedUser=Depends(require_user)):
    assert_access(str(business_id),user,'manager')
    return {'asset':studio.set_purpose(business_id,project_id,asset_id,body,user)}
@router.delete('/{business_id}/{project_id}/assets/{asset_id}')
def delete_asset(business_id:UUID,project_id:UUID,asset_id:UUID,user:AuthedUser=Depends(require_user)):
    assert_access(str(business_id),user,'manager')
    return studio.delete_asset(business_id,project_id,asset_id,user)

@router.get('/{business_id}/{project_id}/library')
def library(business_id:UUID,project_id:UUID,user:AuthedUser=Depends(require_user)):
    assert_access(str(business_id),user,'manager')
    return studio.library(business_id,project_id,user)

@router.post('/{business_id}/{project_id}/library/{source_id}')
def import_library(business_id:UUID,project_id:UUID,source_id:UUID,user:AuthedUser=Depends(require_user)):
    assert_access(str(business_id),user,'manager')
    return {'asset':studio.import_library(business_id,project_id,source_id,user)}
