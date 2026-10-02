from copy import deepcopy
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
import csv
import io

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

import program_outcomes_service as service
import program_outcomes_router as router
import restricted_modules
from auth_supabase import require_user

BIZ, ENROLL, READINGS, REPORT = [f'00000000-0000-4000-8000-{i:012d}' for i in range(1, 5)]
OWNER, MANAGER, MEMBER, VIEWER, FOREIGN = [f'00000000-0000-4000-8000-{i:012d}' for i in range(5, 10)]


@pytest.fixture
def store(monkeypatch):
    fields = [{'name': n} for n in ['person', 'cohort', 'status', 'date', 'value']]
    state = {'calls': [], 'roles': {MANAGER: 'manager', MEMBER: 'member', VIEWER: 'viewer'},
             'restricted': False, 'minimum': 'manager', 'reports': [],
             'enrollments': [{'id': 'enroll-1', 'data': {'person': 'student-private-id', 'cohort': 'Fall', 'status': 'active'}}],
             'readings': [{'id': 'reading-1', 'data': {'person': 'student-private-id', 'date': '2026-09-01', 'value': 600}},
                          {'id': 'reading-2', 'data': {'person': 'student-private-id', 'date': '2026-10-01', 'value': 680}}]}
    def get(path):
        state['calls'].append(path)
        parsed = urlparse(path)
        q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        if parsed.path == '/businesses':
            return [{'id': BIZ, 'owner_id': OWNER, 'name': 'Example Organization'}] if q.get('id') == 'eq.' + BIZ else []
        if parsed.path == '/business_users':
            uid = q['user_id'].removeprefix('eq.')
            return [{'role': state['roles'][uid]}] if q['business_id'] == 'eq.' + BIZ and uid in state['roles'] else []
        if parsed.path == '/custom_modules':
            if q['business_id'] != 'eq.' + BIZ or q['id'].removeprefix('eq.') not in (ENROLL, READINGS):
                return []
            restricted = state['restricted'] and q['id'] == 'eq.' + READINGS
            return [{'id': q['id'][3:], 'schema': {'fields': fields},
                     'agent_config': {'access_level': 'restricted' if restricted else 'standard'},
                     'restricted_min_role': state['minimum']}]
        if parsed.path in ('/module_entries', '/restricted_module_entries'):
            assert q['business_id'] == 'eq.' + BIZ
            assert q['status'] == 'eq.active'
            return deepcopy(state['enrollments' if q['module_id'] == 'eq.' + ENROLL else 'readings'])
        if parsed.path == '/program_outcome_reports':
            if q['business_id'] != 'eq.' + BIZ:
                return []
            return deepcopy([r for r in state['reports'] if 'id' not in q or q['id'] == 'eq.' + r['id']])
        raise AssertionError(path)
    def post(path, body):
        if path == '/program_outcome_reports':
            row = dict(deepcopy(body), id=REPORT, created_at='2026-10-20T12:00:00Z')
            state['reports'].append(row)
            return [deepcopy(row)]
        if path == '/rpc/approve_program_outcome_report':
            row = state['reports'][0]
            assert body['p_business_id'] == BIZ and body['p_content_hash'] == row['content_hash']
            row.update(status='approved', approved_by=body['p_actor_id'], approved_at='2026-10-20T12:05:00Z')
            return deepcopy(row)
        raise AssertionError(path)
    monkeypatch.setattr(service.sb_clients, 'sb_get_as_service', get)
    monkeypatch.setattr(service.sb_clients, 'sb_post_as_service', post)
    monkeypatch.setattr(restricted_modules, '_sb', lambda method, path, *a, **k: get(path) if method == 'GET' else None)
    return state


def config():
    return service.Configuration.model_validate({'definition': {'title': 'Outcomes', 'cohort': 'Fall',
        'baseline_start': '2026-09-01', 'baseline_end': '2026-09-07',
        'followup_start': '2026-10-01', 'followup_end': '2026-10-14',
        'metrics': [{'key': 'credit', 'label': 'Credit score', 'target': 680}]},
        'enrollment': {'module_id': ENROLL, 'subject_field': 'person', 'cohort_field': 'cohort', 'status_field': 'status'},
        'measurements': [{'module_id': READINGS, 'metric': 'credit', 'subject_field': 'person', 'date_field': 'date', 'value_field': 'value'}]})


def user(uid):
    return SimpleNamespace(id=uid, email='staff@example.test')


@pytest.mark.parametrize('uid', [VIEWER, FOREIGN])
def test_denied_staff_never_read_entries(store, uid):
    with pytest.raises(HTTPException) as exc:
        service.preview(BIZ, config(), user(uid))
    assert exc.value.status_code == 403
    assert not any('module_entries?' in p for p in store['calls'])


def test_restricted_role_checked_before_any_entries(store):
    store['restricted'] = True
    with pytest.raises(HTTPException) as exc:
        service.preview(BIZ, config(), user(MEMBER))
    assert exc.value.status_code == 403
    assert not any('module_entries?' in p for p in store['calls'])
    result = service.preview(BIZ, config(), user(MANAGER))
    assert result['snapshot']['metrics'][0]['mean_change_paired'] == '80.00'
    assert any('/restricted_module_entries?' in p for p in store['calls'])


def test_owner_only_restriction_cannot_be_bypassed_by_manager(store):
    store.update(restricted=True, minimum=None)
    with pytest.raises(HTTPException):
        service.preview(BIZ, config(), user(MANAGER))
    assert service.preview(BIZ, config(), user(OWNER))['snapshot']['included_count'] == 1


def test_foreign_source_rejected_before_data_load(store):
    cfg = config().model_dump(mode='json')
    cfg['measurements'][0]['module_id'] = FOREIGN
    with pytest.raises(HTTPException) as exc:
        service.preview(BIZ, cfg, user(OWNER))
    assert exc.value.status_code == 404
    assert not any('module_entries?' in p for p in store['calls'])


def test_snapshot_is_frozen_and_approval_bound_to_reviewed_hash(store):
    report = service.create_report(BIZ, config(), user(MANAGER))
    store['readings'][1]['data']['value'] = 750
    loaded = service.load_report(BIZ, REPORT, user(MANAGER))
    assert loaded['snapshot']['metrics'][0]['mean_change_paired'] == '80.00'
    with pytest.raises(HTTPException) as exc:
        service.approve_report(BIZ, REPORT, '0' * 64, user(MANAGER))
    assert exc.value.status_code == 409
    approved = service.approve_report(BIZ, REPORT, report['content_hash'], user(MANAGER))
    assert approved['status'] == 'approved'
    assert approved['approved_by'] == MANAGER


def test_revoked_staff_and_new_restrictions_protect_existing_snapshots(store):
    service.create_report(BIZ, config(), user(MANAGER))
    del store['roles'][MANAGER]
    with pytest.raises(HTTPException) as exc:
        service.load_report(BIZ, REPORT, user(MANAGER))
    assert exc.value.status_code == 403
    store.update(restricted=True, minimum=None)
    with pytest.raises(HTTPException):
        service.load_report(BIZ, REPORT, user(MEMBER))


def test_member_can_preview_but_cannot_create_or_approve(store):
    assert service.preview(BIZ, config(), user(MEMBER))['snapshot']['included_count'] == 1
    with pytest.raises(HTTPException):
        service.create_report(BIZ, config(), user(MEMBER))


def test_storage_failure_never_returns_empty_success(store, monkeypatch):
    monkeypatch.setattr(service.sb_clients, 'sb_get_as_service', lambda path: None)
    with pytest.raises(HTTPException) as exc:
        service._entries(BIZ, READINGS, False, user(OWNER))
    assert exc.value.status_code == 503


def test_csv_retains_missing_and_source_references_and_neutralizes_formulas(store):
    store['enrollments'][0]['data']['person'] = '=HYPERLINK("https://invalid.test")'
    store['readings'] = []
    report = service.create_report(BIZ, config(), user(OWNER))
    rows = list(csv.DictReader(io.StringIO(service.csv_export(report).decode('utf-8-sig'))))
    assert rows[0]['participant_id'].startswith("'=")
    assert rows[0]['baseline'] == rows[0]['followup'] == ''
    assert rows[0]['enrollment_source_id'] == 'enroll-1'
    assert rows[0]['content_hash'] == report['content_hash']


def test_pdf_is_aggregate_only_with_missing_counts_and_draft_status(store):
    from program_outcomes_pdf import render
    from pypdf import PdfReader
    report = service.create_report(BIZ, config(), user(OWNER))
    content = render(report, 'Example Organization')
    text = ''.join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)
    assert 'NOT APPROVED' in text
    assert 'Missing baseline / follow-up' in text
    assert '80.00' in text
    assert 'student-private-id' not in text
    assert 'reading-1' not in text


def test_long_pdf_page_numbers_use_final_total(store):
    from program_outcomes_pdf import render
    from pypdf import PdfReader
    report = service.create_report(BIZ, config(), user(OWNER))
    report['snapshot']['metrics'] *= 8
    pages = PdfReader(io.BytesIO(render(report, 'Example Organization'))).pages
    assert len(pages) > 1
    for index, page in enumerate(pages, 1):
        assert f'Page {index} of {len(pages)}' in page.extract_text()


def test_export_http_rechecks_permission_and_disables_caching(store):
    service.create_report(BIZ, config(), user(OWNER))
    app = FastAPI()
    app.include_router(router.router)
    app.dependency_overrides[require_user] = lambda: user(MEMBER)
    client = TestClient(app)
    response = client.get(f'/program-outcomes/{BIZ}/reports/{REPORT}/export.csv')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    del store['roles'][MEMBER]
    assert client.get(f'/program-outcomes/{BIZ}/reports/{REPORT}/export.pdf').status_code == 403


def test_invalid_foreign_observation_subject_is_ignored_safely(store):
    store['readings'].append({'id': 'junk', 'data': {'person': {'invalid': True}, 'value': 50}})
    assert service.preview(BIZ, config(), user(OWNER))['snapshot']['metrics'][0]['paired_count'] == 1
