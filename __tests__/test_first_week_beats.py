"""The week (Wave C, 2026-09-02): the launch script is said once, Chief's
greeting knows the day for days two to seven, and the day-three and
day-seven emails go out once each with ONE ask built from the same
plug-in probes Chief reads.
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

import chief_of_staff as cos  # noqa: E402
import first_run_arc as fra  # noqa: E402
import lifecycle_emails as le  # noqa: E402
import sb_clients  # noqa: E402
from test_first_run_concierge import _ctx as concierge_ctx  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402

NOW = datetime(2026, 9, 5, 14, 45, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class _Mail:
    def __init__(self):
        self.sent = []

    async def send(self, **kw):
        self.sent.append(kw)
        return {"id": f"m{len(self.sent)}"}


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.delenv("LIFECYCLE_EMAILS", raising=False)
    monkeypatch.setattr(le, "_now", lambda: NOW)
    return fb


@pytest.fixture
def mail(monkeypatch):
    m = _Mail()
    import email_sender
    monkeypatch.setattr(email_sender, "send_via_resend", m.send)
    return m


@pytest.fixture
def owners(monkeypatch):
    async def lookup(owner_id):
        return {"own1": "kim@example.com"}.get(owner_id)
    monkeypatch.setattr(le, "_owner_email", lookup)
    monkeypatch.setattr(le, "_is_grandfathered", lambda oid: False)


def _biz(fake, *, days_old: float, stamps=None, **over):
    row = {"id": over.pop("id", "b1"), "name": "Fade Society", "type": "personal_services",
           "owner_id": "own1", "subscription_status": "trialing", "trial_ends_at": None,
           "comp_tier": None, "created_at": _iso(NOW - timedelta(days=days_old)),
           "settings": {"practitioner_name": "Marcus Reed",
                        "lifecycle_emails": dict(stamps or {})},
           "is_active": True, "stripe_account_id": None}
    row.update(over)
    fake.post("/businesses", row)
    return row


def _plugins(monkeypatch, done=1, total=4):
    import business_track_router as btr
    items = [{"key": "import_contacts", "title": "Bring your client list over", "why": "first domino",
              "nav": {"tab": "operate", "sub": "contacts"}, "done": done >= 1, "blocked_by": []},
             {"key": "offerings", "title": "Load what you sell", "why": "prices drive everything",
              "nav": {"tab": "operate", "sub": "offerings-manager"}, "done": done >= 2, "blocked_by": []},
             {"key": "availability", "title": "Set the hours you actually work", "why": "booking",
              "nav": {"tab": "build", "page": "booking"}, "done": done >= 3, "blocked_by": []},
             {"key": "site", "title": "Put your site up", "why": "front door",
              "nav": {"tab": "build", "page": "my-site"}, "done": done >= 4, "blocked_by": []}][:total]
    monkeypatch.setattr(btr, "resolve_plugins", lambda biz: items)


# ─── classification ──────────────────────────────────────────────────────

class TestClassify:
    def test_day_three_window_then_stamp(self):
        row = {"created_at": _iso(NOW - timedelta(days=3)), "settings": {}}
        assert le._classify_week(row, NOW) == "day_three"
        row["settings"] = {"lifecycle_emails": {"day_three_at": "x"}}
        assert le._classify_week(row, NOW) is None

    def test_day_seven_window(self):
        row = {"created_at": _iso(NOW - timedelta(days=7)), "settings": {"lifecycle_emails": {"day_three_at": "x"}}}
        assert le._classify_week(row, NOW) == "day_seven"
        row["settings"]["lifecycle_emails"]["day_seven_at"] = "y"
        assert le._classify_week(row, NOW) is None

    def test_outside_the_windows_is_quiet(self):
        for d in (0.5, 2.0, 5.5, 10.0):
            assert le._classify_week({"created_at": _iso(NOW - timedelta(days=d)), "settings": {}}, NOW) is None
        assert le._classify_week({"created_at": None, "settings": {}}, NOW) is None


# ─── the sweep ──────────────────────────────────────────────────────────

class TestWeekBeats:
    def test_day_three_says_where_they_are_and_one_thing(self, fake, mail, owners, monkeypatch):
        _biz(fake, days_old=3)
        _plugins(monkeypatch, done=1, total=4)
        out = asyncio.run(le.week_beats_tick())
        assert out["ok"] and out["sent"] == 1 and out["sent_kinds"] == ["day_three"]
        m = mail.sent[0]
        assert m["to_email"] == "kim@example.com"
        assert "Day three" in m["subject"] and "Fade Society" in m["subject"]
        assert "Hi Marcus" in m["body"]
        assert "1 of 4" in m["body"]
        assert "Load what you sell" in m["body"] and "prices drive everything" in m["body"]
        assert "twenty minutes" in m["body"].lower()
        # stamped, so the next tick is quiet
        out2 = asyncio.run(le.week_beats_tick())
        assert out2["sent"] == 0 and len(mail.sent) == 1

    def test_day_seven_share_kit_when_the_site_is_up(self, fake, mail, owners, monkeypatch):
        _biz(fake, days_old=7, stamps={"day_three_at": "x"})
        fake.post("/business_sites", {"id": "s1", "business_id": "b1", "status": "published",
                                      "slug": "fade-society", "site_config": {}})
        _plugins(monkeypatch, done=4, total=4)
        import brand_engine
        monkeypatch.setattr(brand_engine, "public_site_url", lambda site: "https://fade-society.mysolutionist.app")
        out = asyncio.run(le.week_beats_tick())
        assert out["sent_kinds"] == ["day_seven"]
        m = mail.sent[0]
        assert "send" in m["subject"].lower() and "one person" in m["subject"]
        assert "https://fade-society.mysolutionist.app" in m["body"]
        assert "one person today" in m["body"]

    def test_day_seven_without_a_site_asks_for_the_link_move(self, fake, mail, owners, monkeypatch):
        _biz(fake, days_old=7)
        _plugins(monkeypatch, done=2, total=4)
        out = asyncio.run(le.week_beats_tick())
        assert out["sent_kinds"] == ["day_seven"]
        m = mail.sent[0]
        assert "One week in" in m["subject"]
        assert "2 of 4" in m["body"] and "Set the hours you actually work" in m["body"]

    def test_grandfathered_and_disabled_are_quiet(self, fake, mail, owners, monkeypatch):
        _biz(fake, days_old=3)
        _plugins(monkeypatch)
        monkeypatch.setattr(le, "_is_grandfathered", lambda oid: True)
        assert asyncio.run(le.week_beats_tick())["sent"] == 0
        monkeypatch.setattr(le, "_is_grandfathered", lambda oid: False)
        monkeypatch.setenv("LIFECYCLE_EMAILS", "off")
        assert asyncio.run(le.week_beats_tick())["reason"] == "disabled"
        assert mail.sent == []

    def test_a_dead_probe_still_sends_a_shorter_mail(self, fake, mail, owners, monkeypatch):
        _biz(fake, days_old=3)
        import business_track_router as btr
        def boom(biz):
            raise RuntimeError("probes down")
        monkeypatch.setattr(btr, "resolve_plugins", boom)
        out = asyncio.run(le.week_beats_tick())
        assert out["sent"] == 1 and "waiting for its first pieces" in mail.sent[0]["body"]


# ─── the arc: the introduction once ──────────────────────────────────────

class TestIntroDelivered:
    def test_mark_then_read(self, fake):
        fra.begin("b1", source="signup")
        assert fra.intro_delivered("b1") is False
        assert fra.mark_intro_delivered("b1") is True
        assert fra.intro_delivered("b1") is True
        row = fra.state("b1")
        assert row["status"] == "walking" and row["intro_delivered_at"]

    def test_no_arc_reads_as_not_delivered(self, fake):
        assert fra.intro_delivered("nope") is False
        assert fra.mark_intro_delivered("") is False


# ─── Chief's greeting knows the day ──────────────────────────────────────

class TestWeekClause:
    def test_days_two_to_seven_get_the_week_read(self):
        prompt = cos._build_system_prompt(concierge_ctx(), True, time_of_day="morning",
                                          setup_block="SETUP STATUS — x", week_day=3)
        assert "FIRST WEEK, DAY 3" in prompt
        assert "Yesterday you brought" in prompt
        assert "THIS BUSINESS IS BRAND NEW" not in prompt

    def test_first_run_wins_over_the_week_read(self):
        prompt = cos._build_system_prompt(concierge_ctx(), True, time_of_day="morning",
                                          setup_block="SETUP STATUS — x", first_run=True, week_day=2)
        assert "THIS BUSINESS IS BRAND NEW" in prompt and "FIRST WEEK, DAY" not in prompt

    def test_no_week_read_on_ordinary_turns(self):
        prompt = cos._build_system_prompt(concierge_ctx(), False, week_day=4)
        assert "FIRST WEEK, DAY" not in prompt
