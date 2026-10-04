import csv
import io
from datetime import datetime, timezone
from uuid import UUID
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import acuity_migration as am
import acuity_migration_router as ar

BIZ = UUID('11111111-1111-4111-8111-111111111111')
OWNER = UUID('22222222-2222-4222-8222-222222222222')
OFFER = '33333333-3333-4333-8333-333333333333'
BATCH = '44444444-4444-4444-8444-444444444444'
NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)
HEADERS = ['Appointment ID', 'First Name', 'Last Name', 'Email', 'Start Time', 'End Time',
           'Time Zone', 'Appointment Type', 'Calendar', 'Price', 'Paid', 'Amount Paid Online', 'Notes']
BASE = ['123', 'Jamie', 'Rivera', 'jamie@example.com', '2027-01-04 09:00', '2027-01-04 10:00',
        'America/New_York', 'Coaching', 'Main', '75.00', 'yes', '25.00', 'Client supplied note']


def file(rows, headers=HEADERS):
    buf = io.StringIO()
    out = csv.writer(buf)
    out.writerow(headers)
    out.writerows(rows)
    return buf.getvalue()


def plan(rows=None, **kw):
    defaults = dict(zone='America/New_York', date_order='month_first', mappings={'Coaching': OFFER},
                    offerings=[{'id': OFFER, 'is_active': True}], active_only_confirmed=True, now=NOW)
    defaults.update(kw)
    return am.plan_files('', file(rows or [BASE]), **defaults)


def test_realistic_export_preserves_paid_record_and_source_without_inventing_payment():
    p = plan()
    assert p['ready']
    a = p['appointments'][0]
    assert (a['start'], a['duration'], a['price'], a['paid_online'], a['paid']) == ('2027-01-04T14:00:00Z', 60, '75.00', '25.00', True)
    assert a['source']['Notes'] == 'Client supplied note'
    assert p['reminders'] == 'paused'
    assert len(p['clients']) == 1
    assert 'payment_intent' not in a


@pytest.mark.parametrize('value', ['2026-03-08 02:30', '2026-11-01 01:30'])
def test_dst_gap_and_fold_cannot_be_guessed(value):
    with pytest.raises(am.MigrationError, match='daylight-saving'):
        am.timestamp(value, 'America/New_York', 'month_first')


def test_explicit_offset_resolves_fold_and_date_order_is_explicit():
    assert am.timestamp('2026-11-01T01:30:00-04:00', 'America/New_York', 'month_first').hour == 5
    assert am.timestamp('04/05/2027 9:00 AM', 'UTC', 'day_first').month == 5
    assert am.timestamp('04/05/2027 9:00 AM', 'UTC', 'month_first').month == 4


@pytest.mark.parametrize('text', ['Name,Name\na,b', 'Name,Email\na', 'Name,\na,b', 'Name\n"unterminated', 'a\x00b'])
def test_invalid_csv_is_not_partially_imported(text):
    with pytest.raises(am.MigrationError):
        am.read_csv(text)


def test_bom_quoted_multiline_and_unknown_fields_survive():
    row = BASE.copy()
    row[-1] = 'A comma, and\na second line'
    p = am.plan_files('', '\ufeff' + file([row]), zone='UTC', date_order='month_first',
                      mappings={'Coaching': OFFER}, offerings=[{'id': OFFER, 'is_active': True}],
                      active_only_confirmed=True, now=NOW)
    assert p['appointments'][0]['source']['Notes'] == row[-1]


@pytest.mark.parametrize('column,value,reason', [
    (0, '', 'Appointment ID'), (3, 'bad', 'email'), (4, 'tomorrow', 'date/time'),
    (5, '2027-01-04 08:00', 'minutes'), (6, 'Eastern', 'time zone'),
    (9, '$75', 'plain number'), (10, 'maybe', 'payment status'),
])
def test_bad_row_has_specific_issue_and_cannot_commit(column, value, reason):
    row = BASE.copy(); row[column] = value
    p = plan([row])
    assert not p['ready'] and reason in p['issues'][0]['message']
    assert not p['appointments']


def test_service_must_belong_to_active_catalog():
    assert not plan(offerings=[])['ready']
    assert not plan(offerings=[{'id': OFFER, 'is_active': False}])['ready']


def test_cancelled_export_requires_explicit_confirmation_and_cannot_sneak_status():
    assert not plan(active_only_confirmed=False)['ready']
    p = am.plan_files('', file([BASE + ['canceled']], HEADERS + ['Status']), zone='UTC',
        date_order='month_first', mappings={'Coaching': OFFER}, offerings=[{'id': OFFER, 'is_active': True}],
        active_only_confirmed=True, now=NOW)
    assert not p['ready']


def test_overlaps_duplicate_ids_and_staff_calendars_are_blocked():
    assert not plan([BASE, BASE])['ready']
    second = BASE.copy(); second[0] = '124'; second[8] = 'Second staff'
    p = plan([BASE, second])
    assert any('calendar' in x['message'] for x in p['issues'])
    assert any('Overlaps' in x['message'] for x in p['issues'])


def test_back_to_back_is_not_overlap():
    second = BASE.copy(); second[0] = '124'; second[4] = '2027-01-04 10:00'; second[5] = '2027-01-04 11:00'
    assert plan([BASE, second])['ready']


def test_historical_is_a_time_classification_not_attendance():
    row = BASE.copy(); row[4] = '2025-01-01 09:00'; row[5] = '2025-01-01 10:00'
    a = plan([row])['appointments'][0]
    assert a['historical'] and 'completed' not in a


def test_duplicate_client_identity_needs_review():
    clients = file([['A', 'a@example.com'], ['B', 'a@example.com']], ['Name', 'Email'])
    p = am.plan_files(clients, '', zone='UTC', date_order='month_first', mappings={}, offerings=[], active_only_confirmed=False)
    assert not p['ready']


def test_file_limits_do_not_silently_truncate():
    with pytest.raises(am.MigrationError, match='500'):
        am.read_csv(file([BASE] * 501))


@pytest.fixture
def db(monkeypatch):
    written = []
    def get(path):
        if path.startswith('/businesses?'):
            return [{'id': str(BIZ), 'owner_id': str(OWNER), 'settings': {}}]
        if path.startswith('/offerings?'):
            return [{'id': OFFER, 'name': 'Coaching', 'is_active': True}]
        if path.startswith('/custom_modules?'):
            return [{'id': OFFER}]
        return []
    def post(path, payload):
        written.append((path, payload))
        return [{'id': BATCH}]
    monkeypatch.setattr(ar.sb_clients, 'sb_get_as_service', get)
    monkeypatch.setattr(ar.sb_clients, 'sb_post_as_service', post)
    return written, get


def request(**kwargs):
    data = dict(appointments_csv=file([BASE]), timezone='America/New_York', date_order='month_first',
                mappings={'Coaching': OFFER}, active_only_confirmed=True)
    data.update(kwargs)
    return ar.Review(**data)


def test_preview_only_saves_review_not_business_records(db):
    writes, _ = db
    out = ar.preview(BIZ, request(), SimpleNamespace(id=OWNER))
    assert out['ready'] and out['batch_id'] == BATCH
    assert [w[0] for w in writes] == ['/acuity_migration_batches']
    assert 'source' not in out['appointments'][0]


@pytest.mark.parametrize('flag', ['uses_staff_calendars','uses_classes','uses_subscriptions','has_prepaid_balances'])
def test_readiness_reports_real_dependencies_and_does_not_save_ready_review(db, flag):
    out = ar.preview(BIZ, request(**{flag: True}), SimpleNamespace(id=OWNER))
    assert not out['ready'] and not out['batch_id'] and not db[0]


def test_foreign_owner_cannot_even_inspect_file(db):
    with pytest.raises(HTTPException) as exc:
        ar.inspect(BIZ, ar.Files(clients_csv='Name,Email\nA,a@example.com'), SimpleNamespace(id=BIZ))
    assert exc.value.status_code == 403 and not db[0]


def test_failed_database_read_cannot_be_treated_as_no_conflicts(db, monkeypatch):
    _, original = db
    monkeypatch.setattr(ar.sb_clients, 'sb_get_as_service', lambda path: None if path.startswith('/sessions?') else original(path))
    with pytest.raises(HTTPException) as exc:
        ar.preview(BIZ, request(), SimpleNamespace(id=OWNER))
    assert exc.value.status_code == 503 and not db[0]


def test_existing_overlap_blocks_preview(db, monkeypatch):
    _, original = db
    monkeypatch.setattr(ar.sb_clients, 'sb_get_as_service', lambda path: [{'id': 'x','scheduled_for':'2027-01-04T14:30:00Z','duration_minutes':60}] if path.startswith('/sessions?') else original(path))
    out = ar.preview(BIZ, request(), SimpleNamespace(id=OWNER))
    assert not out['ready'] and any('overlaps' in x['message'] for x in out['issues'])


def test_commit_requires_review_and_passes_verified_owner(db):
    with pytest.raises(HTTPException):
        ar.commit(BIZ, ar.Commit(batch_id=BATCH), SimpleNamespace(id=OWNER))
    assert not db[0]


def test_lost_commit_response_recovers_receipt_without_reimport(db, monkeypatch):
    _, original = db
    receipt = {'batch_id': BATCH, 'appointments_imported': 1}
    monkeypatch.setattr(ar.sb_clients, 'sb_post_as_service', lambda *args: None)
    monkeypatch.setattr(ar.sb_clients, 'sb_get_as_service', lambda path: [{'state':'imported','receipt':receipt}] if path.startswith('/acuity_migration_batches?') else original(path))
    assert ar.commit(BIZ, ar.Commit(batch_id=BATCH, reviewed=True), SimpleNamespace(id=OWNER)) == receipt


def test_date_without_time_does_not_become_midnight():
    with pytest.raises(am.MigrationError, match='date/time'):
        am.timestamp('2027-01-04', 'UTC', 'month_first')


def test_enabling_reminders_requires_explicit_cutover_confirmation(db):
    with pytest.raises(HTTPException) as exc:
        ar.reminders(BIZ, ar.Reminders(batch_id=BATCH, enabled=True), SimpleNamespace(id=OWNER))
    assert exc.value.status_code == 422 and not db[0]


@pytest.mark.parametrize('enabled', [True, False])
def test_reminder_setting_uses_verified_owner_and_returns_durable_receipt(db, monkeypatch, enabled):
    receipt = {'batch_id': BATCH, 'reminders': 'enabled' if enabled else 'paused'}
    calls = []
    def post(path, payload):
        calls.append((path, payload))
        return receipt
    monkeypatch.setattr(ar.sb_clients, 'sb_post_as_service', post)
    assert ar.reminders(BIZ, ar.Reminders(batch_id=BATCH, enabled=enabled, cutover_confirmed=enabled), SimpleNamespace(id=OWNER)) == receipt
    assert calls == [('/rpc/acuity_migration_reminders', {
        'p_business': str(BIZ), 'p_owner': str(OWNER), 'p_batch': str(BATCH), 'p_enabled': enabled})]


def test_imported_session_is_skipped_before_any_reminder_send(monkeypatch):
    import asyncio
    import sms_alerts
    monkeypatch.setattr(sms_alerts, '_in_send_window', lambda: True)
    async def get(client, path):
        if path.startswith('/sessions?'):
            assert 'metadata' in path
            return [{'id': 'paused-session', 'metadata': {'migration_reminders_paused': True}}]
        return []
    async def send(*args, **kwargs):
        pytest.fail('An imported session sent a reminder before cutover')
    monkeypatch.setattr(sms_alerts, '_sb_get', get)
    monkeypatch.setattr(sms_alerts, '_send_platform_sms', send)
    out = asyncio.run(sms_alerts.reminder_sweep())
    assert out['sent'] == 0 and out['skipped_toggled_off'] == 1
