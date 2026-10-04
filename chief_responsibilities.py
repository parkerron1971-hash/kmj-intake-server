"""A read-only account of Chief's work, shared by chat, voice and the app.

Source failures remain visible. Work status is never inferred from a model's
promise, and business outcomes are observations rather than causal claims.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
import sb_clients
from auth_supabase import AuthedUser, require_user

router = APIRouter(prefix='/agents/chief', tags=['chief-responsibilities'])
LIMIT = 40
# A normal owner report should fit inside the three available read rounds.
# Stay below the reviewer's per-source cap, including the result envelope.
REPORT_PAGE_SIZE = 16
REPORT_PAGE_MAX_CHARS = 8200
REPORT_MAX_RESULT_CHARS = 10000


def _text(value, limit=240):
    return str(value or '')[:limit]


def _dict(value):
    return value if isinstance(value, dict) else {}


def source_queries(bid):
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat().replace('+00:00', 'Z')
    return {
        'assignments': f'/chief_assignments?business_id=eq.{bid}&or=(status.eq.active,updated_at.gte.{since})&select=id,title,status,target,progress,deadline,next_check_at,last_worked_at,report,updated_at&order=updated_at.desc&limit={LIMIT}',
        'missions': f'/chief_missions?business_id=eq.{bid}&status=in.(draft,active,awaiting_approval,paused)&select=id,title,status,steps,updated_at&order=updated_at.desc&limit={LIMIT}',
        'jobs': f'/chief_jobs?business_id=eq.{bid}&or=(status.in.(queued,running,failed),result->>status.in.(held,needs_answer,needs_hand,done_with_gaps),created_at.gte.{since})&select=id,kind,status,params,result,created_at,finished_at&order=created_at.desc&limit={LIMIT}',
        'errands': f'/chief_errands?business_id=eq.{bid}&status=in.(planned,approved,running,needs_you,paused,interrupted,failed)&select=id,job_id,title,status,created_at&order=created_at.desc&limit={LIMIT}',
        'approvals': f'/agent_queue?business_id=eq.{bid}&status=eq.draft&select=id,subject,channel,created_at&order=created_at.desc&limit={LIMIT}',
    }


def normalize(source, row):
    rid = _text(row.get('id'), 100)
    status = _text(row.get('status'))
    item = {'id': f'{source}:{rid}', 'source': source, 'source_id': rid,
            'title': _text(row.get('title') or row.get('subject') or 'Chief work', 160),
            'status': status, 'needs_you': False, 'next_check_at': None,
            'deadline': None, 'summary': '', 'conversation_id': None,
            'observed_at': row.get('updated_at') or row.get('finished_at') or row.get('created_at')}
    if source == 'assignments':
        progress = _dict(row.get('progress'))
        item.update(summary=_text(progress.get('label') or row.get('report') or 'Not measured yet'),
                    deadline=row.get('deadline'), next_check_at=row.get('next_check_at'),
                    observed_at=row.get('last_worked_at') or row.get('updated_at'),
                    target=_dict(row.get('target')), measurement=progress,
                    attribution='Observed business progress; not proof that Chief caused it.')
        if str(row.get('report') or '').startswith('Progress could not be checked'):
            item.update(needs_you=True, summary=_text(row['report']), status='measurement_unavailable')
    elif source == 'missions':
        steps = row.get('steps') if isinstance(row.get('steps'), list) else []
        done = sum(1 for s in steps if isinstance(s, dict) and s.get('status') == 'done')
        item.update(needs_you=status in ('draft', 'awaiting_approval', 'paused'),
                    summary=f'{done} of {len(steps)} steps completed.')
    elif source == 'jobs':
        from chief_jobs import KIND_META
        result, params = _dict(row.get('result')), _dict(row.get('params'))
        facts = _dict(params.get('facts'))
        job_label = KIND_META.get(row.get('kind'), {}).get('label') or 'Background work'
        state = status if status in ('queued', 'running') else _text(result.get('status') or status)
        item.update(title=_text(facts.get('title') or facts.get('name') or job_label, 160),
                    status=state, needs_you=state in ('held','needs_answer','needs_hand','failed','done_with_gaps'),
                    summary=_text(_dict(result.get('question')).get('text') or
                                  _dict(result.get('held')).get('label') or result.get('summary_label') or
                                  _dict(result.get('progress')).get('stage') or
                                  ('Work stopped; review the result before trying again.' if state == 'failed' else state)),
                    conversation_id=params.get('conversation_id'))
    elif source == 'errands':
        item.update(needs_you=status in ('planned','needs_you','paused','interrupted','failed'),
                    summary='Check the supplier before starting again.' if status in ('interrupted','failed') else status.replace('_',' '))
    elif source == 'approvals':
        item.update(status='awaiting_approval', needs_you=True, summary='Waiting for your decision; not sent.')
    elif source == 'events':
        item.update(title='Interrupted business follow-up', status='needs_review', needs_you=True,
                    summary=_text(row.get('summary')), source_id=_text(row.get('event_id'),100),
                    id='events:' + _text(row.get('event_id'),100))
    return item


async def snapshot(business_id):
    bid = str(UUID(str(business_id)))
    queries = source_queries(bid)
    import chief_event_delivery
    if chief_event_delivery.enabled():
        queries['events'] = f'/chief_event_deliveries?business_id=eq.{bid}&phase=eq.needs_review&select=event_id,phase,summary,updated_at&order=updated_at.desc&limit={LIMIT}'

    async def read(name, query):
        try:
            rows = await asyncio.to_thread(sb_clients.sb_get_as_service, query)
            if not isinstance(rows, list):
                raise RuntimeError('unavailable')
            return name, rows, None
        except Exception:
            return name, [], 'Could not read this part of Chief\'s work.'

    results = await asyncio.gather(*(read(k, q) for k, q in queries.items()))
    sources = {name: {'available': error is None, 'limited': len(rows) == LIMIT}
               for name, rows, error in results}
    errors = [{'source': name, 'message': error} for name, _, error in results if error]
    errand_jobs = {str(r.get('job_id')) for name, rows, _ in results if name == 'errands' for r in rows if r.get('job_id')}
    items = [normalize(name, row) for name, rows, _ in results for row in rows
             if not (name == 'jobs' and str(row.get('id')) in errand_jobs)]
    items.sort(key=lambda r: (not r['needs_you'], r['id']))
    partial = bool(errors) or any(s['limited'] for s in sources.values())
    return {'ok': not errors, 'partial': partial, 'as_of': datetime.now(timezone.utc).isoformat(),
            'items': items, 'sources': sources, 'errors': errors,
            'needs_you': sum(1 for i in items if i['needs_you']),
            'note': 'A scheduled check is not a promised completion time. Finished work and business impact are separate.'}


async def handle_responsibility_status(client, biz, action):
    out = await snapshot(biz['id'])
    source = action.get('source')
    if source:
        if source not in ('assignments','missions','jobs','errands','approvals','events'):
            raise ValueError('Unknown responsibility source.')
        out['items'] = [i for i in out['items'] if i['source'] == source]
    offset = action.get('offset', 0)
    if type(offset) is not int or not 0 <= offset <= 240:
        raise ValueError('Choose a work report offset between 0 and 240.')
    count = len(out['items'])
    out['needs_you'] = sum(1 for i in out['items'] if i['needs_you'])
    out['scope'] = source or 'all'
    out['source_counts'] = {
        name: {'found': sum(i['source'] == name for i in out['items']),
               'needs_you': sum(i['source'] == name and i['needs_you'] for i in out['items'])}
        for name in out['sources'] if not source or name == source}
    summary = f'{count} work item(s) found; {out["needs_you"]} need your attention.'
    if out['partial']:
        summary += ' Some work could not be checked; this is not a complete account.'
    # Native tool replies have a bounded context budget. Keep a useful whole
    # report rather than letting the transport cut JSON in the middle of a row.
    out['total_found'] = count
    out['items'] = [{k: item[k] for k in ('id','source_id','title','status','needs_you','summary','next_check_at','deadline','observed_at')}
                    for item in out['items'][offset:offset+REPORT_PAGE_SIZE]]
    while len(out['items']) > 1 and len(json.dumps(out)) > REPORT_PAGE_MAX_CHARS:
        out['items'].pop()
    out['more_items'] = max(0, count - offset - len(out['items']))
    out['next_offset'] = offset + len(out['items']) if out['more_items'] else None
    out['offset'] = offset
    out['page_count'] = len(out['items'])
    return {'type': 'responsibility_status', 'label': 'Chief responsibilities', 'result': summary,
            'responsibilities': out, 'nav': None,
            'for_chief': 'Report current work, what needs the owner, and recorded next checks. '
                         'total_found and source_counts cover the scope; page_count covers only this page. '
                         'Source counts with unavailable or limited sources are not complete totals. '
                         'For a full report, follow next_offset while more_items is nonzero before answering. '
                         'If the reading budget runs out, identify what remains unread. '
                         'Do not restart work, promise missing check times, or call partial data an empty queue.'}


async def handle_acknowledge_follow_up(client, biz, action):
    import chief_of_staff
    from chief_event_delivery import rpc
    if str(chief_of_staff._TURN_USER_ID.get()) != str(biz.get('owner_id')):
        return {'type':'acknowledge_follow_up','failed':True,'label':'Owner review required',
                'result':'Only the business owner can acknowledge this review.'}
    event = str(UUID(str(action.get('event_id'))))
    updated = datetime.fromisoformat(str(action.get('observed_at')).replace('Z','+00:00'))
    if updated.tzinfo is None:
        raise ValueError('Review needs the timestamp from the current work report.')
    ok = await asyncio.to_thread(rpc, 'resolve', {'p_business':str(UUID(str(biz['id']))),
        'p_event':event, 'p_updated_at':updated.isoformat()})
    label = 'Review acknowledged. No actions were replayed.' if ok is True else 'This review changed. Read Chief responsibilities again.'
    return {'type':'acknowledge_follow_up','failed':ok is not True,'label':label,'result':label,'nav':None}


@router.get('/responsibilities')
async def get_responsibilities(business_id: UUID, user: AuthedUser = Depends(require_user)):
    bid = str(business_id)
    rows = await asyncio.to_thread(sb_clients.sb_get_as_service,
        f'/businesses?id=eq.{bid}&select=id,owner_id&limit=1')
    if not rows or str(rows[0].get('owner_id')) != str(user.id):
        raise HTTPException(403, 'Not authorized for this business.')
    return await snapshot(bid)
