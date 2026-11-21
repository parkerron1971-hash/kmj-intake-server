"""Who calls our guests (guest_calls.py; church_follow_up's start, sweep and
_sweep_handed for a guest's follow-up).

Kevin, 2026-11-20: "by default the calls goes to people and care until we
get a welcome team. of course allow this to be selected by any church as to
how they want it done so there structure is unique to them", then "build".

Pins:
  * the caller, in order: a rule (pastor_ask, baptism, door:<door>), then
    the mode (person, team: fewest open guest calls, people_care), and auto:
    People & Care until there's a Welcome Team AND the office said yes, then
    today's choose()
  * People & Care is whoever does First-time guests: a Manager login holding
    the duty, else the owner, as their person (found by sign-in email; a
    login with none gets one, made once)
  * the call is due in due_days at 6 PM church time; one guest, one caller
  * telling a login caller (push + email), a member caller (today's email);
    the guest ladder: reminded, the backup a day late, the pastor at three
  * _sweep_handed leaves these alone; recheck re-hands when the caller can't
    take it any more; the switch off is the old behavior
  * GET/PUT /church/guest-calls: who may read, who may change, what's checked
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_follow_up as cfu  # noqa: E402
import guest_calls as gc  # noqa: E402
import guest_path  # noqa: E402
import sb_clients  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from test_church_follow_up import (  # noqa: E402
    ANDRE, BAPTISM, BIZ, DANA, KEISHA, MARCUS, MINISTER, NAMES, OWNER, PASTOR, ROBERT, TASHA, FakeDB, _role, cid)

ET = ZoneInfo("America/New_York")
# Sunday, November 22, 10:30 AM at church.
SUNDAY = datetime(2026, 11, 22, 10, 30, tzinfo=ET).astimezone(timezone.utc)
RENEE, NEW_LOGIN, MEDIA = cid(20), cid(21), cid(22)
RENEE_SEAT, MEDIA_SEAT, ADMIN_SEAT, NEW_SEAT = "u-renee", "u-media", "u-admin", "u-new"
TEAM = "aaaaaaaa-0000-0000-0000-000000000001"


@pytest.fixture
def g(monkeypatch):
    people = dict(NAMES, **{RENEE: "Renee Ellis", MEDIA: "Mia Booth"})
    fake = FakeDB(
        contacts=[{"id": k, "business_id": BIZ, "name": v, "email": f"{v.split()[0].lower()}@example.com", "phone": "",
                   "metadata": {}} for k, v in people.items()],
        church_leader_roles=[_role(PASTOR, "pastor"), _role(MINISTER, "baptism_minister"),
                             _role(TASHA, "team_leader", "Hospitality Team"), _role(ANDRE, "deacon"),
                             _role(KEISHA, "deacon")],
        church_role_defs=[], church_role_settings=[], church_duty_holders=[], church_follow_ups=[],
        church_follow_up_notes=[], events=[], intake_forms=[dict(BAPTISM, business_id=BIZ)],
        businesses=[{"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": OWNER,
                     "settings": {"practitioner_name": "Pastor Kevin"}}],
        business_sites=[{"business_id": BIZ, "slug": "love-city-church", "site_config": {}}],
        business_users=[
            {"business_id": BIZ, "user_id": RENEE_SEAT, "invited_email": "renee@example.com", "role": "manager",
             "lane": "people_care", "status": "active", "name": "Renee Ellis"},
            {"business_id": BIZ, "user_id": MEDIA_SEAT, "invited_email": "mia@example.com", "role": "manager",
             "lane": "media_comms", "status": "active", "name": "Mia Booth"},
            {"business_id": BIZ, "user_id": ADMIN_SEAT, "invited_email": "office@lovecity.org", "role": "admin",
             "status": "active", "name": "The Office"}],
        groups=[{"id": TEAM, "business_id": BIZ, "name": "Hospitality Team", "kind": "team", "active": True}],
        group_members=[{"business_id": BIZ, "group_id": TEAM, "contact_id": c, "role": "member"}
                       for c in (TASHA, MINISTER, DANA)],
    )
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", fake.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fake.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fake.delete)
    on = {"on": True}
    monkeypatch.setattr(guest_path, "switched_on", lambda biz: on["on"])
    fake.on = on
    import member_asks
    import messaging_router
    monkeypatch.setattr(member_asks, "_OWNER_CACHE", {})
    monkeypatch.setattr(messaging_router, "owner_email_read", lambda uid: "kevin@example.com")
    monkeypatch.setattr(messaging_router, "_owner_email", lambda uid: "kevin@example.com")
    import church_over
    monkeypatch.setattr(church_over, "_OWNER_EMAIL", {})
    monkeypatch.setattr(gc, "_zone", lambda ch: ET)
    clock = {"now": SUNDAY}
    monkeypatch.setattr(cfu, "_now", lambda: clock["now"])
    fake.clock = clock

    import business_settings

    def merge(bid, put=None, drop=(), under=()):
        row = next(b for b in fake.t["businesses"] if b["id"] == str(bid))
        row["settings"] = business_settings.merge_at(row.get("settings"), list(under), dict(put or {}), list(drop))
        return row["settings"]
    monkeypatch.setattr(business_settings, "merge", merge)
    return fake


@pytest.fixture
def told(monkeypatch):
    sent = {"email": [], "alert": [], "login": [], "gc_alert": []}

    async def email(biz, to, name, subject, body, key):
        sent["email"].append((to, subject, key))
        return True

    async def alert(biz_id, title, body, key, person, action="Open the Follow-up board"):
        sent["alert"].append((title, key))
        sent.setdefault("action", []).append(action)
        return True

    def login(ctx, uid, words, ref):
        sent["login"].append((uid, words["title"], words["body"], ref))
        return True

    async def gc_alert(biz_id, title, body, key, person_id=None, action=""):
        sent["gc_alert"].append((title, body, key))
        return True
    monkeypatch.setattr(cfu, "_email", email)
    monkeypatch.setattr(cfu, "_office_alert", alert)
    monkeypatch.setattr(gc, "tell_login", login)
    monkeypatch.setattr(gc, "office_alert", gc_alert)
    return sent


def _conf(g, **kw):
    g.t["businesses"][0]["settings"]["guest_calls"] = kw


def _connect(g, person=MARCUS, receipt=None, said="This is my first time", **extra):
    fields = {"visits": said, **extra}
    return cfu.on_connect_card(BIZ, person, {"fields": fields}, receipt or str(uuid.uuid4()))


def _welcome_team(g):
    g.t["church_leader_roles"].append(_role(ROBERT, "welcome_lead"))


def _row(g, fid):
    return next(r for r in g.t["church_follow_ups"] if r["id"] == fid)


# ─── The setting ──────────────────────────────────────────────────────

def test_nothing_saved_is_auto_due_in_two_days_and_junk_reads_as_the_default():
    assert gc.settings_of(None) == gc.DEFAULTS
    junk = gc.settings_of({"mode": "everyone", "due_days": 9, "rules": [{"when": "door:moon", "to": {}}] * 20,
                           "person": {"contact_id": "nope"}, "tell": {"app": False, "email": False}})
    assert junk == gc.DEFAULTS


# ─── The caller ───────────────────────────────────────────────────────

def test_by_default_people_and_care_makes_the_call_until_there_is_a_welcome_team(g):
    row = _connect(g)
    assert row["leader_contact_id"] == RENEE and row["leader_role"] == gc.MARK
    assert row["assigned_by"] == "guest_calls:people_care"
    assert row["reason"] == "Renee Ellis does First-time guests, so the call is theirs until there’s a Welcome Team."
    [note] = [n for n in g.t["church_follow_up_notes"] if n["follow_up_id"] == row["id"]]
    assert note["body"].startswith("Handed to Renee Ellis.")


def test_a_welcome_team_keeps_people_and_care_until_the_office_says_yes(g):
    _welcome_team(g)
    first = _connect(g)
    assert first["leader_contact_id"] == RENEE
    assert "until the office moves guest calls to the Welcome Team" in first["reason"]
    _conf(g, mode="auto", welcome_ok=True)
    second = _connect(g, person=DANA)
    assert (second["leader_contact_id"], second["leader_role"]) == (ROBERT, "welcome_lead")
    assert second["assigned_by"] == "guest_calls:welcome"
    assert _row(g, first["id"])["leader_contact_id"] == RENEE, "guests already handed stay put"


def test_always_people_and_care_even_with_a_welcome_team(g):
    _welcome_team(g)
    _conf(g, mode="people_care", welcome_ok=True)
    row = _connect(g)
    assert row["leader_contact_id"] == RENEE
    assert row["reason"] == "Renee Ellis does First-time guests, and the church keeps guest calls with them."


def test_one_person_picked_and_someone_who_cant_call_falls_to_people_and_care(g):
    _conf(g, mode="person", person={"contact_id": MINISTER})
    row = _connect(g)
    assert (row["leader_contact_id"], row["assigned_by"]) == (MINISTER, "guest_calls:person")
    _conf(g, mode="person", person={"contact_id": DANA})          # no login, no role
    row = _connect(g, person=ANDRE)
    assert row["leader_contact_id"] == RENEE
    assert row["reason"].startswith("The person picked for guest calls can’t take this one, so Renee Ellis has it")


def test_a_team_shares_the_calls_the_fewest_open_first(g):
    _conf(g, mode="team", team="Hospitality Team")
    a = _connect(g, person=MARCUS)
    b = _connect(g, person=DANA)
    # Dana is on the team but can't call (no login, no role): never handed one.
    assert {a["leader_contact_id"], b["leader_contact_id"]} == {MINISTER, TASHA}
    assert a["leader_contact_id"] == MINISTER, "Angela and Tasha both had none: by name"
    assert "had the fewest open" in b["reason"]


def test_a_role_two_people_hold_is_a_team_too(g):
    import church_roles as cr
    g.t["church_role_defs"].append({"id": str(uuid.uuid4()), "business_id": BIZ, "key": "deacon", "title": "Deacons",
                                    "job": "care", "covers": "church", "status": "active", "handles": [], "sees": [],
                                    "oversees_teams": [], "sort": 50})
    assert cr.defs(BIZ)
    _conf(g, mode="team", team="Deacons")
    row = _connect(g)
    assert row["leader_contact_id"] == ANDRE and row["assigned_by"] == "guest_calls:team"


def test_rules_send_some_guests_elsewhere(g):
    _conf(g, rules=[{"when": "pastor_ask", "to": {"contact_id": PASTOR}},
                    {"when": "baptism", "to": {"contact_id": MINISTER}},
                    {"when": "door:kids", "to": {"contact_id": TASHA}}])
    ask = _connect(g, person=MARCUS, interests="I’d like to talk with a pastor")
    assert ask["leader_contact_id"] == PASTOR and ask["assigned_by"] == "guest_calls:rule"
    assert ask["reason"] == "They asked to talk with a pastor, and the church sends those guests to Kevin McCloud."
    dip = _connect(g, person=DANA, interests=["Baptism", "Serving on a team"])
    assert dip["leader_contact_id"] == MINISTER
    next(c for c in g.t["contacts"] if c["id"] == ANDRE)["metadata"] = {"new_here": {"door": "kids"}}
    kids = cfu.on_first_check_in(BIZ, ANDRE, family_key="fam-1", said="Checked in Sofia at Kids")
    assert kids["leader_contact_id"] == TASHA and kids["reason"] == "Guests met at the kids desk go to Tasha Williams."
    plain = _connect(g, person=KEISHA)
    assert plain["leader_contact_id"] == RENEE, "every other guest goes to the caller"


def test_people_care_calls_before_the_executive_pastor(g):
    """Love City, 2026-11-21: the Executive Pastor holds every duty by
    oversight and her name sorts first, but People & Care makes the calls."""
    abby = cid(23)
    g.t["contacts"].append({"id": abby, "business_id": BIZ, "name": "Abby Adams", "email": "abby@example.com",
                            "phone": "", "metadata": {}})
    # As Love City's is: no stored lane, seven areas, so every duty in them.
    g.t["business_users"].append({"business_id": BIZ, "user_id": "u-abby", "invited_email": "abby@example.com",
                                  "role": "manager", "lane": None, "status": "active", "name": "Abby Adams",
                                  "areas": ["worship_media", "people_care", "kids_youth", "groups_classes",
                                            "messages_safety", "website_outreach", "office"]})
    import church_over
    ch = church_over.Church(next(b for b in g.t["businesses"] if b["id"] == BIZ))
    assert guest_path.FIRST_GUESTS in ch.held("u-abby"), "she holds First-time guests through her areas"
    first = _connect(g)
    assert first["leader_contact_id"] == RENEE, "People & Care, not the Executive Pastor"
    second = _connect(g, person=DANA)
    assert second["leader_contact_id"] == RENEE, "even carrying more open calls than the Executive Pastor"
    g.t["business_users"] = [s for s in g.t["business_users"] if s["user_id"] != RENEE_SEAT]
    third = _connect(g, person=KEISHA)
    assert third["leader_contact_id"] == abby, "with no People & Care login, the Executive Pastor before the owner"


def test_with_no_manager_on_first_guests_the_owner_makes_the_call(g):
    g.t["business_users"] = [s for s in g.t["business_users"] if s["user_id"] != RENEE_SEAT]
    row = _connect(g)
    assert row["leader_contact_id"] == PASTOR, "the owner, as his person (by sign-in email)"


def test_a_login_with_no_person_gets_one_made_once(g):
    g.t["business_users"] = [s for s in g.t["business_users"] if s["user_id"] != RENEE_SEAT]
    g.t["business_users"].append({"business_id": BIZ, "user_id": NEW_SEAT, "invited_email": "tiara@lovecity.org",
                                  "role": "manager", "lane": "people_care", "status": "active", "name": "Tiara Gold"})
    row = _connect(g)
    made = [c for c in g.t["contacts"] if c.get("email") == "tiara@lovecity.org"]
    assert len(made) == 1 and made[0]["source"] == "office_login" and made[0]["name"] == "Tiara Gold"
    assert row["leader_contact_id"] == made[0]["id"]
    again = _connect(g, person=DANA)
    assert again["leader_contact_id"] == made[0]["id"]
    assert len([c for c in g.t["contacts"] if c.get("email") == "tiara@lovecity.org"]) == 1


def test_the_call_is_due_in_due_days_at_six_church_time(g):
    row = _connect(g)
    assert cfu._parse(row["due_at"]) == datetime(2026, 11, 24, 18, tzinfo=ET), "a Sunday guest: Tuesday 6 PM"
    _conf(g, due_days=1)
    row = _connect(g, person=DANA)
    assert cfu._parse(row["due_at"]) == datetime(2026, 11, 23, 18, tzinfo=ET)


def test_one_guest_one_caller_a_second_door_is_one_note_and_the_caller_stays(g):
    """The doors keep one guest to one follow-up (new_here.second_door, #2008):
    a second card door is one note on the open one, which keeps the caller
    Who calls our guests gave it."""
    first = cfu.start(BIZ, MARCUS, card_key="text:new_here", card_name="New here", kind="connect",
                      answers=[{"q": "Tell us about you", "a": "Here with my kids"}])
    assert first["leader_contact_id"] == RENEE
    again = _connect(g)
    assert again is None and len(g.t["church_follow_ups"]) == 1
    notes = [n for n in g.t["church_follow_up_notes"] if n["follow_up_id"] == first["id"] and n["kind"] == "note"]
    assert len(notes) == 1 and notes[0]["body"].startswith("Also sent the website connect card.")
    assert _row(g, first["id"])["leader_contact_id"] == RENEE


def test_a_card_that_isnt_a_guests_is_handed_as_always(g):
    row = cfu.on_intake_form({"id": BIZ, "type": "ministry"}, BAPTISM, {"faith": "Yes"}, MARCUS)
    assert (row["leader_contact_id"], row["assigned_by"]) == (MINISTER, "chief")


def test_the_switch_off_is_exactly_the_old_hand_off(g):
    g.on["on"] = False
    _welcome_team(g)
    a = _connect(g)
    b = cfu.start(BIZ, MARCUS, card_key="text:new_here", card_name="New here", kind="connect", answers=[])
    assert (a["leader_contact_id"], a["leader_role"], a["assigned_by"]) == (ROBERT, "welcome_lead", "chief")
    assert b is not None, "two doors still make two follow-ups with the path off"
    assert cfu._parse(a["due_at"]) == SUNDAY + timedelta(days=2)


def test_a_read_that_fails_hands_the_guest_as_before_rather_than_drop_the_card(g, monkeypatch):
    _welcome_team(g)
    monkeypatch.setattr(gc, "people", lambda ch: (_ for _ in ()).throw(HTTPException(503, "x")))
    row = _connect(g)
    assert (row["leader_contact_id"], row["assigned_by"]) == (ROBERT, "chief")


# ─── Telling, and the ladder ──────────────────────────────────────────

def test_a_login_caller_hears_in_the_app_and_by_email_once(g, told):
    row = _connect(g)
    asyncio.run(cfu.sweep(now=SUNDAY + timedelta(minutes=5)))
    [(uid, title, body, ref)] = told["login"]
    assert uid == RENEE_SEAT and title == "Chief: a new guest for you"
    assert body == "Marcus Taylor filled in the website card today. Your call is due Tuesday by 6 PM."
    assert told["email"] == [], "not the Lead tab's email: a login has no Lead tab"
    assert _row(g, row["id"])["leader_told_at"]
    asyncio.run(cfu.sweep(now=SUNDAY + timedelta(minutes=10)))
    assert len(told["login"]) == 1


def test_a_member_caller_keeps_todays_email(g, told):
    _conf(g, mode="person", person={"contact_id": MINISTER})
    _connect(g)
    asyncio.run(cfu.sweep(now=SUNDAY + timedelta(minutes=5)))
    assert told["login"] == []
    assert [(to, s) for to, s, _ in told["email"]] == [("angela@example.com", "Marcus Taylor is yours to follow up")]


def test_the_ladder_reminds_then_the_backup_takes_it_then_the_pastor_hears(g, told):
    _conf(g, backup={"contact_id": MINISTER})
    row = _connect(g)
    due = cfu._parse(row["due_at"])
    asyncio.run(cfu.sweep(now=SUNDAY + timedelta(minutes=5)))                  # told
    asyncio.run(cfu.sweep(now=due - timedelta(hours=10)))                      # Tuesday 8 AM: nothing yet
    assert len(told["login"]) == 1
    asyncio.run(cfu.sweep(now=due - timedelta(hours=8)))                       # Tuesday 10 AM: reminded
    assert told["login"][-1][1] == "Chief: a guest call is due"
    assert told["login"][-1][2] == "Your welcome call with Marcus Taylor is due today by 6 PM."
    assert _row(g, row["id"])["late_level"] == 1
    asyncio.run(cfu.sweep(now=due + timedelta(days=1, minutes=5)))             # a day late: the backup
    r = _row(g, row["id"])
    assert (r["leader_contact_id"], r["assigned_by"], r["late_level"]) == (MINISTER, "guest_calls:backup", 2)
    assert told["email"][-1][:2] == ("angela@example.com", "Marcus Taylor is yours to call")
    assert told["login"][-1][:2] == (RENEE_SEAT, "Chief: your guest went to the backup")
    asyncio.run(cfu.sweep(now=due + timedelta(days=3, minutes=5)))             # three days: the pastor
    assert _row(g, row["id"])["late_level"] == 3
    assert told["login"][-1][:2] == (OWNER, "Marcus Taylor hasn’t had a welcome call"), "Kevin is the owner's person"
    assert told["alert"][-1][0] == "Hand Marcus Taylor to someone else?"
    assert told["action"][-1] == "Open Visitor flow", "a guest's call is worked in Visitor flow"
    kinds = [n["kind"] for n in g.t["church_follow_up_notes"] if n["follow_up_id"] == row["id"]]
    assert kinds.count("nudged") == 1 and kinds.count("reassigned") == 1 and kinds.count("pastors_told") == 1
    asyncio.run(cfu.sweep(now=due + timedelta(days=5)))
    assert kinds.count("pastors_told") == 1


def test_with_no_backup_a_day_late_is_todays_chain(g, told):
    row = _connect(g)
    due = cfu._parse(row["due_at"])
    asyncio.run(cfu.sweep(now=SUNDAY + timedelta(minutes=5)))
    asyncio.run(cfu.sweep(now=due - timedelta(hours=8)))
    asyncio.run(cfu.sweep(now=due + timedelta(days=1, minutes=5)))
    r = _row(g, row["id"])
    assert r["leader_contact_id"] == RENEE and r["late_level"] == 2
    assert told["email"][-1][:2] == ("kevin@example.com", "Marcus Taylor hasn’t been reached")


def test_the_late_ladder_for_a_guests_call(g):
    row = _connect(g)
    ctx = gc.Ctx(g.t["businesses"][0])
    due = cfu._parse(row["due_at"])
    assert gc.late_step(row, due - timedelta(hours=10), ctx) is None
    assert gc.late_step(row, due - timedelta(hours=9), ctx) == (1, "guest_nudged")
    assert gc.late_step(dict(row, late_level=1), due + timedelta(days=1), ctx) == (2, "overseer_told")
    assert gc.late_step(dict(row, late_level=2), due + timedelta(days=3), ctx) == (3, "next_up")
    assert gc.late_step(dict(row, late_level=2, assigned_by="guest_calls:backup"), due + timedelta(days=3), ctx) == \
        (3, "pastor_told")
    assert gc.late_step(dict(row, step=1, due_at=row["due_at"]), due + timedelta(hours=1), ctx) == (1, "nudged"), \
        "past the call: today's ladder"


def test_a_welcome_team_lead_asks_the_office_once(g, told):
    _welcome_team(g)
    _connect(g)
    asyncio.run(cfu.sweep(now=SUNDAY + timedelta(minutes=5)))
    asyncio.run(cfu.sweep(now=SUNDAY + timedelta(minutes=10)))
    asks = [a for a in told["gc_alert"] if a[0] == "Move guest calls to the Welcome Team?"]
    assert len(asks) == 1 and "Robert Hayes now leads your Welcome Team" in asks[0][1]
    assert g.t["businesses"][0]["settings"]["guest_calls"]["welcome_asked"]


def test_quiet_hours_hold_a_guests_telling(g, told, monkeypatch):
    import member_push
    monkeypatch.setattr(member_push, "quiet_hour", lambda biz, now=None: True)
    _connect(g)
    asyncio.run(cfu.sweep(now=SUNDAY + timedelta(minutes=5)))
    assert told["login"] == [] and told["email"] == []


# ─── A caller who can no longer take it ───────────────────────────────

def test_the_hand_back_sweep_leaves_a_login_caller_alone(g, told):
    row = _connect(g)
    asyncio.run(cfu._sweep_handed())
    assert _row(g, row["id"])["leader_contact_id"] == RENEE, "Renee holds no church role, and that's fine"


def test_a_login_that_left_has_the_guest_handed_again_with_a_note(g, told):
    row = _connect(g)
    g.t["business_users"] = [s for s in g.t["business_users"] if s["user_id"] != RENEE_SEAT]
    asyncio.run(cfu._sweep_handed())
    r = _row(g, row["id"])
    assert r["leader_contact_id"] == PASTOR and r["assigned_by"] == "guest_calls:people_care"
    assert r["leader_told_at"] is None, "the new caller is told on the next sweep"
    note = [n["body"] for n in g.t["church_follow_up_notes"] if n["kind"] == "reassigned"]
    assert note == ["Renee Ellis no longer has an office login or a role here. Handed to Kevin McCloud."]


def test_a_duty_that_moved_moves_the_guest(g, told):
    row = _connect(g)
    next(s for s in g.t["business_users"] if s["user_id"] == RENEE_SEAT)["lane"] = "media_comms"
    asyncio.run(cfu._sweep_handed())
    assert _row(g, row["id"])["leader_contact_id"] == PASTOR
    assert any("no longer does First-time guests" in n["body"] for n in g.t["church_follow_up_notes"])


def test_with_the_path_off_a_caller_who_left_goes_back_to_the_office(g, told):
    row = _connect(g)
    g.on["on"] = False
    g.t["business_users"] = [s for s in g.t["business_users"] if s["user_id"] != RENEE_SEAT]
    asyncio.run(cfu._sweep_handed())
    r = _row(g, row["id"])
    assert r["leader_contact_id"] is None and r["assigned_by"] == "chief"


def test_a_church_that_cant_be_read_moves_no_one(g, told, monkeypatch):
    row = _connect(g)
    g.t["business_users"] = [s for s in g.t["business_users"] if s["user_id"] != RENEE_SEAT]
    real = g.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/business_users") else real(path, **kw))
    asyncio.run(cfu._sweep_handed())
    assert _row(g, row["id"])["leader_contact_id"] == RENEE


# ─── The sheet: GET and PUT ───────────────────────────────────────────

@pytest.fixture
def office(g, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import business_access
    import church_duties
    who = {"role": "manager", "id": RENEE_SEAT}
    monkeypatch.setattr(business_access, "_resolve_role", lambda b, u: who["role"])
    monkeypatch.setattr(church_duties, "_CACHE", {})
    app = FastAPI()
    app.include_router(gc.router)
    app.dependency_overrides[sb_clients.authed_request] = (
        lambda: SimpleNamespace(user=SimpleNamespace(id=who["id"], email="x@example.com", user_metadata={})))
    c = TestClient(app)
    c.who = who
    return c


def test_the_sheet_reads_who_calls_and_the_choices(office, g):
    r = office.get(f"/church/guest-calls/{BIZ}")
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["on"] is True and v["settings"]["mode"] == "auto" and v["settings"]["due_days"] == 2
    assert v["caller"] == {"contact_id": RENEE, "name": "Renee Ellis", "title": "People & Care"}
    assert v["how"] == "People & Care makes the calls until you have a Welcome Team."
    assert v["welcome_team"] == {"exists": False, "lead": None}
    people = {p["contact_id"]: p for p in v["choices"]["people"]}
    assert people[RENEE]["login"] is True and people[PASTOR]["login"] is True and people[MINISTER]["login"] is False
    assert DANA not in people, "no login and no role: never offered"
    assert v["choices"]["teams"] == ["Hospitality Team"]
    assert v["may_edit"] is True and v["backup"] is None
    assert [s["when"] for s in v["ladder"]] == ["On the due day", "A day late", "Three days late"]
    assert v["people_care"] == v["caller"] and v["pastor"] == "Kevin McCloud"
    assert [d["key"] for d in v["doors"]] == list(guest_path.DOORS)


def test_a_login_that_doesnt_do_first_guests_reads_but_cant_change(office, g):
    office.who.update(role="manager", id=MEDIA_SEAT)
    assert office.get(f"/church/guest-calls/{BIZ}").json()["may_edit"] is False
    r = office.put(f"/church/guest-calls/{BIZ}", json={"mode": "people_care"})
    assert r.status_code == 403 and "whoever does First-time guests" in r.json()["detail"]
    office.who.update(role="member")
    assert office.get(f"/church/guest-calls/{BIZ}").status_code == 404


def test_a_duty_that_cant_be_read_is_a_503_never_a_yes(office, g, monkeypatch):
    import church_duties
    monkeypatch.setattr(church_duties, "holds", lambda *a: (_ for _ in ()).throw(HTTPException(503, "unread")))
    r = office.put(f"/church/guest-calls/{BIZ}", json={"mode": "people_care"})
    assert r.status_code == 503
    assert office.get(f"/church/guest-calls/{BIZ}").json()["may_edit"] is False


def test_saving_writes_only_the_setting_and_keeps_the_servers_stamp(office, g):
    _conf(g, mode="auto", welcome_asked="2026-11-21T00:00:00+00:00")
    g.t["businesses"][0]["settings"]["new_here"] = {"on": True}
    body = {"mode": "person", "person": {"contact_id": MINISTER}, "backup": {"contact_id": PASTOR},
            "rules": [{"when": "door:kids", "to": {"contact_id": TASHA}}], "due_days": 1}
    r = office.put(f"/church/guest-calls/{BIZ}", json=body)
    assert r.status_code == 200, r.text
    saved = g.t["businesses"][0]["settings"]
    assert saved["new_here"] == {"on": True}
    assert saved["guest_calls"]["mode"] == "person" and saved["guest_calls"]["due_days"] == 1
    assert saved["guest_calls"]["welcome_asked"] == "2026-11-21T00:00:00+00:00"
    v = r.json()
    assert v["caller"]["contact_id"] == MINISTER and v["backup"]["contact_id"] == PASTOR
    assert v["how"] == "Angela Price makes every call."
    assert v["ladder"][1]["what"] == "Kevin McCloud takes the guest, and Angela is told."


@pytest.mark.parametrize("body, said", [
    ({"mode": "anyone"}, "Pick who makes the calls."),
    ({"mode": "person"}, "Pick the person who makes the calls."),
    ({"mode": "person", "person": {"contact_id": DANA}}, "can’t take guest calls"),
    ({"mode": "person", "person": {"contact_id": cid(99)}}, "can’t take guest calls"),
    ({"mode": "team", "team": "Choir"}, "isn’t one of yours"),
    ({"mode": "auto", "due_days": 4}, "1, 2 or 3 days"),
    ({"mode": "auto", "due_days": True}, "1, 2 or 3 days"),
    ({"mode": "auto", "rules": [{"when": "door:moon", "to": {"contact_id": PASTOR}}]}, "the door they came through"),
    ({"mode": "auto", "rules": [{"when": "pastor_ask", "to": {"contact_id": PASTOR}}] * 2}, "Keep one"),
    ({"mode": "auto", "rules": [{"when": f"door:{d}", "to": {"contact_id": PASTOR}} for d in guest_path.DOORS]
      + [{"when": "pastor_ask", "to": {"contact_id": PASTOR}}] * 5}, "Up to 10 rules"),
    ({"mode": "auto", "tell": {"app": False, "email": False}}, "at least one way"),
])
def test_a_save_checks_what_it_writes(office, g, body, said):
    r = office.put(f"/church/guest-calls/{BIZ}", json=body)
    assert r.status_code == 400 and said in r.json()["detail"], r.text
    assert "guest_calls" not in g.t["businesses"][0]["settings"]


def test_with_the_path_off_the_sheet_says_so_and_saves_nothing(office, g):
    g.on["on"] = False
    assert office.get(f"/church/guest-calls/{BIZ}").json()["on"] is False
    assert office.put(f"/church/guest-calls/{BIZ}", json={"mode": "people_care"}).status_code == 404


def test_a_welcome_team_shows_on_the_sheet_and_a_yes_moves_future_guests(office, g):
    _welcome_team(g)
    v = office.get(f"/church/guest-calls/{BIZ}").json()
    assert v["welcome_team"] == {"exists": True, "lead": "Robert Hayes"}
    assert v["how"] == "People & Care makes the calls until you move them to the Welcome Team."
    v = office.put(f"/church/guest-calls/{BIZ}", json={"mode": "auto", "welcome_ok": True}).json()
    assert v["caller"]["contact_id"] == ROBERT and v["backup"]["contact_id"] == RENEE
    assert v["how"] == "The Welcome Team makes the calls, and Renee Ellis is the backup."


def test_guest_calls_is_a_server_key():
    import business_settings
    assert business_settings.server_owned(gc.KEY)


def test_the_route_is_guarded_by_business_access():
    from fastapi.routing import APIRoute
    for r in gc.router.routes:
        if isinstance(r, APIRoute):
            assert r.path == "/church/guest-calls/{business_id}"
            deps = [d.call.__qualname__ for d in r.dependant.dependencies]
            assert any("business_access" in q for q in deps), r.path
