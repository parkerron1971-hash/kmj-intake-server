"""Owner-only read, correction, history, and queued discovery APIs."""
import asyncio
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from auth_supabase import AuthedUser, require_user
from business_profile_router import _require_owner
import business_learning as learning
import sb_clients

router = APIRouter(prefix='/business-learning', tags=['business-learning'])


class DiscoverBody(learning.StrictModel):
    description: str = Field(min_length=1, max_length=12000)
    research_question: str = Field(default='', max_length=1000)


class CorrectionBody(learning.StrictModel):
    key: str = Field(pattern=r'^[a-z][a-z0-9_]{0,63}$')
    kind: learning.KINDS
    statement: str = Field(min_length=1, max_length=700)
    expected_revision: int = Field(ge=1)
    resolves_gap: str | None = None


@router.get('/{business_id}')
def get_profile(business_id: UUID, user: AuthedUser = Depends(require_user)):
    _require_owner(str(business_id), user)
    try:
        return {'ok': True, 'profile': learning.load(str(business_id))}
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e


@router.get('/{business_id}/history')
def history(business_id: UUID, user: AuthedUser = Depends(require_user)):
    _require_owner(str(business_id), user)
    rows = sb_clients.sb_get_as_service(
        f'/business_operating_profile_history?business_id=eq.{business_id}&order=revision.desc&limit=50')
    if rows is None:
        raise HTTPException(503, 'Knowledge history could not be read.')
    return {'ok': True, 'history': rows}


@router.post('/{business_id}/discover')
async def discover(business_id: UUID, body: DiscoverBody, user: AuthedUser = Depends(require_user)):
    await asyncio.to_thread(_require_owner, str(business_id), user)
    import chief_jobs
    try:
        await asyncio.to_thread(learning.load, str(business_id))
        async with httpx.AsyncClient() as client:
            job = await chief_jobs.enqueue(client, user_id=str(user.id), business_id=str(business_id),
                                           kind='learn_business', params=body.model_dump(), source='desktop')
        if not job:
            raise RuntimeError('Business discovery could not be started.')
        return {'ok': True, 'job': job}
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e


@router.post('/{business_id}/correct')
def correction(business_id: UUID, body: CorrectionBody, user: AuthedUser = Depends(require_user)):
    _require_owner(str(business_id), user)
    try:
        return {'ok': True, 'profile': learning.correct(str(business_id), **body.model_dump())}
    except learning.Conflict as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
