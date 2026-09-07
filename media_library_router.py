from uuid import UUID
from fastapi import APIRouter, Depends, Response
from auth_supabase import AuthedUser, require_user
import media_library


def private_response(response: Response):
    response.headers['Cache-Control'] = 'no-store'


router = APIRouter(prefix='/media-library', tags=['media-library'], dependencies=[Depends(private_response)])


@router.get('/{business_id}')
def library(business_id: UUID, user: AuthedUser = Depends(require_user)):
    media_library.access(business_id, user)
    rows = media_library.read(f'/media_assets?business_id=eq.{business_id}&select={media_library.PUBLIC_COLUMNS}&order=created_at.desc&limit=500')
    return {'ok': True, 'configuration': media_library.configuration(), 'assets': [media_library.public(r) for r in rows]}


@router.post('/{business_id}/drive')
def import_drive(business_id: UUID, body: media_library.DriveImport, user: AuthedUser = Depends(require_user)):
    return {'ok': True, 'asset': media_library.import_drive(business_id, body, user)}


@router.post('/{business_id}/clips')
def create_clip(business_id: UUID, body: media_library.Clip, user: AuthedUser = Depends(require_user)):
    return {'ok': True, 'asset': media_library.create_clip(business_id, body, user)}


@router.post('/{business_id}/{asset_id}/approve')
def approve(business_id: UUID, asset_id: UUID, body: media_library.Review, user: AuthedUser = Depends(require_user)):
    return {'ok': True, 'asset': media_library.approve(business_id, asset_id, body, user)}


@router.get('/{business_id}/{asset_id}/preview')
def preview(business_id: UUID, asset_id: UUID, user: AuthedUser = Depends(require_user)):
    return {'ok': True, **media_library.playback(business_id, asset_id, user)}


@router.get('/{business_id}/{asset_id}/download')
def download(business_id: UUID, asset_id: UUID, user: AuthedUser = Depends(require_user)):
    return {'ok': True, **media_library.playback(business_id, asset_id, user, reviewed=True)}
