from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from auth_supabase import AuthedUser, require_user
from business_users_router import require_role
from program_outcomes import StrictModel
import financial_policy
import ledger_unlock
import sb_clients

router = APIRouter(prefix='/financial-policy', tags=['financial-policy'])


class Change(StrictModel):
    mode: Literal['standard', 'view_only']
    reason: str = Field(min_length=10, max_length=500)


@router.get('/{business_id}')
def get_policy(business_id: UUID, user: AuthedUser = Depends(require_user)):
    require_role(str(business_id), str(user.id), 'viewer')
    return {'ok': True, 'policy': financial_policy.policy_for(str(business_id))}


@router.put('/{business_id}')
def change_policy(business_id: UUID, body: Change, request: Request,
                  user: AuthedUser = Depends(require_user)):
    require_role(str(business_id), str(user.id), 'owner')
    ledger_unlock.require_unlock(request, str(user.id), scope=ledger_unlock.SCOPE_DANGER)
    result = sb_clients.sb_post_as_service('/rpc/set_business_financial_policy', {
        'p_business_id': str(business_id), 'p_actor_id': str(user.id),
        'p_mode': body.mode, 'p_reason': body.reason})
    if isinstance(result, list):
        result = result[0] if result else None
    if not isinstance(result, dict) or result.get('mode') != body.mode:
        raise HTTPException(503, 'The financial policy was not confirmed. Refresh before continuing.')
    return {'ok': True, 'policy': result}
