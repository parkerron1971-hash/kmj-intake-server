"""Lifecycle emails — welcome, trial ending, trial ended.

The failure this module exists to fix is silence: a trial lapsing with
no warning. So the tests that matter are (1) each email goes out at its
moment, (2) each goes out ONCE, (3) the sweep stays quiet where a lock
never happens, and (4) nothing raises out of a signup or a scheduler
tick. The send seam is the real `email_sender.send_via_resend` name —
a fake wired one layer closer would pass with the seam unplugged.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timedelta, timezone

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import lifecycle_emails as le  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _Mail:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    async def send(self, **kw):
        if self.fail:
            raise RuntimeError("resend down")
        self.sent.append(kw)
        return {"id": f"m{len(self.sent)}"}


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.delenv("LIFECYCLE_EMAILS", raising=False)
    monkeypatch.delenv("LIFECYCLE_TRIAL_ENDING_DAYS", raising=False)
    return fb


@pytest.fixture
def mail(monkeypatch):
    m = _Mail()
    import email_sender
    monkeypatch.setattr(email_sender, "send_via_resend", m.send)
    return m


@pytest.fixture
def owners(monkeypatch):
    """Auth Admin is a network hop; the sweep asks it by owner_id."""
    table = {"own1": "kim@example.com", "own2": "lee@example.com"}

    async def lookup(owner_id):
        return table.get(owner_id)

    monkeypatch.setattr(le, "_owner_email", lookup)
    import usage_metering
    monkeypatch.setattr(usage_metering, "is_grandfathered_user",
                        lambda uid: uid == "gf")
    monkeypatch.setattr(usage_metering, "trial_credits_exhausted",
                        lambda biz_id, row=None: False)
    return table


def _biz(fb, **over):
    row = {"id": "b1", "name": "Northside Cuts", "type": "barber",
           "owner_id": "own1", "subscription_status": "trialing",
           "trial_ends_at": _iso(_now() + timedelta(days=1, hours=6)),
           "comp_tier": None, "settings": {"theme": "ledger"},
           "is_active": True}
    row.update(over)
    fb.rows("businesses").append(row)
    return row


def _stamps(fb, biz_id="b1"):
    row = [r for r in fb.rows("businesses") if r["id"] == biz_id][0]
    return (row.get("settings") or {}).get(le.SETTINGS_KEY) or {}


# ─── Welcome ─────────────────────────────────────────────────────────

def test_welcome_goes_to_the_signup_email_and_stamps_once(fake, mail):
    row = _biz(fake, trial_ends_at=None, subscription_status=None)
    out = asyncio.run(le.send_welcome(row, "kim@example.com", "Kim Ortiz"))
    assert out["sent"] is True
    assert len(mail.sent) == 1
    m = mail.sent[0]
    assert m["to_email"] == "kim@example.com"
    assert "Northside Cuts" in m["subject"]
    assert "Hi Kim," in m["body"]
    assert le.app_base_url() in m["body"]
    assert m["reply_to"]                      # a person reads replies
    assert _stamps(fake)["welcome_at"]
    # Theme survived the stamp — settings were merged, not replaced.
    assert fake.rows("businesses")[0]["settings"]["theme"] == "ledger"

    again = asyncio.run(le.send_welcome(fake.rows("businesses")[0],
                                        "kim@example.com", "Kim"))
    assert again["sent"] is False and again["reason"] == "already_sent"
    assert len(mail.sent) == 1


def test_welcome_is_for_the_first_business_only(fake, mail):
    _biz(fake, id="b0", trial_ends_at=None)          # already had one
    second = _biz(fake, id="b1", name="Second Shop", trial_ends_at=None)
    out = asyncio.run(le.send_welcome(second, "kim@example.com", "Kim"))
    assert out["sent"] is False and out["reason"] == "not_first_business"
    assert mail.sent == []


def test_welcome_never_raises_and_leaves_no_stamp_on_failure(fake, monkeypatch):
    import email_sender
    monkeypatch.setattr(email_sender, "send_via_resend", _Mail(fail=True).send)
    row = _biz(fake, trial_ends_at=None)
    out = asyncio.run(le.send_welcome(row, "kim@example.com", "Kim"))
    assert out["sent"] is False and out["reason"] == "error"
    assert "welcome_at" not in _stamps(fake)


def test_welcome_honours_the_kill_switch(fake, mail, monkeypatch):
    monkeypatch.setenv("LIFECYCLE_EMAILS", "off")
    row = _biz(fake, trial_ends_at=None)
    out = asyncio.run(le.send_welcome(row, "kim@example.com", "Kim"))
    assert out["sent"] is False and out["reason"] == "disabled"
    assert mail.sent == []


def test_create_business_schedules_the_welcome_after_the_response(fake, monkeypatch):
    """The door: launch_access hands the row to send_welcome as a
    background task, with the signup email and the practitioner's name
    from the onboarding settings. With no BackgroundTasks (older
    callers, tests) it schedules nothing and still creates the business."""
    import launch_access as la
    monkeypatch.delenv("LAUNCH_INVITE_ONLY", raising=False)
    import usage_metering
    monkeypatch.setattr(usage_metering, "is_grandfathered_user", lambda uid: True)

    class _BG:
        def __init__(self):
            self.tasks = []

        def add_task(self, fn, *a, **kw):
            self.tasks.append((fn, a, kw))

    user = type("U", (), {"id": "own1", "email": "kim@example.com"})()
    body = la.CreateBusinessBody(name="Northside Cuts", type="barber",
                                 settings={"practitioner_name": "Kim Ortiz"})
    bg = _BG()
    out = la.create_business(body, user, bg)
    assert out["ok"]
    welcome = [t for t in bg.tasks if t[0] is le.send_welcome]
    assert len(welcome) == 1
    fn, args, _ = welcome[0]
    assert args[0]["name"] == "Northside Cuts"
    assert args[1] == "kim@example.com"
    assert args[2] == "Kim Ortiz"

    out2 = la.create_business(body, user, None)
    assert out2["ok"]


# ─── Trial ending ────────────────────────────────────────────────────

def test_trial_ending_sends_once_inside_the_window(fake, mail, owners):
    _biz(fake)                                       # ends in ~1.25 days
    out = asyncio.run(le.sweep_tick())
    assert out["ok"] and out["sent"] == 1 and out["sent_kinds"] == ["trial_ending"]
    m = mail.sent[0]
    assert m["to_email"] == "kim@example.com"
    assert "tomorrow" in m["subject"]
    assert "settings=billing" in m["body"]
    assert _stamps(fake)["trial_ending_at"]

    out2 = asyncio.run(le.sweep_tick())              # next day's pass
    assert out2["sent"] == 0 and len(mail.sent) == 1


def test_trial_ending_waits_until_the_window(fake, mail, owners):
    _biz(fake, trial_ends_at=_iso(_now() + timedelta(days=5)))
    out = asyncio.run(le.sweep_tick())
    assert out["sent"] == 0 and mail.sent == []
    assert _stamps(fake) == {}


def test_trial_mail_skips_comped_and_grandfathered(fake, mail, owners):
    _biz(fake, id="b1", comp_tier="professional")
    _biz(fake, id="b2", owner_id="gf")
    out = asyncio.run(le.sweep_tick())
    assert out["scanned"] == 2 and out["sent"] == 0 and mail.sent == []


# ─── Trial ended ─────────────────────────────────────────────────────

def test_trial_ended_on_the_calendar_sends_once(fake, mail, owners):
    _biz(fake, trial_ends_at=_iso(_now() - timedelta(hours=20)))
    out = asyncio.run(le.sweep_tick())
    assert out["sent"] == 1 and out["sent_kinds"] == ["trial_ended"]
    assert "has ended" in mail.sent[0]["subject"]
    assert "export" in mail.sent[0]["body"].lower()
    assert _stamps(fake)["trial_ended_at"]
    assert asyncio.run(le.sweep_tick())["sent"] == 0


def test_trial_ended_is_not_a_backfill(fake, mail, owners):
    """First deploy: a trial that lapsed weeks ago gets nothing."""
    _biz(fake, trial_ends_at=_iso(_now() - timedelta(days=le.ENDED_LOOKBACK_DAYS + 2)))
    out = asyncio.run(le.sweep_tick())
    assert out["sent"] == 0 and mail.sent == []


def test_trial_ended_by_the_tank_beats_the_calendar(fake, mail, owners, monkeypatch):
    """Credits ran out with days left — and AFTER the ending-soon mail
    already went. The ended mail must still go, and say why."""
    _biz(fake, trial_ends_at=_iso(_now() + timedelta(days=1)),
         settings={le.SETTINGS_KEY: {"trial_ending_at": "2026-09-01T00:00:00Z"}})
    import usage_metering
    monkeypatch.setattr(usage_metering, "trial_credits_exhausted",
                        lambda biz_id, row=None: True)
    out = asyncio.run(le.sweep_tick())
    assert out["sent_kinds"] == ["trial_ended"]
    assert "allowance" in mail.sent[0]["body"]
    assert asyncio.run(le.sweep_tick())["sent"] == 0


def test_canceled_at_trial_end_counts_as_ended(fake, mail, owners):
    _biz(fake, id="b1", subscription_status="canceled",
         trial_ends_at=_iso(_now() - timedelta(days=1)))
    _biz(fake, id="b2", subscription_status="canceled",
         trial_ends_at=_iso(_now() - timedelta(days=30)))   # old churn, not a trial
    out = asyncio.run(le.sweep_tick())
    assert out["sent"] == 1 and mail.sent[0]["to_email"] == "kim@example.com"


def test_active_subscriptions_are_never_scanned(fake, mail, owners):
    _biz(fake, subscription_status="active",
         trial_ends_at=_iso(_now() - timedelta(hours=1)))
    out = asyncio.run(le.sweep_tick())
    assert out["scanned"] == 0 and mail.sent == []


# ─── Quiet where a lock never happens; loud nowhere ──────────────────

def test_sweep_is_silent_while_enforcement_is_off(fake, mail, owners, monkeypatch):
    monkeypatch.setenv("BILLING_ENFORCE", "off")
    _biz(fake, trial_ends_at=_iso(_now() - timedelta(hours=2)))
    out = asyncio.run(le.sweep_tick())
    assert out["ok"] is False and out["reason"] == "enforcement_off"
    assert mail.sent == []


def test_sweep_kill_switch(fake, mail, owners, monkeypatch):
    monkeypatch.setenv("LIFECYCLE_EMAILS", "off")
    _biz(fake)
    out = asyncio.run(le.sweep_tick())
    assert out["reason"] == "disabled" and mail.sent == []


def test_a_failed_send_is_retried_next_pass_not_stamped(fake, owners, monkeypatch):
    import email_sender
    failing = _Mail(fail=True)
    monkeypatch.setattr(email_sender, "send_via_resend", failing.send)
    _biz(fake)
    out = asyncio.run(le.sweep_tick())                # must not raise
    assert out["failed"] == 1 and out["sent"] == 0
    assert _stamps(fake) == {}

    good = _Mail()
    monkeypatch.setattr(email_sender, "send_via_resend", good.send)
    out2 = asyncio.run(le.sweep_tick())
    assert out2["sent"] == 1 and len(good.sent) == 1


def test_sweep_survives_a_dead_database(fake, mail, owners, monkeypatch):
    import sb_clients

    def boom(path):
        raise RuntimeError("postgrest 503")

    monkeypatch.setattr(sb_clients, "sb_get_as_service", boom)
    out = asyncio.run(le.sweep_tick())
    assert out["ok"] is False and out["reason"].startswith("read_failed")


def test_no_owner_email_means_skip_not_crash(fake, mail, owners):
    _biz(fake, owner_id="nobody")
    out = asyncio.run(le.sweep_tick())
    assert out["skipped"] == 1 and out["sent"] == 0 and mail.sent == []


def test_scheduler_registers_the_daily_pass():
    """The job exists in the boot file — a module nobody schedules is a
    module that never runs (interval-jobs-never-fire class)."""
    src = (_here.parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert 'id="lifecycle_emails"' in src
    assert "_lifecycle.sweep_tick" in src
