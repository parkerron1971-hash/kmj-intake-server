"""Shepherding, round 2 (church_shepherd_signals.py; the drift numbers on
Shepherding, the shepherd's family page, Chief's section and draft moves).

Kevin, 2026-10-17: drifting is judged on Sundays only, never giving; any
attendance counts; nobody is flagged unless they came 2 of the 6 recorded
Sundays before the 3 they missed; a week with no reach goes one step up the
shepherd's chain (canvas 31su6kdYmYecH5b2NxjBJN, board 4). Pins:
  · the rule, and that a Sunday nobody recorded is nobody's miss; only the
    church's service weekday counts; a check-in occasion's own day wins;
  · Monday (the church's clock, from 7:00) opens a signal and tells the
    shepherd once; a week with no touch climbs to who they answer to, then
    one more step, and stops at the top; a touch stops the climb; coming
    back resolves it;
  · birthdays in the shepherd's email, a child by first name only; the Lead
    Pastor's brief;
  · a care need reaches the shepherd within the hour without the card's
    words, once; a pastor's card is "A pastor has this one.";
  · the office's numbers; Chief's section is owner/manager only and never
    a note's words; Chief's moves are a draft the office approves, and
    approving tells only the new shepherd; a Welcome card hears who
    shepherds the new member."""
from __future__ import annotations

import asyncio
import fnmatch
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.dirname(os.path.abspath(__file__))):
    if p not in sys.path:
        sys.path.insert(0, p)

import chief_church_actions as A  # noqa: E402
import church_families as cf  # noqa: E402
import church_follow_up as cfu  # noqa: E402
import church_shepherd_signals as sig  # noqa: E402
import church_shepherding as shep  # noqa: E402
import member_portal_lead as mpl  # noqa: E402
import sb_clients  # noqa: E402
from test_church_shepherding import (  # noqa: E402,F401
    ANDRE, AVA, BEN, BETH, BIZ, BUSINESS, CALVIN, DANA, DEFS, GRACE, JAYLEN, KMJ, MARCUS, PAUL, PEOPLE, REED, ROBERT,
    TANYA, ShepDB, _home, _me, _req, holder, mail, person, shell)

# Monday Oct 19 2026, 9:00 in Detroit (13:00 UTC).
NOW = datetime(2026, 10, 19, 13, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    """The pages and the office read "now"; pin it to that Monday."""
    monkeypatch.setattr(sig, "_now", lambda: NOW)
    monkeypatch.setattr(shep, "_now", lambda: NOW)
SUNDAYS = [date(2026, 10, 18) - timedelta(weeks=i) for i in range(9)]  # 10/18 … 8/23, newest first


class SigDB(ShepDB):
    """ShepDB plus PostgREST `like` (the sent-once ledger reads by pattern)."""

    def _match(self, row, filters):
        rest = []
        for f in filters:
            if f[0] != "or" and f[1] == "like":
                if not fnmatch.fnmatchcase(str(row.get(f[0]) or ""), f[2]):
                    return False
            else:
                rest.append(f)
        return super()._match(row, rest)


@pytest.fixture
def db(monkeypatch):
    fake = SigDB(
        contacts=PEOPLE,
        church_role_defs=DEFS,
        church_leader_roles=[holder(KMJ, "pastor"), holder(ANDRE, "associate_pastor"), holder(MARCUS, "elders"),
                             holder(TANYA, "elders"), holder(REED, "deacons"), holder(ROBERT, "welcome_lead")],
        households=[], household_adults=[], children=[], child_care_notes=[], church_family_dismissals=[],
        church_shepherd_settings=[], church_shepherds=[], church_shepherd_drafts=[], church_shepherd_touches=[],
        church_shepherd_signals=[], church_shepherd_notices=[], church_checkin_settings=[],
        attendance=[], module_entries=[], groups=[], group_members=[], church_follow_ups=[],
        church_follow_up_notes=[],
        businesses=[dict(BUSINESS)],
        business_sites=[{"business_id": BIZ, "slug": "love-city-church", "site_config": {"custom_domain": "lovecityc.com"}}],
    )
    for name in ("sb_get_as_service", "sb_post_as_service", "sb_patch_as_service", "sb_delete_as_service"):
        monkeypatch.setattr(sb_clients, name, getattr(fake, name.split("_")[1]))
    return fake


def _sunday(db, day, people, *, own_day=True):
    """A service on `day` and who checked in (the church's own check-in
    occasion carries its day)."""
    eid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"svc-{day}"))
    if not any(e["id"] == eid for e in db.t["module_entries"]):
        db.t["module_entries"].append({"id": eid, "business_id": BIZ,
                                       "data": {"_checkin_day": day.isoformat()} if own_day else {"title": "Service"}})
    for c in people:
        db.t["attendance"].append({"id": str(uuid.uuid4()), "business_id": BIZ, "entry_id": eid, "contact_id": c,
                                   "method": "self", "checked_in_at": f"{day.isoformat()}T15:10:00+00:00"})
    return eid


def _carters(db, shepherd=MARCUS):
    hid = _home(db, "The Carter family", [CALVIN, DANA], [JAYLEN, AVA])
    db.t["church_shepherds"].append({"household_id": hid, "business_id": BIZ, "shepherd_contact_id": shepherd,
                                     "assigned_at": "2026-08-01T12:00:00+00:00", "reason": ""})
    return hid


def _drifting_carters(db):
    """Every Sunday recorded (Kevin is always there); the Carters came 9/27
    and 9/20, then missed 10/4, 10/11 and 10/18."""
    hid = _carters(db)
    for d in SUNDAYS:
        _sunday(db, d, [KMJ] + ([CALVIN] if d in (date(2026, 9, 27), date(2026, 9, 20)) else []))
    return hid


def _run(at=NOW):
    stats = {"churches": 0, "care": 0, "emails": 0, "drifting": 0, "climbed": 0, "resolved": 0}
    asyncio.run(sig.run_church(dict(BUSINESS), at, stats))
    return stats


# ─── the rule ────────────────────────────────────────────────────────

def test_three_missed_after_coming_two_of_six_is_drifting():
    got = sig.drift(SUNDAYS, {SUNDAYS[3], SUNDAYS[4]})
    assert got == {"since": SUNDAYS[2], "last_seen": SUNDAYS[3]}


@pytest.mark.parametrize("here", [
    {SUNDAYS[3]},                      # only 1 of the 6 before: the pattern guard
    {SUNDAYS[1], SUNDAYS[3], SUNDAYS[4]},  # came to one of the last three
    set(),                             # never came in 12 weeks: not drifting, just not here
])
def test_the_guard_and_a_recent_sunday_flag_nobody(here):
    assert sig.drift(SUNDAYS, here) is None


def test_fewer_than_five_recorded_sundays_flag_nobody():
    assert sig.drift(SUNDAYS[:4], {SUNDAYS[3]}) is None
    assert sig.drift(SUNDAYS[:5], {SUNDAYS[3], SUNDAYS[4]}) == {"since": SUNDAYS[2], "last_seen": SUNDAYS[3]}


def test_a_sunday_nobody_recorded_is_nobodys_miss_and_only_sundays_count(db):
    _drifting_carters(db)
    # A Wednesday Bible study the Carters came to doesn't count, and its
    # day comes from the check-ins (no occasion day of its own).
    _sunday(db, date(2026, 10, 14), [CALVIN], own_day=False)
    rec = sig.recorded(dict(BUSINESS), now=NOW)
    assert rec["days"] == SUNDAYS and date(2026, 10, 14) not in rec["seen"][CALVIN]
    # Check-in was off on 10/11: nobody recorded, so it's nobody's miss.
    eid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"svc-{date(2026, 10, 11)}"))
    db.t["attendance"] = [a for a in db.t["attendance"] if a["entry_id"] != eid]
    rec = sig.recorded(dict(BUSINESS), now=NOW)
    assert date(2026, 10, 11) not in rec["days"]
    assert sig.drift(rec["days"], rec["seen"][CALVIN]) is None, "10/18, 10/4 missed but 9/27 came"


def test_an_occasions_own_day_wins_over_when_it_was_recorded(db):
    _sunday(db, date(2026, 10, 18), [KMJ])
    eid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"svc-{date(2026, 10, 18)}"))
    for a in db.t["attendance"]:
        a["checked_in_at"] = "2026-10-20T14:00:00+00:00"  # typed in on Tuesday
    rec = sig.recorded(dict(BUSINESS), now=NOW + timedelta(days=2))
    assert rec["days"] == [date(2026, 10, 18)] and eid


def test_a_class_night_counts_in_attendance_but_is_never_a_sunday(db):
    """Kevin 2026-10-18, "Count class nights": a class night is its own
    occasion (academy_class_nights), even one held on a Sunday afternoon."""
    hid = _drifting_carters(db)
    for day in (date(2026, 10, 18), date(2026, 10, 11), date(2026, 10, 4)):
        eid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"class-{day}"))
        db.t["module_entries"].append({"id": eid, "business_id": BIZ, "data": {"_class_session": f"s-{day}", "type": "class"}})
        db.t["attendance"].append({"id": str(uuid.uuid4()), "business_id": BIZ, "entry_id": eid, "contact_id": CALVIN,
                                   "method": "online", "checked_in_at": f"{day.isoformat()}T21:00:00+00:00"})
    rec = sig.recorded(dict(BUSINESS), now=NOW)
    assert sig.drift(rec["days"], rec["seen"][CALVIN]) == {"since": date(2026, 10, 4), "last_seen": date(2026, 9, 27)}
    # A Sunday with only a class on it is no recorded Sunday either.
    svc = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"svc-{date(2026, 10, 18)}"))
    db.t["attendance"] = [a for a in db.t["attendance"] if a["entry_id"] != svc]
    assert date(2026, 10, 18) not in sig.recorded(dict(BUSINESS), now=NOW)["days"] and hid


# ─── Monday ──────────────────────────────────────────────────────────

def test_monday_tells_the_shepherd_once_and_opens_a_signal(db, mail):
    hid = _drifting_carters(db)
    stats = _run()
    assert stats["drifting"] == 1
    [s] = db.t["church_shepherd_signals"]
    assert (s["household_id"], s["started_on"], s["last_seen"], s["level"]) == (hid, "2026-10-04", "2026-09-27", 0)
    marcus = [m for m in mail if m["to"] == "marcus@example.com"]
    assert len(marcus) == 1
    assert "The Carter family hasn’t been at church since Sept 27." in marcus[0]["body"]
    assert "giving is never part of it" in marcus[0]["body"] and "/my/lead/families" in marcus[0]["body"]
    brief = [m for m in mail if m["to"] == "kevin@example.com"]
    assert len(brief) == 1 and "1 drifting: The Carter family (Marcus Grant)" in brief[0]["body"]
    assert "system.mysolutionist.app/#/operate/shepherding" in brief[0]["body"]
    sent = len(mail)
    _run(NOW + timedelta(hours=1))
    assert len(mail) == sent and len(db.t["church_shepherd_signals"]) == 1, "once a week"


def test_monday_waits_for_seven_on_the_churchs_clock(db, mail):
    _drifting_carters(db)
    _run(datetime(2026, 10, 19, 10, 30, tzinfo=timezone.utc))  # 6:30 in Detroit
    assert not mail and not db.t["church_shepherd_signals"]
    _run(datetime(2026, 10, 20, 13, 0, tzinfo=timezone.utc))  # Tuesday
    assert not mail and not db.t["church_shepherd_signals"]


def _open_signal(db, hid, level=0, told=NOW - timedelta(days=7)):
    db.t["church_shepherd_signals"].append({"id": str(uuid.uuid4()), "business_id": BIZ, "household_id": hid,
                                            "kind": "drift", "started_on": "2026-10-04", "last_seen": "2026-09-27",
                                            "level": level, "told_at": sig._iso(told), "resolved_at": None})
    return db.t["church_shepherd_signals"][-1]


def test_a_week_with_no_reach_climbs_the_chain_and_stops_at_the_top(db, mail):
    hid = _drifting_carters(db)
    s = _open_signal(db, hid)
    _run()
    assert s["level"] == 1
    andre = [m for m in mail if m["to"] == "andre@example.com"]
    assert len(andre) == 1 and "Marcus Grant shepherds them" in andre[0]["body"]
    assert "hasn’t been reached in a week" in andre[0]["subject"]
    # A week on, one step up: the Lead Pastor.
    mail.clear()
    _run(NOW + timedelta(days=7))
    assert s["level"] == 2 and any(m["to"] == "kevin@example.com" and "shepherds them" in m["body"] for m in mail)
    # The top: nobody above Kevin, so it stays.
    mail.clear()
    _run(NOW + timedelta(days=14))
    assert s["level"] == 2 and not any("shepherds them" in m["body"] for m in mail)


def test_a_touch_stops_the_climb_and_coming_back_resolves_it(db, mail):
    hid = _drifting_carters(db)
    s = _open_signal(db, hid)
    db.t["church_shepherd_touches"].append({"id": "t1", "business_id": BIZ, "household_id": hid,
                                            "shepherd_contact_id": MARCUS, "kind": "call", "note": "THE KIDS HAD FLU",
                                            "needs_pastor": False, "created_at": "2026-10-06T20:00:00+00:00"})
    _run()
    assert s["level"] == 0 and not any(m["to"] == "andre@example.com" for m in mail)
    _sunday(db, date(2026, 10, 25), [DANA])
    _run(NOW + timedelta(days=7))
    assert s["resolved_at"], "back at church on 10/25"


def test_birthdays_this_week_children_by_first_name_only(db, mail):
    hid = _carters(db)
    _sunday(db, SUNDAYS[0], [CALVIN])
    kid = next(k for k in db.t["children"] if k["contact_id"] == AVA)
    kid["birthdate"] = "2019-10-22"
    next(p for p in db.t["contacts"] if p["id"] == DANA)["birthdate"] = "1990-10-24"
    _run()
    [m] = [m for m in mail if m["to"] == "marcus@example.com"]
    assert "Ava turns 7 on Thursday." in m["body"] and "Dana turns 36 on Saturday." in m["body"]
    assert "Ava Carter" not in m["body"] and m["subject"] == "Birthdays in your families this week"
    assert hid


# ─── a care need ─────────────────────────────────────────────────────

def _card(db, who, words, leader=REED, role="deacons", ago=timedelta(hours=1)):
    db.t["church_follow_ups"].append({"id": str(uuid.uuid4()), "business_id": BIZ, "contact_id": who,
                                      "leader_contact_id": leader, "leader_role": role, "path_kind": "connect",
                                      "answers": [{"q": "How can we pray for you?", "a": words}], "status": "open",
                                      "created_at": sig._iso(NOW - ago)})
    return db.t["church_follow_ups"][-1]


def test_a_care_need_tells_the_shepherd_within_the_hour_never_the_words(db, mail):
    _carters(db)
    _card(db, CALVIN, "My mother is in the hospital after SURGERY")
    _run(datetime(2026, 10, 21, 15, 0, tzinfo=timezone.utc))  # a Wednesday
    [m] = mail
    assert m["to"] == "marcus@example.com" and "Reed Owens (Deacons) has a care need for the Carter family" in m["body"]
    assert "SURGERY" not in m["body"] and "hospital" not in m["body"].lower()
    _run(datetime(2026, 10, 21, 16, 0, tzinfo=timezone.utc))
    assert len(mail) == 1, "once"


def test_no_care_notice_to_the_shepherd_who_holds_it_or_for_a_pastors_card(db, mail):
    _carters(db)
    _card(db, CALVIN, "I'm sick and need prayer", leader=MARCUS, role="elders")
    _card(db, DANA, "I'd like to talk with a pastor", leader=KMJ, role="pastor")
    _run(datetime(2026, 10, 21, 15, 0, tzinfo=timezone.utc))
    assert not mail


def test_the_family_page_says_who_has_it_and_never_the_words(db, shell):
    hid = _drifting_carters(db)
    _open_signal(db, hid)
    _card(db, CALVIN, "In the HOSPITAL")
    _card(db, DANA, "I'd like to talk with a pastor", leader=KMJ, role="pastor")
    html, status = asyncio.run(mpl.serve(_req(), BUSINESS, {}, _me(MARCUS), f"/my/lead/family/{hid}"))
    assert status == 200
    assert "Drifting · last here Sept 27" in html
    assert "Reed Owens (Deacons) has a care need for this family since" in html and "A pastor has this one." in html
    assert "HOSPITAL" not in html and "talk with a pastor" not in html
    fams, _ = asyncio.run(mpl.serve(_req(), BUSINESS, {}, _me(MARCUS), "/my/lead/families"))
    assert "Missed three Sundays · last here Sept 27" in fams and "has missed three Sundays" in fams


def test_a_family_back_at_church_says_so(db, shell):
    hid = _carters(db)
    _sunday(db, SUNDAYS[0], [JAYLEN])  # a child checking in counts for the family
    html, _ = asyncio.run(mpl.serve(_req(), BUSINESS, {}, _me(MARCUS), f"/my/lead/family/{hid}"))
    assert "At church Oct 18" in html


# ─── the office ──────────────────────────────────────────────────────

def test_the_office_sees_who_is_drifting_and_who_was_told(db):
    hid = _drifting_carters(db)
    _open_signal(db, hid, level=1)
    out = shep.overview(dict(BUSINESS))
    assert out["counts"]["drifting"] == 1 and out["counts"]["sundays_recorded"] == 9
    assert out["counts"]["not_reached_60"] == 1, "placed in August, never reached"
    [d] = out["drifting"]
    assert (d["name"], d["shepherd_name"], d["level"], d["told"]) == ("The Carter family", "Marcus Grant", 1, "Andre Mills")
    card = next(s for s in out["shepherds"] if s["contact_id"] == MARCUS)
    assert card["drifting"] == 1 and card["families"][0]["drifting_since"] == "2026-10-04"
    fam = shep.office_family(dict(BUSINESS), hid)
    assert fam["drifting"]["level"] == 1 and fam["lines"] == []


def test_a_failed_attendance_read_fails_the_page_not_zero(db, monkeypatch):
    _drifting_carters(db)
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/attendance") else real(path, **kw))
    assert shep.overview(dict(BUSINESS)) is None


# ─── Chief ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("role", ["member", "viewer", None])
def test_chiefs_shepherding_is_owner_or_manager_only(db, monkeypatch, role):
    monkeypatch.setattr(A, "_caller_role", lambda b: role)
    out = asyncio.run(A.handle_church_people(None, dict(BUSINESS), {"section": "shepherding"}))
    assert out["result"].startswith("refused")


def test_chief_answers_who_shepherds_the_carters_never_a_notes_words(db, monkeypatch):
    monkeypatch.setattr(A, "_caller_role", lambda b: "manager")
    hid = _drifting_carters(db)
    _open_signal(db, hid)
    db.t["church_shepherd_touches"].append({"id": "t1", "business_id": BIZ, "household_id": hid,
                                            "shepherd_contact_id": MARCUS, "kind": "call", "note": "JOB MOVED TO SUNDAYS",
                                            "needs_pastor": False, "created_at": "2026-09-10T20:00:00+00:00"})
    out = asyncio.run(A.handle_church_people(None, dict(BUSINESS), {"section": "shepherding", "name": "the Carters"}))
    r = out["result"]
    assert "The Carter family" in r and "shepherded by Marcus Grant" in r and "Last reached Sept 10 (called)" in r
    assert "Drifting" in r and "last here Sept 27" in r and "Marcus Grant has been told" in r and "Jaylen (9)" in r
    assert "JOB MOVED" not in r and "giving" not in r.split("Drifting")[0].lower()
    whole = asyncio.run(A.handle_church_people(None, dict(BUSINESS), {"section": "shepherding"}))["result"]
    assert "1 member family has a shepherd" in whole and "- The Carter family (shepherd Marcus Grant)" in whole
    assert "Recorded Sundays in the last 12 weeks: 9." in whole


def test_chief_drafts_moves_and_approving_tells_only_the_new_shepherd(db, monkeypatch, mail):
    monkeypatch.setattr(A, "_caller_role", lambda b: "owner")
    hid = _carters(db)
    out = asyncio.run(A.handle_draft_shepherd_moves(None, dict(BUSINESS),
                                                    {"moves": [{"family": "the Carters", "to": "Elder Tanya Brooks"}]}))
    assert "Drafted: The Carter family: Marcus Grant → Tanya Brooks" in out["result"]
    assert "no one is told until" in out["result"] and out["nav"] == {"tab": "operate", "sub": "shepherding"}
    assert db.t["church_shepherds"][0]["shepherd_contact_id"] == MARCUS, "a draft moves nothing"
    view = shep.proposal(dict(BUSINESS))["proposal"]
    row = next(r for r in view["rows"] if r["unit"] == f"h:{hid}")
    assert row["from_shepherd_contact_id"] == MARCUS and row["shepherd_contact_id"] == TANYA
    assert view["rows"][0]["unit"] == f"h:{hid}", "moves first"
    tanya = next(s for s in view["shepherds"] if s["contact_id"] == TANYA)
    marcus = next(s for s in view["shepherds"] if s["contact_id"] == MARCUS)
    assert (tanya["count"], marcus["count"]) == (1, 0)
    done = shep.approve(dict(BUSINESS), None)
    assert db.t["church_shepherds"][0]["shepherd_contact_id"] == TANYA and done["gained"] == {TANYA: ["The Carter family"]}
    asyncio.run(shep.tell_shepherds(dict(BUSINESS), done["gained"], done["ctx"], "s1"))
    assert [m["to"] for m in mail] == ["tanya@example.com"]


def test_chief_asks_when_a_name_is_unknown_or_its_their_own_family(db, monkeypatch):
    monkeypatch.setattr(A, "_caller_role", lambda b: "owner")
    _carters(db)
    out = asyncio.run(A.handle_draft_shepherd_moves(None, dict(BUSINESS),
                                                    {"moves": [{"family": "the Zebras", "to": "Tanya"}]}))
    assert out["failed"] and "Which family do you mean" in out["result"]
    out = asyncio.run(A.handle_draft_shepherd_moves(None, dict(BUSINESS),
                                                    {"moves": [{"family": "the Carters", "to": "Reed Owens"}]}))
    assert out["failed"] and "isn't one of the shepherds" in out["result"]
    monkeypatch.setattr(A, "_caller_role", lambda b: "member")
    out = asyncio.run(A.handle_draft_shepherd_moves(None, dict(BUSINESS),
                                                    {"moves": [{"family": "the Carters", "to": "Tanya"}]}))
    assert out["failed"] and not db.t["church_shepherd_drafts"]


def test_registered_as_a_draft_write_chief_can_call():
    import action_registry
    import chief_of_staff
    import mcp_server
    assert chief_of_staff.ACTION_HANDLERS["draft_shepherd_moves"] is A.handle_draft_shepherd_moves
    assert action_registry.effect("draft_shepherd_moves") != action_registry.READ
    schema = mcp_server.TOOL_SCHEMAS["church_people"]
    assert "shepherding" in str(schema) and "name" in str(schema)


# ─── the hand-off and the name ───────────────────────────────────────

def test_a_new_members_welcome_card_hears_who_shepherds_them(db, mail):
    fid = _card(db, GRACE, "Plan my visit", leader=ROBERT, role="welcome_lead")["id"]
    db.t["church_shepherd_drafts"].append({"business_id": BIZ, "made_at": "2026-10-19T00:00:00+00:00", "rows": [
        {"unit": f"c:{GRACE}", "shepherd_contact_id": ANDRE, "reason": "even", "why": "Room on their list", "moved": False}]})
    shep.approve(dict(BUSINESS), None)
    notes = [n for n in db.t["church_follow_up_notes"] if n["follow_up_id"] == fid]
    assert [n["body"] for n in notes] == ["Now shepherded by Andre Mills."] and not notes[0]["pastors_only"]


def test_a_family_name_keeps_the_last_name_as_written():
    rows = [person("x1", "tashaunnia mcbride", first="tashaunnia", last="mcbride"),
            person("x2", "Tay McBride", first="Tay", last="McBride")]
    assert cf._family_name(rows) == "The McBride family"
    assert cf._family_name(list(reversed(rows))) == "The McBride family"
    assert cf._family_name([rows[0]]) == "The Mcbride family"


def test_the_sweep_runs_each_church_and_one_failing_never_stops_it(db, mail, monkeypatch):
    _drifting_carters(db)
    db.t["businesses"].append({"id": "33333333-3333-3333-3333-333333333333", "name": "Other", "type": "ministry"})
    db.t["church_shepherds"].append({"household_id": "h-x", "business_id": "33333333-3333-3333-3333-333333333333",
                                     "shepherd_contact_id": BEN, "assigned_at": "2026-10-01", "reason": ""})
    real = sig.run_church

    async def flaky(biz, now, stats):
        if biz["name"] == "Other":
            raise RuntimeError("boom")
        await real(biz, now, stats)
    monkeypatch.setattr(sig, "run_church", flaky)
    stats = asyncio.run(sig.sweep(NOW))
    assert stats["churches"] == 2 and stats["drifting"] == 1
