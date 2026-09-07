"""Staff-authorized outcomes; creating or approving a report never sends it."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import Field

from auth_supabase import AuthedUser, require_user
from program_outcomes import StrictModel
import program_outcomes_service

def private_response(response: Response):
    response.headers['Cache-Control'] = 'no-store'


router = APIRouter(prefix='/program-outcomes', tags=['program-outcomes'],
                   dependencies=[Depends(private_response)])


class Approval(StrictModel):
    content_hash: str = Field(pattern=r'^[a-f0-9]{64}$')


@router.get('/{business_id}/sources')
def sources(business_id: UUID, user: AuthedUser = Depends(require_user)):
    current_role = program_outcomes_service.role(str(business_id), user)
    modules = program_outcomes_service._read(f'/custom_modules?business_id=eq.{business_id}&is_active=eq.true&select=id,name,schema,archetype,archetype_params,agent_config&order=name.asc&limit=500')
    visible = []
    for module in modules:
        try:
            program_outcomes_service._module(str(business_id), module['id'], user)
        except HTTPException as exc:
            if exc.status_code in (403, 404):
                continue
            raise
        visible.append({k: module.get(k) for k in ('id', 'name', 'schema', 'archetype', 'archetype_params')})
    return {'ok': True, 'role': current_role, 'modules': visible}


@router.post('/{business_id}/preview')
def preview(business_id: UUID, body: program_outcomes_service.Configuration, user: AuthedUser = Depends(require_user)):
    return {'ok': True, **program_outcomes_service.preview(str(business_id), body, user)}


@router.post('/{business_id}/reports')
def create(business_id: UUID, body: program_outcomes_service.Configuration, user: AuthedUser = Depends(require_user)):
    return {'ok': True, 'report': program_outcomes_service.create_report(str(business_id), body, user)}


@router.get('/{business_id}/reports')
def reports(business_id: UUID, user: AuthedUser = Depends(require_user)):
    program_outcomes_service.role(str(business_id), user)
    rows = program_outcomes_service._read(f'/program_outcome_reports?business_id=eq.{business_id}&order=created_at.desc&limit=50&select=*')
    visible = []
    for row in rows:
        try:
            program_outcomes_service.authorize_sources(str(business_id), row['configuration'], user, validate_fields=False)
        except HTTPException as exc:
            if exc.status_code in (403, 404):
                continue
            raise
        visible.append({key: row.get(key) for key in ('id', 'status', 'created_at', 'approved_at', 'content_hash')}
                       | {'title': row['snapshot']['definition']['title'], 'cohort': row['snapshot']['definition']['cohort']})
    return {'ok': True, 'reports': visible}


@router.get('/{business_id}/reports/{report_id}')
def get_report(business_id: UUID, report_id: UUID, user: AuthedUser = Depends(require_user)):
    return {'ok': True, 'report': program_outcomes_service.load_report(str(business_id), str(report_id), user)}


@router.post('/{business_id}/reports/{report_id}/approve')
def approve(business_id: UUID, report_id: UUID, body: Approval, user: AuthedUser = Depends(require_user)):
    return {'ok': True, 'report': program_outcomes_service.approve_report(str(business_id), str(report_id), body.content_hash, user)}


@router.get('/{business_id}/reports/{report_id}/export.csv')
def export_csv(business_id: UUID, report_id: UUID, user: AuthedUser = Depends(require_user)):
    report = program_outcomes_service.load_report(str(business_id), str(report_id), user)
    return Response(program_outcomes_service.csv_export(report), media_type='text/csv', headers={
        'Content-Disposition': f'attachment; filename="outcomes-{report_id}.csv"',
        'Cache-Control': 'no-store'})


@router.get('/{business_id}/reports/{report_id}/export.pdf')
def export_pdf(business_id: UUID, report_id: UUID, user: AuthedUser = Depends(require_user)):
    report = program_outcomes_service.load_report(str(business_id), str(report_id), user)
    businesses = program_outcomes_service._read(f'/businesses?id=eq.{business_id}&select=name&limit=1')
    if not businesses:
        raise HTTPException(404, 'Business not found.')
    from program_outcomes_pdf import render
    return Response(render(report, businesses[0].get('name') or 'Program'), media_type='application/pdf', headers={
        'Content-Disposition': f'attachment; filename="outcomes-{report_id}.pdf"',
        'Cache-Control': 'no-store'})
