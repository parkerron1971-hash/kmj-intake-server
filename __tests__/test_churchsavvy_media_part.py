"""The Media part on a church's ChurchSavvy team (worship_team.py), and the
routes outside ChurchSavvy it opens: the livestream (live_router.require)
and video clips (media_library.access). Kevin, 2026-10-23: a Media team
gets the media part already set up; the artifact "Church Areas and Keys".

Pins:
  * media is a part: it runs the livestream, works on clips and keeps
    sermons and the screens' library; never the plan, the screens or the setup
  * the booth runs the livestream too, and nothing else new
  * a part opens these routes only while ChurchSavvy is open to that person;
    a seat is checked first and still works as it did
  * approving a clip to post and importing from the church's Drive stay
    with a seat, whatever the part
  * someone taken off the team, or a stranger, is refused; a failed read is
    a 503, never "not on the team"
  * Go live lists the church's services for a part with no seat, and counts
    attendance only for one of the church's own
  * "Your clips are ready" reaches a volunteer by email, opening ChurchSavvy's
    Clips; an office login hears by phone as before
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import live_router  # noqa: E402
import media_library  # noqa: E402
import sb_clients  # noqa: E402
import worship_team as wt  # noqa: E402
from auth_supabase import AuthedUser  # noqa: E402
from test_church_roles import FakeDB  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OWNER = "00000000-0000-4000-8000-000000000001"
PEOPLE = {n: AuthedUser(id=f"00000000-0000-4000-8000-{i:012d}", email=f"{n}@lovecity.org", role="authenticated")
          for i, n in enumerate(("mo", "sam", "ana", "gone", "manager", "member", "stranger"), start=10)}


def _row(name, roles, status="active"):
    return {"business_id": BIZ, "user_id": PEOPLE[name].id, "name": name.title(), "roles": roles, "status": status}


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB(
        businesses=[{"id": BIZ, "name": "Love City Church", "owner_id": OWNER, "type": "ministry"}],
        business_users=[{"business_id": BIZ, "user_id": PEOPLE["manager"].id, "role": "manager", "status": "active"},
                        {"business_id": BIZ, "user_id": PEOPLE["member"].id, "role": "member", "status": "active"}],
        worship_team=[_row("mo", ["media"]), _row("sam", ["booth"]), _row("ana", ["planner", "worship"]),
                      _row("gone", ["media"], status="removed")],
    )
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    return fake


def _refused(fn, *args, **kw):
    with pytest.raises(HTTPException) as e:
        fn(*args, **kw)
    return e.value.status_code


# ─── The part ─────────────────────────────────────────────────────────

def test_media_is_a_part_with_its_own_work_and_none_of_the_plan_or_screens():
    assert "media" in wt.ROLES and wt.ROLE_LABEL["media"] == "Media"
    assert wt._clean_roles(["admin", "media"]) == ["media", "admin"]
    media = {"media"}
    assert [k for k in wt.CAN if wt.can(media, k)] == ["media", "live", "clips", "sermons"]
    assert [k for k in wt.CAN if wt.can({"booth"}, k)] == ["fix", "run", "live"]
    assert not any(wt.can({"planner", "worship"}, k) for k in ("live", "clips", "sermons"))
    assert all(wt.can({"admin"}, k) for k in wt.CAN)
    with pytest.raises(HTTPException):
        wt._clean_roles(["pastor"])


def test_a_part_opens_its_routes_only_while_churchsavvy_is_open_to_them(db, monkeypatch):
    mo = PEOPLE["mo"]
    assert wt.team_can(BIZ, mo, "clips") and wt.team_can(BIZ, mo, "live")
    assert wt.team_can(BIZ, PEOPLE["sam"], "live") and not wt.team_can(BIZ, PEOPLE["sam"], "clips")
    assert not wt.team_can(BIZ, PEOPLE["ana"], "live")
    assert not wt.team_can(BIZ, PEOPLE["gone"], "clips"), "taken off the team"
    assert not wt.team_can(BIZ, PEOPLE["stranger"], "clips")
    monkeypatch.setenv("WORSHIP_SONGS", "owner")
    assert not wt.team_can(BIZ, mo, "clips"), "only the platform owner while it's owner-only"
    monkeypatch.setenv("WORSHIP_SONGS", "off")
    assert not wt.team_can(BIZ, mo, "clips")


def test_a_failed_team_read_is_a_503(db, monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **kw: None)
    assert _refused(wt.team_can, BIZ, PEOPLE["mo"], "clips") == 503


# ─── The livestream ──────────────────────────────────────────────────

def test_the_livestream_takes_a_seat_as_before_or_a_part_that_runs_it(db):
    assert live_router.require(BIZ, PEOPLE["manager"], "manager") == "manager"
    assert live_router.require(BIZ, PEOPLE["member"], "member") == "member"
    assert live_router.require(BIZ, PEOPLE["mo"], "manager") == "team"
    assert live_router.require(BIZ, PEOPLE["sam"], "manager") == "team"
    assert _refused(live_router.require, BIZ, PEOPLE["ana"], "manager") == 403
    assert _refused(live_router.require, BIZ, PEOPLE["gone"], "member") == 403
    assert _refused(live_router.require, BIZ, PEOPLE["stranger"], "member") == 403
    assert _refused(live_router.require, "22222222-2222-4222-8222-222222222222", PEOPLE["mo"], "member") == 404


def test_an_outage_on_the_seat_check_is_an_outage_not_the_teams_yes(db, monkeypatch):
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.lstrip("/").startswith("businesses?") else real(path, **kw))
    assert _refused(live_router.require, BIZ, PEOPLE["mo"], "manager") == 503


def test_the_livestream_closes_to_the_team_when_churchsavvy_does(db, monkeypatch):
    monkeypatch.setenv("WORSHIP_SONGS", "off")
    assert _refused(live_router.require, BIZ, PEOPLE["mo"], "manager") == 403
    assert live_router.require(BIZ, PEOPLE["manager"], "manager") == "manager"


# ─── Video clips ──────────────────────────────────────────────────────

def test_clips_take_a_managers_seat_or_the_media_part(db):
    assert media_library.access(BIZ, PEOPLE["manager"]) == "manager"
    assert media_library.access(BIZ, PEOPLE["mo"]) == "team"
    for name in ("sam", "ana", "gone", "member", "stranger"):
        assert _refused(media_library.access, BIZ, PEOPLE[name]) == 403, name


def test_approving_a_clip_and_importing_from_drive_stay_with_a_seat(db, monkeypatch):
    monkeypatch.setattr(media_library, "asset", lambda *a, **k: pytest.fail("the clip was read before the seat check"))
    review = media_library.Review(fingerprint="a" * 64, permission_note="Recorded authorization", rights_confirmed=True,
                                  privacy_checked=True, caption_checked=True, destination_checked=True)
    assert _refused(media_library.approve, BIZ, "33333333-3333-4333-8333-333333333333", review, PEOPLE["mo"]) == 403
    assert _refused(media_library.access, BIZ, PEOPLE["mo"], team=False) == 403
    monkeypatch.setattr(media_library.httpx, "Client", lambda *a, **k: pytest.fail("Google was asked before the seat check"))
    drive = type("Body", (), {"access_token": None, "file_id": "f", "permission_note": "x"})()
    assert _refused(media_library.import_drive, BIZ, drive, PEOPLE["mo"]) == 403


# ─── Go live's "Counts as attendance for" ─────────────────────────────

MOD = "77777777-7777-4777-8777-777777777777"
E = {n: f"88888888-8888-4888-8888-{i:012d}" for i, n in enumerate(("past", "next", "today", "undated", "gone", "theirs"))}


def _day(n):
    return (datetime.now(timezone.utc).date() + timedelta(days=n)).isoformat()


@pytest.fixture
def calendar(db, monkeypatch):
    db.t["custom_modules"] = [{"id": MOD, "business_id": BIZ, "archetype": "event_roster", "is_active": True,
                               "name": "Services", "archetype_params": {"date_field": "when", "title_field": "name"}}]

    def entry(n, data, biz=BIZ, status="active"):
        return {"id": E[n], "business_id": biz, "module_id": MOD, "status": status, "data": data}
    db.t["module_entries"] = [
        entry("past", {"when": _day(-3), "name": "Last week"}),
        entry("next", {"when": _day(7) + "T11:00", "name": "Next Sunday"}),
        entry("today", {"when": _day(0), "name": "  "}),
        entry("undated", {"name": "Someday"}),
        entry("gone", {"when": _day(0), "name": "Taken down"}, status="archived"),
        entry("theirs", {"when": _day(0), "name": "Another church"}, biz="22222222-2222-4222-8222-222222222222"),
    ]
    monkeypatch.setattr(sb_clients, "sb_post_as_service", db.post)
    monkeypatch.setattr(live_router, "_tell_members_live", lambda biz, row: None)
    return db


def test_go_live_lists_the_churchs_services_from_today_soonest_first_for_the_team(calendar):
    """A part has no seat to read Services & Events with, so the picker was
    empty for the team; the server reads it for them now."""
    want = [{"id": E["today"], "title": "Untitled", "when": _day(0)},
            {"id": E["next"], "title": "Next Sunday", "when": _day(7) + "T11:00"}]
    for name in ("mo", "sam", "manager"):
        assert live_router.live_occasions(BIZ, PEOPLE[name]) == {"occasions": want}, name
    for name in ("ana", "member", "stranger"):
        assert _refused(live_router.live_occasions, BIZ, PEOPLE[name]) == 403, name


def test_a_failed_calendar_read_is_a_503_never_an_empty_picker(calendar, monkeypatch):
    real = calendar.get
    for table in ("custom_modules?", "module_entries?"):
        monkeypatch.setattr(sb_clients, "sb_get_as_service",
                            lambda path, t=table, **kw: None if path.lstrip("/").startswith(t) else real(path, **kw))
        assert _refused(live_router.live_occasions, BIZ, PEOPLE["mo"]) == 503, table


def test_going_live_counts_attendance_only_for_one_of_the_churchs_own_services(calendar):
    def start(entry):
        return live_router.live_start(live_router.StartIn(
            business_id=BIZ, title="Sunday Worship", stream_url="https://www.youtube.com/watch?v=abc123", entry_id=entry),
            PEOPLE["mo"])
    for n in ("theirs", "gone"):
        assert _refused(start, E[n]) == 400, n
    assert not calendar.t.get("live_sessions"), "nothing went live on a refused service"
    assert start(E["today"])["live"]["entry_id"] == E["today"]


# ─── "Your clips are ready" ───────────────────────────────────────────

@pytest.fixture
def heard(db, monkeypatch):
    import churchsavvy_billing
    import email_sender
    import push_notifications
    out = {"push": [], "email": []}
    db.t["worship_team"][0]["email"] = "mo@lovecity.org"
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda path, body, **kw: [body])
    monkeypatch.setattr(push_notifications, "send_to_user", lambda uid, **kw: out["push"].append((uid, kw["nav"])) or 1)

    async def send(**kw):
        out["email"].append(kw)
        return {"id": "e1"}
    monkeypatch.setattr(email_sender, "send_via_resend", send)
    monkeypatch.setattr(churchsavvy_billing, "app_url", lambda: "https://app.test/churchsavvy")
    return out


def _ready(who):
    import clip_finder
    clip_finder.notify({"id": f"run-{who}", "business_id": BIZ, "created_by": who},
                       {"id": "s1", "name": "Sunday, Oct 26"}, 12, 2)


def test_clips_ready_reaches_an_office_login_by_phone_and_a_volunteer_by_email(heard):
    _ready(PEOPLE["manager"].id)
    _ready(OWNER)
    assert heard["push"] == [(PEOPLE["manager"].id, "grow:video-clips"), (OWNER, "grow:video-clips")]
    assert heard["email"] == []
    _ready(PEOPLE["mo"].id)
    assert len(heard["push"]) == 2, "a volunteer can't turn on phone alerts, so none is sent"
    [mail] = heard["email"]
    assert mail["to_email"] == "mo@lovecity.org" and mail["from_name"] == "Love City Church"
    assert mail["subject"] == "12 clips are ready" and mail["idempotency_key"] == f"clips-ready-run-{PEOPLE['mo'].id}"
    assert "https://app.test/churchsavvy/media/clips" in mail["body"] and "Hi Mo," in mail["body"]


def test_clips_ready_goes_by_phone_as_before_when_the_seat_read_fails(heard, db, monkeypatch):
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.lstrip("/").startswith("business_users?") else real(path, **kw))
    _ready(PEOPLE["mo"].id)
    assert heard["push"] == [(PEOPLE["mo"].id, "grow:video-clips")] and heard["email"] == []


def test_a_volunteer_with_no_email_on_the_team_hears_nothing_and_nothing_breaks(heard, db):
    db.t["worship_team"][0]["email"] = ""
    _ready(PEOPLE["mo"].id)
    assert heard == {"push": [], "email": []}
