"""Customer-visible lifecycle failures, without sending real email."""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
import lifecycle_emails as le
import lifecycle_delivery as delivery
from lifecycle_delivery_fake import install_delivery_fake
from test_lifecycle_emails import fake, mail, owners, _biz, _iso, _stamps


def test_failed_welcome_is_recovered_and_not_repeated(fake, mail, owners, monkeypatch):
    row = _biz(fake, created_at=_iso(datetime.now(timezone.utc)-timedelta(hours=2)))
    mail.fail = True
    assert not asyncio.run(le.send_welcome(row, 'kim@example.com'))['sent']
    mail.fail = False
    assert asyncio.run(le.welcome_retry_tick())['sent'] == 1
    assert asyncio.run(le.welcome_retry_tick())['sent'] == 0
    assert len(mail.sent) == 1


def test_welcome_recovery_does_not_email_old_businesses(fake, mail, owners):
    _biz(fake, created_at=_iso(datetime.now(timezone.utc)-timedelta(days=30)))
    assert asyncio.run(le.welcome_retry_tick())['sent'] == 0
    assert mail.sent == []


def test_delivery_receipt_survives_a_failed_business_stamp(fake, mail, owners, monkeypatch):
    row = _biz(fake, created_at=_iso(datetime.now(timezone.utc)-timedelta(hours=2)))
    stamp = le._stamp
    monkeypatch.setattr(le, '_stamp', lambda *a: (_ for _ in ()).throw(RuntimeError('DB unavailable')))
    assert not asyncio.run(le.send_welcome(row, 'kim@example.com'))['sent']
    assert len(mail.sent) == 1
    monkeypatch.setattr(le, '_stamp', stamp)
    assert asyncio.run(le.welcome_retry_tick())['sent'] == 1
    assert len(mail.sent) == 1
    assert _stamps(fake)['welcome_at']


def test_ambiguous_acknowledgement_retries_the_identical_provider_request(monkeypatch):
    db = install_delivery_fake(monkeypatch)
    db.fail_finish = True
    send = AsyncMock(return_value={'id': 'provider-1'})
    monkeypatch.setattr('email_sender.send_via_resend', send)
    with pytest.raises(RuntimeError):
        asyncio.run(delivery.send_once('welcome/1', {'body': 'Original'}))
    db.fail_finish = False
    asyncio.run(delivery.send_once('welcome/1', {'body': 'New copy'}))
    assert send.call_args_list[0] == send.call_args_list[1]
    asyncio.run(delivery.send_once('welcome/1', {'body': 'New copy'}))
    assert send.call_count == 2


@pytest.mark.parametrize('state', ['sending', 'review'])
def test_claim_conflict_or_expired_retry_window_never_sends(monkeypatch, state):
    db = install_delivery_fake(monkeypatch)
    db.rows['a'] = {'state': state, 'payload': {}}
    send = AsyncMock()
    monkeypatch.setattr('email_sender.send_via_resend', send)
    with pytest.raises(RuntimeError):
        asyncio.run(delivery.send_once('a', {}))
    send.assert_not_called()


def test_signup_rechecks_completion_before_sending(monkeypatch):
    monkeypatch.delenv('LIFECYCLE_EMAILS', raising=False)
    candidate = {'user_id': 'one', 'email': 'one@example.com', 'kind': 'signup_day_one'}
    monkeypatch.setattr(delivery, 'rpc', lambda name, data: [] if data else [candidate])
    send = AsyncMock()
    monkeypatch.setattr(le, '_send', send)
    assert asyncio.run(le.signup_reminders_tick())['sent'] == 0
    send.assert_not_called()


def test_signup_uses_only_fresh_verified_recipient_and_bounded_stage(monkeypatch):
    monkeypatch.delenv('LIFECYCLE_EMAILS', raising=False)
    stale = {'user_id': 'one', 'email': 'old@example.com', 'kind': 'signup_day_one'}
    fresh = dict(stale, email='current@example.com', kind='signup_day_three')
    monkeypatch.setattr(delivery, 'rpc', lambda name, data: [fresh if data else stale])
    send = AsyncMock()
    monkeypatch.setattr(le, '_send', send)
    assert asyncio.run(le.signup_reminders_tick())['sent'] == 1
    args = send.call_args.kwargs
    assert args['to_email'] == 'current@example.com'
    assert args['delivery_key'].endswith('/signup_day_three')
    assert 'last setup reminder' in args['body']


@pytest.mark.parametrize('status', ['canceled', 'past_due', 'unpaid'])
def test_week_mail_stops_when_subscription_is_not_fully_accessible(monkeypatch, status):
    monkeypatch.setenv('BILLING_ENFORCE', 'on')
    monkeypatch.setattr(le, '_tank_spent', lambda row: False)
    now = datetime.now(timezone.utc)
    row = {'created_at': _iso(now-timedelta(days=7)), 'subscription_status': status}
    assert le._classify_week(row, now) is None


def test_week_mail_stops_when_trial_expires_or_credits_are_spent(monkeypatch):
    monkeypatch.setenv('BILLING_ENFORCE', 'on')
    now = datetime.now(timezone.utc)
    row = {'created_at': _iso(now-timedelta(days=7)), 'subscription_status': 'trialing',
           'trial_ends_at': _iso(now-timedelta(hours=1))}
    monkeypatch.setattr(le, '_tank_spent', lambda row: False)
    assert le._classify_week(row, now) is None
    row['trial_ends_at'] = _iso(now+timedelta(days=1))
    monkeypatch.setattr(le, '_tank_spent', lambda row: True)
    assert le._classify_week(row, now) is None


def test_branded_links_and_normal_punctuation_in_rendered_email_copy(monkeypatch):
    monkeypatch.setenv('APP_BASE_URL', 'https://solutionist-studio.vercel.app/')
    now = datetime.now(timezone.utc)
    common = {'business_name': 'Acme', 'first_name': 'Kim'}
    bodies = [le.welcome_body(**common), le.trial_ending_body(**common, days_left=2, ends_at=now),
              le.trial_ended_body(**common, reason='trial_expired'),
              le.trial_ended_body(**common, reason='trial_credits_spent'),
              le.day_three_body(**common, done=0, total=3, next_title='Contacts', next_why='People — history — invoices'),
              le.day_seven_body(**common, done=0, total=3, next_title='Contacts', site_url=None),
              le.day_seven_body(**common, done=3, total=3, next_title=None, site_url='https://example.com'),
              le.signup_reminder_body('Kim'), le.signup_reminder_body('Kim', final=True)]
    for body in bodies:
        assert '—' not in body and '–' not in body
        assert 'https://system.mysolutionist.app/' in body
        assert 'vercel.app' not in body


def test_scheduler_wires_recovery_and_reminders():
    source = (Path(__file__).parents[1]/'kmj_intake_automation.py').read_text(encoding='utf8')
    assert '_lifecycle.welcome_retry_tick' in source
    assert '_lifecycle.signup_reminders_tick' in source


def test_new_recipient_does_not_receive_a_frozen_old_recipient_retry(monkeypatch):
    db = install_delivery_fake(monkeypatch)
    db.rows['a'] = {'state': 'pending', 'payload': {'to_email': 'old@example.com'}}
    send = AsyncMock()
    monkeypatch.setattr('email_sender.send_via_resend', send)
    with pytest.raises(RuntimeError, match='recipient changed'):
        asyncio.run(delivery.send_once('a', {'to_email': 'new@example.com'}))
    send.assert_not_called()


def test_onboarding_enrollment_uses_the_authenticated_identity(monkeypatch):
    import launch_access
    calls = []
    def insert(path, data, **kwargs):
        calls.append((path, data, kwargs))
        return []
    monkeypatch.setattr(launch_access.sb_clients, 'sb_post_as_service', insert)
    user = type('User', (), {'id': 'signed-in-user'})()
    assert launch_access.onboarding_started(user) == {'ok': True}
    assert calls[0][1] == {'user_id': 'signed-in-user'}
    assert 'ignore-duplicates' in calls[0][2]['prefer']


def test_sender_forwards_provider_idempotency_header(monkeypatch):
    import email_sender
    payloads = []
    class Response:
        status_code = 200
        def json(self): return {'id': 'm1'}
    class Client:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kw):
            payloads.append(kw)
            return Response()
    monkeypatch.setenv('RESEND_API_KEY', 'test-only')
    monkeypatch.setattr(email_sender, 'is_suppressed', AsyncMock(return_value=None))
    monkeypatch.setattr(email_sender, '_apply_business_identity', AsyncMock(return_value=('noreply@mysolutionist.app','The Solutionist System')))
    monkeypatch.setattr(email_sender, '_business_row_for_send', AsyncMock(return_value=None))
    monkeypatch.setattr(email_sender.httpx, 'AsyncClient', Client)
    asyncio.run(email_sender.send_via_resend(to_email='test@example.com', to_name=None,
        from_email='noreply@mysolutionist.app',from_name='The Solutionist System',
        subject='Setup',body='Hello',reply_to='info@mysolutionist.app',idempotency_key='lifecycle/test'))
    assert payloads[0]['headers']['Idempotency-Key'] == 'lifecycle/test'
