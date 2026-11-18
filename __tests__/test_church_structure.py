"""The standard start: a church's structure draft (church_structure.py,
chief_church_structure.py). Kevin, 2026-11-18: "will the system know what to
do with other churches? I want to make sure that other churches would have
the right type of setup when it comes to setting up there structure", then
"standard start first, then giving also consider adding the setup with the
church planning strategy".

Pins:
  * the four shapes and the jobs each starts from; every job a draft
    proposes is one the church could really make
  * a tradition's own words where church_roles has them
  * what the server does with a person: cleans every field and says what it
    left out, picks a job from the title or the work, never a pick between
    two people
  * money, honestly: whoever keeps the books is an Admin with the notes; a
    counter or a depositor gets no money access; Giving & money and the money
    duties never ride on anything but an Admin, kept or forged
  * a person's state as the church changes: needs an email, new, invited, a
    login set up differently, done
  * every gap, in the draft and in the standing check
  * a draft from the planning course, and its refusals
  * who may draft, read and clear; the draft is one per church, kept in its
    own server-only table (never in settings), and grants nothing
  * before that table is there: no draft, `ready` false, the standing check
    still answers, and a write is a plain 503
  * a login on one of the church's own jobs holds only the duties given on
    its sheet
  * Chief's two verbs, where they are placed, the hold on a tainted turn,
    the navigate flag, the instructions, and the planning coach's one offer

People and churches here are made up."""
from __future__ import annotations

import asyncio
import os
import pathlib
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
import church_structure as st  # noqa: E402
import sb_clients  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from test_church_duties import DutyDB  # noqa: E402
from test_church_follow_up import BIZ, OWNER  # noqa: E402

ADMIN = "c1000000-0000-4000-8000-000000000001"     # Alma Price, an Admin login (the treasurer)
HOLDER = "c2000000-0000-4000-8000-000000000002"    # Nora Whitfield, a Manager who sets up jobs and sheets
MANAGER = "c3000000-0000-4000-8000-000000000003"   # Caleb Stone, a Manager in People & Care
LOOSE = "c4000000-0000-4000-8000-000000000004"     # Gwen Abara, a Manager nothing places
STRANGER = "c9000000-0000-4000-8000-000000000009"
SHOP = "d0000000-0000-4000-8000-0000000000d0"      # a business that is not a church
C_MARIA = "e1000000-0000-4000-8000-0000000000e1"
C_DANA = "e2000000-0000-4000-8000-0000000000e2"
C_LEE_1 = "e3000000-0000-4000-8000-0000000000e3"
C_LEE_2 = "e4000000-0000-4000-8000-0000000000e4"


class StructDB(DutyDB):
    """The duties' fake, plus the drafts' upsert on the church's own row
    (POST ?on_conflict=business_id with resolution=merge-duplicates)."""

    def post(self, path, body, prefer=None, **kw):
        if path.startswith(f"/{st.TABLE}"):
            assert "on_conflict=business_id" in path and "resolution=merge-duplicates" in (prefer or "")
            rows = self.t.setdefault(st.TABLE, [])
            self.t[st.TABLE] = [r for r in rows if r["business_id"] != body["business_id"]] + [dict(body)]
            self.keeps = getattr(self, "keeps", 0) + 1
            return [dict(body)]
        return super().post(path, body, prefer, **kw)


def _seat(uid, role, email, name, lane=None, areas=None, status="active"):
    return {"business_id": BIZ, "user_id": uid, "role": role, "invited_email": email, "lane": lane, "areas": areas,
            "contact_id": None, "name": name, "status": status}


def _contact(cid, name, email=""):
    return {"id": cid, "business_id": BIZ, "name": name, "email": email, "phone": ""}


@pytest.fixture
def db(monkeypatch):
    """Hope Chapel on its first day: the pastor and nobody else."""
    fake = StructDB(
        businesses=[{"id": BIZ, "name": "Hope Chapel", "type": "church", "owner_id": OWNER,
                     "settings": {"practitioner_name": "Pastor Daniel Brooks", "theme": "light"}},
                    {"id": SHOP, "name": "Corner Barbers", "type": "barber", "owner_id": OWNER, "settings": {}}],
        business_users=[],
        contacts=[_contact(C_MARIA, "Maria Lopez", "maria@hopechapel.example"), _contact(C_DANA, "Dana Reed"),
                  _contact(C_LEE_1, "Lee Carter", "lee1@hopechapel.example"),
                  _contact(C_LEE_2, "Lee Carter", "lee2@hopechapel.example")],
        church_role_defs=[], church_leader_roles=[], church_role_settings=[], church_area_places=[],
        church_duty_holders=[], church_duty_changes=[], church_jobs=[], church_sheet_changes=[], strategy_tracks=[],
        church_structure_drafts=[],
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
    monkeypatch.setattr(co, "_OWNER_EMAIL", {})
    monkeypatch.setattr(messaging_router, "_owner_email", lambda uid: "")
    monkeypatch.setattr(messaging_router, "owner_email_read", lambda uid: "pastor@hopechapel.example")
    monkeypatch.setattr(cj, "tell_owner", lambda business, title, body, tag: None)
    return fake


@pytest.fixture(autouse=True)
def _fresh():
    import chief_areas
    import chief_office
    for c in (cd._CACHE, cd._FAILED, ca._MY_CACHE, chief_office._CACHE):
        c.clear()
    chief_areas.forget()
    yield
    for c in (cd._CACHE, cd._FAILED, ca._MY_CACHE, chief_office._CACHE):
        c.clear()
    chief_areas.forget()


def _office(db):
    """The same church a year on: an Admin, a holder of the grant, a Manager
    in a lane and a Manager nothing places."""
    db.t["business_users"] += [
        _seat(ADMIN, "admin", "alma@hopechapel.example", "Alma Price", lane="treasurer"),
        _seat(HOLDER, "manager", "nora@hopechapel.example", "Nora Whitfield", lane="office_leadership",
              areas=["messages_safety", "office"]),
        _seat(MANAGER, "manager", "caleb@hopechapel.example", "Caleb Stone", lane="people_care",
              areas=["people_care", "kids_youth", "groups_classes"]),
        _seat(LOOSE, "manager", "gwen@hopechapel.example", "Gwen Abara"),
    ]
    cs.change(_biz(db), OWNER, HOLDER, {"duties": {"add": [cj.GRANT]}})


def _biz(db, biz=BIZ):
    return next(b for b in db.t["businesses"] if b["id"] == biz)


def _draft(db, answers=None, by=OWNER, ed="owner", from_plan=False):
    business = _biz(db)
    return st.draft(business, co.Church(business), by, ed, answers, from_plan)


def _read(db, by=OWNER, ed="owner"):
    business = _biz(db)
    return st.read(business, co.Church(business), by, ed)


def _p(d, name):
    return next(p for p in d["people"] if p["name"] == name)


def _keys(gaps):
    return [g["key"] for g in gaps]


def _labels(d):
    return [j["label"] for j in d["jobs"]]


SMALL = {
    "leads": "pastor",
    "money": {"counts": ["Dana Reed", "Sam Ortiz"], "deposits": "Sam Ortiz", "books": "Alma Price"},
    "bodies": [], "staff": "volunteers", "guests": "Maria Lopez",
    "people": [
        {"name": "Alma Price", "title": "Treasurer", "does": "keeps the books and pays the bills",
         "email": "alma@hopechapel.example"},
        {"name": "Maria Lopez", "does": "calls every guest and runs the prayer chain"},
        {"name": "Dana Reed", "does": "counts the offering with Sam"},
    ],
}


# ─── The shapes ───────────────────────────────────────────────────────

@pytest.mark.parametrize("leads, shape, jobs", [
    ("pastor", "pastor_helpers", ["Treasurer", "Office & Leadership", "People & Care"]),
    ("pastor_board", "pastor_board", ["Treasurer", "Office & Leadership", "People & Care", "Board member"]),
    ("elders", "elder_led", ["Treasurer", "Office & Leadership", "People & Care", "Elder"]),
    ("staff", "staff_led", ["Executive Pastor", "Treasurer", "Office & Leadership", "People & Care",
                            "Sunday & Serving", "Media & Communications"]),
])
def test_each_shape_starts_from_its_own_jobs_and_every_one_it_proposes_could_really_be_made(db, leads, shape, jobs):
    d = _draft(db, {"leads": leads, "people": []})
    assert d["shape"]["key"] == shape and d["shape"]["label"] == st.SHAPES[shape]["label"]
    assert d["shape"]["why"].startswith(st.SHAPES[shape]["why"])
    assert _labels(d) == jobs and d["source"] == "questions" and d["made_by_name"] == "Pastor Daniel Brooks"
    for j in d["jobs"]:
        if j["label"] in [x["label"] for x in cj.presets()]:
            assert j["exists"] and not j["custom"] and j["key"] in ca.LANES
        else:
            assert j["custom"] and not j["exists"] and j["key"] is None
            kept = cj.clean(j, "owner")                      # the church's own job save takes it as it is
            assert kept["role"] == j["role"] and kept["areas"] == j["areas"] and kept["duties"] == j["duties"]
    by = {j["label"]: j for j in d["jobs"]}
    assert by["Treasurer"]["role"] == "admin" and by["Treasurer"]["areas"] is None
    assert by["Treasurer"]["duties"] == cd.STARTER["treasurer"]


def test_the_bodies_a_church_names_each_bring_their_own_job_whatever_the_shape(db):
    d = _draft(db, {"leads": "pastor", "bodies": ["deacons", "trustees", "council"], "people": []})
    assert _labels(d)[-2:] == ["Deacon", "Trustee"]
    by = {j["label"]: j for j in d["jobs"]}
    assert by["Deacon"]["areas"] == ["people_care"] and by["Deacon"]["duties"] == ["care_visits", "help_requests"]
    assert by["Trustee"]["duties"] == ["rooms", "building", "supplies"] and by["Trustee"]["role"] == "manager"
    assert any("“council” isn't a body" in n for n in d["notes"])
    board = {j["label"]: j for j in _draft(db, {"leads": "pastor_board", "people": []})["jobs"]}["Board member"]
    assert board["role"] == "viewer" and board["areas"] == ["office"] and board["duties"] == []
    # A board the church named by its own bodies is those bodies, with no second "board" beside them;
    # elders lead an elder-led church whatever else it named.
    assert "Board member" not in _labels(_draft(db, {"leads": "pastor_board", "bodies": ["deacons"], "people": []}))
    assert _labels(_draft(db, {"leads": "elders", "bodies": ["deacons"], "people": []}))[-2:] == ["Elder", "Deacon"]
    assert not any(church_money for j in d["jobs"] if j["custom"]
                   for church_money in [k for k in j["duties"] if cd.CATALOG[k]["money"]])
    assert all(ca.FINANCE_ONLY not in (j["areas"] or []) for j in d["jobs"])


def test_a_shape_nobody_named_is_worked_out_from_the_rest_and_says_so(db):
    board = _draft(db, {"bodies": ["deacons", "trustees"], "people": []})
    assert board["shape"]["key"] == "pastor_board" and "You named deacons and trustees" in board["shape"]["why"]
    assert "Tell Chief if the church is led another way" in board["shape"]["why"]
    assert _draft(db, {"staff": "paid_team", "people": []})["shape"]["key"] == "staff_led"
    plain = _draft(db, {"leads": "congregation", "people": [{"name": "Maria Lopez", "does": "guests"}]})
    assert plain["shape"]["key"] == "pastor_helpers"
    assert any("isn't one of the four ways a church is led" in n for n in plain["notes"])


def test_a_traditions_own_words_are_used_where_church_roles_has_them(db):
    import church_roles as cr
    for body, words in st.BODY_WORDS.items():
        for tkey, (_label, row) in words.items():
            assert any(r["key"] == row for r in cr.TYPES[tkey]["rows"]), (tkey, row)
    db.t["church_role_settings"].append({"business_id": BIZ, "church_type": "presby", "guessed_type": "nondenom"})
    d = _draft(db, {"leads": "pastor_board", "bodies": ["elders"],
                    "people": [{"name": "Dana Reed", "title": "Clerk of Session", "does": "keeps the minutes"}]})
    by = {j["label"]: j for j in d["jobs"]}
    # A Presbyterian church's board is its Session: one job, the elders' one.
    assert "Board member" not in by and by["Ruling Elder"]["duties"] == ["care_visits", "prayer", "shepherding"]
    assert by["Office & Leadership"]["also_called"] == "Clerk of Session"
    assert _p(d, "Dana Reed")["job_key"] == "office_leadership"
    db.t["church_role_settings"][0]["church_type"] = "baptist"
    d = _draft(db, {"leads": "pastor_board", "people": [
        {"name": "Alma Price", "title": "Financial Secretary", "does": "the tithes and the bills"},
        {"name": "Dana Reed", "title": "Church Clerk", "does": "the minutes and the roll"}]})
    by = {j["label"]: j for j in d["jobs"]}
    assert by["Treasurer"]["also_called"] == "Financial Secretary"
    assert by["Office & Leadership"]["also_called"] == "Church Clerk"
    assert _p(d, "Alma Price")["role"] == "admin" and _p(d, "Alma Price")["job_key"] == "treasurer"
    assert _p(d, "Dana Reed")["job_label"] == "Office & Leadership"
    # No tradition kept, or one that can't be read: the plain words, never a failure.
    db.t["church_role_settings"].clear()
    assert st.tradition(BIZ) == "nondenom" and st.also_called("cogic", "office_leadership") is None


# ─── Money, honestly ──────────────────────────────────────────────────

def test_whoever_keeps_the_books_is_an_admin_with_the_notes_and_a_counter_gets_no_money(db):
    d = _draft(db, SMALL)
    alma = _p(d, "Alma Price")
    assert alma["role"] == "admin" and alma["areas"] is None and alma["job_key"] == "treasurer"
    assert alma["duties"] == cd.STARTER["treasurer"]
    assert st.ADMIN_SEES in alma["notes"] and st.OWNER_MAKES_ADMIN in alma["notes"]
    assert "Giving opens only for an Admin login today" in alma["why"]
    dana = _p(d, "Dana Reed")
    assert dana["role"] != "admin" and ca.FINANCE_ONLY not in dana["areas"]
    assert not [k for k in dana["duties"] if cd.CATALOG[k]["money"]]
    assert st.COUNTER_NOTE.format(name="Dana Reed") in dana["notes"]
    # Sam counts and deposits but isn't one of the people: said, and nothing set up.
    assert ("Sam Ortiz counts the offering and takes the deposit but isn't one of the people here, so nothing is "
            "set up for them. They need no login for that today.") in d["notes"]
    assert [p["name"] for p in d["people"] if p["role"] == "admin"] == ["Alma Price"]


def test_money_never_rides_on_anything_but_an_admin_whatever_chief_passes(db):
    d = _draft(db, {"leads": "pastor", "money": {"counts": [], "deposits": "Sam Ortiz", "books": None}, "people": [
        {"name": "Sam Ortiz", "does": "takes the deposit to the bank on Monday", "role": "manager",
         "areas": ["giving_money", "office"], "duties": ["deposit", "books", "calendar"]},
        {"name": "Lee Park", "does": "handles the money"},
        {"name": "Rita Vance", "title": "Bookkeeper", "does": "enters the giving", "role": "member"},
    ]})
    sam = _p(d, "Sam Ortiz")
    assert sam["role"] == "manager" and sam["areas"] == ["office"] and sam["duties"] == ["calendar"]
    assert "Giving & money was left off: it opens only for an Admin login." in sam["notes"]
    assert any("The Sunday deposit and The books left off" in n for n in sam["notes"])
    assert st.DEPOSITOR_NOTE.format(name="Sam Ortiz") in sam["notes"]
    lee = _p(d, "Lee Park")
    assert lee["job_label"] == "" and lee["areas"] == [] and lee["duties"] == [] and lee["role"] == "viewer"
    assert st.MONEY_WORDS_NOTE.format(name="Lee Park") in lee["notes"]
    assert st.NO_JOB_NOTE.format(name="Lee Park") in lee["notes"]
    rita = _p(d, "Rita Vance")                              # a bookkeeper is the money job, whatever level was said
    assert rita["role"] == "admin" and rita["job_key"] == "treasurer"
    assert any(n.startswith("You said Member, but whoever keeps the books needs an Admin login today") for n in rita["notes"])


def test_the_books_person_is_added_when_nobody_listed_them_and_a_helper_hears_only_the_owner_makes_an_admin(db):
    _office(db)
    d = _draft(db, {"leads": "pastor", "money": {"counts": [], "deposits": None, "books": "Rita Vance"},
                    "people": []}, by=HOLDER, ed="holder")
    rita = _p(d, "Rita Vance")
    assert rita["role"] == "admin" and rita["does"] == "Keeps the books" and rita["why"].startswith("You said they keep")
    assert "Only the owner can make someone an Admin, so this one waits for Pastor Daniel Brooks." in rita["notes"]
    assert d["made_by_name"] == "Nora Whitfield"
    # The pastor keeping the books is nobody's Admin login.
    mine = _draft(db, {"leads": "pastor", "money": {"counts": [], "deposits": None, "books": "me"}, "people": []})
    assert mine["people"] == []


def test_an_admin_someone_asked_for_carries_the_same_notes_and_opens_everything(db):
    d = _draft(db, {"leads": "staff", "people": [
        {"name": "Joel Hart", "title": "Executive Pastor", "does": "runs the staff", "role": "admin",
         "areas": ["office"], "duties": ["calendar"]}]})
    joel = _p(d, "Joel Hart")
    assert joel["role"] == "admin" and joel["areas"] is None and joel["duties"] == []
    assert joel["job_label"] == "Executive Pastor" and st.ADMIN_SEES in joel["notes"]
    assert "Drafted as an Admin login because that was asked for." in joel["why"]


# ─── Cleaning: nothing is dropped quietly ─────────────────────────────

def test_every_field_is_checked_against_the_real_lists_and_what_is_left_out_is_said(db):
    d = _draft(db, {"leads": "pastor", "people": [
        {"name": "Maria Lopez", "does": "guests", "email": "maria at hopechapel", "role": "boss",
         "areas": ["people_care", "the_basement"], "duties": ["first_guests", "make_coffee"]},
        {"name": "Tom Reyes", "does": "runs the sound board", "role": "member", "areas": ["worship_media"],
         "duties": ["production_schedule"]},
        {"name": "", "does": "something"},
        {"name": "Pastor Daniel Brooks", "does": "preaches"},
        {"name": "Tom Reyes", "does": "also the slides"},
        "not a person",
    ]})
    maria = _p(d, "Maria Lopez")
    assert maria["areas"] == ["people_care"] and maria["duties"] == ["first_guests"]
    assert any("“maria at hopechapel” isn't an email address" in n for n in maria["notes"])
    # The one Maria Lopez in the church's people is her, so her record's email stands in, and that is said.
    assert maria["email"] == "maria@hopechapel.example" and maria["contact_id"] == C_MARIA
    assert any("“boss” isn't a login level" in n for n in maria["notes"])
    assert any("“the_basement” isn't one of the church's areas" in n for n in maria["notes"])
    assert any("“make_coffee” isn't one of the church's duties" in n for n in maria["notes"])
    tom = _p(d, "Tom Reyes")
    assert tom["role"] == "member" and tom["areas"] == ["worship_media"] and tom["duties"] == []
    assert any(n.startswith("A Member login doesn't do office jobs") for n in tom["notes"])
    assert tom["does"] == "runs the sound board; also the slides"
    assert any("was named more than once" in n for n in tom["notes"])
    assert [p["name"] for p in d["people"]] == ["Maria Lopez", "Tom Reyes"]
    assert [p["ref"] for p in d["people"]] == ["p1", "p2"]
    assert "One person had no name, so they were left out." in d["notes"]
    assert any(n.startswith("Pastor Daniel Brooks is the owner, who already opens everything") for n in d["notes"])


def test_a_draft_holds_forty_people_and_says_when_more_were_named(db):
    d = _draft(db, {"leads": "pastor", "people": [{"name": f"Helper {n}", "does": "ushers"} for n in range(45)]})
    assert len(d["people"]) == st.MAX_PEOPLE
    assert any(n.startswith("A draft holds 40 people.") for n in d["notes"])


# ─── The job a person gets ────────────────────────────────────────────

def test_a_title_the_church_already_uses_is_that_job_and_a_new_title_is_one_it_would_make(db):
    cj.create(_biz(db), {"label": "Kids Director", "does": "Runs the kids rooms", "role": "manager",
                         "areas": ["kids_youth"], "duties": ["kids"]}, OWNER, "owner")
    d = _draft(db, {"leads": "pastor", "people": [
        {"name": "Ana Bell", "title": "kids director", "does": "runs the kids rooms"},
        {"name": "Tom Reyes", "title": "Minister of Music", "does": "leads the choir and plans the worship"},
        {"name": "Joy Lin", "title": "Minister of Music", "does": "helps with the choir", "role": "viewer"},
        {"name": "Ike Dunn", "title": "Armor Bearer", "does": "carries the bags on Sunday"},
    ]})
    ana = _p(d, "Ana Bell")
    assert ana["job_key"] == "kids_director" and ana["areas"] == ["kids_youth"] and ana["duties"] == ["kids"]
    assert "is one of your church's jobs" in ana["why"]
    by = {j["label"]: j for j in d["jobs"]}
    assert by["Kids Director"]["exists"] and by["Kids Director"]["custom"] and by["Kids Director"]["key"] == "kids_director"
    music = by["Minister of Music"]
    assert music["custom"] and not music["exists"] and music["key"] is None and music["role"] == "manager"
    assert music["areas"] == ["worship_media"] and "sunday_plan" in music["duties"]
    assert cj.clean(music, "owner")["label"] == "Minister of Music"
    tom = _p(d, "Tom Reyes")
    assert tom["job_label"] == "Minister of Music" and tom["job_key"] is None and tom["duties"] == music["duties"]
    assert "isn't a ready-made job, so it is one your church would make" in tom["why"]
    # Two people with one title share the one job; a Viewer among them holds no duties.
    assert _labels(d).count("Minister of Music") == 1
    joy = _p(d, "Joy Lin")
    assert joy["role"] == "viewer" and joy["duties"] == [] and joy["areas"] == ["worship_media"]
    # A title that points nowhere is still the church's own job, with nothing on it yet.
    ike = _p(d, "Ike Dunn")
    assert ike["job_label"] == "Armor Bearer" and ike["areas"] == [] and ike["duties"] == []
    assert ike["role"] == "viewer"


def test_with_no_title_a_person_gets_a_job_of_the_churchs_own_with_only_what_they_need(db):
    """Kevin, 2026-11-18: never a ready-made job that opens more than they
    described. A person with no title is given a job the church would make,
    named in plain words from the work, carrying only that work's areas and
    duties."""
    d = _draft(db, {"leads": "pastor", "people": [
        {"name": "Maria Lopez", "does": "calls every guest and runs the prayer chain"},
        {"name": "Tom Reyes", "does": "runs the livestream and the slides"},
        {"name": "Nia Cole", "does": "keeps the calendar and the office"},
        {"name": "Cy Hale", "does": "helps with the youth"},
        {"name": "Val Roy", "does": "kids", "role": "member"},
        {"name": "Ida Poe", "does": "all of care", "areas": list(ca.LANES["people_care"]["areas"]),
         "duties": list(cd.STARTER["people_care"])},
        {"name": "Bo Finch", "does": "helps out"},
    ]})
    by = {j["label"]: j for j in d["jobs"]}
    maria = _p(d, "Maria Lopez")
    assert maria["job_label"] == "Guest follow-up and prayer" and maria["job_key"] is None
    assert maria["areas"] == ["people_care"] and maria["duties"] == ["first_guests", "prayer"]
    assert set(maria["duties"]) < set(cd.STARTER["people_care"])         # far less than People & Care opens
    assert st.NAMED_NOTE.format(job="Guest follow-up and prayer") in maria["notes"]
    assert maria["why"].startswith("No title was given, so this is a job your church would make, with only what")
    job = by["Guest follow-up and prayer"]
    assert job["custom"] and not job["exists"] and job["areas"] == ["people_care"]
    assert job["duties"] == ["first_guests", "prayer"] and cj.clean(job, "owner")["duties"] == job["duties"]
    tom = _p(d, "Tom Reyes")
    assert tom["areas"] == ["worship_media"] and tom["duties"] == ["production_schedule", "stream"]
    assert _p(d, "Nia Cole")["job_label"] == "Calendar" and _p(d, "Nia Cole")["duties"] == ["calendar"]
    assert _p(d, "Nia Cole")["areas"] == ["office"]                      # not Messages & safety, not 14 duties
    assert _p(d, "Cy Hale")["job_label"] == "Youth" and _p(d, "Cy Hale")["duties"] == ["youth"]
    val = _p(d, "Val Roy")                                               # no duty matched: named by its area
    assert val["job_label"] == "Kids & youth helper" and val["role"] == "member" and val["duties"] == []
    assert by["Kids & youth helper"]["role"] == "member" and by["Kids & youth helper"]["areas"] == ["kids_youth"]
    # Nobody without a title was handed a ready-made job, except the one whose areas and duties ARE that job.
    assert [p["name"] for p in d["people"] if p["job_key"] in ca.LANES] == ["Ida Poe"]
    assert _p(d, "Ida Poe")["why"] == "What they do is People & Care, the ready-made job, exactly."
    for name in ("Maria Lopez", "Tom Reyes", "Nia Cole", "Cy Hale", "Val Roy"):
        p = _p(d, name)
        made = cj.clean(by[p["job_label"]], "owner")                     # each is a job the church could make
        assert set(made["areas"]) == set(p["areas"]) and set(made["duties"]) == set(p["duties"])
    bo = _p(d, "Bo Finch")
    assert bo["job_key"] is None and bo["job_label"] == "" and bo["areas"] == []
    assert bo["role"] == "viewer" and not bo["no_login"]         # nothing to switch on: the least a login can be
    assert "couldn't tell what they do" in bo["why"] and st.NO_JOB_NOTE.format(name="Bo Finch") in bo["notes"]
    # A ready-made job nobody holds is not a gap any more; a job the draft proposes that nobody holds is.
    assert "job_unheld" not in _keys(d["gaps"])
    board = _draft(db, {"leads": "pastor_board", "people": []})
    assert [g["line"] for g in board["gaps"] if g["key"] == "job_unheld"] == ["No one holds Board member yet."]


def test_a_job_with_no_areas_is_nothing_switched_on_whatever_it_is_called(db):
    d = _draft(db, {"leads": "pastor", "people": [
        {"name": "Ike Dunn", "title": "Armor Bearer", "does": "carries the bags on Sunday",
         "email": "ike@hopechapel.example"}]})
    ike = _p(d, "Ike Dunn")
    assert ike["job_label"] == "Armor Bearer" and ike["areas"] == [] and ike["role"] == "viewer"
    assert st.EMPTY_JOB_NOTE.format(job="Armor Bearer", name="Ike Dunn") in ike["notes"]
    assert "Nothing is switched on for Ike Dunn yet." in [g["line"] for g in d["gaps"]]


def test_a_body_title_and_whoever_is_over_the_office_get_their_own_jobs(db):
    d = _draft(db, {"leads": "staff", "people": [
        {"name": "Joel Hart", "title": "Operations Pastor", "does": "runs the staff and the office"},
        {"name": "Ruth Okoye", "title": "Deacon", "does": "visits the sick"},
        {"name": "Sol Marsh", "title": "Trustee", "does": "the building"},
    ]})
    by = {j["label"]: j for j in d["jobs"]}
    assert "Executive Pastor" not in by                       # the church's own title for them is the job
    assert by["Operations Pastor"]["duties"] == ["monthly_report", "oversee_lanes"]
    assert ca.FINANCE_ONLY not in by["Operations Pastor"]["areas"] and len(by["Operations Pastor"]["areas"]) == 7
    assert _p(d, "Ruth Okoye")["job_label"] == "Deacon" and _p(d, "Ruth Okoye")["duties"] == ["care_visits", "help_requests"]
    sol = _p(d, "Sol Marsh")
    assert sol["job_label"] == "Trustee" and any(n.startswith("Trustees often keep the money too") for n in sol["notes"])
    # Someone who only sets up jobs can't put the lanes' oversight in one, so their draft leaves it off and says so.
    _office(db)
    held = _draft(db, {"leads": "staff", "people": []}, by=HOLDER, ed="holder")
    exec_job = {j["label"]: j for j in held["jobs"]}["Executive Pastor"]
    assert exec_job["duties"] == [] and cj.clean(exec_job, "holder")["label"] == "Executive Pastor"
    assert any("they are left off Executive Pastor" in n for n in held["notes"])


def test_whoever_should_hear_about_a_guest_gets_the_duty_on_their_sheet(db):
    d = _draft(db, {"leads": "pastor", "guests": "Tom Reyes", "people": [
        {"name": "Tom Reyes", "does": "runs the livestream"}]})
    tom = _p(d, "Tom Reyes")
    assert "people_care" in tom["areas"] and "first_guests" in tom["duties"]
    assert any("should hear when a guest comes, so First-time guests and welcome calls is on their sheet" in n
               for n in tom["notes"])
    assert "no_guests" not in _keys(d["gaps"])


# ─── Who they already are ─────────────────────────────────────────────

def test_a_person_is_tied_to_the_login_or_the_member_they_already_are_only_when_one_fits(db):
    _office(db)
    db.t["business_users"].append(_seat("c5000000-0000-4000-8000-000000000005", "member",
                                        "caleb.y@hopechapel.example", "Caleb Young"))
    d = _draft(db, {"leads": "pastor", "people": [
        {"name": "A. Price", "does": "keeps the books", "email": "ALMA@hopechapel.example"},
        {"name": "Sister Nora Whitfield", "does": "runs the office"},
        {"name": "Gwen", "does": "the youth"},
        {"name": "Caleb", "does": "prayer"},
        {"name": "Maria Lopez", "does": "guests"},
        {"name": "Lee Carter", "does": "ushers"},
        {"name": "Dana Reed", "does": "kids", "email": "dana@hopechapel.example"},
        {"name": "Zed Novak", "does": "sound"},
    ]})
    assert _p(d, "A. Price")["user_id"] == ADMIN                               # by email
    nora = _p(d, "Sister Nora Whitfield")
    assert nora["user_id"] == HOLDER and nora["email"] == "nora@hopechapel.example"   # by name, honorific aside
    assert _p(d, "Gwen")["user_id"] == LOOSE                                   # the one login called Gwen
    assert any(n.startswith("Chief took “Gwen” to be Gwen Abara, the one login by that name.")
               for n in _p(d, "Gwen")["notes"])
    caleb = _p(d, "Caleb")                                                     # two Calebs: never a pick
    assert caleb["user_id"] is None and any("More than one login here is called Caleb" in n for n in caleb["notes"])
    maria = _p(d, "Maria Lopez")                                               # a member, by name
    assert maria["user_id"] is None and maria["contact_id"] == C_MARIA and maria["email"] == "maria@hopechapel.example"
    assert any("Their email comes from their record" in n for n in maria["notes"])
    lee = _p(d, "Lee Carter")                                                  # two members by that name
    assert lee["contact_id"] is None and lee["email"] is None
    assert any("More than one person here is named Lee Carter" in n for n in lee["notes"])
    assert _p(d, "Dana Reed")["contact_id"] == C_DANA and _p(d, "Dana Reed")["email"] == "dana@hopechapel.example"
    zed = _p(d, "Zed Novak")
    assert zed["user_id"] is None and zed["contact_id"] is None and zed["state"] == "needs_email"


def test_a_wildcard_in_a_name_or_an_email_finds_nobody(db, monkeypatch):
    """PostgREST reads * as a wildcard in ilike. Whatever the database hands
    back, only a row that IS that name or that email counts."""
    real = db.get
    maria = next(c for c in db.t["contacts"] if c["id"] == C_MARIA)
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: [dict(maria)] if path.startswith("/contacts") and "ilike" in path
                        else real(path, **kw))
    d = _draft(db, {"leads": "pastor", "people": [{"name": "M* L*", "does": "guests"},
                                                  {"name": "Zed Novak", "does": "sound", "email": "*@hopechapel.example"}]})
    assert [(p["contact_id"], p["user_id"]) for p in d["people"]] == [(None, None), (None, None)]
    assert _p(d, "M* L*")["email"] is None


# ─── A person's state, as the church changes ──────────────────────────

def test_state_follows_the_church_from_needing_an_email_to_done(db):
    answers = {"leads": "pastor", "people": [{"name": "Zed Novak", "title": "People & Care",
                                              "does": "calls every guest"}]}
    assert _p(_draft(db, answers), "Zed Novak")["state"] == "needs_email"
    answers["people"][0]["email"] = "zed@hopechapel.example"
    d = _draft(db, answers)
    zed = _p(d, "Zed Novak")
    assert zed["state"] == "new" and zed["job_key"] == "people_care" and zed["user_id"] is None
    # Invited: read again, nothing drafted again.
    uid = "c6000000-0000-4000-8000-000000000006"
    db.t["business_users"].append(_seat(uid, "manager", "zed@hopechapel.example", "Zed Novak", status="invited"))
    db.t["business_users"][-1]["user_id"] = None
    assert _p(_read(db)["draft"], "Zed Novak")["state"] == "invited"
    # Accepted, but with no job and no areas: a login set up differently.
    db.t["business_users"][-1].update(user_id=uid, status="active")
    got = _p(_read(db)["draft"], "Zed Novak")
    assert got["state"] == "login" and got["user_id"] == uid
    # Its job and areas as drafted: done.
    db.t["business_users"][-1].update(lane="people_care", areas=list(ca.LANES["people_care"]["areas"]))
    cd._CACHE.clear()
    assert _p(_read(db)["draft"], "Zed Novak")["state"] == "done"
    # A different level is not done.
    db.t["business_users"][-1]["role"] = "member"
    assert _p(_read(db)["draft"], "Zed Novak")["state"] == "login"


def test_an_email_typed_on_review_reaches_the_draft_and_ties_the_invitation_and_the_login(db):
    d = _draft(db, {"leads": "pastor", "people": [
        {"name": "Zed Novak", "title": "People & Care", "does": "calls every guest", "email": "zed at home"},
        {"name": "Maria Lopez", "does": "runs the prayer chain"},
        {"name": "Ivy Shaw", "does": "keeps the calendar and the office"}]})
    zed = _p(d, "Zed Novak")
    assert zed["state"] == "needs_email" and any("isn't an email address" in n for n in zed["notes"])
    business = _biz(db)

    def put(ref, email):
        return st.set_email(business, co.Church(business), ref, email)
    got = put(zed["ref"], " Zed@HopeChapel.example ")
    zed = _p(got, "Zed Novak")
    assert zed["email"] == "zed@hopechapel.example" and zed["state"] == "new" and got["id"] == d["id"]
    assert not any("isn't an email address" in n for n in zed["notes"])
    # Only that person changed, and it is kept.
    assert [(p["name"], p["email"]) for p in got["people"] if p["name"] != "Zed Novak"] == [
        ("Maria Lopez", "maria@hopechapel.example"), ("Ivy Shaw", None)]
    assert _p(_read(db)["draft"], "Zed Novak")["email"] == "zed@hopechapel.example"
    # The invitation the app sends next is this person's; so is the login when they accept.
    uid = "c6000000-0000-4000-8000-000000000006"
    db.t["business_users"].append(_seat(uid, "manager", "zed@hopechapel.example", "", status="invited",
                                        lane="people_care", areas=list(ca.LANES["people_care"]["areas"])))
    db.t["business_users"][-1]["user_id"] = None
    assert _p(_read(db)["draft"], "Zed Novak")["state"] == "invited"
    db.t["business_users"][-1].update(user_id=uid, status="active")
    cd._CACHE.clear()
    zed = _p(_read(db)["draft"], "Zed Novak")
    assert zed["state"] == "done" and zed["user_id"] == uid
    # A corrected email replaces the one taken from a member's record, with its note.
    maria = _p(put(_p(d, "Maria Lopez")["ref"], "maria.l@hopechapel.example"), "Maria Lopez")
    assert maria["email"] == "maria.l@hopechapel.example" and maria["contact_id"] == C_MARIA
    assert not any(n.startswith("Their email comes from their record") for n in maria["notes"])
    # An email that is already a login's is that login.
    db.t["business_users"].append(_seat(LOOSE, "manager", "ivy.s@hopechapel.example", ""))
    ivy = _p(put(_p(d, "Ivy Shaw")["ref"], "ivy.s@hopechapel.example"), "Ivy Shaw")
    assert ivy["user_id"] == LOOSE and ivy["state"] == "login"
    # The refusals: not an email, the owner's, another person's in the draft, nobody by that ref.
    for bad, code, said in (("nope", 400, "That isn't an email address."), ("", 400, "That isn't an email address."),
                            ("pastor@hopechapel.example", 400, "That is the owner's own email."),
                            ("zed@hopechapel.example", 400, "Zed Novak already has that email in this draft.")):
        with pytest.raises(HTTPException) as e:
            put(_p(d, "Ivy Shaw")["ref"], bad)
        assert e.value.status_code == code and e.value.detail.startswith(said)
    with pytest.raises(HTTPException) as e:
        put("p99", "someone@hopechapel.example")
    assert e.value.status_code == 404
    st.discard(business)
    with pytest.raises(HTTPException) as e:
        put("p1", "someone@hopechapel.example")
    assert e.value.status_code == 404 and KEY_NOT_KEPT(db)


def test_an_accepted_invitation_with_a_church_job_reads_login_until_the_sheet_holds_the_rest(db):
    """Through the real job, invite row and sheet save: a login on one of the
    church's own jobs is `login` while the draft still holds more than the
    job gave, and `done` once the sheet is saved."""
    d = _draft(db, {"leads": "pastor", "guests": "Tom Reyes", "people": [
        {"name": "Tom Reyes", "title": "Minister of Music", "does": "leads the choir and plans the worship",
         "email": "tom@hopechapel.example"}]})
    job = cj.create(_biz(db), next(j for j in d["jobs"] if j["label"] == "Minister of Music"), OWNER, "owner")["job"]
    lane = ca.lane(job["key"], BIZ)                            # what the invite stores (make_invite_row)
    uid = "c7000000-0000-4000-8000-000000000007"
    db.t["business_users"].append(_seat(uid, lane["role"], "tom@hopechapel.example", "Tom Reyes", lane=lane["key"],
                                        areas=lane["areas"]))
    tom = _p(_read(db)["draft"], "Tom Reyes")
    assert tom["state"] == "login" and tom["user_id"] == uid and tom["job_key"] == job["key"]
    # The pastor finishes the areas and duties on the sheet: done.
    cs.change(_biz(db), OWNER, uid, {"areas": tom["areas"], "duties": {"add": tom["duties"]}})
    cd._CACHE.clear()
    ca._MY_CACHE.clear()
    assert _p(_read(db)["draft"], "Tom Reyes")["state"] == "done"


def test_someone_made_an_admin_reads_login_until_the_treasurers_job_is_saved_too(db):
    """The money duties come with the Treasurer job: the sheet takes no
    separate duty for an Admin (an Admin does every duty), so `done` is the
    level AND the job."""
    _draft(db, SMALL)
    uid = "c8000000-0000-4000-8000-000000000008"
    db.t["business_users"].append(_seat(uid, "member", "alma@hopechapel.example", "Alma Price"))
    assert _p(_read(db)["draft"], "Alma Price")["state"] == "login"
    cs.change(_biz(db), OWNER, uid, {"level": "admin"})
    cd._CACHE.clear()
    alma = _p(_read(db)["draft"], "Alma Price")
    assert alma["state"] == "login" and alma["duties"] == cd.STARTER["treasurer"]
    with pytest.raises(HTTPException) as e:                   # there is no "save the money duties" for an Admin
        cs.change(_biz(db), OWNER, uid, {"duties": {"add": alma["duties"]}})
    assert e.value.status_code == 400
    assert _p(_read(db)["draft"], "Alma Price")["state"] == "login"
    cs.change(_biz(db), OWNER, uid, {"job": "treasurer"})
    cd._CACHE.clear()
    assert _p(_read(db)["draft"], "Alma Price")["state"] == "done"


def test_every_gap_carries_its_tone_and_only_the_two_money_ones_warn(db):
    _office(db)
    db.t["business_users"] = [r for r in db.t["business_users"] if r["user_id"] != ADMIN]
    d = _draft(db, {"leads": "pastor_board", "money": {"counts": ["Bo Finch"], "deposits": "Bo Finch", "books": None},
                    "guests": "Zed Novak", "people": [{"name": "Bo Finch", "does": "helps out"},
                                                      {"name": "Cy Hale", "does": "helps out"}]})
    gaps =d["gaps"] + _read(db)["status"]["gaps"] + _read_alone(db)
    assert {g["key"] for g in gaps} == set(st.GAP_KEYS)        # every key the engine emits, each seen here
    assert all(g["tone"] == ("warn" if g["key"] in ("no_giving", "counts_and_deposits") else "note") for g in gaps)
    assert st.WARN_GAPS == {"no_giving", "counts_and_deposits"}


def _read_alone(db):
    db.t["business_users"] = []
    cd._CACHE.clear()
    st.discard(_biz(db))
    return _read(db)["status"]["gaps"]


def test_a_job_the_church_makes_later_is_found_by_its_title(db):
    d = _draft(db, {"leads": "pastor", "people": [
        {"name": "Tom Reyes", "title": "Minister of Music", "does": "leads the choir", "email": "tom@hopechapel.example"}]})
    job = next(j for j in d["jobs"] if j["label"] == "Minister of Music")
    assert not job["exists"] and _p(d, "Tom Reyes")["job_key"] is None
    made = cj.create(_biz(db), job, OWNER, "owner")["job"]
    again = _read(db)["draft"]
    job = next(j for j in again["jobs"] if j["label"] == "Minister of Music")
    assert job["exists"] and job["key"] == made["key"] and _p(again, "Tom Reyes")["job_key"] == made["key"]
    assert again["id"] == d["id"]


# ─── The gaps ─────────────────────────────────────────────────────────

def test_a_church_with_only_its_pastor_is_told_so_and_nothing_heavy_is_read(db, monkeypatch):
    monkeypatch.setattr(ca, "build", lambda business: (_ for _ in ()).throw(AssertionError("not read")))
    got = _read(db)
    assert got["draft"] is None and got["can_draft"] and got["status"] == {
        "logins": 0, "placed": 0, "gaps": [st._gap("pastor_only", "You are the only login.",
                                                   got["status"]["gaps"][0]["fix"])]}
    d = _draft(db, {"leads": "pastor", "people": []})
    assert _keys(d["gaps"])[:2] == ["pastor_only", "no_giving"] and "job_unheld" not in _keys(d["gaps"])
    board = _draft(db, {"leads": "pastor_board", "people": []})
    assert _keys(board["gaps"])[:2] == ["pastor_only", "no_giving"] and _keys(board["gaps"])[-1] == "job_unheld"


def test_the_drafts_gaps_name_what_is_still_missing_each_with_its_fix(db):
    d = _draft(db, {"leads": "pastor", "money": {"counts": ["Dana Reed"], "deposits": "Dana Reed", "books": None},
                    "people": [{"name": "Dana Reed", "does": "counts the offering"},
                               {"name": "Bo Finch", "does": "helps out"}]})
    keys = _keys(d["gaps"])
    assert keys.count("no_giving") == 1 and "counts_and_deposits" in keys and "no_guests" in keys
    # Bo has nothing on; Dana only counts, which needs no login, so she isn't a gap.
    assert [g["line"] for g in d["gaps"] if g["key"] == "nothing_on"] == ["Nothing is switched on for Bo Finch yet."]
    assert _p(d, "Dana Reed")["no_login"] and _p(d, "Dana Reed")["role"] == "viewer" and "pastor_only" not in keys
    assert _p(d, "Dana Reed")["why"] == "Counting the offering needs no login today, so nothing is switched on."
    by = {g["key"]: g for g in d["gaps"]}
    assert by["no_giving"]["line"] == "Nobody but you handles giving."
    assert by["counts_and_deposits"]["line"] == "Dana Reed both counts the offering and deposits it."
    assert "Two people on the money" in by["counts_and_deposits"]["fix"]
    assert all(g["line"] and g["fix"] for g in d["gaps"])
    assert "job_unheld" not in keys                              # a ready-made job nobody holds is no gap
    # The pastor doing it all is said in their own words.
    mine = _draft(db, {"leads": "pastor", "money": {"counts": ["me"], "deposits": "Pastor Daniel Brooks", "books": "I"},
                       "guests": "me", "people": []})
    by = {g["key"]: g for g in mine["gaps"]}
    assert by["no_giving"]["line"] == "Only you handle giving."
    assert by["counts_and_deposits"]["line"] == "You count the offering and deposit it yourself."
    assert "no_guests" not in by
    # Two counters, one of them the depositor, is not the two-person gap.
    assert "counts_and_deposits" not in _keys(_draft(db, SMALL)["gaps"])
    # Someone named for guests who isn't here is said by name.
    gone = _draft(db, {"leads": "pastor", "guests": "Zed Novak", "people": []})
    assert "Zed Novak should hear when a guest comes, but isn't set up to." in [g["line"] for g in gone["gaps"]]


def test_a_full_small_church_has_nothing_missing(db):
    d = _draft(db, SMALL)
    assert d["gaps"] == []
    maria = _p(d, "Maria Lopez")
    assert maria["duties"] == ["first_guests", "prayer"] and maria["job_label"] == "Guest follow-up and prayer"


def test_the_standing_check_reads_the_church_as_it_is_with_or_without_a_draft(db):
    _office(db)
    s = _read(db)["status"]
    assert s["logins"] == 4 and s["placed"] == 3
    assert _keys(s["gaps"]) == ["sees_everything"]
    assert s["gaps"][0]["line"].startswith("Gwen Abara's login opens the whole church")
    # Without an Admin, and without anyone on guests.
    db.t["business_users"] = [r for r in db.t["business_users"] if r["user_id"] not in (ADMIN, MANAGER)]
    cd._CACHE.clear()
    s = _read(db)["status"]
    # A Manager nothing places does every duty in the church, the welcome calls too.
    assert _keys(s["gaps"]) == ["no_giving", "sees_everything"]
    gwen = next(r for r in db.t["business_users"] if r["user_id"] == LOOSE)
    gwen.update(lane="media_comms", areas=list(ca.LANES["media_comms"]["areas"]))
    cd._CACHE.clear()
    s = _read(db)["status"]
    assert _keys(s["gaps"]) == ["no_giving", "no_guests"] and s["placed"] == 2
    gwen.update(lane=None, areas=None)
    cd._CACHE.clear()
    # A draft that places the loose login no longer lists it; one that doesn't still does.
    d = _draft(db, {"leads": "pastor", "people": [{"name": "Gwen Abara", "does": "leads the youth group"}]})
    assert "sees_everything" not in _keys(d["gaps"]) and _p(d, "Gwen Abara")["state"] == "login"
    d = _draft(db, {"leads": "pastor", "money": {"counts": ["Gwen Abara"], "deposits": "Gwen Abara", "books": None},
                    "people": [{"name": "Zed Novak", "does": "guests"}]})
    assert "sees_everything" in _keys(d["gaps"])
    assert "counts_and_deposits" in _keys(_read(db)["status"]["gaps"])       # the standing check keeps what was said


# ─── From the planning course ─────────────────────────────────────────

PLAN = {
    "leaders": {"teams": [{"name": "Welcome Team", "leader": "Maria Lopez", "needs": "two more greeters"},
                          {"name": "Media Team", "leader": "Tom Reyes and Ana Bell"},
                          {"name": "Deacons", "leader": "TBD"}],
                "gaps": ["A youth leader"], "care": "The deacons visit the sick."},
    "ministries": {"ministries": [{"name": "Kids Church", "leader": "Maria Lopez", "call": "grow"},
                                  {"name": "Men's Breakfast", "leader": "Sol Marsh", "call": "pause"},
                                  {"name": "Finance Team", "leader": "Rita Vance", "call": "keep"}]},
    "stewardship": {"priorities": ["A new roof"]},
}


def _plan(db, phases=PLAN):
    db.t["strategy_tracks"].append({"id": "f1", "business_id": BIZ, "status": "in_progress", "phases": phases,
                                    "created_at": "2026-11-10T00:00:00+00:00"})


def test_a_draft_from_the_plan_maps_what_is_written_and_says_the_rest(db, monkeypatch):
    for mod in ("anthropic", "httpx"):                       # no model and no network anywhere on this path
        monkeypatch.setitem(sys.modules, mod, None)
    _plan(db)
    d = _draft(db, from_plan=True)
    assert d["source"] == "plan" and d["shape"]["key"] == "pastor_board"     # the plan names deacons
    assert "This comes from the Leaders and Ministries pages of your plan" in d["shape"]["why"]
    assert [p["name"] for p in d["people"]] == ["Maria Lopez", "Tom Reyes", "Ana Bell", "Rita Vance"]
    maria = _p(d, "Maria Lopez")
    assert maria["does"] == "Leads Welcome Team and Kids Church" and maria["contact_id"] == C_MARIA
    # The plan gives no titles, so each job is called by what they lead, with only what that needs.
    assert maria["job_label"] == "Welcome Team and Kids Church leader" and maria["job_key"] is None
    assert maria["areas"] == ["people_care", "kids_youth"] and maria["duties"] == ["first_guests", "kids"]
    tom, ana = _p(d, "Tom Reyes"), _p(d, "Ana Bell")
    assert tom["job_label"] == ana["job_label"] == "Media Team leader" and tom["areas"] == ["worship_media"]
    assert tom["duties"] == [] and _labels(d).count("Media Team leader") == 1
    assert not [p for p in d["people"] if p["job_key"] in ca.LANES]      # nobody is handed a ready-made job
    rita = _p(d, "Rita Vance")                               # leading the finance team is not an Admin login
    assert rita["role"] == "viewer" and rita["areas"] == [] and rita["job_label"] == "Finance Team leader"
    assert st.MONEY_WORDS_NOTE.format(name="Rita Vance") in rita["notes"]
    assert st.EMPTY_JOB_NOTE.format(job="Finance Team leader", name="Rita Vance") in rita["notes"]
    notes = " ".join(d["notes"])
    assert "Deacons has no leader named in your plan" in notes
    assert "Men's Breakfast is marked pause in your plan" in notes
    assert "these leaders are still needed: A youth leader." in notes
    assert "Stewardship page names no one who counts the offering" in notes
    assert "no_giving" in _keys(d["gaps"]) and "Deacon" in _labels(d)
    assert _read(db)["plan"] == {"leaders_written": True, "can_use": True}
    # What Chief was also told is laid over the plan.
    d = _draft(db, {"leads": "staff", "money": {"counts": [], "deposits": None, "books": "Rita Vance"}}, from_plan=True)
    assert d["shape"]["key"] == "staff_led" and _p(d, "Rita Vance")["role"] == "admin"


def test_a_draft_from_the_plan_is_refused_until_leaders_is_written_and_to_whoever_the_course_isnt(db, monkeypatch):
    with pytest.raises(HTTPException) as e:
        _draft(db, from_plan=True)                           # no plan at all
    assert e.value.status_code == 400 and e.value.detail == st.PLAN_NOT_WRITTEN
    _plan(db, {"calling": {"mission": "To love the city"}, "ministries": PLAN["ministries"]})
    with pytest.raises(HTTPException) as e:
        _draft(db, from_plan=True)
    assert e.value.status_code == 400 and _read(db)["plan"] == {"leaders_written": False, "can_use": True}
    db.t["strategy_tracks"][0]["phases"] = PLAN
    _office(db)
    with pytest.raises(HTTPException) as e:
        _draft(db, by=HOLDER, ed="holder", from_plan=True)
    assert e.value.status_code == 403 and e.value.detail == st.PLAN_NOT_YOURS
    assert _read(db, HOLDER, "holder")["plan"] == {"leaders_written": False, "can_use": False}
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/strategy_tracks") else real(path, **kw))
    with pytest.raises(HTTPException) as e:
        _draft(db, from_plan=True)
    assert e.value.status_code == 503
    assert KEY_NOT_KEPT(db)


def _row(db, biz=BIZ):
    """The church's kept draft row, or None."""
    return next((r for r in db.t[st.TABLE] if r["business_id"] == biz), None)


def KEY_NOT_KEPT(db):
    return _row(db) is None


def test_nothing_said_is_a_400_and_nothing_is_kept(db):
    for answers in (None, {}, "who helps"):
        with pytest.raises(HTTPException) as e:
            _draft(db, answers)
        assert e.value.status_code == 400 and e.value.detail == st.NOTHING_SAID
    assert KEY_NOT_KEPT(db)


# ─── How it is kept ───────────────────────────────────────────────────

def test_the_draft_is_one_per_church_in_its_own_table_and_nothing_else_is_written(db):
    before = {t: [dict(r) for r in rows] for t, rows in db.t.items() if t != st.TABLE}
    first = _draft(db, SMALL)
    second = _draft(db, {"leads": "pastor_board", "people": [{"name": "Zed Novak", "title": "Usher", "does": "guests"}]})
    assert len(db.t[st.TABLE]) == 1 and db.keeps == 2
    row = _row(db)
    assert set(row) == {"business_id", "draft", "made_by", "made_at", "updated_at"} and row["made_by"] == OWNER
    assert row["draft"]["id"] == second["id"] != first["id"]
    assert [p["name"] for p in row["draft"]["people"]] == ["Zed Novak"]
    # No login, no invitation, no job, no sheet change, and nothing in the church's settings: every other
    # table is as it was (the role library aside, which the Logins & areas page fills when it is first read).
    after = {t: rows for t, rows in db.t.items() if t not in (st.TABLE, "church_role_defs")}
    assert after == {t: rows for t, rows in before.items() if t != "church_role_defs"}
    assert _biz(db)["settings"] == {"practitioner_name": "Pastor Daniel Brooks", "theme": "light"}
    assert db.t["business_users"] == [] and db.t["church_jobs"] == [] and db.t["church_sheet_changes"] == []
    st.discard(_biz(db))
    assert KEY_NOT_KEPT(db)
    st.discard(_biz(db))                                    # nothing to clear is not a failure


def test_nothing_about_a_draft_is_ever_in_settings():
    import business_settings
    src = (pathlib.Path(ROOT) / "church_structure.py").read_text(encoding="utf-8")
    assert "business_settings" not in src.split('"""', 2)[2] and "merge_business_settings" not in src
    assert "church_structure" not in business_settings.SERVER_KEYS
    assert not (pathlib.Path(ROOT) / "supabase" / "APPLY-2026-11-18-church-structure-key.sql").exists()


def test_a_draft_that_doesnt_save_is_a_503_never_a_draft(db, monkeypatch):
    real = db.post
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda path, body, prefer=None, **kw: None if path.startswith(f"/{st.TABLE}")
                        else real(path, body, prefer, **kw))
    with pytest.raises(HTTPException) as e:
        _draft(db, SMALL)
    assert e.value.status_code == 503 and e.value.detail == st.UNSAVED and KEY_NOT_KEPT(db)


def _table_gone(db, monkeypatch):
    """The drafts' table before its file is applied: PostgREST answers an
    error, which the service helpers hand back as None."""
    get, post = db.get, db.post
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith(f"/{st.TABLE}") else get(path, **kw))
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda path, body, prefer=None, **kw: None if path.startswith(f"/{st.TABLE}")
                        else post(path, body, prefer, **kw))
    monkeypatch.setattr(sb_clients, "sb_delete_as_service",
                        lambda path, **kw: False if path.startswith(f"/{st.TABLE}") else db.delete(path, **kw))


def test_before_the_table_is_there_nothing_is_drafted_and_the_standing_check_still_answers(db, monkeypatch):
    _office(db)
    _table_gone(db, monkeypatch)
    got = _read(db)
    assert got["ready"] is False and got["draft"] is None and got["can_draft"] is True
    assert got["status"]["logins"] == 4 and _keys(got["status"]["gaps"]) == ["sees_everything"]
    business = _biz(db)
    for go in (lambda: _draft(db, SMALL), lambda: st.set_email(business, co.Church(business), "p1", "a@b.example"),
               lambda: st.discard(business)):
        with pytest.raises(HTTPException) as e:
            go()
        assert e.value.status_code == 503 and e.value.detail == st.NOT_READY
    assert st.NOT_READY == "Team setup is being switched on. Try again shortly."
    # Chief relays the sentence and never says a draft was made; the status read still works.
    no = chief(db, OWNER, "draft_church_structure", answers=SMALL)
    assert no["failed"] and no["result"] == f"Failed: {st.NOT_READY.rstrip('.')}. No draft was made."
    status = chief(db, OWNER, "church_structure_status")
    assert not status.get("failed") and "4 logins besides the owner; 3 placed" in status["result"]
    assert "isn't switched on here yet" in status["result"] and "draft_church_structure" not in status["result"]
    assert st.coach_block(business, OWNER).count("A draft of the office team") == 0


def test_the_migration_is_one_server_only_table_and_the_export_knows_it():
    import account_lifecycle
    sql = (pathlib.Path(ROOT) / "supabase" / "APPLY-2026-11-18-church-structure-drafts.sql").read_text(encoding="utf-8")
    code = "\n".join(line.split("--", 1)[0] for line in sql.splitlines()).lower()
    assert code.count("create table if not exists public.church_structure_drafts(") == 1
    assert "business_id uuid primary key references public.businesses(id) on delete cascade" in code
    for col in ("draft jsonb not null", "made_by uuid", "made_at timestamptz not null default now()",
                "updated_at timestamptz not null default now()"):
        assert col in code, col
    assert "alter table public.church_structure_drafts enable row level security;" in code
    assert "revoke all on public.church_structure_drafts from public, anon, authenticated;" in code
    assert "grant all on public.church_structure_drafts to service_role;" in code
    assert "create policy" not in code and "drop " not in code and "security definer" not in code
    assert code.index("begin;") < code.index("create table") < code.index("commit;")
    assert "-- Check:" in sql and "-- Rollback" in sql and "drop table if exists public.church_structure_drafts;" in sql
    assert st.TABLE in account_lifecycle.BUSINESS_CHILD_TABLES and st.TABLE in account_lifecycle._IMPORT_SKIP
    assert st.TABLE not in account_lifecycle.EXPORT_EXCLUDED
    ledger = (pathlib.Path(ROOT) / "docs" / "MIGRATIONS.md").read_text(encoding="utf-8")
    row = next(ln for ln in ledger.splitlines() if "APPLY-2026-11-18-church-structure-drafts.sql" in ln)
    assert row.rstrip().endswith("| **NOT APPLIED** |") and "church-structure-key" not in ledger


def test_a_church_that_cant_be_read_is_a_503_with_nothing_kept(db, monkeypatch):
    _office(db)

    def unread(business):
        raise HTTPException(503, "The areas couldn't be read just now. Try again.")
    monkeypatch.setattr(ca, "build", unread)
    with pytest.raises(HTTPException) as e:
        _draft(db, SMALL)
    assert e.value.status_code == 503 and KEY_NOT_KEPT(db)
    got = chief(db, OWNER, "draft_church_structure", answers=SMALL)
    assert got["failed"] and "No draft was made." in got["result"] and KEY_NOT_KEPT(db)


def test_what_is_kept_is_cleaned_again_on_every_read_so_a_forged_draft_opens_nothing(db):
    """Only the server writes the table, and what it reads back is still
    cleaned: whatever a row holds, what comes out is a proposal inside the
    rules."""
    db.t[st.TABLE].append({"business_id": BIZ, "draft": None})
    _row(db)["draft"] = {
        "id": "x", "made_at": "2026-11-18T10:00:00+00:00", "made_by_name": "Someone", "source": "elsewhere",
        "shape": {"key": "theocracy", "why": "w" * 5000},
        "jobs": [{"label": "Money Friend", "role": "manager", "areas": ["giving_money", "office"],
                  "duties": ["deposit", "calendar"], "custom": True, "exists": True, "key": "treasurer",
                  "description": {"not": "words"}}, "junk"],
        "people": [{"name": "Zed Novak", "role": "manager", "areas": ["giving_money", "office"],
                    "duties": ["books", "calendar"], "user_id": "not-a-uuid", "email": "nope", "state": "done",
                    "job_label": "Money Friend", "notes": ["n" * 900]},
                   {"name": "Ivy Shaw", "role": "emperor", "areas": "all", "duties": ["pay"]}, 7],
        "answers": {"leads": "x", "money": "y", "bodies": "z"},
    }
    d = _read(db)["draft"]
    assert d["shape"] == {"key": "pastor_helpers", "label": "Pastor and helpers", "why": "w" * 700}
    assert d["source"] == "questions"
    job = d["jobs"][0]
    assert job["areas"] == ["office"] and job["duties"] == ["calendar"] and not job["exists"] and job["key"] is None
    zed, ivy = d["people"]
    assert zed["areas"] == ["office"] and zed["duties"] == ["calendar"] and zed["user_id"] is None
    assert zed["email"] is None and zed["state"] == "needs_email" and len(zed["notes"][0]) <= st.NOTE_MAX
    # Nothing switched on is never more than a Viewer, and never someone to invite.
    assert ivy["role"] == "viewer" and ivy["areas"] == [] and ivy["duties"] == [] and ivy["state"] == "needs_job"
    assert job["description"] is None                       # a description that isn't words is no description
    for junk in (None, "draft", {"people": "many"}, {"people": [], "jobs": None}):
        _row(db)["draft"] = junk
        got = _read(db)
        assert got["draft"] is None and got["ready"] is True


# ─── A church job brings only the duties given on the sheet ───────────
# Kevin, 2026-11-18. Found while building this: a login on one of the
# church's own jobs whose areas were exactly a starting job's areas held that
# starting job's duties (church_duties._seat_lane fell back to the lane the
# areas spell), and any other login on a church job held every duty in its
# areas.

TOM = "c7000000-0000-4000-8000-000000000007"
PAT = "c7100000-0000-4000-8000-000000000071"
KAY = "c7200000-0000-4000-8000-000000000072"


def _held(db, uid):
    cd._CACHE.clear()
    ca._MY_CACHE.clear()
    ch = co.Church(_biz(db))
    return set(ch.held(uid)), set(cd.standing(BIZ, uid)["duties"]), ch.lanes(uid)


def test_a_login_on_a_church_job_holds_only_the_duties_given_on_its_sheet(db):
    job = cj.create(_biz(db), {"label": "Minister of Music", "role": "manager", "areas": ["worship_media"],
                               "duties": ["sunday_plan"]}, OWNER, "owner")["job"]
    assert ca.LANES["sunday_serving"]["areas"] == ["worship_media"]      # the same areas as a starting job
    db.t["business_users"] += [
        _seat(TOM, "manager", "tom@hopechapel.example", "Tom Reyes", lane=job["key"], areas=["worship_media"]),
        _seat(PAT, "manager", "pat@hopechapel.example", "Pat Shaw", areas=["worship_media"]),
        _seat(KAY, "manager", "kay@hopechapel.example", "Kay Odum", areas=["kids_youth"]),
    ]
    tom = next(x for x in db.t["business_users"] if x["user_id"] == TOM)
    assert cd.own_job_seat(tom) and cd._seat_lane(tom) is None
    # Tom, on the church's own job: nothing from Sunday & Serving, nothing from the area, nothing from the
    # job's own list. A job is a starting point for a sheet, never the sheet.
    assert _held(db, TOM) == (set(), set(), [])
    page = {d["key"]: d for d in cd.build(_biz(db))["duties"]}
    assert all(TOM not in [h["user_id"] for h in d["holders"]] for d in page.values())
    # Given on his sheet, it is his: exactly that.
    cs.change(_biz(db), OWNER, TOM, {"duties": {"add": ["sunday_plan"]}})
    assert _held(db, TOM)[:2] == ({"sunday_plan"}, {"sunday_plan"})
    sheet = cs.compose(_biz(db), OWNER, TOM)
    assert sheet["job"] == {"key": job["key"], "label": "Minister of Music", "custom": True}
    assert {d["key"] for d in sheet["duties"] if d["held"]} == {"sunday_plan"}
    # Pat has no job, and her picked areas spell Sunday & Serving: that lane's duties, as before.
    pat = next(x for x in db.t["business_users"] if x["user_id"] == PAT)
    assert not cd.own_job_seat(pat) and cd._seat_lane(pat) == "sunday_serving"
    held, standing, lanes = _held(db, PAT)
    assert held == standing == set(cd.STARTER["sunday_serving"]) and lanes == ["sunday_serving"]
    # Kay has no job and areas no lane spells: the duties in her areas, as before.
    held, standing, lanes = _held(db, KAY)
    assert held == standing == {"kids", "youth", "background_checks"} and lanes == []
    # A starting job stored on a login is still that job's duties (less the one that moved to Tom by name).
    pat.update(lane="media_comms", areas=list(ca.LANES["media_comms"]["areas"]))
    assert _held(db, PAT)[0] == set(cd.STARTER["media_comms"]) - {"sunday_plan"}


def test_putting_someone_on_a_church_job_keeps_the_duties_their_sheet_showed_by_name(db):
    """A save that leaves a Manager on a church job must not quietly take
    away what they did by their areas: each duty is given to them by name."""
    job = cj.create(_biz(db), {"label": "Kids Director", "role": "manager", "areas": ["kids_youth"],
                               "duties": ["kids"]}, OWNER, "owner")["job"]
    db.t["business_users"].append(_seat(KAY, "manager", "kay@hopechapel.example", "Kay Odum", areas=["kids_youth"]))
    before = _held(db, KAY)[0]
    assert before == {"kids", "youth", "background_checks"}
    asked = []
    got = cs.change(_biz(db), OWNER, KAY, {"job": job["key"]}, widening=lambda: asked.append(1))
    assert asked == [] and not got["widens"]
    assert got["summary"] == ("changed Kay Odum's sheet: job: Kids Director; kept “Kids”, “Youth and Teen Bible "
                              "Study” and “Background checks” by name")
    assert db.t["church_sheet_changes"][-1]["detail"]["kept_by_name"] == ["kids", "youth", "background_checks"]
    assert _held(db, KAY)[0] == before
    named = {r["duty"] for r in db.t["church_duty_holders"] if r["user_id"] == KAY}
    assert named == before                                   # by name now, not by her areas
    # Widening her areas afterwards brings no duty with it: a church job never does.
    cs.change(_biz(db), OWNER, KAY, {"areas": ["kids_youth", "groups_classes"]})
    assert _held(db, KAY)[0] == before


def test_after_accepting_a_job_gives_done_only_when_nothing_more_is_drafted(db):
    """What the app reads right after an invitation is accepted (the invite
    stores the job's key and its areas): a ready-made job brings its duties,
    a church job brings none. So `done` is straight away for a ready-made job
    held as it is and for a church job with no duties drafted; a drafted duty
    on a church job is `login` until the sheet is saved."""
    d = _draft(db, {"leads": "pastor_board", "people": [
        {"name": "Ida Poe", "title": "People & Care", "does": "all of care", "email": "ida@hopechapel.example"},
        {"name": "Sol Marsh", "title": "Board member", "does": "sits on the board", "email": "sol@hopechapel.example"},
        {"name": "Ruth Okoye", "title": "Deacon", "does": "visits the sick", "email": "ruth@hopechapel.example"}]})
    made = {}
    for j in d["jobs"]:
        if not j["exists"]:
            made[j["label"]] = cj.create(_biz(db), j, OWNER, "owner")["job"]["key"]
    for n, (name, email, key) in enumerate((("Ida Poe", "ida@hopechapel.example", "people_care"),
                                            ("Sol Marsh", "sol@hopechapel.example", made["Board member"]),
                                            ("Ruth Okoye", "ruth@hopechapel.example", made["Deacon"]))):
        lane = ca.lane(key, BIZ)                              # what make_invite_row stores
        db.t["business_users"].append(_seat(f"c8{n}00000-0000-4000-8000-00000000008{n}", lane["role"], email, name,
                                            lane=lane["key"], areas=lane["areas"]))
    cd._CACHE.clear()
    got = _read(db)["draft"]
    assert _p(got, "Ida Poe")["state"] == "done"             # a ready-made job, held as it is
    assert _p(got, "Sol Marsh")["state"] == "done"           # a church job with no duties drafted
    ruth = _p(got, "Ruth Okoye")
    assert ruth["state"] == "login" and ruth["duties"] == ["care_visits", "help_requests"]
    cs.change(_biz(db), OWNER, ruth["user_id"], {"duties": {"add": ruth["duties"]}})
    cd._CACHE.clear()
    assert _p(_read(db)["draft"], "Ruth Okoye")["state"] == "done"


# ─── The routes ───────────────────────────────────────────────────────

@pytest.fixture
def office(db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import business_access
    _office(db)
    who = {"id": OWNER}

    def role(biz, uid):
        if uid == OWNER:
            return "owner"
        return next((s["role"] for s in db.t["business_users"] if s["user_id"] == uid and biz == BIZ), None)
    monkeypatch.setattr(business_access, "_resolve_role", role)
    app = FastAPI()
    app.include_router(st.router)
    app.dependency_overrides[sb_clients.authed_request] = (
        lambda: SimpleNamespace(user=SimpleNamespace(id=who["id"], email="someone@example.com", user_metadata={})))
    client = TestClient(app)
    client.who = who
    return client


def test_the_email_door_is_the_drafters_and_asks_for_no_password_like_the_draft_itself(office, db):
    d = office.post("/church/structure/draft", json={"business_id": BIZ, "answers": SMALL}).json()["draft"]
    ref = _p(d, "Dana Reed")["ref"]
    for uid in (OWNER, ADMIN, HOLDER):
        office.who["id"] = uid
        r = office.post("/church/structure/person",
                        json={"business_id": BIZ, "ref": ref, "email": f"dana.{uid[:2]}@hopechapel.example"})
        assert r.status_code == 200 and r.json()["ok"]
        assert _p(r.json()["draft"], "Dana Reed")["email"] == f"dana.{uid[:2]}@hopechapel.example"
        assert all(g["tone"] in ("warn", "note") for g in r.json()["draft"]["gaps"])
    kept = _p(_read(db)["draft"], "Dana Reed")["email"]
    office.who["id"] = MANAGER
    body = {"business_id": BIZ, "ref": ref, "email": "someone@hopechapel.example"}
    assert office.post("/church/structure/person", json=body).status_code == 403
    office.who["id"] = STRANGER
    assert office.post("/church/structure/person", json=body).status_code == 404
    office.who["id"] = OWNER
    assert office.post("/church/structure/person", json={**body, "email": "nope"}).status_code == 400
    assert office.post("/church/structure/person", json={**body, "ref": "p99"}).status_code == 404
    assert office.post("/church/structure/person", json={**body, "business_id": "nope"}).status_code == 400
    assert office.post("/church/structure/person", json={**body, "business_id": SHOP}).status_code == 404
    assert _p(_read(db)["draft"], "Dana Reed")["email"] == kept
    # None of the three doors is behind the password: a draft grants nothing. (The invite and the sheet are.)
    import inspect
    for fn in (st.post_draft, st.post_person, st.delete_structure):
        assert "require_unlock" not in inspect.getsource(fn) and "request" not in inspect.signature(fn).parameters
    assert "ledger_unlock" not in inspect.getsource(st)


def test_the_owner_an_admin_and_whoever_sets_up_jobs_draft_read_and_clear(office, db):
    for uid in (OWNER, ADMIN, HOLDER):
        office.who["id"] = uid
        r = office.post("/church/structure/draft", json={"business_id": BIZ, "answers": SMALL})
        assert r.status_code == 200 and r.json()["ok"] and r.json()["draft"]["shape"]["key"] == "pastor_helpers"
        got = office.get(f"/church/structure?business_id={BIZ}").json()
        assert got["ok"] and got["can_draft"] and got["ready"] and got["draft"]["id"] == r.json()["draft"]["id"]
        assert got["status"]["logins"] == 4 and got["plan"]["can_use"] == (uid != HOLDER)
        assert set(got["draft"]) >= {"id", "made_at", "made_by_name", "source", "shape", "jobs", "people", "gaps"}
        person = got["draft"]["people"][0]
        assert set(person) >= {"ref", "name", "email", "user_id", "contact_id", "job_label", "job_key", "role",
                               "areas", "duties", "why", "state", "notes"}
        assert set(got["draft"]["jobs"][0]) >= {"key", "label", "does", "description", "role", "areas", "duties",
                                                "custom", "exists"}
        assert office.delete(f"/church/structure?business_id={BIZ}").json() == {"ok": True}
        assert office.get(f"/church/structure?business_id={BIZ}").json()["draft"] is None
    # The treasurer already has her login, set up as drafted.
    office.who["id"] = OWNER
    d = office.post("/church/structure/draft", json={"business_id": BIZ, "answers": SMALL}).json()["draft"]
    assert _p(d, "Alma Price")["state"] == "done" and _p(d, "Alma Price")["user_id"] == ADMIN


def test_everyone_else_is_refused_and_a_plain_login_reads_nothing_of_it(office, db):
    office.post("/church/structure/draft", json={"business_id": BIZ, "answers": SMALL})
    kept = dict(_row(db)["draft"])
    office.who["id"] = MANAGER
    r = office.post("/church/structure/draft", json={"business_id": BIZ, "answers": SMALL})
    assert r.status_code == 403 and r.json()["detail"] == st.NOT_YOURS
    assert office.delete(f"/church/structure?business_id={BIZ}").status_code == 403
    got = office.get(f"/church/structure?business_id={BIZ}").json()
    assert got == {"ok": True, "draft": None, "status": {"logins": 0, "placed": 0, "gaps": []}, "can_draft": False,
                   "ready": False, "plan": {"leaders_written": False, "can_use": False}}
    assert _row(db)["draft"] == kept
    office.who["id"] = STRANGER
    assert office.get(f"/church/structure?business_id={BIZ}").status_code == 404
    assert office.post("/church/structure/draft", json={"business_id": BIZ, "answers": SMALL}).status_code == 404
    assert office.delete(f"/church/structure?business_id={BIZ}").status_code == 404
    office.who["id"] = OWNER
    for bad in ("nope", f"{BIZ}%23", ""):
        assert office.get(f"/church/structure?business_id={bad}").status_code in (400, 422)
        assert office.post("/church/structure/draft", json={"business_id": bad, "answers": SMALL}).status_code == 400
    assert office.get(f"/church/structure?business_id={SHOP}").status_code == 404        # not a church
    assert office.post("/church/structure/draft", json={"business_id": SHOP, "answers": SMALL}).status_code == 404
    assert office.post("/church/structure/draft", json={"business_id": BIZ}).status_code == 400
    office.who["id"] = HOLDER
    r = office.post("/church/structure/draft", json={"business_id": BIZ, "from_plan": True})
    assert r.status_code == 403 and r.json()["detail"] == st.PLAN_NOT_YOURS
    # from_plan is a real true, never a truthy word.
    office.who["id"] = OWNER
    assert office.post("/church/structure/draft", json={"business_id": BIZ, "from_plan": "yes"}).status_code == 400


def test_the_routes_are_off_where_logins_and_areas_is_off(office, monkeypatch):
    monkeypatch.setenv("CHURCH_AREAS", "off")
    assert office.get(f"/church/structure?business_id={BIZ}").status_code == 404
    assert office.post("/church/structure/draft", json={"business_id": BIZ, "answers": SMALL}).status_code == 404


def test_the_router_is_mounted_before_the_catch_all():
    text = (pathlib.Path(ROOT) / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert text.index("app.include_router(church_structure_router)") < text.rindex("public_site_router")


# ─── Chief ────────────────────────────────────────────────────────────

def chief(db, uid, verb, taint=0, **action):
    """One Chief verb in one turn, as `uid` ('' for nobody signed in)."""
    import chief_of_staff as cos

    async def go():
        cos._UNTRUSTED_TAINT.set(taint)
        return await cos.ACTION_HANDLERS[verb](None, {"id": BIZ}, dict(action))
    token = cos._TURN_USER_ID.set(uid or "")
    try:
        return asyncio.run(go())
    finally:
        cos._TURN_USER_ID.reset(token)


def test_both_verbs_are_handlers_placed_by_their_own_check_and_never_an_outside_agents():
    import action_registry
    import chief_areas
    import chief_church_structure as ccst
    import chief_of_staff as cos
    import chief_tool_loop
    assert set(ccst.HANDLERS) == {"draft_church_structure", "church_structure_status"} == set(ccst.PROGRESS)
    assert {t["name"] for t in ccst.TOOLS} == set(ccst.HANDLERS)
    assert ccst.WRITES == {"draft_church_structure"}
    for verb in ccst.HANDLERS:
        assert cos.ACTION_HANDLERS[verb] is ccst.HANDLERS[verb]
        assert chief_areas.VERBS[verb] == (chief_areas.ALL,) and verb not in chief_areas.OWNERS
        assert action_registry.effect(verb) == action_registry.READ
        assert not action_registry.may_expose_to_agent(verb)
    said = next(t["description"] for t in ccst.TOOLS if t["name"] == "draft_church_structure")
    assert "THIS SAVES THE PROPOSAL" in said and "no login, no invitation, no job and no sheet" in said
    names = {t["name"] for t in chief_tool_loop.tool_definitions_for_turn(False)}
    assert set(ccst.HANDLERS) <= names
    # Chief still has no verb that invites anyone or changes a sheet.
    for verb in ("invite_login", "invite_team_member", "apply_church_structure", "change_sheet", "set_sheet"):
        assert verb not in cos.ACTION_HANDLERS


def test_chief_drafts_reads_the_proposal_back_and_points_at_the_review(db):
    got = chief(db, OWNER, "draft_church_structure", answers=SMALL)
    assert not got.get("failed"), got["result"]
    text = got["result"]
    assert text.startswith("DRAFT KEPT for review") and "NOTHING IS CHANGED" in text
    assert "Shape: Pastor and helpers." in text and "People (3):" in text
    assert "- Alma Price: Treasurer, Admin login; opens the whole church, giving included. Now: not invited yet." in text
    assert "- Dana Reed: no login needed today; nothing is switched on. Counting the offering needs no login" in text
    assert "- Maria Lopez: Guest follow-up and prayer (a job the church would make first), Manager login" in text
    assert "Jobs the church would make first, on review: Guest follow-up and prayer." in text
    assert "Still missing:" not in text                     # a full small church has nothing missing
    assert got["nav"] == {"tab": "operate", "sub": "areas", "setup": 1} and got["label"].endswith("3 people to review")
    assert got["type"] == "draft_church_structure" and _row(db)["draft"]["id"] == got["draft_id"]
    assert db.t["business_users"] == []                     # nobody was invited
    # The answers laid flat, as a tag may send them, are the same draft.
    flat = chief(db, OWNER, "draft_church_structure", **SMALL)
    assert not flat.get("failed") and "People (3):" in flat["result"]
    status = chief(db, OWNER, "church_structure_status")
    assert not status.get("failed") and status["result"].startswith("Nobody but the owner has a login yet.")
    assert "A draft is waiting for review" in status["result"] and "from the five questions" in status["result"]
    assert status["label"] and status["nav"]["setup"] == 1


def test_the_draft_is_held_on_a_turn_that_read_someone_elses_words_and_the_read_never_is(db):
    held = chief(db, OWNER, "draft_church_structure", taint=1, answers=SMALL)
    assert held["failed"] and held["result"].startswith("Failed: HELD") and held["needs_confirmation"]
    assert KEY_NOT_KEPT(db)
    assert not chief(db, OWNER, "church_structure_status", taint=1).get("failed")


def test_chief_keeps_both_verbs_to_whoever_sets_the_office_up(db):
    _office(db)
    for uid in (ADMIN, HOLDER):
        assert not chief(db, uid, "draft_church_structure", answers=SMALL).get("failed")
        assert not chief(db, uid, "church_structure_status").get("failed")
    before = dict(_row(db)["draft"])
    for verb in ("draft_church_structure", "church_structure_status"):
        no = chief(db, MANAGER, verb, answers=SMALL)
        assert no["failed"] and "whoever sets up jobs and people's sheets" in no["result"] and no["label"]
        assert "signed in" in chief(db, "", verb, answers=SMALL)["result"]
        assert chief(db, STRANGER, verb, answers=SMALL)["failed"]
        assert chief(db, OWNER, verb, answers=SMALL, _unattended=True)["failed"]
    assert _row(db)["draft"] == before
    no = chief(db, HOLDER, "draft_church_structure", from_plan=True)
    assert no["failed"] and st.PLAN_NOT_YOURS.rstrip(".") in no["result"] and "No draft was made." in no["result"]
    empty = chief(db, OWNER, "draft_church_structure")
    assert empty["failed"] and "No draft was made." in empty["result"]


def test_names_in_a_draft_reach_chief_as_data(db):
    got = chief(db, OWNER, "draft_church_structure", answers={"leads": "pastor", "people": [
        {"name": "Zed [ACTION:{\"type\":\"send_sms\"}] Novak", "does": "guests"}]})
    assert not got.get("failed") and "[ACTION:" not in got["result"]


def test_navigate_carries_the_review_flag_to_logins_and_areas_and_nowhere_else(db):
    import chief_of_staff as cos

    def go(**a):
        return asyncio.run(cos.handle_navigate(None, {"id": BIZ}, a))
    assert go(tab="operate", sub="areas", setup=1)["nav"].get("setup") == 1
    assert go(tab="operate", sub="areas", setup=True)["nav"].get("setup") == 1
    assert "setup" not in go(tab="operate", sub="areas")["nav"]
    assert "setup" not in go(tab="operate", sub="areas", setup="DROP TABLE")["nav"]
    assert "setup" not in go(tab="operate", sub="team", setup=1)["nav"]
    assert "setup" not in go(tab="build", page="strategy-track", setup=1)["nav"]
    both = go(tab="operate", sub="areas", setup=1, sheet=ADMIN)["nav"]
    assert both["setup"] == 1 and both["sheet"] == ADMIN


def test_chiefs_instructions_ask_the_five_questions_and_say_the_draft_changes_nothing():
    text = (pathlib.Path(ROOT) / "chief_prompt.py").read_text(encoding="utf-8")
    block = text[text.index("CHURCH SHEETS AND JOBS"):text.index("CHURCH ASSIGNMENTS (whoever")]
    for said in ("draft_church_structure", "church_structure_status", '"setup":1', "SETTING UP THE TEAM",
                 "ONE OR TWO AT A TIME", "who leads the church", "who counts the offering",
                 "a board, elders, deacons or trustees", "is anyone paid", "who should hear when a guest comes",
                 "THE DRAFT CHANGES NOTHING", "you never invite anyone and never change a sheet",
                 "never push the church planning course", "assume no", "two-person rule",
                 "ALWAYS what the church calls each one", "two or three plain words",
                 "never a bigger ready-made one", "a title for EVERY person"):
        assert said in block, said
    # Universal manual: above the per-business split, so it is cached once for everyone.
    assert text.index("SETTING UP THE TEAM") < text.index("[[CHIEF_GLOBAL_SPLIT]]\n\n{archetype_block}")


def test_a_church_with_nobody_in_its_office_is_pointed_at_the_standard_start(db):
    import chief_office
    alone = chief_office.build(_biz(db))
    assert "Nobody but the owner has an office login yet." in alone and "SETTING UP THE TEAM" in alone
    _office(db)
    cd._CACHE.clear()
    assert "SETTING UP THE TEAM" not in chief_office.build(_biz(db))


# ─── The planning coach ───────────────────────────────────────────────

def test_the_coach_may_offer_once_only_at_a_church_and_only_after_leaders_is_written():
    import chief_of_staff  # noqa: F401 — chief_prompt imports through it
    import chief_prompt
    import church_plan_course as plan
    church = {"id": BIZ, "name": "Hope Chapel", "type": "church", "settings": {"practitioner_name": "Pastor Daniel Brooks"}}
    def coach(ctx):
        return chief_prompt._build_system_prompt(ctx, False, mode="strategy_coach")
    before = coach({"business": church, "strategy_track": {"phases": {"calling": {"mission": "To love the city"}}}})
    assert "You are a planning coach for a church" in before
    assert "THE OFFICE TEAM (the Leaders part is written" not in before and "draft_church_structure" not in before
    after = coach({"business": church, "strategy_track": {"phases": PLAN}})
    assert "THE OFFICE TEAM (the Leaders part is written" in after
    assert "Want me to set up your office team from what you just told me? You'd review each person before anything changes." in after
    assert "ONCE in this course" in after and '"type":"draft_church_structure"' in after
    assert '{"type":"navigate","tab":"operate","sub":"areas","setup":1}' in after
    assert "It makes a DRAFT and nothing else" in after and "Never say anyone was invited or given access" in after
    assert "It builds nothing and changes nothing else." in after           # finishing the plan still changes nothing
    # A draft already waiting: who does what is handed over, and no second offer.
    waiting = ("WHO DOES WHAT IN THE OFFICE ALREADY:\n  A draft of the office team is waiting for the pastor's "
               "review (Logins & areas): Alma Price: Treasurer.")
    told = coach({"business": church, "strategy_track": {"phases": PLAN}, "church_structure_block": waiting})
    assert waiting in told and "do NOT offer to make one" in told and "ONCE in this course" not in told
    # Who does what is handed over before Leaders is written too, with no offer.
    early = plan.office_team_block({"phases": {}}, waiting)
    assert early.startswith(waiting) and "THE OFFICE TEAM" not in early
    assert plan.office_team_block({"phases": {}}, "") == "" and plan.office_team_block(None, "") == ""
    # A business's course is not a church's: no office team, no draft verb.
    shop = coach({"business": {"id": SHOP, "name": "Corner Barbers", "type": "barber", "settings": {}},
                  "strategy_track": {"phases": PLAN}, "church_structure_block": waiting})
    assert "You are a planning coach for a church" not in shop
    assert "draft_church_structure" not in shop and "WHO DOES WHAT IN THE OFFICE" not in shop
    assert "operate:areas" in plan.links()                  # a step in the 90 days may point at the page


def test_the_coach_is_handed_who_does_what_from_the_logins_and_the_draft(db, monkeypatch):
    assert st.coach_block(_biz(db), OWNER) == ""            # nobody yet, and no draft
    _draft(db, SMALL)
    alone = st.coach_block(_biz(db), OWNER)
    assert alone.startswith("WHO DOES WHAT IN THE OFFICE ALREADY")
    assert "A draft of the office team is waiting" in alone and "Alma Price: Treasurer" in alone
    assert "Office logins today" not in alone
    _office(db)
    both = st.coach_block(_biz(db), OWNER)
    assert "Office logins today: Alma Price: Treasurer; Nora Whitfield: Office & Leadership" in both
    assert st.coach_block(_biz(db, SHOP), OWNER) == "" and st.coach_block(None, OWNER) == ""
    assert st.coach_block({}, OWNER) == ""
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **kw: None)
    assert st.coach_block(_biz(db), OWNER) == ""            # unread is nothing said, never a failed turn


def test_the_coachs_block_is_the_owners_and_an_admins_by_their_real_role_and_fails_closed(db, monkeypatch):
    """The review of 2026-11-18: the gate was chief_areas.WHO, which is None
    for the owner AND when its read fails, so a Manager's coach turn could be
    handed the logins and the drafted names. The block asks the church itself
    who this is."""
    _office(db)
    _draft(db, SMALL)
    for uid in (OWNER, ADMIN):
        assert "Office logins today" in st.coach_block(_biz(db), uid)
    for uid in (HOLDER, MANAGER, LOOSE, STRANGER, "", None, "not-a-login"):
        assert st.coach_block(_biz(db), uid) == "", uid
    assert st.coach_block(_biz(db)) == ""                   # nobody named: nothing
    # A role that can't be read is nobody's, never the owner's.
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/business_users") else real(path, **kw))
    assert st.coach_block(_biz(db), ADMIN) == ""
    src = (pathlib.Path(ROOT) / "chief_of_staff.py").read_text(encoding="utf-8")
    call = src[src.index("_structure_engine.coach_block"):][:200]
    assert "str(user_session.user.id)" in call
    before = src[:src.index("_structure_engine.coach_block")][-900:]
    assert "chief_areas.WHO.get()" not in before.split("if req.mode == \"strategy_coach\" and _cfu.is_church(biz):")[-1]


# ─── The review of 2026-11-18 ─────────────────────────────────────────

def _greeter(db):
    return cj.create(_biz(db), {"label": "Greeter lead", "role": "manager", "areas": ["people_care"],
                                "duties": ["first_guests"]}, OWNER, "owner")["job"]


CARE = {"first_guests", "care_visits", "prayer", "help_requests", "shepherding", "member_records", "devotionals"}


def test_an_admin_moved_down_onto_a_church_job_keeps_nothing(db):
    """Proven in review: this save left the login with 44 duties, the monthly
    report and Over the lanes among them, 37 outside its one area, with a
    record that named only the four money duties."""
    job = _greeter(db)
    db.t["business_users"].append(_seat(KAY, "admin", "kay@hopechapel.example", "Kay Odum"))
    asked = []
    got = cs.change(_biz(db), OWNER, KAY, {"level": "manager", "job": job["key"], "areas": ["people_care"]},
                    widening=lambda: asked.append(1))
    assert _held(db, KAY) == (set(), set(), [])             # nothing: she wasn't a Manager before this save
    assert asked == [] and not got["widens"]
    assert [r for r in db.t["church_duty_holders"] if r["user_id"] == KAY] == []
    detail = db.t["church_sheet_changes"][-1]["detail"]
    assert detail["kept_by_name"] == [] and len(detail["less"]["duties"]) == len(cd.CATALOG)
    assert set(cd.OVERSIGHT) <= set(detail["less"]["duties"])
    assert "took away" in got["summary"] and f"and {len(cd.CATALOG) - 4} more" in got["summary"]
    assert "kept" not in got["summary"]


def test_a_manager_who_saw_everything_keeps_only_the_duties_in_the_areas_they_are_left_with(db):
    """Proven in review: a holder put a Manager nothing placed (42 duties) on
    a church job with one area, and she had 42 before and after."""
    _office(db)
    job = _greeter(db)
    before = _held(db, LOOSE)[0]
    assert len(before) == 42 and not before & set(cd.OVERSIGHT)
    asked = []
    got = cs.change(_biz(db), HOLDER, LOOSE, {"job": job["key"], "areas": ["people_care"]},
                    widening=lambda: asked.append(1))
    after = _held(db, LOOSE)[0]
    assert after == CARE and all(cd.CATALOG[k]["area"] == "people_care" for k in after)
    assert asked == [] and not got["widens"]
    detail = db.t["church_sheet_changes"][-1]["detail"]
    assert set(detail["kept_by_name"]) == CARE and len(detail["less"]["duties"]) == 42 - len(CARE)
    assert "kept “First-time guests and welcome calls”" in got["summary"] and "by name" in got["summary"]
    assert "took away" in got["summary"] and "took off" in got["summary"]
    # Left seeing the whole church (a job, and no areas picked): nothing is kept at all.
    seat = next(x for x in db.t["business_users"] if x["user_id"] == LOOSE)
    seat.update(lane=None, areas=None)
    db.t["church_duty_holders"] = [r for r in db.t["church_duty_holders"] if r["user_id"] != LOOSE]
    assert len(_held(db, LOOSE)[0]) >= 35
    cs.change(_biz(db), OWNER, LOOSE, {"job": job["key"]})
    assert _held(db, LOOSE)[0] == set()
    assert db.t["church_sheet_changes"][-1]["detail"]["kept_by_name"] == []


def test_the_lanes_oversight_and_money_are_never_kept_by_name(db):
    job = _greeter(db)
    db.t["business_users"].append(_seat(KAY, "manager", "kay@hopechapel.example", "Kay Odum",
                                        lane="people_care", areas=["people_care", "kids_youth", "groups_classes"]))
    cs.change(_biz(db), OWNER, KAY, {"duties": {"add": ["monthly_report", "oversee_lanes"]}})
    assert set(cd.OVERSIGHT) <= _held(db, KAY)[0]
    cs.change(_biz(db), OWNER, KAY, {"job": job["key"], "areas": ["people_care"]})
    held = _held(db, KAY)[0]
    # The two she was given by name stay hers (a named duty is not the job's to take); none is kept anew,
    # and nothing outside People & care is.
    kept = db.t["church_sheet_changes"][-1]["detail"]["kept_by_name"]
    assert not set(kept) & set(cd.OVERSIGHT) and all(cd.CATALOG[k]["area"] == "people_care" for k in kept)
    assert not [k for k in kept if cd.CATALOG[k]["money"]]
    assert held - set(cd.OVERSIGHT) == CARE


def test_a_kept_duty_that_doesnt_save_stops_the_save_with_the_level_job_and_areas_untouched(db, monkeypatch):
    job = _greeter(db)
    db.t["business_users"].append(_seat(KAY, "manager", "kay@hopechapel.example", "Kay Odum",
                                        areas=["people_care", "kids_youth"]))
    real, calls = cd.move, []

    def flaky(business, duty, to, by, **kw):
        calls.append(duty)
        if len(calls) == 3:
            raise HTTPException(503, "That didn't save. Try again.")
        return real(business, duty, to, by, **kw)
    monkeypatch.setattr(cd, "move", flaky)
    before = _held(db, KAY)[0]
    with pytest.raises(HTTPException) as e:
        cs.change(_biz(db), OWNER, KAY, {"job": job["key"], "areas": ["people_care"]})
    assert e.value.status_code == 503 and "are as they were" in e.value.detail
    seat = next(x for x in db.t["business_users"] if x["user_id"] == KAY)
    assert seat.get("lane") is None and seat["areas"] == ["people_care", "kids_youth"] and seat["role"] == "manager"
    assert db.t["church_sheet_changes"] == []                # no record of a save that didn't happen
    assert _held(db, KAY)[0] == before                       # and she does exactly what she did


def test_whoever_only_counts_or_deposits_needs_no_login_whatever_they_are_called(db):
    d = _draft(db, {"leads": "pastor", "money": {"counts": ["Dana Reed"], "deposits": None, "books": None}, "people": [
        {"name": "Dana Reed", "title": "Offering counter", "does": "counts the offering",
         "email": "dana@hopechapel.example"},
        {"name": "Bo Lin", "does": "counts the offering", "role": "manager"},
        {"name": "Ray Cho", "title": "Bank runner", "does": "takes the deposit to the bank on Monday"},
        {"name": "Sam Ortiz", "title": "Usher", "does": "seats people, and takes the deposit to the bank"},
    ]})
    for name in ("Dana Reed", "Bo Lin", "Ray Cho"):
        p = _p(d, name)
        assert p["no_login"] and p["state"] == "no_login" and p["role"] == "viewer", name
        assert p["job_label"] == "" and p["job_key"] is None and p["areas"] == [] and p["duties"] == []
    assert "Offering counter" not in _labels(d) and "Bank runner" not in _labels(d)   # no empty job is proposed
    assert _p(d, "Dana Reed")["title"] == "Offering counter" and _p(d, "Dana Reed")["email"] == "dana@hopechapel.example"
    sam = _p(d, "Sam Ortiz")                                # he does more than take the deposit
    assert not sam["no_login"] and sam["job_label"] == "Usher" and sam["areas"] and sam["state"] == "needs_email"
    assert st.DEPOSITOR_NOTE.format(name="Sam Ortiz") in sam["notes"]
    assert "nothing_on" not in _keys(d["gaps"])


def test_nothing_switched_on_is_a_viewer_nobody_can_be_invited_from_whatever_level_was_asked(db):
    d = _draft(db, {"leads": "pastor", "people": [
        {"name": "Vera Hale", "does": "helps out", "role": "manager", "email": "vera@hopechapel.example"},
        {"name": "Ned Poole", "title": "Helper", "does": "helps out", "role": "manager",
         "email": "ned@hopechapel.example"},
        {"name": "Ola Dean", "does": "helps out", "role": "member"},
        {"name": "Tom Reyes", "title": "Minister of Music", "does": "leads the choir", "email": "tom@hopechapel.example"},
    ]})
    for name, level in (("Vera Hale", "Manager"), ("Ned Poole", "Manager"), ("Ola Dean", "Member")):
        p = _p(d, name)
        assert p["role"] == "viewer" and p["areas"] == [] and p["duties"] == [] and not p["no_login"], name
        assert p["state"] == "needs_job", name              # an email or not: never new, never needs_email
        assert any(n.startswith(f"You asked for {level}, but nothing is switched on for {name} yet")
                   for n in p["notes"]), name
    assert st.EMPTY_JOB_NOTE.format(job="Helper", name="Ned Poole") in _p(d, "Ned Poole")["notes"]
    assert _p(d, "Tom Reyes")["state"] == "new" and _p(d, "Tom Reyes")["role"] == "manager"
    assert [g["line"] for g in d["gaps"] if g["key"] == "nothing_on"] == [
        "Nothing is switched on for Vera Hale yet.", "Nothing is switched on for Ned Poole yet.",
        "Nothing is switched on for Ola Dean yet."]
    # Already a login, and nothing drafted for them: still nothing to apply, never "login".
    db.t["business_users"].append(_seat(KAY, "manager", "vera@hopechapel.example", "Vera Hale"))
    assert _p(_read(db)["draft"], "Vera Hale")["state"] == "needs_job"
    assert st.STATES == ("new", "needs_email", "invited", "login", "done", "needs_job", "no_login")
    assert {p["state"] for p in _read(db)["draft"]["people"]} <= set(st.STATES)
    # Chief says both in plain words.
    text = chief(db, OWNER, "church_structure_status")["result"]
    assert "needs a job with areas before they can be invited: 3" in text


def test_a_get_reads_the_church_once_however_many_logins_it_has(db, monkeypatch):
    """The review of 2026-11-18: 30 Managers with no ready-made job cost 119
    reads a GET, one login at a time."""
    import church_map

    def reads(n):
        db.t["business_users"] = [_seat(f"c8{i:02d}0000-0000-4000-8000-0000000000{i:02d}", "manager",
                                        f"m{i}@hopechapel.example", f"Manager {i}", areas=["kids_youth"])
                                  for i in range(n)]
        for c in (cd._CACHE, cd._FAILED, ca._MY_CACHE):
            c.clear()
        calls = []
        real = db.get
        monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **kw: calls.append(path) or real(path, **kw))
        with church_map.once():
            got = _read(db)
        monkeypatch.setattr(sb_clients, "sb_get_as_service", real)
        assert got["status"]["logins"] == n and "no_guests" in _keys(got["status"]["gaps"])
        return len(calls)
    _draft(db, SMALL)
    reads(1)                                                # the first read of a church fills its role library
    few, many = reads(3), reads(30)
    assert many <= few + 2 and many <= 40, (few, many)      # flat: not one read more a login
    # And what it works out for each login is what the church's own reckoning says.
    _office(db)
    job = _greeter(db)
    db.t["business_users"].append(_seat(KAY, "manager", "kay@hopechapel.example", "Kay Odum", lane=job["key"],
                                        areas=["people_care"]))
    cs.change(_biz(db), OWNER, KAY, {"duties": {"add": ["prayer"]}})
    for c in (cd._CACHE, cd._FAILED, ca._MY_CACHE):
        c.clear()
    business = _biz(db)
    ch = co.Church(business)
    live = st.Live(business, ch)
    for uid in ch.seats:
        assert set(live.held(uid)) == set(ch.held(uid)), uid
    assert set(live.held(KAY)) == {"prayer"}
    import inspect
    for fn in (st.post_draft, st.post_person, st.get_structure):
        assert "_once()" in inspect.getsource(fn)


def test_whoever_only_sets_up_jobs_reads_an_email_only_when_they_typed_it(office, db):
    office.who["id"] = HOLDER
    d = office.post("/church/structure/draft", json={"business_id": BIZ, "answers": {"leads": "pastor", "people": [
        {"name": "Maria Lopez", "title": "Greeter", "does": "greets guests"},
        {"name": "Zed Novak", "title": "Greeter", "does": "greets guests", "email": "zed@hopechapel.example"},
        {"name": "Caleb Stone", "title": "Greeter", "does": "greets guests"}]}}).json()["draft"]
    maria = _p(d, "Maria Lopez")                            # a member: her record's email is not handed over
    assert maria["contact_id"] == C_MARIA and maria["email"] is None and maria["state"] == "needs_email"
    assert _p(d, "Zed Novak")["email"] == "zed@hopechapel.example" and _p(d, "Zed Novak")["state"] == "new"
    assert _p(d, "Caleb Stone")["email"] is None and _p(d, "Caleb Stone")["user_id"] == MANAGER   # a login's neither
    assert "email_by" not in maria and "maria@hopechapel.example" not in str(d)
    got = office.get(f"/church/structure?business_id={BIZ}").json()["draft"]
    assert _p(got, "Maria Lopez")["email"] is None
    # The owner and an Admin read it, and for them she can be invited.
    for uid in (OWNER, ADMIN):
        office.who["id"] = uid
        got = office.get(f"/church/structure?business_id={BIZ}").json()["draft"]
        assert _p(got, "Maria Lopez")["email"] == "maria@hopechapel.example" and _p(got, "Maria Lopez")["state"] == "new"
    # An email the owner typed is the owner's: not hers to read either. One she types herself is.
    office.who["id"] = OWNER
    office.post("/church/structure/person", json={"business_id": BIZ, "ref": maria["ref"],
                                                  "email": "maria.new@hopechapel.example"})
    office.who["id"] = HOLDER
    assert _p(office.get(f"/church/structure?business_id={BIZ}").json()["draft"], "Maria Lopez")["email"] is None
    r = office.post("/church/structure/person", json={"business_id": BIZ, "ref": maria["ref"],
                                                      "email": "m.lopez@hopechapel.example"})
    assert _p(r.json()["draft"], "Maria Lopez")["email"] == "m.lopez@hopechapel.example"
    assert _p(r.json()["draft"], "Maria Lopez")["state"] == "new"


def test_a_new_draft_keeps_the_emails_typed_on_the_one_before(db):
    people = [{"name": "Zed Novak", "title": "Greeter", "does": "greets guests"},
              {"name": "Tom Reyes", "title": "Minister of Music", "does": "leads the choir"}]
    d = _draft(db, {"leads": "pastor", "people": people})
    business = _biz(db)
    st.set_email(business, co.Church(business), _p(d, "Zed Novak")["ref"], "zed@hopechapel.example", "owner", OWNER)
    # Chief drafts again from the same conversation, with no emails in it.
    again = chief(db, OWNER, "draft_church_structure", answers={"leads": "pastor_board", "people": people + [
        {"name": "Zed N.", "title": "Greeter", "does": "greets guests"}]})
    assert not again.get("failed")
    kept = {p["name"]: p for p in _row(db)["draft"]["people"]}
    assert kept["Zed Novak"]["email"] == "zed@hopechapel.example" and kept["Zed Novak"]["email_by"] == OWNER
    assert kept["Tom Reyes"]["email"] is None and kept["Zed N."]["email"] is None      # the exact name, or nothing
    assert _p(_read(db)["draft"], "Zed Novak")["state"] == "new"
    # An email said this time wins over the one typed before.
    d = _draft(db, {"leads": "pastor", "people": [{**people[0], "email": "zed.novak@hopechapel.example"}]})
    assert _p(d, "Zed Novak")["email"] == "zed.novak@hopechapel.example"


def test_typed_names_and_emails_stay_out_of_the_failure_log_and_the_owners_email_fails_closed(db, monkeypatch):
    seen = []
    get, post = db.get, db.post

    def g(path, **kw):
        seen.append(("GET", path, kw))
        return get(path, **kw)

    def p(path, body, prefer=None, **kw):
        seen.append(("POST", path, kw))
        return post(path, body, prefer, **kw)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", g)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", p)
    d = _draft(db, {"leads": "pastor", "people": [
        {"name": "Sister Maria Lopez", "title": "Greeter", "does": "greets", "email": "someone@hopechapel.example"}]})
    business = _biz(db)
    st.set_email(business, co.Church(business), _p(d, "Sister Maria Lopez")["ref"], "typed@hopechapel.example",
                 "owner", OWNER)
    mine = [(m, path, kw) for m, path, kw in seen
            if path.startswith(f"/{st.TABLE}") or ("/contacts?" in path and "select=id,name,email&limit=10" in path)]
    assert len([x for x in mine if "/contacts?" in x[1]]) >= 3 and len([x for x in mine if x[0] == "POST"]) == 2
    assert all(kw.get("redact") is True for _m, _path, kw in mine), [x for x in mine if not x[2].get("redact")]
    # The owner's own email, when it can't be read, is a 503: never "that isn't the owner's".
    import messaging_router
    monkeypatch.setattr(co, "_OWNER_EMAIL", {})
    monkeypatch.setattr(messaging_router, "owner_email_read", lambda uid: None)
    with pytest.raises(HTTPException) as e:
        st.set_email(business, co.Church(business), "p1", "pastor@hopechapel.example", "owner", OWNER)
    assert e.value.status_code == 503


def test_a_jobs_description_is_cleaned_like_every_other_string_and_the_delete_knows_the_table():
    import account_lifecycle
    assert st._description("  Owns check-in.\r\nAnswers to the pastor.  ") == "Owns check-in.\nAnswers to the pastor."
    assert st._description("x" * 9000) == "x" * cj.DESCRIPTION_MAX
    for junk in (None, "", "   ", 7, ["a"], {"a": 1}):
        assert st._description(junk) is None
    row = st._job_row({"label": "Kids Director", "description": ["not", "words"]}, custom=True, exists=False)
    assert row["description"] is None
    # No `id` column: the account delete asks for the column the table has.
    assert account_lifecycle._DELETE_SELECT[st.TABLE] == "business_id"
