"""One sheet per person (church_sheet.py, church_job_defs.py). Kevin,
2026-11-17: "yes to all and build it. also allow for custom roles to be set",
then "also allow for permission to be given to a person to create roles like
how my wife over administration team".

Pins:
  * the jobs: the five starting ones, a church's own beside them, a removed
    one still naming whoever held it, and the code working before the table
    is there (reads say "no custom jobs", a write is a 503)
  * what a job may hold: an Admin job is the owner's, Giving and the money
    duties only with an Admin job, pay never
  * who reads a sheet: the owner and an Admin anyone's, a holder a Manager's
    or below, anyone their own; another Manager is refused
  * who changes one, and every refusal in the holder's rules: their own, an
    Admin's, an Admin job, Giving & money, a money duty, the lanes'
    oversight, the grant itself
  * the grant: given and taken by the owner or an Admin, to a Manager login,
    kept beside the duties without becoming one
  * a holder's change is recorded and told to the owner; the owner's own
    isn't told
  * giving someone more asks for the password again; taking away never does
  * an invite can carry a church's own job, and the login reads as it

People and the church here are made up."""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_areas as ca  # noqa: E402
import church_duties as cd  # noqa: E402
import church_job_defs as cj  # noqa: E402
import church_over as co  # noqa: E402
import church_sheet as cs  # noqa: E402
import sb_clients  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from test_church_duties import DutyDB  # noqa: E402
from test_church_follow_up import BIZ, OWNER  # noqa: E402

ADMIN = "b1000000-0000-4000-8000-000000000001"     # Tasha Moore, an Admin login
RUTH = "b2000000-0000-4000-8000-000000000002"      # Ruth Ellison, a Manager: she will hold the grant
JORDAN = "b3000000-0000-4000-8000-000000000003"    # Jordan Lee, a Manager in Media & Communications
SARAH = "b4000000-0000-4000-8000-000000000004"     # Sarah Okafor, a Manager with picked areas
MARK = "b5000000-0000-4000-8000-000000000005"      # Mark Diaz, a Member login
ADMIN2 = "b6000000-0000-4000-8000-000000000006"    # Priya Nair, a second Admin login
STRANGER = "b9000000-0000-4000-8000-000000000009"


def _seat(uid, role, email, name, lane=None, areas=None):
    return {"business_id": BIZ, "user_id": uid, "role": role, "invited_email": email, "lane": lane, "areas": areas,
            "contact_id": None, "name": name, "status": "active"}


@pytest.fixture
def db(monkeypatch):
    fake = DutyDB(
        businesses=[{"id": BIZ, "name": "Grace Fellowship", "type": "church", "owner_id": OWNER,
                     "settings": {"practitioner_name": "Pastor Daniel Brooks"}}],
        business_users=[
            _seat(ADMIN, "admin", "tasha@gracefellowship.example", "Tasha Moore", lane="treasurer"),
            _seat(RUTH, "manager", "ruth@gracefellowship.example", "Ruth Ellison", lane="office_leadership",
                  areas=["messages_safety", "office"]),
            _seat(JORDAN, "manager", "jordan@gracefellowship.example", "Jordan Lee", lane="media_comms",
                  areas=["worship_media", "website_outreach"]),
            _seat(SARAH, "manager", "sarah@gracefellowship.example", "Sarah Okafor", areas=["kids_youth"]),
            _seat(MARK, "member", "mark@gracefellowship.example", "Mark Diaz"),
            _seat(ADMIN2, "admin", "priya@gracefellowship.example", "Priya Nair"),
        ],
        contacts=[], church_role_defs=[], church_leader_roles=[], church_role_settings=[], church_area_places=[],
        church_duty_holders=[], church_duty_changes=[], church_jobs=[], church_sheet_changes=[],
    )
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", fake.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fake.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fake.delete)
    for k in ("CHURCH_DUTIES", "CHURCH_AREAS", "CHURCH_KEYS", "CHIEF_AREAS"):
        monkeypatch.delenv(k, raising=False)
    import member_asks
    import messaging_router
    monkeypatch.setattr(member_asks, "_OWNER_CACHE", {})
    monkeypatch.setattr(messaging_router, "_owner_email", lambda uid: "")
    monkeypatch.setattr(messaging_router, "owner_email_read", lambda uid: "pastor@gracefellowship.example")
    fake.told = []
    monkeypatch.setattr(cj, "tell_owner", lambda business, title, body, tag: fake.told.append((title, body)))
    return fake


@pytest.fixture(autouse=True)
def _fresh():
    import chief_areas
    for c in (cd._CACHE, cd._FAILED, ca._MY_CACHE):
        c.clear()
    chief_areas.forget()
    yield
    for c in (cd._CACHE, cd._FAILED, ca._MY_CACHE):
        c.clear()
    chief_areas.forget()


def _biz(db):
    return db.t["businesses"][0]


def _seat_of(db, uid):
    return next(s for s in db.t["business_users"] if s["user_id"] == uid)


def _give_grant(db, uid=RUTH):
    cs.change(_biz(db), OWNER, uid, {"duties": {"add": [cj.GRANT]}})


JOB = {"label": "Kids Director", "does": "Runs the kids rooms on Sunday and the workers who serve in them",
       "description": "Owns check-in, the rooms and the workers.\nAnswers to the Executive Pastor.",
       "role": "manager", "areas": ["kids_youth", "groups_classes"], "duties": ["kids", "youth"]}


# ─── The jobs ─────────────────────────────────────────────────────────

def test_the_five_starting_jobs_are_the_lanes_with_their_starter_duties(db):
    jobs = cj.jobs(BIZ)
    assert [j["key"] for j in jobs] == list(ca.LANES)
    assert all(not j["custom"] and j["description"] is None for j in jobs)
    by = {j["key"]: j for j in jobs}
    assert by["treasurer"]["role"] == "admin" and by["treasurer"]["areas"] is None
    assert by["people_care"]["duties"] == cd.STARTER["people_care"]


def test_a_church_makes_changes_and_removes_its_own_job(db):
    made = cj.create(_biz(db), JOB, OWNER, "owner")
    job = made["job"]
    assert job["key"] == "kids_director" and job["custom"] and made["created"]
    assert job["areas"] == ["kids_youth", "groups_classes"] and job["duties"] == ["kids", "youth"]
    assert [j["key"] for j in cj.jobs(BIZ)][-1] == "kids_director"
    # The same title again, or a starting job's title, is refused.
    for label in ("kids director", "Treasurer"):
        with pytest.raises(HTTPException) as e:
            cj.create(_biz(db), {**JOB, "label": label}, OWNER, "owner")
        assert e.value.status_code == 409
    got = cj.update(_biz(db), "kids_director", {**JOB, "label": "Children's Director", "areas": ["kids_youth"]},
                    OWNER, "owner")
    assert got["job"]["label"] == "Children's Director" and got["before"]["label"] == "Kids Director"
    assert got["job"]["key"] == "kids_director"          # the key is the job's for good
    cj.remove(_biz(db), "kids_director", OWNER, "owner")
    assert "kids_director" not in [j["key"] for j in cj.jobs(BIZ)]
    assert cj.label_of(BIZ, "kids_director") == "Children's Director"     # whoever held it still reads as it
    # A new job with the old title gets a new key: the removed one keeps its own.
    assert cj.create(_biz(db), {**JOB, "label": "Kids Director"}, OWNER, "owner")["job"]["key"] == "kids_director_2"


def test_a_starting_job_cant_be_changed_or_removed(db):
    for fn in (lambda: cj.update(_biz(db), "people_care", JOB, OWNER, "owner"),
               lambda: cj.remove(_biz(db), "treasurer", OWNER, "owner")):
        with pytest.raises(HTTPException) as e:
            fn()
        assert e.value.status_code == 400 and "starting jobs" in e.value.detail


def test_before_the_table_is_there_reads_say_no_custom_jobs_and_a_write_is_a_503(db, monkeypatch):
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/church_jobs") else real(path, **kw))
    assert [j["key"] for j in cj.jobs(BIZ)] == list(ca.LANES)
    assert cj.label_of(BIZ, "kids_director") is None
    assert [x["key"] for x in ca.lanes_view(BIZ)] == list(ca.LANES)
    with pytest.raises(HTTPException) as e:
        cj.create(_biz(db), JOB, OWNER, "owner")
    assert e.value.status_code == 503 and e.value.detail == cj.NOT_READY
    # And a sheet still opens.
    assert cs.compose(_biz(db), OWNER, SARAH)["person"]["name"] == "Sarah Okafor"


@pytest.mark.parametrize("change,by_role,status,word", [
    ({"role": "admin"}, "admin", 403, "Only the owner"),
    ({"role": "admin"}, "holder", 403, "Only the owner"),
    ({"areas": ["giving_money"]}, "owner", 400, "Giving & money"),
    ({"duties": ["kids", "deposit"]}, "owner", 400, "money job"),
    ({"duties": ["monthly_report"]}, "holder", 403, "Only the owner or an Admin"),
    ({"role": "member"}, "owner", 400, "Member or Viewer"),
    ({"label": "K"}, "owner", 400, "title"),
    ({"areas": ["the_basement"]}, "owner", 400, "eight"),
    ({"duties": ["sweeping"]}, "owner", 400, "isn't a duty"),
    ({"description": "Runs the kids rooms. Paid $18 an hour."}, "owner", 400, "Pay stays out"),
])
def test_what_a_job_may_not_hold(db, change, by_role, status, word):
    with pytest.raises(HTTPException) as e:
        cj.clean({**JOB, **change}, by_role)
    assert e.value.status_code == status and word in e.value.detail


def test_the_owner_makes_an_admin_job_and_it_sees_the_whole_church(db):
    job = cj.create(_biz(db), {"label": "Finance Director", "does": "Keeps the books", "role": "admin",
                               "areas": ["office"], "duties": ["books", "deposit"]}, OWNER, "owner")["job"]
    assert job["role"] == "admin" and job["areas"] is None and job["duties"] == ["deposit", "books"]
    # An Admin can't change or remove it afterwards.
    for fn in (lambda: cj.update(_biz(db), job["key"], {"label": "Finance Lead", "role": "manager"}, ADMIN, "admin"),
               lambda: cj.remove(_biz(db), job["key"], ADMIN, "admin")):
        with pytest.raises(HTTPException) as e:
            fn()
        assert e.value.status_code == 403


# ─── Reading a sheet ──────────────────────────────────────────────────

def test_a_sheet_puts_a_logins_job_areas_duties_and_what_chief_knows_in_one_place(db):
    s = cs.compose(_biz(db), OWNER, JORDAN)
    assert s["ok"] and s["can_edit"] and s["editor"] == "owner"
    assert s["person"] == {"user_id": JORDAN, "name": "Jordan Lee", "email": "jordan@gracefellowship.example",
                           "role": "manager", "status": "active", "is_owner": False, "is_self": False}
    assert s["job"] == {"key": "media_comms", "label": "Media & Communications", "custom": False}
    assert s["areas"]["picked"] == ["worship_media", "website_outreach"] and s["areas"]["by"] == "picked"
    duties = {d["key"]: d for d in s["duties"]}
    assert set(duties) == set(cd.CATALOG) | {cj.GRANT}
    assert duties["website"]["held"] and not duties["weekly_text"]["held"] and not duties["books"]["held"]
    assert duties["weekly_text"]["others"] == ["Ruth Ellison"]
    assert duties[cj.GRANT] == {**duties[cj.GRANT], "held": False, "others": [], "area": "office", "grant": True}
    guarded = {g["key"]: g for g in s["guarded"]}
    assert not guarded["who_gave"]["holds"] and not guarded["bank"]["holds"] and guarded["logins"]["holds"]
    assert not guarded["kids_medical"]["holds"]
    assert s["chief"]["summary"][0] == "Jordan Lee works in Worship & media and Website & outreach."
    assert "Change the website" in s["chief"]["will"]
    assert any(w.startswith("Read what was given") and "Giving & money" in w for w in s["chief"]["wont"])
    assert [j["key"] for j in s["jobs"]] == list(ca.LANES)
    # Step one: Giving and the money duties aren't a Manager's to hold, whoever edits.
    assert s["locked_areas"] == ["giving_money"]
    assert s["locked_duties"] == [k for k, d in cd.CATALOG.items() if d["money"]]
    assert s["limits"] == []


def test_an_admins_and_the_owners_sheets_say_they_keep_everything(db):
    a = cs.compose(_biz(db), OWNER, ADMIN)
    assert a["areas"] == {"picked": None, "shown": None, "by": "all", "why": "Sees the whole church", "guess": []}
    assert a["job"] == {"key": "treasurer", "label": "Treasurer", "custom": False}
    assert all(d["held"] for d in a["duties"]) and a["can_edit"]
    assert set(a["locked_areas"]) == set(ca.AREA_ORDER) and len(a["locked_duties"]) == len(cd.CATALOG) + 1
    assert {g["key"] for g in a["guarded"] if g["holds"]} >= {"who_gave", "bank", "kids_medical", "pastors_notes"}
    o = cs.compose(_biz(db), OWNER, OWNER)
    assert o["person"]["is_owner"] and o["person"]["is_self"] and not o["can_edit"]
    assert o["person"]["email"] == "pastor@gracefellowship.example"
    assert o["chief"]["summary"][0].startswith("Pastor Daniel Brooks is the owner")


@pytest.mark.parametrize("viewer,target,ok", [
    (OWNER, MARK, True), (ADMIN, JORDAN, True), (ADMIN, ADMIN2, True), (ADMIN, OWNER, True),
    (JORDAN, JORDAN, True), (MARK, MARK, True),
    (JORDAN, SARAH, False), (MARK, JORDAN, False), (SARAH, ADMIN, False),
])
def test_who_reads_whose_sheet(db, viewer, target, ok):
    if ok:
        assert cs.compose(_biz(db), viewer, target)["person"]["user_id"] == target
    else:
        with pytest.raises(HTTPException) as e:
            cs.compose(_biz(db), viewer, target)
        assert e.value.status_code == 403 and e.value.detail == cs.NOT_YOURS


def test_someone_with_no_login_here_reads_nothing_and_a_missing_login_is_a_404(db):
    with pytest.raises(HTTPException) as e:
        cs.compose(_biz(db), STRANGER, JORDAN)
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        cs.compose(_biz(db), OWNER, STRANGER)
    assert e.value.status_code == 404


def test_a_member_reading_their_own_sheet_isnt_shown_who_does_each_duty(db):
    s = cs.compose(_biz(db), MARK, MARK)
    assert not s["can_edit"] and all(d["others"] == [] for d in s["duties"])
    assert all(k in s["locked_duties"] for k in cd.CATALOG)          # nothing here is theirs to tick


# ─── Changing a sheet ─────────────────────────────────────────────────

@pytest.mark.parametrize("viewer,target,word", [
    (JORDAN, JORDAN, cs.OWN_SHEET),               # their own
    (OWNER, OWNER, cs.OWNERS_SHEET),
    (ADMIN, ADMIN, cs.OWN_SHEET),
    (ADMIN, ADMIN2, cs.ADMINS_SHEET),             # an Admin never changes an Admin
    (ADMIN, OWNER, cs.OWNERS_SHEET),
    (JORDAN, SARAH, cs.NOT_AN_EDITOR),            # a Manager without the grant
    (MARK, SARAH, cs.NOT_AN_EDITOR),
])
def test_who_may_not_change_a_sheet(db, viewer, target, word):
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), viewer, target, {"areas": ["office"]})
    assert e.value.status_code == 403 and e.value.detail == word
    assert db.told == [] and db.t["church_sheet_changes"] == []


def test_the_owner_changes_areas_a_job_and_duties_through_the_writes_they_already_had(db):
    cj.create(_biz(db), JOB, OWNER, "owner")
    got = cs.change(_biz(db), OWNER, SARAH, {"job": "kids_director", "areas": ["kids_youth", "groups_classes"],
                                             "duties": {"add": ["weekly_text"], "remove": []}})
    assert got["changed"] and got["widens"]
    seat = _seat_of(db, SARAH)
    assert seat["areas"] == ["kids_youth", "groups_classes"] and seat["lane"] == "kids_director"
    # The weekly text was Ruth's by her job: both of them do it now, by name, logged by the duties' own write.
    holders = sorted(r["user_id"] for r in db.t["church_duty_holders"] if r["duty"] == "weekly_text")
    assert holders == sorted([RUTH, SARAH])
    assert db.t["church_duty_changes"][-1]["changed_by"] == OWNER
    s = cs.compose(_biz(db), OWNER, SARAH)
    assert s["job"] == {"key": "kids_director", "label": "Kids Director", "custom": True}
    assert {d["key"] for d in s["duties"] if d["held"]} >= {"weekly_text", "kids"}
    # The record says what really changed, the duties her new area brings too.
    assert got["summary"].startswith("changed Sarah Okafor's sheet: job: Kids Director; added Groups & classes; gave ")
    assert f"“{cd.CATALOG['weekly_text']['label']}”" in got["summary"]
    # Recorded, and the owner isn't told about their own change.
    rec = db.t["church_sheet_changes"][-1]
    assert rec["kind"] == "sheet" and rec["subject_user_id"] == SARAH and rec["changed_by"] == OWNER
    assert db.told == []
    # The job taken off the list: Sarah keeps her areas, and still reads as it.
    cj.remove(_biz(db), "kids_director", OWNER, "owner")
    s = cs.compose(_biz(db), OWNER, SARAH)
    assert s["job"]["label"] == "Kids Director" and s["areas"]["picked"] == ["kids_youth", "groups_classes"]


def test_a_job_is_a_label_and_never_changes_who_already_holds_it(db):
    cj.create(_biz(db), JOB, OWNER, "owner")
    cs.change(_biz(db), OWNER, SARAH, {"job": "kids_director"})
    assert _seat_of(db, SARAH)["areas"] == ["kids_youth"]             # only what was sent changed
    cj.update(_biz(db), "kids_director", {**JOB, "areas": ["office"], "duties": []}, OWNER, "owner")
    assert _seat_of(db, SARAH)["areas"] == ["kids_youth"] and _seat_of(db, SARAH)["lane"] == "kids_director"


def test_taking_the_only_doer_off_a_duty_is_refused_and_says_where_to_name_someone(db):
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), OWNER, RUTH, {"duties": {"remove": ["weekly_text"]}})
    assert e.value.status_code == 400
    assert f"only one who does “{cd.CATALOG['weekly_text']['label']}”" in e.value.detail
    assert db.t["church_duty_holders"] == []
    # With someone else doing it too, it comes off.
    cs.change(_biz(db), OWNER, SARAH, {"duties": {"add": ["weekly_text"]}})
    cs.change(_biz(db), OWNER, RUTH, {"duties": {"remove": ["weekly_text"]}})
    assert [r["user_id"] for r in db.t["church_duty_holders"] if r["duty"] == "weekly_text"] == [SARAH]


@pytest.mark.parametrize("body,word", [
    ({"areas": ["giving_money", "office"]}, "Giving & money"),
    ({"duties": {"add": ["books"]}}, "money job"),
    ({"areas": []}, "at least one"),
    ({"duties": {"add": ["sweeping"]}}, "isn't a duty"),
    ({"job": "no_such_job"}, "isn't one of this church's jobs"),
    ({"job": "treasurer"}, "Admin login"),
])
def test_what_even_the_owner_cant_put_on_a_managers_sheet_in_step_one(db, body, word):
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), OWNER, JORDAN, body)
    assert e.value.status_code == 400 and word in e.value.detail


def test_a_member_logins_duties_stay_locked_but_its_areas_can_be_set(db):
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), OWNER, MARK, {"duties": {"add": ["website"]}})
    assert e.value.detail == cs.NO_OFFICE_JOBS
    cs.change(_biz(db), OWNER, MARK, {"areas": ["website_outreach"]})
    assert _seat_of(db, MARK)["areas"] == ["website_outreach"]


def test_giving_more_asks_for_the_password_and_taking_away_never_does(db):
    asked = []
    _seat_of(db, SARAH)["areas"] = ["kids_youth", "website_outreach"]
    got = cs.change(_biz(db), OWNER, SARAH, {"areas": ["kids_youth"]}, widening=lambda: asked.append(1))
    assert asked == [] and not got["widens"] and got["changed"]       # an area taken off, and nothing gained
    cs.change(_biz(db), OWNER, SARAH, {"areas": ["kids_youth", "office"]}, widening=lambda: asked.append(1))
    assert asked == [1]

    def locked():
        raise HTTPException(403, {"code": "ledger_locked"})
    with pytest.raises(HTTPException):
        cs.change(_biz(db), OWNER, JORDAN, {"duties": {"add": ["first_guests"]}}, widening=locked)
    assert db.t["church_duty_holders"] == []                           # refused before anything was written


# ─── The grant, and what a holder may and may not do ──────────────────

def test_the_owner_or_an_admin_gives_the_grant_to_a_manager_and_it_isnt_a_duty(db):
    _give_grant(db)
    assert cj.grant_holders(BIZ) == {RUTH} and cj.holds_grant(BIZ, RUTH, "manager")
    assert cj.GRANT not in cd._moved(BIZ) and cj.GRANT not in cd.CATALOG
    assert cd.standing(BIZ, RUTH)["duties"] == frozenset(cd.STARTER["office_leadership"])
    s = cs.compose(_biz(db), OWNER, RUTH)
    assert next(d for d in s["duties"] if d["key"] == cj.GRANT)["held"]
    assert any("sets up the church's jobs and people's sheets" in line for line in s["chief"]["summary"])
    # An Admin gives it too, and takes it away.
    cs.change(_biz(db), ADMIN, JORDAN, {"duties": {"add": [cj.GRANT]}})
    assert cj.grant_holders(BIZ) == {RUTH, JORDAN}
    cs.change(_biz(db), ADMIN, JORDAN, {"duties": {"remove": [cj.GRANT]}})
    assert cj.grant_holders(BIZ) == {RUTH}
    assert db.t["church_duty_changes"][-1]["duty"] == cj.GRANT            # who gave it and when: the duties' log


@pytest.mark.parametrize("target", [MARK, ADMIN])
def test_the_grant_goes_only_to_a_manager_login(db, target):
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), OWNER, target, {"duties": {"add": [cj.GRANT]}})
    assert e.value.status_code == 400 and cj.grant_holders(BIZ) == set()


def test_a_holder_changes_a_managers_sheet_and_the_owner_is_told(db):
    _give_grant(db)
    db.told.clear()
    s = cs.compose(_biz(db), RUTH, SARAH)
    assert s["can_edit"] and s["editor"] == "holder"
    assert cs.GIVING_LOCKED in s["limits"] and cs.GRANT_LOCKED in s["limits"]
    assert "giving_money" in s["locked_areas"] and cj.GRANT in s["locked_duties"]
    assert {"monthly_report", "oversee_lanes", "books"} <= set(s["locked_duties"])
    got = cs.change(_biz(db), RUTH, SARAH, {"areas": ["kids_youth", "people_care"],
                                            "duties": {"add": ["first_guests"]}})
    assert got["changed"] and _seat_of(db, SARAH)["areas"] == ["people_care", "kids_youth"]
    rec = db.t["church_sheet_changes"][-1]
    assert rec["changed_by"] == RUTH and rec["subject_user_id"] == SARAH
    assert len(db.told) == 1
    title, body = db.told[0]
    assert title.startswith("Ruth Ellison changed Sarah Okafor's sheet: added People & care")
    assert "sets up jobs and people's sheets at Grace Fellowship" in body
    # And a Member's.
    cs.change(_biz(db), RUTH, MARK, {"areas": ["website_outreach"]})
    assert len(db.told) == 2


@pytest.mark.parametrize("target,body,word", [
    (RUTH, {"areas": ["office"]}, cs.OWN_SHEET),                                    # their own
    (ADMIN, {"duties": {"remove": ["books"]}}, cs.ADMINS_SHEET),                    # an Admin's
    (OWNER, {"areas": ["office"]}, cs.OWNERS_SHEET),                                # the owner's
    (SARAH, {"areas": ["kids_youth", "giving_money"]}, cs.GIVING_LOCKED),           # Giving & money
    (SARAH, {"duties": {"add": ["books"]}}, cs.MONEY_DUTY),                         # a money duty
    (SARAH, {"duties": {"add": ["oversee_lanes"]}}, cs.OVERSIGHT_LOCKED),           # the lanes' oversight
    (SARAH, {"duties": {"add": [cj.GRANT]}}, cs.GRANT_LOCKED),                      # the grant itself
    (JORDAN, {"duties": {"remove": [cj.GRANT]}}, cs.GRANT_LOCKED),                  # another holder's grant
    (SARAH, {"job": "treasurer"}, cs.ADMIN_JOB),                                    # an Admin job
])
def test_what_a_holder_may_not_do(db, target, body, word):
    _give_grant(db)
    _give_grant(db, JORDAN)
    db.told.clear()
    before = [dict(s) for s in db.t["business_users"]]
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), RUTH, target, body)
    assert e.value.status_code == 403 and e.value.detail == word
    assert db.t["business_users"] == before and cj.grant_holders(BIZ) == {RUTH, JORDAN} and db.told == []


def test_a_holder_makes_changes_and_removes_jobs_but_never_an_admin_job(db):
    _give_grant(db)
    db.told.clear()
    made = cs.save_job(_biz(db), "holder", RUTH, "Ruth Ellison", JOB)
    assert made["job"]["key"] == "kids_director"
    assert db.told[-1][0] == "Ruth Ellison added the job “Kids Director”"
    cs.save_job(_biz(db), "holder", RUTH, "Ruth Ellison", {**JOB, "does": "Runs the kids rooms"}, "kids_director")
    assert db.told[-1][0] == "Ruth Ellison changed the job “Kids Director”"
    with pytest.raises(HTTPException) as e:
        cs.save_job(_biz(db), "holder", RUTH, "Ruth Ellison", {**JOB, "label": "Finance Lead", "role": "admin"})
    assert e.value.status_code == 403 and e.value.detail == cj.OWNER_ONLY_ADMIN
    cs.remove_job(_biz(db), "holder", RUTH, "Ruth Ellison", "kids_director")
    assert db.told[-1][0] == "Ruth Ellison removed the job “Kids Director”"
    assert [r["kind"] for r in db.t["church_sheet_changes"]][-3:] == ["job", "job", "job"]
    # The owner's own job changes are recorded and not told.
    n = len(db.told)
    cs.save_job(_biz(db), "owner", OWNER, "Pastor Daniel Brooks", {**JOB, "label": "Youth Director"})
    assert len(db.told) == n


def test_a_login_moved_down_no_longer_holds_the_grant(db):
    _give_grant(db)
    _seat_of(db, RUTH)["role"] = "member"
    assert not cj.holds_grant(BIZ, RUTH, "member")
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), RUTH, SARAH, {"areas": ["office"]})
    assert e.value.detail == cs.NOT_AN_EDITOR


def test_a_grant_that_cant_be_read_is_never_a_yes(db, monkeypatch):
    _give_grant(db)
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **kw: (
        None if path.startswith("/church_duty_holders") and cj.GRANT in path else real(path, **kw)))
    assert cj.grant_holders(BIZ) is None and not cj.holds_grant(BIZ, RUTH, "manager")
    assert cj.editor(BIZ, RUTH, "manager") is None


# ─── An invite carries a church's own job ─────────────────────────────

def test_an_invite_can_carry_a_churchs_own_job_and_the_login_reads_as_it(db):
    import business_users_router as bu
    cj.create(_biz(db), JOB, OWNER, "owner")
    lane = ca.lane_for_invite(BIZ, "kids_director")
    assert lane == {"key": "kids_director", "label": "Kids Director", "role": "manager",
                    "areas": ["kids_youth", "groups_classes"], "does": JOB["does"], "custom": True}
    assert [x["key"] for x in ca.lanes_view(BIZ)] == list(ca.LANES) + ["kids_director"]
    assert [x["key"] for x in ca.lanes_view()] == list(ca.LANES)
    row = bu.make_invite_row(BIZ, email="ines@gracefellowship.example", role=lane["role"], lane=lane, person=None,
                             invited_by=OWNER)
    assert row["lane"] == "kids_director" and row["areas"] == ["kids_youth", "groups_classes"]
    INES = "b7000000-0000-4000-8000-000000000007"
    next(r for r in db.t["business_users"] if r.get("invited_email") == "ines@gracefellowship.example").update(
        user_id=INES, status="active")
    assert bu._lane_label(BIZ, INES, "manager", row["areas"]) == "Kids Director"
    # The areas page shows her job by its key, and the job is on its list.
    m = ca.build(_biz(db))
    assert next(x for x in m["logins"] if x["user_id"] == INES)["lane"] == "kids_director"
    assert m["lanes"][-1]["key"] == "kids_director"
    with pytest.raises(HTTPException) as e:
        ca.lane_for_invite(BIZ, "no_such_job")
    assert e.value.status_code == 400


# ─── What Chief is said to do is what Chief does ──────────────────────

def test_each_example_of_what_chief_does_is_a_verb_placed_in_that_area():
    import chief_areas
    for area, verb, _words in cs.EXAMPLES:
        assert area in chief_areas.VERBS[verb], (area, verb)
    assert {a for a, _v, _w in cs.EXAMPLES} <= set(ca.AREA_ORDER)


def test_chiefs_words_follow_the_sheet(db):
    s = cs.compose(_biz(db), OWNER, SARAH)
    assert s["chief"]["summary"][0] == "Sarah Okafor works in Kids & youth."
    assert "Start a class" not in s["chief"]["will"] and any(w.startswith("Start a class") for w in s["chief"]["wont"])
    cs.change(_biz(db), OWNER, SARAH, {"areas": ["kids_youth", "groups_classes"]})
    s = cs.compose(_biz(db), OWNER, SARAH)
    assert "Start a class" in s["chief"]["will"]


# ─── The routes ───────────────────────────────────────────────────────

@pytest.fixture
def office(db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import business_access
    import church_job_descriptions as cjd
    who = {"id": OWNER}

    def role(biz, uid):
        return "owner" if uid == OWNER else next((s["role"] for s in db.t["business_users"] if s["user_id"] == uid), None)
    monkeypatch.setattr(business_access, "_resolve_role", role)
    app = FastAPI()
    app.include_router(cjd.router)
    app.include_router(cs.router)
    app.dependency_overrides[sb_clients.authed_request] = (
        lambda: SimpleNamespace(user=SimpleNamespace(id=who["id"], email="someone@example.com", user_metadata={})))
    client = TestClient(app)
    client.who = who
    client.app_ = app
    return client


def test_the_sheet_route_answers_its_readers_and_refuses_the_rest(office, db):
    q = f"/church/sheet?business_id={BIZ}&user_id="
    assert office.get(q + JORDAN).json()["person"]["name"] == "Jordan Lee"
    office.who["id"] = JORDAN
    assert office.get(q + JORDAN).json()["can_edit"] is False
    r = office.get(q + SARAH)
    assert r.status_code == 403 and r.json()["detail"] == cs.NOT_YOURS
    office.who["id"] = STRANGER
    assert office.get(q + JORDAN).status_code == 404
    office.who["id"] = OWNER
    assert office.get(q + "not-a-login").status_code == 400
    db.t["businesses"][0]["type"] = "salon"
    assert office.get(q + JORDAN).status_code == 404


def test_the_put_asks_for_the_password_only_when_it_gives_more(office, db):
    _seat_of(db, SARAH)["areas"] = ["kids_youth", "website_outreach"]
    body = {"business_id": BIZ, "user_id": SARAH, "areas": ["kids_youth"]}
    r = office.put("/church/sheet", json=body)                       # an area taken off: no password
    assert r.status_code == 200 and r.json()["areas"]["picked"] == ["kids_youth"] and r.json()["changed"]
    assert r.json()["owner_told"] is False
    r = office.put("/church/sheet", json={**body, "areas": ["kids_youth", "office"]})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "ledger_locked"
    assert _seat_of(db, SARAH)["areas"] == ["kids_youth"]
    # With the password just re-proved (the invite's own unlock), it saves.
    import ledger_unlock
    os.environ.setdefault("AUDITOR_LINK_SECRET", "test-secret-for-the-sheet")
    token = ledger_unlock.mint(OWNER, ledger_unlock.SCOPE_ACCESS, BIZ)["token"]
    r = office.put("/church/sheet", json={**body, "areas": ["kids_youth", "office"]},
                   headers={ledger_unlock.UNLOCK_HEADER: token})
    assert r.status_code == 200 and _seat_of(db, SARAH)["areas"] == ["kids_youth", "office"]
    body = {"business_id": BIZ, "user_id": SARAH}
    office.who["id"] = JORDAN
    r = office.put("/church/sheet", json={**body, "user_id": SARAH})
    assert r.status_code == 403 and r.json()["detail"] == cs.NOT_AN_EDITOR


def test_the_job_routes_keep_to_whoever_sets_jobs_up(office, db):
    body = {"business_id": BIZ, **JOB}
    assert office.post("/church/jobs", json=body).json()["job"]["key"] == "kids_director"
    got = office.get(f"/church/sheet/jobs?business_id={BIZ}").json()
    assert got["can_manage"] and got["can_make_admin_job"] and got["jobs"][-1]["label"] == "Kids Director"
    assert office.put("/church/jobs/kids_director", json={**body, "label": "Children's Director"}).status_code == 200
    office.who["id"] = ADMIN
    got = office.get(f"/church/sheet/jobs?business_id={BIZ}").json()
    assert got["can_manage"] and not got["can_make_admin_job"]
    office.who["id"] = JORDAN                                         # a Manager without the grant
    got = office.get(f"/church/sheet/jobs?business_id={BIZ}").json()
    assert not got["can_manage"] and len(got["jobs"]) == 6
    assert office.post("/church/jobs", json={**body, "label": "Usher Lead"}).status_code == 403
    assert office.delete(f"/church/jobs/kids_director?business_id={BIZ}").status_code == 403
    office.who["id"] = MARK                                           # a Member doesn't read the list
    assert office.get(f"/church/sheet/jobs?business_id={BIZ}").status_code == 404
    _give_grant(db, JORDAN)
    office.who["id"] = JORDAN
    assert office.get(f"/church/sheet/jobs?business_id={BIZ}").json()["can_manage"]
    assert office.delete(f"/church/jobs/kids_director?business_id={BIZ}").status_code == 200
    assert cj.label_of(BIZ, "kids_director") == "Children's Director"


def test_the_job_descriptions_fixed_paths_still_answer_before_a_jobs_key(office):
    from starlette.routing import Match
    def first(method, path):
        scope = {"type": "http", "method": method, "path": path, "root_path": "", "query_string": b"", "headers": []}
        return next(r.endpoint.__name__ for r in office.app_.router.routes if r.matches(scope)[0] == Match.FULL)
    assert first("PUT", "/church/jobs/person") == "jobs_set"
    assert first("GET", "/church/jobs/whose") == "jobs_whose"
    assert first("GET", "/church/jobs") == "jobs_roster"
    assert first("PUT", "/church/jobs/kids_director") == "put_job"
    assert first("POST", "/church/jobs") == "post_job"
    assert "person" in cj._reserved() and "whose" in cj._reserved() and "draft" in cj._reserved()


# ─── Chief ────────────────────────────────────────────────────────────

def chief(db, uid, verb, taint=0, **action):
    """One Chief verb in one turn, as `uid` ('' for nobody signed in)."""
    import asyncio
    import chief_of_staff as cos

    async def go():
        cos._UNTRUSTED_TAINT.set(taint)
        return await cos.ACTION_HANDLERS[verb](None, {"id": BIZ}, dict(action))
    token = cos._TURN_USER_ID.set(uid or "")
    try:
        return asyncio.run(go())
    finally:
        cos._TURN_USER_ID.reset(token)


def test_every_verb_is_a_handler_placed_by_its_own_checks_and_never_the_owners_alone():
    import action_registry
    import chief_areas
    import chief_church_sheet as ccs
    import chief_of_staff as cos
    for verb in ccs.HANDLERS:
        assert cos.ACTION_HANDLERS[verb] is ccs.HANDLERS[verb]
        assert chief_areas.VERBS[verb] == (chief_areas.ALL,) and verb not in chief_areas.OWNERS
        assert not action_registry.may_expose_to_agent(verb)
    assert {t["name"] for t in ccs.TOOLS} == {"sheet_of", "list_church_jobs", "draft_church_job"}
    assert ccs.WRITES == {"save_church_job", "remove_church_job"}


def test_chief_reads_a_sheet_for_whoever_may_read_it(db):
    got = chief(db, OWNER, "sheet_of", who="Jordan")
    assert not got.get("failed"), got["result"]
    assert got["result"].startswith("Jordan Lee's sheet: Manager login.")
    assert "Job: Media & Communications." in got["result"]
    assert "Areas: Worship & media and Website & outreach (Picked by your church)." in got["result"]
    assert "Who gave, and how much: not open to them." in got["result"]
    assert f"sheet {JORDAN}" in got["result"] and got["nav"] == {"tab": "operate", "sub": "areas", "sheet": JORDAN}
    mine = chief(db, JORDAN, "sheet_of", who="me")
    assert "(yours)" in mine["result"] and "Nobody changes their own sheet" in mine["result"]
    # Another Manager's isn't theirs to read, by any name.
    no = chief(db, JORDAN, "sheet_of", who="Sarah Okafor")
    assert no["failed"] and cs.NOT_YOURS in no["result"]
    # A first name two people share asks which.
    _seat_of(db, MARK)["name"] = "Jordan Diaz"
    both = chief(db, OWNER, "sheet_of", who="Jordan")
    assert both["failed"] and "could be Jordan Diaz and Jordan Lee" in both["result"]


def test_chief_keeps_sheets_and_jobs_to_someone_signed_in_at_a_church(db):
    assert "signed in" in chief(db, "", "sheet_of", who="me")["result"]
    assert chief(db, STRANGER, "list_church_jobs")["failed"]
    assert "only when someone at the church asks" in chief(db, OWNER, "sheet_of", who="me", _unattended=True)["result"]
    db.t["businesses"][0]["type"] = "salon"
    assert "a church's office" in chief(db, OWNER, "list_church_jobs")["result"]


def test_chief_hands_over_the_pieces_of_a_job_only_to_whoever_sets_jobs_up(db):
    got = chief(db, OWNER, "draft_church_job")
    assert "kids_youth: Kids & youth" in got["result"] and "- weekly_text: " in got["result"]
    assert "- books: " in got["result"] and "Admin: sees the whole church" in got["result"]
    no = chief(db, JORDAN, "draft_church_job")
    assert no["failed"] and "sets up jobs and people's sheets" in no["result"]
    _give_grant(db, JORDAN)
    held = chief(db, JORDAN, "draft_church_job")
    assert not held.get("failed")
    # A holder isn't offered what a holder can't put in a job.
    assert "- books: " not in held["result"] and "- oversee_lanes: " not in held["result"]
    assert "Admin: sees the whole church" not in held["result"]
    assert "An Admin job is the owner's alone to make." in held["result"]


def test_chief_saves_changes_and_removes_a_job_for_the_owner_and_for_a_holder(db):
    got = chief(db, OWNER, "save_church_job", **JOB)
    assert not got.get("failed"), got["result"]
    assert got["job"] == "kids_director" and got["created"] and "Saved the job “Kids Director”" in got["result"]
    listed = chief(db, JORDAN, "list_church_jobs")
    assert "Kids Director (the church made it; Manager login; key kids_director)" in listed["result"]
    assert "Only the owner, an Admin, or whoever sets up jobs" in listed["result"]
    # A Manager without the grant can't change it; with it, they can, and the owner is told.
    no = chief(db, JORDAN, "save_church_job", job="Kids Director", does="Runs the kids rooms")
    assert no["failed"] and "Nothing changed" in no["result"]
    _give_grant(db, JORDAN)
    db.told.clear()
    changed = chief(db, JORDAN, "save_church_job", job="Kids Director", does="Runs the kids rooms",
                    role="manager", areas=["kids_youth"], duties=["kids"])
    assert not changed.get("failed") and not changed["created"]
    assert "Nobody who already holds it changed." in changed["result"]
    assert db.told[-1][0] == "Jordan Lee changed the job “Kids Director”"
    admin_job = chief(db, JORDAN, "save_church_job", label="Finance Lead", role="admin")
    assert admin_job["failed"] and "Only the owner" in admin_job["result"]
    preset = chief(db, OWNER, "save_church_job", job="Treasurer", does="Counts")
    assert preset["failed"] and "starting jobs" in preset["result"]
    gone = chief(db, JORDAN, "remove_church_job", job="kids_director")
    assert not gone.get("failed") and cj.customs(BIZ) == []


def test_a_job_just_made_can_be_undone_and_a_change_cant(db):
    import action_inverse
    made = chief(db, OWNER, "save_church_job", **JOB)
    inv = action_inverse.INVERSES["save_church_job"]
    assert inv.build({}, made) == {"type": "remove_church_job", "job": "kids_director"}
    changed = chief(db, OWNER, "save_church_job", job="Kids Director", does="Runs the kids rooms")
    assert inv.build({}, changed) is None


def test_a_save_on_a_turn_that_read_someone_elses_words_waits_for_the_person(db):
    held = chief(db, OWNER, "save_church_job", taint=1, **JOB)
    assert held["failed"] and held["needs_confirmation"] and "HELD" in held["result"]
    assert cj.customs(BIZ) == []
    assert not chief(db, OWNER, "list_church_jobs", taint=1).get("failed")       # a read is never held


def test_a_holders_own_prompt_line_says_what_they_set_up_and_what_stays_the_owners(db):
    import chief_areas
    import chief_church_sheet as ccs
    assert ccs.grant_line(BIZ, RUTH) is None
    _give_grant(db)
    line = ccs.grant_line(BIZ, RUTH)
    assert "sets up the church's jobs and people's sheets" in line and "never Giving & money" in line
    assert line in (chief_areas._jobs(BIZ, RUTH) or "")
    assert ccs.grant_line(BIZ, OWNER) is None and ccs.grant_line(BIZ, ADMIN) is None


def test_chiefs_instructions_say_it_never_changes_a_sheet_itself():
    import pathlib
    text = (pathlib.Path(ROOT) / "chief_prompt.py").read_text(encoding="utf-8")
    block = text[text.index("CHURCH SHEETS AND JOBS"):][:6000]
    for verb in ("sheet_of", "list_church_jobs", "draft_church_job", "save_church_job", "remove_church_job"):
        assert verb in block
    assert "YOU NEVER CHANGE A PERSON'S SHEET YOURSELF" in block
    assert "WHAT STAYS WITH THE OWNER OR AN ADMIN" in block
    import chief_of_staff as cos
    assert "change_sheet" not in cos.ACTION_HANDLERS and "set_sheet" not in cos.ACTION_HANDLERS


def test_navigate_carries_a_login_id_to_logins_and_areas_and_nothing_else(db):
    import asyncio
    import chief_of_staff as cos

    def go(**a):
        return asyncio.run(cos.handle_navigate(None, {"id": BIZ}, {"type": "navigate", **a}))
    assert go(tab="operate", sub="areas", sheet=JORDAN)["nav"]["sheet"] == JORDAN
    assert "sheet" not in go(tab="operate", sub="areas", sheet="open the books")["nav"]
    assert "sheet" not in go(tab="operate", sub="tasks", sheet=JORDAN)["nav"]


# ─── The security review (2026-11-17): "more" is judged by the result ──

def _lane_spelled_apart(db):
    """Sarah's stored job is Office & Leadership while her areas spell People & Care."""
    _seat_of(db, SARAH).update(lane="office_leadership", areas=["people_care", "kids_youth", "groups_classes"])


def _taking_away_that_gives_more(db):
    """Three changes that read as taking away and leave the login with more:
    (who, body, what it gains)."""
    return [
        # Back to Chief's guess: nothing places Sarah, so she would see the whole church.
        (SARAH, {"areas": None}, "the whole church"),
        # One area off Media & Communications spells Sunday & Serving, and brings its duties.
        (JORDAN, {"areas": ["worship_media"]}, "background_checks"),
        # No job: the lane her areas spell takes over, with its duties.
        ("spelled", {"job": None}, "first_guests"),
    ]


@pytest.mark.parametrize("case", [0, 1, 2])
def test_a_change_that_reads_as_taking_away_but_gives_more_asks_the_owner_for_the_password(db, case):
    who, body, gains = _taking_away_that_gives_more(db)[case]
    if who == "spelled":
        _lane_spelled_apart(db)
        who = SARAH
    before = dict(_seat_of(db, who))
    held = set(cd.standing(BIZ, who)["duties"])

    def locked():
        raise HTTPException(403, {"code": "ledger_locked"})
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), OWNER, who, body, widening=locked)
    assert e.value.detail == {"code": "ledger_locked"}
    assert _seat_of(db, who) == before and db.t["church_duty_holders"] == []      # nothing was written
    # With the password re-proved it saves, and the login really has more.
    asked = []
    got = cs.change(_biz(db), OWNER, who, body, widening=lambda: asked.append(1))
    assert asked == [1] and got["widens"]
    for c in (cd._CACHE, ca._MY_CACHE):
        c.clear()
    after = set(cd.standing(BIZ, who)["duties"])
    assert after - held, "it gained duties"
    if gains != "the whole church":
        assert gains in after - held
    else:
        assert cs.compose(_biz(db), OWNER, who)["areas"]["shown"] is None
        assert "areas back to Chief's guess" in got["summary"]


def test_a_holder_never_sends_a_login_back_to_chiefs_guess(db):
    _give_grant(db)
    db.told.clear()
    before = dict(_seat_of(db, SARAH))
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), RUTH, SARAH, {"areas": None})
    assert e.value.status_code == 403 and e.value.detail == cs.BACK_TO_GUESS
    assert _seat_of(db, SARAH) == before and db.told == []


@pytest.mark.parametrize("case", [1, 2])
def test_a_holder_needs_the_password_too_when_taking_away_gives_more(db, case):
    _give_grant(db)
    who, body, gains = _taking_away_that_gives_more(db)[case]
    if who == "spelled":
        _lane_spelled_apart(db)
        who = SARAH
    before = dict(_seat_of(db, who))

    def locked():
        raise HTTPException(403, {"code": "ledger_locked"})
    with pytest.raises(HTTPException):
        cs.change(_biz(db), RUTH, who, body, widening=locked)
    assert _seat_of(db, who) == before
    asked = []
    got = cs.change(_biz(db), RUTH, who, body, widening=lambda: asked.append(1))
    assert asked == [1] and got["owner_told"]
    assert "; gave " in " ".join(db.told[-1])                     # the owner reads that it came with duties


def test_a_holders_ceiling_is_held_on_what_the_change_leaves_the_login_with(db, monkeypatch):
    # However a change comes to give the lanes' oversight (here: forced), a holder's is refused before any write.
    _give_grant(db)
    real = cs._held
    calls = []

    def held(*a, **k):
        calls.append(1)
        out = real(*a, **k)
        return out | {"oversee_lanes"} if len(calls) == 2 else out          # the "after" answer
    monkeypatch.setattr(cs, "_held", held)
    before = dict(_seat_of(db, SARAH))
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), RUTH, SARAH, {"areas": ["kids_youth", "office"]})
    assert e.value.status_code == 403 and e.value.detail == cs.OVERSIGHT_LOCKED
    assert _seat_of(db, SARAH) == before


def test_the_sheets_reckoning_of_a_logins_duties_is_the_churchs_own(db):
    ch = co.Church(_biz(db))
    for uid in (ADMIN, RUTH, JORDAN, SARAH, MARK):
        seat = ch.seats[uid]
        shown = None if seat["role"] == "admin" else cs._areas(_biz(db), ch, uid)["shown"]
        picked = seat["areas"] if isinstance(seat["areas"], list) else None
        assert cs._held(ch, uid, seat["role"], seat["lane"], picked, shown, ch.moved) == ch.held(uid), uid
        assert set(ch.held(uid)) == set(cd.standing(BIZ, uid)["duties"])


def test_a_job_alone_is_a_label_and_asks_for_no_password(db):
    cj.create(_biz(db), {**JOB, "areas": ["kids_youth"], "duties": []}, OWNER, "owner")
    asked = []
    got = cs.change(_biz(db), OWNER, SARAH, {"job": "kids_director"}, widening=lambda: asked.append(1))
    assert asked == [] and not got["widens"]
    # A church job brings only the duties given on the sheet (2026-11-18), so the three she did by her
    # area are kept for her by name, and the record says so.
    assert got["summary"] == ("changed Sarah Okafor's sheet: job: Kids Director; kept “Kids”, “Youth and Teen "
                              "Bible Study” and “Background checks” by name")


def test_changing_only_the_areas_keeps_a_churchs_own_job_on_the_login(db):
    cj.create(_biz(db), JOB, OWNER, "owner")
    cs.change(_biz(db), OWNER, SARAH, {"job": "kids_director"})
    cs.change(_biz(db), OWNER, SARAH, {"areas": ["kids_youth", "people_care"]})
    assert _seat_of(db, SARAH)["lane"] == "kids_director"
    # The older Logins & areas route picking a lane makes that lane the job.
    assert ca.set_login(BIZ, SARAH, "manager", areas=list(ca.LANES["people_care"]["areas"]),
                        job="people_care") == "people_care"
    cs.change(_biz(db), OWNER, SARAH, {"job": "kids_director", "areas": ["kids_youth", "people_care"]})
    # A removed job stays too: she still reads as it.
    cj.remove(_biz(db), "kids_director", OWNER, "owner")
    cs.change(_biz(db), OWNER, SARAH, {"areas": ["kids_youth"]})
    assert _seat_of(db, SARAH)["lane"] == "kids_director"
    # A lane is still the lane the areas spell, as it always was.
    cs.change(_biz(db), OWNER, JORDAN, {"areas": ["worship_media"]})
    assert _seat_of(db, JORDAN)["lane"] == "sunday_serving"
    # And "no job" clears a church's own job.
    cs.change(_biz(db), OWNER, SARAH, {"job": None})
    assert _seat_of(db, SARAH)["lane"] is None


def test_a_member_or_viewer_reading_their_own_sheet_isnt_sent_the_churchs_jobs(db):
    cj.create(_biz(db), JOB, OWNER, "owner")
    assert cs.compose(_biz(db), MARK, MARK)["jobs"] == []
    assert len(cs.compose(_biz(db), JORDAN, JORDAN)["jobs"]) == 6
    for uid in (MARK, STRANGER):
        with pytest.raises(HTTPException) as e:
            cs.jobs_view(_biz(db), uid)
        assert e.value.status_code == 403


@pytest.mark.parametrize("body", [
    {"areas": [[]]}, {"areas": [{}]}, {"areas": "office"}, {"areas": [5]},
    {"duties": {"add": 5}}, {"duties": {"add": [[]]}}, {"duties": {"remove": [{}]}}, {"duties": "website"},
    {"duties": {"add": "website"}}, {"job": {}}, {"job": ["kids_director"]}, {"job": 5},
])
def test_a_malformed_change_is_a_400_and_never_a_crash(db, body):
    before = dict(_seat_of(db, JORDAN))
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), OWNER, JORDAN, body)
    assert e.value.status_code == 400 and isinstance(e.value.detail, str) and e.value.detail
    assert _seat_of(db, JORDAN) == before


@pytest.mark.parametrize("change", [{"areas": [[]]}, {"areas": [{}]}, {"duties": [{}]}, {"duties": [[]]},
                                    {"duties": "kids"}, {"role": []}, {"role": {}}, {"areas": "office"}])
def test_a_malformed_job_is_a_400_and_never_a_crash(db, change):
    with pytest.raises(HTTPException) as e:
        cj.clean({**JOB, **change}, "owner")
    assert e.value.status_code == 400


def test_a_grant_that_cant_be_read_refuses_before_anything_is_written(db, monkeypatch):
    monkeypatch.setattr(cj, "grant_holders", lambda biz: None)
    before = dict(_seat_of(db, SARAH))
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), OWNER, SARAH, {"areas": ["kids_youth", "office"],
                                           "duties": {"add": ["first_guests", cj.GRANT]}})
    assert e.value.status_code == 503
    assert _seat_of(db, SARAH) == before and db.t["church_duty_holders"] == []


# ─── A grant never comes back with the person ─────────────────────────

def test_a_login_taken_off_the_team_loses_the_grant_and_a_reinvite_isnt_a_holder(db):
    import business_users_router as bu
    _give_grant(db)
    seat = _seat_of(db, RUTH)
    seat["status"] = "revoked"
    out = bu.hand_back_login(BIZ, RUTH)
    assert out["failed"] == 0 and cj.grant_holders(BIZ) == set()
    assert db.t["church_duty_changes"][-1]["duty"] == cj.GRANT and db.t["church_duty_changes"][-1]["to_holders"] is None
    # Invited again as a Manager: not a holder until the owner gives it again.
    seat["status"] = "active"
    assert not cj.holds_grant(BIZ, RUTH, "manager") and cj.editor(BIZ, RUTH, "manager") is None


def test_a_login_that_just_joined_holds_no_grant_left_from_before(db):
    import business_users_router as bu
    NEW = "b8000000-0000-4000-8000-000000000008"
    db.t["church_duty_holders"].append({"business_id": BIZ, "duty": cj.GRANT, "user_id": NEW})     # left behind
    db.t["business_users"].append({"id": "i1", "business_id": BIZ, "invited_email": "ines@gracefellowship.example",
                                   "role": "manager", "status": "invited", "token": "tok-1", "user_id": None,
                                   "contact_id": None, "name": None, "lane": None, "areas": None})
    bu.accept(bu.AcceptBody(token="tok-1", name="Ines Abara"), SimpleNamespace(id=NEW, email="ines@gracefellowship.example"))
    assert _seat_of(db, NEW)["status"] == "active"
    assert cj.grant_holders(BIZ) == set() and not cj.holds_grant(BIZ, NEW, "manager")


def test_dropping_a_grant_says_when_it_couldnt(db, monkeypatch):
    assert cj.drop_grant(BIZ, MARK) is None                     # held none
    _give_grant(db)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda *a, **k: None)
    assert cj.drop_grant(BIZ, RUTH) is False and cj.grant_holders(BIZ) == {RUTH}


# ─── Re-proving the password works for whoever is acting ──────────────

def test_who_may_re_prove_their_password_to_change_who_can_get_in(db):
    import ledger_unlock as L
    _give_grant(db)
    db.t["business_users"].append(_seat("b0000000-0000-4000-8000-00000000000a", "viewer",
                                        "view@gracefellowship.example", "Vera Lund"))
    OTHER = "0be00000-0000-4000-8000-00000000000b"
    db.t["businesses"].append({"id": OTHER, "name": "Another Church", "type": "church", "owner_id": STRANGER})
    for uid in (OWNER, ADMIN, RUTH):                              # the owner, an Admin, a holder
        assert L._require_actor(BIZ, uid, L.SCOPE_ACCESS)["id"] == BIZ
    for uid in (JORDAN, MARK, "b0000000-0000-4000-8000-00000000000a", STRANGER):
        with pytest.raises(HTTPException) as e:                   # a plain Manager, a Member, a Viewer, another church's owner
            L._require_actor(BIZ, uid, L.SCOPE_ACCESS)
        assert e.value.status_code == 403
    # Danger stays the owner's alone.
    assert L._require_actor(BIZ, OWNER, L.SCOPE_DANGER)["id"] == BIZ
    for uid in (ADMIN, RUTH, JORDAN):
        with pytest.raises(HTTPException) as e:
            L._require_actor(BIZ, uid, L.SCOPE_DANGER)
        assert e.value.status_code == 403
    # A seat that was taken away, and a grant that can't be read, are never a yes.
    _seat_of(db, ADMIN)["status"] = "revoked"
    with pytest.raises(HTTPException):
        L._require_actor(BIZ, ADMIN, L.SCOPE_ACCESS)
    import church_job_defs
    real = church_job_defs.grant_holders
    church_job_defs.grant_holders = lambda biz: None
    try:
        with pytest.raises(HTTPException):
            L._require_actor(BIZ, RUTH, L.SCOPE_ACCESS)
    finally:
        church_job_defs.grant_holders = real
    with pytest.raises(HTTPException) as e:
        L._require_actor(OTHER, OWNER, L.SCOPE_ACCESS)            # this church's owner at someone else's
    assert e.value.status_code == 403


@pytest.mark.parametrize("bad", ["", "not-a-uuid", BIZ + "#", BIZ + "&select=*", "../x", None])
def test_the_step_ups_business_id_is_a_uuid_before_it_reaches_a_path(bad):
    import ledger_unlock as L
    with pytest.raises(HTTPException) as e:
        L._business_uuid(bad)
    assert e.value.status_code == 400
    assert L._business_uuid(BIZ.upper()) == BIZ


def test_the_step_up_route_keeps_its_limit_its_fail_closed_check_and_both_ledger_rows(db, monkeypatch):
    import asyncio
    import audit_log
    import ledger_unlock as L
    import rate_limit
    rows, ok, allow = [], {"v": True}, {"v": True}

    async def check(email, password):
        return ok["v"]
    monkeypatch.setattr(L, "check_password", check)
    monkeypatch.setattr(rate_limit, "allow_strict", lambda name, key: allow["v"])
    monkeypatch.setattr(audit_log, "record", lambda biz, **kw: rows.append((biz, kw["verb"])))
    monkeypatch.setenv("AUDITOR_LINK_SECRET", "test-secret")

    def go(uid, scope, biz=BIZ):
        return asyncio.run(L.step_up(L._StepUpBody(business_id=biz, password="pw", scope=scope),
                                     SimpleNamespace(id=uid, email="someone@example.com")))
    out = go(ADMIN, "access")                                     # an Admin can confirm now
    assert out["ok"] and L.verify(out["token"], ADMIN, L.SCOPE_ACCESS, BIZ)
    assert not L.verify(out["token"], ADMIN, L.SCOPE_ACCESS), "it is for this church and names it"
    assert not L.verify(out["token"], ADMIN, L.SCOPE_ACCESS, "0a000000-0000-4000-8000-00000000000a")
    assert not L.verify(out["token"], ADMIN, L.SCOPE_DANGER, BIZ) and rows[-1] == (BIZ, "stepup:access")
    for uid, scope, status in ((ADMIN, "danger", 403), (JORDAN, "access", 403), (OWNER, "ledger", 400)):
        with pytest.raises(HTTPException) as e:
            go(uid, scope)
        assert e.value.status_code == status
    with pytest.raises(HTTPException) as e:
        go(OWNER, "access", BIZ + "%23")
    assert e.value.status_code == 400
    ok["v"] = False
    with pytest.raises(HTTPException) as e:
        go(ADMIN, "access")
    assert e.value.status_code == 403 and rows[-1] == (BIZ, "stepup:access_failed")
    allow["v"] = False                                            # the limiter says no: never a pass
    with pytest.raises(HTTPException) as e:
        go(OWNER, "access")
    assert e.value.status_code == 429


# ─── The two reads take a real business id ────────────────────────────

@pytest.mark.parametrize("path", ["/church/sheet?user_id=" + JORDAN + "&business_id=", "/church/sheet/jobs?business_id="])
def test_the_reads_refuse_a_business_id_that_isnt_a_uuid_before_anything_is_read(office, db, monkeypatch, path):
    seen = []
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p, **k: (seen.append(p), real(p, **k))[1])
    for bad in (BIZ + "%23", BIZ + "%26select%3D*", "not-a-uuid"):
        r = office.get(path + bad)
        assert r.status_code == 400, (bad, r.status_code)
    assert seen == []                                              # nothing reached the database
    assert office.get(path + BIZ).status_code == 200


# ─── What leaves with the church, and what a restore brings back ───────

def test_the_jobs_are_exported_and_their_change_record_is_not():
    import account_lifecycle as al
    assert "church_jobs" in al.BUSINESS_CHILD_TABLES, "a church's own jobs are its data: exported, and deleted with it"
    assert "church_jobs" in al._IMPORT_SKIP, "they name logins by sign-in id: a restored church sets them up again"
    assert "church_sheet_changes" in al.EXPORT_EXCLUDED and "church_sheet_changes" not in al.BUSINESS_CHILD_TABLES
    sql = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "supabase",
                            "APPLY-2026-11-17-church-jobs.sql"), encoding="utf-8").read()
    assert sql.count("references public.businesses(id) on delete cascade") == 2      # both go with the church


# ─── The sheet sets a login's level (2026-11-18) ──────────────────────
# Kevin, on whether the sheet should change a login's level: "everything
# else, I agree." Until then only the invite set it.

def _level(db, uid):
    return _seat_of(db, uid)["role"]


def _options(db, viewer, target):
    return cs.compose(_biz(db), viewer, target)["level_options"]


def test_the_sheet_lists_the_four_levels_and_which_this_editor_may_set(db):
    got = _options(db, OWNER, JORDAN)
    assert [o["key"] for o in got] == ["viewer", "member", "manager", "admin"]
    assert all(o["allowed"] and o["why"] == "" and o["label"] and o["means"] for o in got)
    assert [o["key"] for o in got if o["current"]] == ["manager"]
    # An Admin, and whoever sets up jobs and sheets, set every level but Admin.
    _give_grant(db)
    for editor in (ADMIN, RUTH):
        got = {o["key"]: o for o in _options(db, editor, JORDAN)}
        assert [k for k, o in got.items() if o["allowed"]] == ["viewer", "member", "manager"]
        assert got["admin"]["why"] == cs.ADMIN_LEVEL
    # A sheet that can't be changed offers none: your own, an Admin's for another Admin, the owner's.
    assert _options(db, JORDAN, JORDAN) == []
    assert _options(db, ADMIN, ADMIN2) == []
    assert _options(db, ADMIN, OWNER) == [] and _options(db, OWNER, OWNER) == []
    # The owner sets an Admin's.
    assert [o["key"] for o in _options(db, OWNER, ADMIN) if o["current"]] == ["admin"]


def test_raising_a_level_asks_for_the_password_and_lowering_one_doesnt(db):
    def locked():
        raise HTTPException(403, {"code": "ledger_locked"})
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), OWNER, MARK, {"level": "manager"}, widening=locked)
    assert e.value.detail == {"code": "ledger_locked"} and _level(db, MARK) == "member"     # nothing written
    asked = []
    got = cs.change(_biz(db), OWNER, MARK, {"level": "manager"}, widening=lambda: asked.append(1))
    assert asked == [1] and got["widens"] and _level(db, MARK) == "manager"
    assert "level: Manager (was Member)" in got["summary"] and "gave " in got["summary"]
    assert got["owner_told"] is False
    # Down again: less, so nothing is asked.
    got = cs.change(_biz(db), OWNER, MARK, {"level": "viewer"}, widening=locked)
    assert not got["widens"] and _level(db, MARK) == "viewer"
    assert "level: Viewer (was Manager)" in got["summary"] and "took away " in got["summary"]
    # Viewer to Member holds no duty either way, and is still a higher level.
    asked = []
    cs.change(_biz(db), OWNER, MARK, {"level": "member"}, widening=lambda: asked.append(1))
    assert asked == [1] and _level(db, MARK) == "member"
    # The same level again changes nothing and asks nothing.
    got = cs.change(_biz(db), OWNER, MARK, {"level": "member"}, widening=locked)
    assert got == {"widens": False, "summary": "", "changed": False, "owner_told": False}


@pytest.mark.parametrize("bad", ["owner", "boss", "", 3, ["manager"]])
def test_a_level_that_isnt_one_is_a_400(db, bad):
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), OWNER, MARK, {"level": bad})
    assert e.value.status_code == 400 and e.value.detail == cs.NOT_A_LEVEL
    assert _level(db, MARK) == "member"


def test_an_admin_sets_every_level_but_admin_and_never_another_admins(db):
    cs.change(_biz(db), ADMIN, MARK, {"level": "manager"})
    assert _level(db, MARK) == "manager"
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), ADMIN, MARK, {"level": "admin"})
    assert e.value.status_code == 403 and e.value.detail == cs.ADMIN_LEVEL and _level(db, MARK) == "manager"
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), ADMIN, ADMIN2, {"level": "manager", "areas": ["office"]})
    assert e.value.status_code == 403 and e.value.detail == cs.ADMINS_SHEET and _level(db, ADMIN2) == "admin"


def test_a_holder_sets_a_level_below_admin_and_the_owner_is_told(db):
    _give_grant(db)
    db.told.clear()
    asked = []
    got = cs.change(_biz(db), RUTH, MARK, {"level": "manager", "areas": ["kids_youth"]},
                    widening=lambda: asked.append(1))
    assert asked == [1] and _level(db, MARK) == "manager" and got["owner_told"] is True
    assert len(db.told) == 1 and "level: Manager (was Member)" in db.told[0][0] + db.told[0][1]
    rec = db.t["church_sheet_changes"][-1]
    assert rec["subject_user_id"] == MARK and rec["changed_by"] == RUTH and rec["detail"]["level"] == "manager"
    # Never Admin, never their own, never an Admin's or the owner's.
    for target, body, word in ((MARK, {"level": "admin"}, cs.ADMIN_LEVEL), (RUTH, {"level": "member"}, cs.OWN_SHEET),
                               (ADMIN, {"level": "manager", "areas": ["office"]}, cs.ADMINS_SHEET),
                               (OWNER, {"level": "manager"}, cs.OWNERS_SHEET)):
        with pytest.raises(HTTPException) as e:
            cs.change(_biz(db), RUTH, target, body)
        assert e.value.status_code == 403 and e.value.detail == word


def test_a_holders_ceiling_holds_when_a_higher_level_would_bring_a_locked_duty(db):
    """A Member whose person is the Executive Pastor would, as a Manager, do
    the lanes' oversight: that is the owner's or an Admin's to give."""
    _give_grant(db)
    db.t["contacts"].append({"id": "c-mark", "business_id": BIZ, "name": "Mark Diaz",
                             "email": "mark@gracefellowship.example"})
    db.t["church_role_defs"].append({"id": "d-exec", "business_id": BIZ, "key": cd.EXEC, "catalog_key": cd.EXEC,
                                     "title": "Executive Pastor", "job": "pastoral", "status": "active"})
    db.t["church_leader_roles"].append({"business_id": BIZ, "contact_id": "c-mark", "role": cd.EXEC,
                                        "status": "active", "scope": None})
    _seat_of(db, MARK)["contact_id"] = "c-mark"
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), RUTH, MARK, {"level": "manager"})
    assert e.value.status_code == 403 and e.value.detail == cs.OVERSIGHT_LOCKED and _level(db, MARK) == "member"
    # The owner can, and it reads as giving more.
    asked = []
    got = cs.change(_biz(db), OWNER, MARK, {"level": "manager"}, widening=lambda: asked.append(1))
    assert asked == [1] and _level(db, MARK) == "manager" and cd.OVERSEE in co.Church(_biz(db)).held(MARK)
    assert got["widens"]


def test_a_login_lowered_below_manager_no_longer_sets_up_jobs_in_the_same_save(db):
    _give_grant(db)
    assert RUTH in cj.grant_holders(BIZ)
    got = cs.change(_biz(db), OWNER, RUTH, {"level": "member"})
    assert _level(db, RUTH) == "member" and RUTH not in cj.grant_holders(BIZ)
    assert f"took away “{cj.GRANT_LABEL}”" in got["summary"]
    # Raised again, the grant doesn't come back with the level.
    cs.change(_biz(db), OWNER, RUTH, {"level": "manager"})
    assert _level(db, RUTH) == "manager" and not cj.holds_grant(BIZ, RUTH, "manager")
    assert cj.editor(BIZ, RUTH, "manager") is None


def test_only_the_owner_or_an_admin_lowers_someone_who_sets_up_jobs(db):
    _give_grant(db, RUTH)
    _give_grant(db, JORDAN)
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), RUTH, JORDAN, {"level": "member"})
    assert e.value.status_code == 403 and e.value.detail == cs.HOLDERS_LEVEL.format(name="Jordan Lee")
    assert _level(db, JORDAN) == "manager" and JORDAN in cj.grant_holders(BIZ)
    cs.change(_biz(db), ADMIN, JORDAN, {"level": "member"})
    assert _level(db, JORDAN) == "member" and JORDAN not in cj.grant_holders(BIZ)


def test_the_owner_makes_someone_an_admin_and_their_areas_stay_stored(db):
    _give_grant(db, JORDAN)
    asked = []
    got = cs.change(_biz(db), OWNER, JORDAN,
                    {"level": "admin", "areas": ["office"], "duties": {"add": ["first_guests"], "remove": ["website"]}},
                    widening=lambda: asked.append(1))
    seat = _seat_of(db, JORDAN)
    assert asked == [1] and seat["role"] == "admin"
    # An Admin sees the whole church: what was sent with it is left as stored, there again if moved back.
    assert seat["areas"] == ["worship_media", "website_outreach"] and seat["lane"] == "media_comms"
    assert "level: Admin (was Manager), so they see the whole church, giving included" in got["summary"]
    assert "Giving & money" in got["summary"]
    assert JORDAN not in cj.grant_holders(BIZ)            # an Admin sets jobs up already: no row left behind
    sheet = cs.compose(_biz(db), OWNER, JORDAN)
    assert sheet["areas"]["by"] == "all" and sheet["person"]["role"] == "admin"


def test_an_admin_job_goes_with_the_admin_level(db):
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), OWNER, JORDAN, {"job": "treasurer"})
    assert e.value.status_code == 400 and e.value.detail == cs.ADMIN_JOB_NEEDS_LEVEL
    cs.change(_biz(db), OWNER, JORDAN, {"job": "treasurer", "level": "admin"})
    seat = _seat_of(db, JORDAN)
    assert seat["role"] == "admin" and seat["lane"] == "treasurer"
    # An Admin can't: the level it needs is the owner's to give.
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), ADMIN, SARAH, {"job": "treasurer", "level": "admin"})
    assert e.value.status_code == 403 and e.value.detail == cs.ADMIN_LEVEL


def test_an_admin_moved_down_must_be_left_with_areas_of_their_own(db):
    def locked():
        raise HTTPException(403, {"code": "ledger_locked"})
    for body in ({"level": "manager"}, {"level": "manager", "areas": None}, {"level": "member"}):
        with pytest.raises(HTTPException) as e:
            cs.change(_biz(db), OWNER, ADMIN, body)
        assert e.value.status_code == 400 and e.value.detail == cs.PICK_AREAS.format(name="Tasha Moore")
        assert _level(db, ADMIN) == "admin"
    # With areas it saves, and it is less than an Admin had: no password.
    got = cs.change(_biz(db), OWNER, ADMIN, {"level": "manager", "areas": ["office", "people_care"]}, widening=locked)
    seat = _seat_of(db, ADMIN)
    assert seat["role"] == "manager" and seat["areas"] == ["people_care", "office"] and not got["widens"]
    assert "level: Manager (was Admin)" in got["summary"] and "took off " in got["summary"]
    sheet = cs.compose(_biz(db), OWNER, ADMIN)
    assert sheet["areas"]["by"] == "picked" and sheet["areas"]["shown"] == ["people_care", "office"]
    # Areas already on the row (kept from before they were an Admin) are enough.
    _seat_of(db, ADMIN2)["areas"] = ["kids_youth"]
    cs.change(_biz(db), OWNER, ADMIN2, {"level": "manager"}, widening=locked)
    assert _level(db, ADMIN2) == "manager" and cs.compose(_biz(db), OWNER, ADMIN2)["areas"]["shown"] == ["kids_youth"]


def test_a_level_and_what_goes_with_it_save_together(db):
    """Start a Member from a Manager job in one save: the level, the areas
    and a duty, each checked for the level the save leaves them with."""
    got = cs.change(_biz(db), OWNER, MARK, {"level": "manager", "job": "people_care",
                                           "areas": ["people_care", "kids_youth", "groups_classes"],
                                           "duties": {"add": ["weekly_text"]}})
    seat = _seat_of(db, MARK)
    assert seat["role"] == "manager" and seat["lane"] == "people_care"
    assert seat["areas"] == ["people_care", "kids_youth", "groups_classes"]
    assert "weekly_text" in co.Church(_biz(db)).held(MARK) and got["widens"]
    # Lowered, a duty can't be given in the same save, and ones sent to take off are simply gone.
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), OWNER, MARK, {"level": "member", "duties": {"add": ["first_guests"]}})
    assert e.value.status_code == 400 and e.value.detail == cs.NO_OFFICE_JOBS and _level(db, MARK) == "manager"
    cs.change(_biz(db), OWNER, MARK, {"level": "member", "duties": {"remove": ["weekly_text"]}})
    assert _level(db, MARK) == "member" and co.Church(_biz(db)).held(MARK) == frozenset()


def test_the_put_takes_a_level_and_asks_for_the_password_when_it_goes_up(office, db):
    body = {"business_id": BIZ, "user_id": MARK, "level": "manager"}
    r = office.put("/church/sheet", json=body)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "ledger_locked"
    assert r.json()["detail"]["scope"] == "access" and _level(db, MARK) == "member"
    import ledger_unlock
    os.environ.setdefault("AUDITOR_LINK_SECRET", "test-secret-for-the-sheet")
    token = ledger_unlock.mint(OWNER, ledger_unlock.SCOPE_ACCESS, BIZ)["token"]
    r = office.put("/church/sheet", json=body, headers={ledger_unlock.UNLOCK_HEADER: token})
    assert r.status_code == 200 and r.json()["person"]["role"] == "manager" and r.json()["changed"]
    assert [o["key"] for o in r.json()["level_options"] if o["current"]] == ["manager"]
    r = office.put("/church/sheet", json={**body, "level": "viewer"})          # down: no password
    assert r.status_code == 200 and _level(db, MARK) == "viewer"


def test_chief_reads_the_level_and_still_has_no_verb_that_changes_a_sheet(db):
    import chief_church_sheet as ccs
    cs.change(_biz(db), OWNER, MARK, {"level": "manager"})
    got = chief(db, OWNER, "sheet_of", who="Mark")
    assert not got.get("failed"), got["result"]
    assert got["result"].startswith("Mark Diaz's sheet: Manager login.")
    assert set(ccs.HANDLERS) == {"sheet_of", "list_church_jobs", "draft_church_job", "save_church_job",
                                 "remove_church_job"}


# ─── The review of the level on the sheet (2026-11-18) ────────────────
# The grant must never come back; nothing is written when any part of a
# save refuses; the level, the areas and the job land in one row write.

def _grant_rows(db):
    return sorted(r["user_id"] for r in db.t["church_duty_holders"] if r["duty"] == cj.GRANT)


def _writes(db, monkeypatch):
    """Every write a save makes, in order: ("grant", ids), ("seat", fields),
    ("duty", key)."""
    seen = []
    real_write, real_patch = cd._write, sb_clients.sb_patch_as_service

    def write(biz, duty, ids, by, undoes=None):
        seen.append(("grant" if duty == cj.GRANT else "duty", duty if duty != cj.GRANT else list(ids)))
        return real_write(biz, duty, ids, by, undoes)

    def patch(path, body, **kw):
        if path.startswith("/business_users?"):
            seen.append(("seat", dict(body)))
        return real_patch(path, body, **kw)
    monkeypatch.setattr(cd, "_write", write)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)
    return seen


def test_the_grant_is_taken_away_before_the_level_is_written(db, monkeypatch):
    _give_grant(db)
    seen = _writes(db, monkeypatch)
    cs.change(_biz(db), OWNER, RUTH, {"level": "member"})
    assert seen == [("grant", []), ("seat", {"role": "member"})]


def test_a_grant_that_wont_come_off_stops_the_whole_save(db, monkeypatch):
    """It was written after the level: the login was moved down, the row
    stayed, and the next move up made them a holder again."""
    _give_grant(db)
    real = cd._write

    def no_grant_write(biz, duty, ids, by, undoes=None):
        if duty == cj.GRANT:
            raise HTTPException(503, "That didn't save. Try again.")
        return real(biz, duty, ids, by, undoes)
    monkeypatch.setattr(cd, "_write", no_grant_write)
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), OWNER, RUTH, {"level": "member"})
    assert e.value.status_code == 503
    assert _level(db, RUTH) == "manager" and _grant_rows(db) == [RUTH], "nothing was written"
    assert db.t["church_sheet_changes"][-1]["subject_user_id"] == RUTH and "level" not in (
        db.t["church_sheet_changes"][-1]["summary"]), "and nothing recorded as changed"


@pytest.mark.parametrize("editor", [OWNER, ADMIN, RUTH])
def test_a_grant_row_left_on_a_login_never_makes_them_a_holder_when_they_are_moved_up(db, editor):
    """However the row came to be left (a save that failed half way, a
    login moved down some other way): a move to Manager clears it."""
    _give_grant(db)
    db.t["church_duty_holders"].append({"business_id": BIZ, "duty": cj.GRANT, "user_id": MARK})
    assert not cj.holds_grant(BIZ, MARK, "member")
    got = cs.change(_biz(db), editor, MARK, {"level": "manager", "areas": ["kids_youth"]})
    assert _level(db, MARK) == "manager"
    assert _grant_rows(db) == [RUTH] and cj.editor(BIZ, MARK, "manager") is None
    assert cj.GRANT_LABEL not in got["summary"], "nobody's grant was taken: nothing to say"


def test_a_left_over_row_that_wont_clear_stops_the_move_up(db, monkeypatch):
    db.t["church_duty_holders"].append({"business_id": BIZ, "duty": cj.GRANT, "user_id": MARK})
    monkeypatch.setattr(cj, "drop_grant", lambda biz, uid: False)
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), ADMIN, MARK, {"level": "manager"})
    assert e.value.status_code == 503 and _level(db, MARK) == "member"


def test_the_owner_can_give_the_grant_in_the_same_save_as_the_level(db, monkeypatch):
    db.t["church_duty_holders"].append({"business_id": BIZ, "duty": cj.GRANT, "user_id": MARK})   # a row left over
    asked = []
    got = cs.change(_biz(db), OWNER, MARK, {"level": "manager", "duties": {"add": [cj.GRANT]}},
                    widening=lambda: asked.append(1))
    assert asked == [1] and cj.editor(BIZ, MARK, "manager") == "holder"
    assert f"gave “{cj.GRANT_LABEL}”" in got["summary"]
    # A Member with no row, the same way: the grant is written last, once they are a Manager.
    _seat_of(db, SARAH)["role"] = "member"
    seen = _writes(db, monkeypatch)
    cs.change(_biz(db), ADMIN, SARAH, {"level": "manager", "duties": {"add": [cj.GRANT]}})
    assert [w[0] for w in seen] == ["seat", "grant"] and cj.editor(BIZ, SARAH, "manager") == "holder"


def test_a_demoted_holder_moved_up_again_by_an_admin_is_not_a_holder(db):
    _give_grant(db)
    cs.change(_biz(db), OWNER, RUTH, {"level": "member"})
    cs.change(_biz(db), ADMIN, RUTH, {"level": "manager"})
    assert cj.editor(BIZ, RUTH, "manager") is None and _grant_rows(db) == []


def test_a_duty_that_is_already_full_refuses_before_the_level_is_saved(db):
    """church_duties.move refuses more than MAX_HOLDERS. It answered after
    the level was saved, so the login was moved up and the save said no."""
    extra = [f"c{n:07d}-0000-4000-8000-00000000000{n % 10}" for n in range(cd.MAX_HOLDERS)]
    for n, u in enumerate(extra):
        db.t["business_users"].append(_seat(u, "manager", f"m{n}@gracefellowship.example", f"Helper {n}",
                                            areas=["office"]))
        db.t["church_duty_holders"].append({"business_id": BIZ, "duty": "first_guests", "user_id": u})
    before = [dict(r) for r in db.t["church_duty_holders"]]
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), OWNER, MARK, {"level": "manager", "areas": ["kids_youth"],
                                         "duties": {"add": ["first_guests"]}})
    assert e.value.status_code == 400 and str(cd.MAX_HOLDERS) in e.value.detail
    seat = _seat_of(db, MARK)
    assert seat["role"] == "member" and not seat.get("areas"), "nothing was written"
    assert [dict(r) for r in db.t["church_duty_holders"]] == before


def test_the_level_the_areas_and_the_job_are_one_row_write(db, monkeypatch):
    seen = _writes(db, monkeypatch)
    cs.change(_biz(db), OWNER, ADMIN2, {"level": "manager", "areas": ["office", "kids_youth"]})
    assert seen == [("seat", {"role": "manager", "areas": ["kids_youth", "office"], "lane": None})]
    seen.clear()
    cs.change(_biz(db), OWNER, MARK, {"level": "manager", "job": "people_care",
                                     "areas": ["people_care", "kids_youth", "groups_classes"]})
    assert seen == [("seat", {"role": "manager", "areas": ["people_care", "kids_youth", "groups_classes"],
                              "lane": "people_care"})]
    # A level alone touches nothing else on the row.
    seen.clear()
    cs.change(_biz(db), OWNER, MARK, {"level": "member"})
    assert seen == [("seat", {"role": "member"})]


def test_an_admin_moved_down_is_never_left_with_no_areas_by_a_save_that_fails(db, monkeypatch):
    """Two writes left a Manager with no areas ("sees the whole church")
    when the second failed. One write: either all of it, or none."""
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda path, body, **kw: None)
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), OWNER, ADMIN2, {"level": "manager", "areas": ["office"]})
    seat = _seat_of(db, ADMIN2)
    assert e.value.status_code == 503 and seat["role"] == "admin" and not seat.get("areas")


def test_an_admin_moved_down_loses_a_job_that_is_an_admin_logins(db):
    _seat_of(db, ADMIN)["areas"] = ["office"]
    assert _seat_of(db, ADMIN)["lane"] == "treasurer"
    got = cs.change(_biz(db), OWNER, ADMIN, {"level": "manager"})
    seat = _seat_of(db, ADMIN)
    assert seat["role"] == "manager" and seat["lane"] is None and seat["areas"] == ["office"]
    assert "no job" in got["summary"]
    assert cs.compose(_biz(db), OWNER, ADMIN)["job"]["key"] is None
    # Unless the save names another job for them.
    _seat_of(db, ADMIN2).update(lane="treasurer", areas=["office", "messages_safety"])
    cs.change(_biz(db), OWNER, ADMIN2, {"level": "manager", "job": "office_leadership"})
    assert _seat_of(db, ADMIN2)["lane"] == "office_leadership"


def test_a_password_confirmed_for_another_church_doesnt_change_a_sheet_here(office, db):
    import ledger_unlock
    os.environ.setdefault("AUDITOR_LINK_SECRET", "test-secret-for-the-sheet")
    body = {"business_id": BIZ, "user_id": MARK, "level": "manager"}
    elsewhere = ledger_unlock.mint(OWNER, ledger_unlock.SCOPE_ACCESS, "0a000000-0000-4000-8000-00000000000a")
    r = office.put("/church/sheet", json=body, headers={ledger_unlock.UNLOCK_HEADER: elsewhere["token"]})
    assert r.status_code == 403 and r.json()["detail"] == {
        "code": "ledger_locked", "scope": "access", "message": ledger_unlock.SCOPE_PROMPT["access"]}
    assert _level(db, MARK) == "member"
    nowhere = ledger_unlock.mint(OWNER, ledger_unlock.SCOPE_ACCESS)["token"]         # names no business
    assert office.put("/church/sheet", json=body,
                      headers={ledger_unlock.UNLOCK_HEADER: nowhere}).status_code == 403
    here = ledger_unlock.mint(OWNER, ledger_unlock.SCOPE_ACCESS, BIZ.upper())["token"]
    assert office.put("/church/sheet", json=body, headers={ledger_unlock.UNLOCK_HEADER: here}).status_code == 200
