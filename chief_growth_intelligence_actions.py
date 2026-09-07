"""Chief and the Growth UI share the same measurements, validation and writes."""
from fastapi import HTTPException
from growth_intelligence_router import load_report, save_record, SaveRecord


def recall_view(report, action):
    """Bounded, pageable recall so the tool loop never loses saved IDs in a long report."""
    section = action.get('section', 'overview')
    result = {k: report[k] for k in ('currency', 'timezone', 'generated_at', 'period')}
    result['available_sections'] = ['overview', 'drivers', 'client_health', 'retention', 'marketing', 'profitability', 'capacity', 'actions', 'records']
    if action.get('record_id'):
        for kind, rows in report['records'].items():
            row = next((r for r in rows if r['id'] == action['record_id']), None)
            if row:
                return {**result, 'kind': kind, 'record': row,
                        'measurement': next(({k: a[k] for k in ('current', 'baseline', 'progress', 'change')} for a in report['actions'] if a['id'] == row['id']), None) if kind == 'actions' else None}
        if report['preferences'].get('id') == action['record_id']:
            return {**result, 'kind': 'preferences', 'record': report['preferences']}
        raise HTTPException(404, 'Growth record not found in this business')
    if section in ('overview', 'drivers'):
        result.update({k: report[k] for k in ('current', 'previous', 'change', 'change_pct', 'drivers', 'conversion', 'quality', 'preferences')})
        result['record_counts'] = {kind: len(rows) for kind, rows in report['records'].items()}
    elif section == 'capacity':
        result.update(capacity=report['capacity'], preferences=report['preferences'])
    else:
        offset = max(0, int(action.get('offset', 0)))
        if section == 'client_health':
            health = report['retention_health']
            result['summary'] = {k: v for k, v in health.items() if k not in ('at_risk', 'lapsed', 'best_clients')}
            kind = action.get('kind', 'at_risk')
            if kind not in ('at_risk', 'lapsed', 'best_clients'):
                raise HTTPException(422, 'Choose at_risk, lapsed or best_clients for client health')
            rows = health[kind]
            query = str(action.get('query', '')).casefold()
            rows = [r for r in rows if query in str(r).casefold()]
            result['kind'] = kind
        elif section == 'retention':
            result['engagement'] = report['engagement']
            result['definitions'] = report['retention_health']['definitions']
            result['cohort_scope'] = 'Latest 12 first-payment months, all recorded payment history; period filters apply to interaction counts only.'
            rows = report['cohorts']
        elif section == 'marketing':
            kind = action.get('kind', 'channels')
            rows = report['campaigns'] if kind == 'campaigns' else report['channels']
        elif section == 'profitability':
            rows = report['profitability']
            result['overhead'] = report['overhead']
        elif section in ('actions', 'records'):
            kind = 'actions' if section == 'actions' else action.get('kind', 'actions')
            rows = report['actions'] if section == 'actions' else report['records'].get(kind, [])
            query = str(action.get('query', '')).casefold()
            rows = [r for r in rows if query in str(r).casefold()]
            rows = [{**{k: v for k, v in r.items() if k not in ('notes', 'contact_ids', 'evidence')},
                     'audience_count': len(r.get('contact_ids') or []),
                     'recall_hint': 'Use record_id for complete notes, audience and evidence before editing.'} for r in rows]
            result['kind'] = kind
        else:
            raise HTTPException(422, 'Choose an available Growth section')
        result.update(rows=rows[offset:offset+5], total=len(rows), offset=offset,
                      next_offset=offset+5 if len(rows)>offset+5 else None)
    return result


async def handle_growth_report(client, biz, action):
    try:
        result = await load_report(client, biz['id'], action.get('period', 'mtd'), action.get('comparison', 'previous'), action.get('start'), action.get('end'))
        result = recall_view(result, action)
        return {'type': 'growth_report', 'label': 'Growth intelligence', 'result': 'Growth report recalled from current records',
                'data': result, 'growth_section': action.get('section', 'drivers'),
                'nav': {'tab': 'grow', 'sub': 'retention' if action.get('section') in ('retention', 'client_health') else 'dashboard'}}
    except (HTTPException, ValueError) as exc:
        message = str(getattr(exc, 'detail', exc))
        return {'type': 'growth_report', 'label': 'Growth report unavailable', 'result': message, 'failed': True}


async def handle_save_growth_record(client, biz, action):
    try:
        payload = {k: action[k] for k in ('data', 'id', 'revision', 'request_id') if k in action}
        if isinstance(payload.get('data'), dict):
            payload['data'] = {k: v for k, v in payload['data'].items() if k not in ('id', 'revision', 'current', 'baseline', 'progress', 'change', 'history_since')}
        request = SaveRecord(**payload)
        row = await save_record(client, biz['id'], action.get('kind'), request)
        return {'type': 'save_growth_record', 'label': 'Growth record saved', 'result': 'Saved and available in Growth intelligence',
                'data': row, 'growth_section': 'actions' if action.get('kind') == 'actions' else 'capacity' if action.get('kind') == 'preferences' else 'marketing', 'nav': {'tab': 'grow', 'sub': 'dashboard'},
                'frontend_event': {'name': 'solutionist-growth-changed', 'detail': {'business_id': biz['id']}}}
    except (HTTPException, ValueError) as exc:
        message = str(getattr(exc, 'detail', exc))
        return {'type': 'save_growth_record', 'label': 'Growth change not saved', 'result': message, 'failed': True}


READ_SCHEMA = ('Recall Growth intelligence: equal-period collections and drivers, 30/60/90-day retention cohorts, source and campaign outcomes, recorded direct-cost contribution, session capacity, and saved growth actions with baselines/results. Defaults to overview; request a section for details. section=client_health recalls the canonical Retention summary and paged people; kind=at_risk/lapsed/best_clients, query filters names. Use this for exact risk counts and follow-ups. section=retention recalls repeat-payment cohorts. These are one Retention workspace, not separate systems. Engagement current_complete/previous_complete=false means incomplete history; never present its zero as no interactions. Lists page five rows with next_offset. section=records, kind=actions/costs/attributions recalls saved records including archives; query searches them. section=marketing, kind=campaigns shows campaign credit. Use record_id to recall complete notes, audience and fields before edits. Call before answering numerical growth questions or changing a saved Growth record. Values are measured, not causal attribution.',
               {'type': 'object', 'properties': {'section': {'type':'string','enum':['overview','drivers','client_health','retention','marketing','profitability','capacity','actions','records']}, 'record_id': {'type':'string','description':'Recall one complete saved record by UUID before editing'}, 'kind': {'type':'string','enum':['actions','costs','attributions','channels','campaigns','at_risk','lapsed','best_clients']}, 'query': {'type':'string','description':'Filter actions or saved records by text'}, 'offset': {'type':'integer','minimum':0,'description':'Next page of five rows'}, 'period': {'type': 'string', 'enum': ['mtd','qtd','ytd','30d','90d','custom']},
                'comparison': {'type': 'string', 'enum': ['previous','year']}, 'start': {'type': 'string', 'description': 'YYYY-MM-DD for custom'}, 'end': {'type': 'string', 'description': 'YYYY-MM-DD inclusive for custom'}}, 'additionalProperties': False})
WRITE_SCHEMA = ('Create or edit a Growth record. Read growth_report first for IDs/revisions. kind=actions data: title, owner, start_date, due_date, metric (revenue/bookings/buyers), target>0, status (planned/active/completed/paused), notes, contact_ids optional UUID array. kind=costs data: description,date,amount>=0,kind (marketing/direct/overhead),source,offering,contact_id,campaign_id,hours optional. Direct cost needs offering or contact_id; marketing needs source. kind=attributions data: invoice_id,campaign_id,evidence. One campaign credit per invoice. kind=preferences data: timezone,currency (3 uppercase letters),weekly_hours (team total). Actions and costs store currency (3 uppercase letters), defaulting to reporting currency at creation; preserve it on edits. Dates YYYY-MM-DD. For edits provide complete data plus id and revision, preserve unchanged fields from recall. Archive costs/actions/credits with archived=true; never delete. Costs are analytical allocations only, never send or charge money. Do not claim saved until success.',
                {'type': 'object', 'properties': {'kind': {'type': 'string', 'enum': ['actions','costs','attributions','preferences']},
                 'data': {'type': 'object', 'description': 'Complete validated record fields described above'}, 'id': {'type': 'string'},
                 'revision': {'type': 'integer', 'minimum': 1}, 'request_id': {'type': 'string', 'description': 'Optional UUID for retry-safe creation; reuse on retry'}},
                 'required': ['kind','data'], 'additionalProperties': False})

PROMPT = '''Growth intelligence and the unified Retention workspace: Retention has Client health and Repeat business views. Always use growth_report section=client_health for current risk counts and names (kind=at_risk/lapsed/best_clients, query and offset supported); never infer full counts from the truncated contact context. Use existing contact editing tools to change health/status or log an interaction; these update the same records the Retention page reads. Saved follow-up goals use save_growth_record kind=actions. Client-health snapshots, all-time paid repeat rate and 30/60/90-day cohorts are distinct labeled measurements. Never count unpaid invoices as repeat purchases. Use growth_report to recall collections/drivers, retention cohorts, marketing credit, recorded direct-cost margins, session capacity, reporting preferences, or tracked growth actions. Use save_growth_record to create/update those same records on request; recall first (section lists are paginated; record_id returns complete fields) and preserve untouched fields. Both are native tools; tags fallback: [ACTION:{"type":"growth_report","period":"mtd"}] or [ACTION:{"type":"save_growth_record","kind":"actions","data":{...}}]. Never claim a save or a financial result without the tool result. Explain missing data, recorded-cost coverage, history start and attribution limitations. Campaign exposure is not proof of causation. Completing an action does not imply it caused the observed outcome.'''
