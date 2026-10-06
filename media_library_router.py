from uuid import UUID
from fastapi import APIRouter, Depends, Response
from auth_supabase import AuthedUser, require_user
import clip_finder
import media_library


def private_response(response: Response):
    response.headers['Cache-Control'] = 'no-store'


router = APIRouter(prefix='/media-library', tags=['media-library'], dependencies=[Depends(private_response)])


@router.get('/{business_id}')
def library(business_id: UUID, user: AuthedUser = Depends(require_user)):
    media_library.access(business_id, user)
    rows = media_library.read(f'/media_assets?business_id=eq.{business_id}&select={media_library.PUBLIC_COLUMNS}&order=created_at.desc&limit=500')
    posters = clip_finder.poster_urls(rows)
    import clip_covers
    shaped = clip_covers.shaped_covers(business_id, rows)
    covers = {clip: shapes['story'] for clip, shapes in shaped.items() if 'story' in shapes}
    assets = [media_library.public(r) | ({'poster_url': posters[str(r['id'])]} if str(r['id']) in posters else {})
              | ({'cover_image_id': covers[str(r['id'])]} if str(r['id']) in covers else {})
              | ({'covers': shaped[str(r['id'])]} if str(r['id']) in shaped else {}) for r in rows]
    return {'ok': True, 'configuration': media_library.configuration(), 'assets': assets,
            'clip_finder': clip_finder.configuration(business_id), 'runs': clip_finder.runs(business_id, user)}


@router.post('/{business_id}/drive')
def import_drive(business_id: UUID, body: media_library.DriveImport, user: AuthedUser = Depends(require_user)):
    return {'ok': True, 'asset': media_library.import_drive(business_id, body, user)}


@router.post('/{business_id}/clips')
def create_clip(business_id: UUID, body: media_library.Clip, user: AuthedUser = Depends(require_user)):
    return {'ok': True, 'asset': media_library.create_clip(business_id, body, user)}


@router.post('/{business_id}/uploads')
def start_upload(business_id: UUID, body: clip_finder.UploadStart, user: AuthedUser = Depends(require_user)):
    return {'ok': True, **clip_finder.start_upload(business_id, body, user)}


@router.post('/{business_id}/uploads/{asset_id}/complete')
def finish_upload(business_id: UUID, asset_id: UUID, user: AuthedUser = Depends(require_user)):
    return {'ok': True, 'asset': clip_finder.finish_upload(business_id, asset_id, user)}


@router.delete('/{business_id}/uploads/{asset_id}')
def cancel_upload(business_id: UUID, asset_id: UUID, user: AuthedUser = Depends(require_user)):
    return {'ok': True, **clip_finder.cancel_upload(business_id, asset_id, user)}


@router.post('/{business_id}/sources/{source_id}/find-clips')
def find_clips(business_id: UUID, source_id: UUID, body: clip_finder.FindClips, user: AuthedUser = Depends(require_user)):
    return {'ok': True, 'run': clip_finder.start_run(business_id, source_id, body, user)}


@router.get('/{business_id}/runs')
def clip_runs(business_id: UUID, user: AuthedUser = Depends(require_user)):
    return {'ok': True, 'runs': clip_finder.runs(business_id, user)}


@router.delete('/{business_id}/runs/{run_id}')
def cancel_run(business_id: UUID, run_id: UUID, user: AuthedUser = Depends(require_user)):
    return {'ok': True, **clip_finder.cancel_run(business_id, run_id, user)}


@router.patch('/{business_id}/assets/{asset_id}')
def update_clip(business_id: UUID, asset_id: UUID, body: clip_finder.ClipUpdate, user: AuthedUser = Depends(require_user)):
    return {'ok': True, 'asset': clip_finder.update_clip(business_id, asset_id, body, user)}


@router.post('/{business_id}/{asset_id}/approve')
def approve(business_id: UUID, asset_id: UUID, body: media_library.Review, user: AuthedUser = Depends(require_user)):
    return {'ok': True, 'asset': media_library.approve(business_id, asset_id, body, user)}


@router.get('/{business_id}/{asset_id}/preview')
def preview(business_id: UUID, asset_id: UUID, user: AuthedUser = Depends(require_user)):
    return {'ok': True, **media_library.playback(business_id, asset_id, user)}


@router.get('/{business_id}/{asset_id}/download')
def download(business_id: UUID, asset_id: UUID, user: AuthedUser = Depends(require_user)):
    return {'ok': True, **media_library.playback(business_id, asset_id, user, reviewed=True)}
