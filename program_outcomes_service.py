"""Authorized source loading and immutable program report snapshots."""
from __future__ import annotations

import csv
import io
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, model_validator

import sb_clients
from auth_supabase import AuthedUser
from program_outcomes import Definition, StrictModel, calculate


class EnrollmentSource(StrictModel):
    module_id: UUID
    subject_field: str = Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_]{0,99}$')
    cohort_field: str = Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_]{0,99}$')
    status_field: str = Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_]{0,99}$')


class MeasurementSource(StrictModel):
    module_id: UUID
    metric: str = Field(pattern=r'^[a-z][a-z0-9_]{0,63}$')
    subject_field: str = Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_]{0,99}$')
    date_field: str = Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_]{0,99}$')
    value_field: str = Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_]{0,99}$')


class Configuration(StrictModel):
    definition: Definition
    enrollment: EnrollmentSource
    measurements: list[MeasurementSource] = Field(min_length=1, max_length=12)

    @model_validator(mode='after')
    def one_source_per_metric(self):
        keys = [m.metric for m in self.measurements]
        if len(set(keys)) != len(keys) or set(keys) != {m.key for m in self.definition.metrics}:
            raise ValueError('Each metric needs exactly one measurement source.')
        return self


def key(value):
    return str(UUID(str(value)))


def _read(path):
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, 'Outcome storage is unavailable. No report was generated.')
    return rows


def role(business_id, user, minimum='member'):
    from business_users_router import require_role
    return require_role(key(business_id), str(user.id), minimum)


def _module(business_id, module_id, user):
    rows = _read(f'/custom_modules?id=eq.{key(module_id)}&business_id=eq.{key(business_id)}&select=*&limit=1')
    if not rows:
        raise HTTPException(404, 'Outcome source module is unavailable.')
    module = rows[0]
    restricted = (module.get('agent_config') or {}).get('access_level') == 'restricted'
    if restricted:
        from restricted_modules import _authorize
        _authorize(key(business_id), key(module_id), user)
    return module, restricted


def authorize_sources(business_id, config, user, *, validate_fields=True):
    """Check EVERY source before any entry read, also on historical exports."""
    role(business_id, user)
    config = Configuration.model_validate(config)
    modules = {}
    for module_id in {str(config.enrollment.module_id), *(str(m.module_id) for m in config.measurements)}:
        modules[module_id] = _module(business_id, module_id, user)
    for source in ([config.enrollment, *config.measurements] if validate_fields else []):
        module = modules[str(source.module_id)][0]
        fields = {f.get('name') for f in (module.get('schema') or {}).get('fields', [])}
        for name, field in source.model_dump().items():
            if name.endswith('_field') and field not in fields:
                raise HTTPException(422, f'Configured field {field} is missing from its source module.')
    return config, modules


def _entries(business_id, module_id, restricted, user):
    table = 'restricted_module_entries' if restricted else 'module_entries'
    rows = []
    for offset in range(0, 200001, 1000):
        page = _read(f'/{table}?business_id=eq.{key(business_id)}&module_id=eq.{key(module_id)}'
                     f'&status=eq.active&select=id,data&order=id.asc&limit=1000&offset={offset}')
        rows.extend(page)
        if len(rows) > 200000:
            raise HTTPException(422, 'The source is too large for one report. Split the reporting source.')
        if len(page) < 1000:
            break
    if restricted:
        from restricted_modules import _audit
        _audit(key(business_id), key(module_id), None, user, 'list', {'purpose': 'program_outcomes', 'count': len(rows)})
    return rows


def preview(business_id, config, user):
    config, modules = authorize_sources(business_id, config, user)
    source_rows = {module_id: _entries(business_id, module_id, restricted, user)
                   for module_id, (_, restricted) in modules.items()}
    enrollment = config.enrollment
    people = []
    for row in source_rows[str(enrollment.module_id)]:
        data = row.get('data') or {}
        # Cohort membership must be exact; another cohort never enters the result.
        if data.get(enrollment.cohort_field) != config.definition.cohort:
            continue
        people.append({'subject_id': data.get(enrollment.subject_field),
                       'cohort': data.get(enrollment.cohort_field),
                       'status': data.get(enrollment.status_field), 'source_id': row['id']})
    subjects = {p['subject_id'] for p in people if isinstance(p['subject_id'], str)}
    observations = []
    for source in config.measurements:
        for row in source_rows[str(source.module_id)]:
            data = row.get('data') or {}
            subject = data.get(source.subject_field)
            if not isinstance(subject, str) or subject not in subjects:
                continue
            value = data.get(source.value_field)
            # An empty measurement is absent; zero is a real observation.
            if value is None or value == '':
                continue
            observations.append({'source_id': f'{row["id"]}:{source.metric}',
                'subject_id': data.get(source.subject_field), 'metric': source.metric,
                'observed_on': data.get(source.date_field), 'value': value})
    try:
        result = calculate(config.definition, people, observations)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {'configuration': config.model_dump(mode='json'), 'snapshot': result}


def create_report(business_id, config, user):
    role(business_id, user, 'manager')
    result = preview(business_id, config, user)
    row = sb_clients.sb_post_as_service('/program_outcome_reports', {
        'business_id': key(business_id), 'configuration': result['configuration'],
        'snapshot': result['snapshot'], 'content_hash': result['snapshot']['content_hash'],
        'created_by': str(user.id), 'status': 'draft'})
    if isinstance(row, list):
        row = row[0] if row else None
    if not row:
        raise HTTPException(503, 'The report snapshot could not be saved.')
    return row


def load_report(business_id, report_id, user):
    role(business_id, user)
    rows = _read(f'/program_outcome_reports?id=eq.{key(report_id)}&business_id=eq.{key(business_id)}&select=*&limit=1')
    if not rows:
        raise HTTPException(404, 'Outcome report not found.')
    row = rows[0]
    _, modules = authorize_sources(business_id, row['configuration'], user, validate_fields=False)
    for module_id, (_, restricted) in modules.items():
        if restricted:
            from restricted_modules import _audit
            _audit(key(business_id), module_id, None, user, 'read',
                   {'purpose': 'program_outcome_snapshot', 'report_id': key(report_id)})
    return row


def approve_report(business_id, report_id, content_hash, user):
    role(business_id, user, 'manager')
    report = load_report(business_id, report_id, user)
    if report['content_hash'] != content_hash:
        raise HTTPException(409, 'The reviewed report does not match this snapshot.')
    rows = sb_clients.sb_post_as_service('/rpc/approve_program_outcome_report', {
        'p_business_id': key(business_id), 'p_report_id': key(report_id),
        'p_content_hash': content_hash, 'p_actor_id': str(user.id)})
    row = rows[0] if isinstance(rows, list) and rows else rows
    if not row:
        raise HTTPException(503, 'Report approval could not be saved.')
    if row.get('conflict'):
        raise HTTPException(409, 'The report changed or is not available for approval.')
    return row


def csv_export(report):
    """Portable participant rows, including missing data and exact provenance."""
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(['report_id', 'content_hash', 'approval_status', 'cohort', 'participant_id',
                     'enrollment_source_id', 'participant_status', 'metric', 'baseline_date',
                     'baseline', 'baseline_source', 'followup_date', 'followup', 'followup_source',
                     'change', 'improvement', 'paired', 'followup_reached'])
    def safe(value):
        text = '' if value is None else str(value)
        # Neutralize spreadsheet formulas without changing numeric negatives.
        if text.lstrip().startswith(('=', '+', '-', '@')):
            try:
                from decimal import Decimal
                if not Decimal(text).is_finite():
                    raise ValueError()
            except Exception:
                return "'" + text
        return text
    snapshot = report['snapshot']
    for metric in snapshot['metrics']:
        for p in metric['participants']:
            a, b = p['baseline'] or {}, p['followup'] or {}
            values = [report['id'], report['content_hash'], report['status'], snapshot['definition']['cohort'],
                p['subject_id'], p['enrollment_source_id'], p['status'], metric['metric']['label'],
                a.get('observed_on'), a.get('value'), a.get('source_id'), b.get('observed_on'),
                b.get('value'), b.get('source_id'), p['change'], p['improvement'], p['paired'], p['followup_reached']]
            writer.writerow([safe(v) for v in values])
    return stream.getvalue().encode('utf-8-sig')
