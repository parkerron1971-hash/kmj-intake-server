"""Shepherding, round 1 (church_families.py, church_shepherding.py, the
office routes in church_router, the shepherd's pages in member_portal_lead).

Kevin, 2026-10-17: "those that can shepherd are elders and pastors.
visitors should go under welcome for now"; Ministers off by default, 12
families per shepherd and 10 for the Lead Pastor, a monthly rhythm (canvas
31su6kdYmYecH5b2NxjBJN). Pins:
  · Chief's guess at families: the same last name, split by street; two
    last names at one street is a question; a member under 18 is a child;
    "Not a family" and anyone already in a family are left out;
  · accepting a family never makes a child a household adult (household
    adults may pick children up at the kiosk), and needs an adult;
  · who shepherds: the senior role and pastors/elders, Ministers only when
    switched on, never Deacons;
  · the proposal: someone who knows them, then close by, then even loads;
    never their own family; never over the cap (the Lead Pastor's is
    lower); the pastor's moves survive a new proposal; full means waiting;
  · approving writes every family (a member in no family becomes a family
    of one) and emails each shepherd once;
  · a shepherd sees only their own families, a child as a first name and
    age, never a child's care notes; logging a touch is theirs alone;
    "needs a pastor" emails the Lead Pastor and no other member; the
    owner's preview never writes."""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.dirname(os.path.abspath(__file__))):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_families as cf  # noqa: E402
import church_follow_up as cfu  # noqa: E402
import church_shepherding as shep  # noqa: E402
import member_portal_church as mpc  # noqa: E402
import member_portal_lead as mpl  # noqa: E402
import sb_clients  # noqa: E402
from test_church_follow_up import FakeDB  # noqa: E402

BIZ = "009e9a2c-3e81-4bfc-a92a-205a8806aa99"
OTHER = "11111111-1111-1111-1111-111111111111"
OWNER = "22222222-2222-2222-2222-222222222222"
TODAY = date.today()


def cid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


(KMJ, ANDRE, MARCUS, TANYA, ANGELA, REED, ROBERT, CALVIN, DANA, JAYLEN, AVA, BEN, BETH, PAUL, GRACE,
 TIA, SAM, VIC, GRANT_W, STRANGER) = (cid(i) for i in range(1, 21))
DAVIS = [cid(30 + i) for i in range(7)]


def born(years: int) -> str:
    return TODAY.replace(year=TODAY.year - years).isoformat() if not (TODAY.month == 2 and TODAY.day == 29) \
        else date(TODAY.year - years, 2, 28).isoformat()


def person(i, name, *, status="active", address="", birthdate=None, first="", last="", email="", phone="", biz=BIZ):
    meta = {"imported_from": "Subsplash"}
    if first or last:
        meta.update(first_name=first, last_name=last)
    if address:
        meta["address"] = address
    return {"id": i, "business_id": biz, "name": name, "status": status, "birthdate": birthdate, "metadata": meta,
            "email": email or f"{name.split()[0].lower()}@example.com", "phone": phone}


PEOPLE = [
    person(KMJ, "Kevin McCloud", address="100 Church St, Muskegon, MI 49442"),
    person(ANDRE, "Andre Mills", address="5 Lake Rd, Muskegon, MI 49444"),
    person(MARCUS, "Marcus Grant"),
    person(GRANT_W, "Wanda Grant"),
    person(TANYA, "Tanya Brooks"),
    person(ANGELA, "Angela Price"),
    person(REED, "Reed Owens"),
    person(ROBERT, "Robert Hayes"),
    person(CALVIN, "Calvin Carter", address="2948 Mason Blvd, Muskegon, MI 49444", first="Calvin", last="Carter",
           phone="(231) 555-0101"),
    person(DANA, "Dana Carter", address="2948 Mason Boulevard, Muskegon MI 49444", first="Dana", last="Carter"),
    person(JAYLEN, "Jaylen Carter", birthdate=born(9), first="Jaylen", last="Carter"),
    person(AVA, "Ava Carter", birthdate=born(6), first="Ava", last="carter"),
    person(BEN, "Ben Bennett"),
    person(BETH, "Beth BENNETT Jr."),
    person(PAUL, "Paul Johnson"),
    person(GRACE, "Grace Nguyen", address="77 Pine Ave, Muskegon, MI 49444"),
    person(TIA, "Tia Hayes", address="1241 West Norton Ave, Muskegon, MI 49441"),
    person(SAM, "Sam Collie", address="1241 W Norton Avenue"),
    person(VIC, "Vic Visitor", status="lead"),
    person(STRANGER, "Sam Other", biz=OTHER),
] + [person(d, f"D{n} Davis") for n, d in enumerate(DAVIS)]


def role_def(key, title, job, sort, reports=None):
    return {"id": str(uuid.uuid5(uuid.NAMESPACE_DNS, key)), "business_id": BIZ, "key": key, "title": title, "job": job,
            "definition": "", "covers": "church", "reports_to": str(uuid.uuid5(uuid.NAMESPACE_DNS, reports)) if reports else None,
            "oversees_teams": [], "handles": [], "sees": [], "term_months": None, "needs_class": None,
            "status": "active", "source": "catalog", "catalog_key": key, "sort": sort, "created_at": "2026-10-17"}


DEFS = [role_def("pastor", "Lead Pastor", "senior", 0),
        role_def("associate_pastor", "Associate Pastor", "pastoral", 1, "pastor"),
        role_def("elders", "Elders", "pastoral", 2, "associate_pastor"),
        role_def("ministers", "Ministers", "pastoral", 3, "pastor"),
        role_def("stewards", "Stewards", "pastoral", 4, "pastor"),
        role_def("deacons", "Deacons", "care", 5, "pastor"),
        role_def("welcome_lead", "Welcome Team lead", "welcome", 6, "associate_pastor")]


def holder(contact, role, status="active"):
    return {"id": str(uuid.uuid4()), "business_id": BIZ, "contact_id": contact, "role": role, "scope": "",
            "status": status, "invited_at": "2026-10-01T00:00:00+00:00", "answered_at": None}


class ShepDB(FakeDB):
    """FakeDB plus PostgREST upserts (on_conflict with merge or ignore)."""

    def post(self, path, body, prefer=None, **kw):
        table, _, qs = path.lstrip("/").partition("?")
        params = dict(x.partition("=")[::2] for x in qs.split("&") if x)
        if params.get("on_conflict"):
            cols = params["on_conflict"].split(",")
            for r in self.t.setdefault(table, []):
                if all(str(r.get(c)) == str(body.get(c)) for c in cols):
                    if "ignore-duplicates" in (prefer or ""):
                        return []
                    r.update(body)
                    self.writes.append(("UPSERT", table, body))
                    return [dict(r)]
        return super().post("/" + table, body, prefer)


@pytest.fixture
def db(monkeypatch):
    fake = ShepDB(
        contacts=PEOPLE,
        church_role_defs=DEFS,
        church_leader_roles=[holder(KMJ, "pastor"), holder(ANDRE, "associate_pastor"), holder(MARCUS, "elders"),
                             holder(TANYA, "elders"), holder(ANGELA, "ministers"), holder(REED, "deacons"),
                             holder(ROBERT, "welcome_lead"), holder(PAUL, "elders", status="invited")],
        households=[], household_adults=[], children=[], child_care_notes=[], church_family_dismissals=[],
        church_shepherd_settings=[], church_shepherds=[], church_shepherd_drafts=[], church_shepherd_touches=[],
        groups=[{"id": "g-men", "business_id": BIZ, "name": "Men of Valor", "active": True}],
        group_members=[{"group_id": "g-men", "business_id": BIZ, "contact_id": MARCUS, "role": "leader"},
                       {"group_id": "g-men", "business_id": BIZ, "contact_id": CALVIN, "role": "member"}],
        church_follow_ups=[],
        businesses=[{"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": OWNER}],
        business_sites=[{"business_id": BIZ, "slug": "love-city-church", "site_config": {"custom_domain": "lovecityc.com"}}],
    )
    for name in ("sb_get_as_service", "sb_post_as_service", "sb_patch_as_service", "sb_delete_as_service"):
        monkeypatch.setattr(sb_clients, name, getattr(fake, name.split("_")[1]))
    return fake


@pytest.fixture
def mail(monkeypatch):
    sent = []

    async def fake_email(biz, to_email, to_name, subject, body, key):
        sent.append({"to": to_email, "subject": subject, "body": body})
        return True
    monkeypatch.setattr(cfu, "_email", fake_email)
    return sent


BUSINESS = {"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": OWNER,
            "settings": {"timezone": "America/Detroit"}}


def _home(db, name, adults, kids=()):
    hid = str(uuid.uuid4())
    db.t["households"].append({"id": hid, "business_id": BIZ, "name": name, "created_at": "2026-10-01"})
    for a in adults:
        db.t["household_adults"].append({"household_id": hid, "contact_id": a, "business_id": BIZ, "relationship": "parent"})
    for k in kids:
        row = next(p for p in PEOPLE if p["id"] == k)
        db.t["children"].append({"id": str(uuid.uuid4()), "business_id": BIZ, "household_id": hid, "contact_id": k,
                                 "first_name": row["name"].split()[0], "last_name": "Carter",
                                 "birthdate": row["birthdate"], "active": True})
    return hid


def _by_name(data, name):
    return next(s for s in data["suggestions"] if s["name"] == name)


# ─── Chief's guess at families ───────────────────────────────────────

def test_chief_groups_by_last_name_and_street_and_knows_the_children(db):
    data = cf.suggestions(BIZ, TODAY)
    assert data["members"] == len([p for p in PEOPLE if p["status"] == "active" and p["business_id"] == BIZ])
    assert data["children"] == 2 and data["in_families"] == 0
    carters = _by_name(data, "The Carter family")
    assert carters["sure"] == "sure", "same last name and the same street, however it was written"
    assert "Same street: 2948 Mason Blvd" in carters["why"] and "2 children by birthdate" in carters["why"]
    kinds = {p["contact_id"]: (p["kind"], p["age"]) for p in carters["people"]}
    assert kinds[JAYLEN] == ("child", 9) and kinds[AVA] == ("child", 6) and kinds[CALVIN] == ("adult", None)
    assert _by_name(data, "The Bennett family")["sure"] == "likely", "Jr. dropped, case ignored"
    davis = _by_name(data, "The Davis family")
    assert davis["sure"] == "check" and davis["ask"].startswith("7 people share this last name")
    mixed = _by_name(data, "The Hayes and Collie family")
    assert mixed["sure"] == "check" and mixed["ask"] == "Two last names at one address. One family?"
    singles = {p["contact_id"] for p in data["singles"]}
    assert {PAUL, GRACE, KMJ}.issubset(singles) and VIC not in singles and STRANGER not in singles
    assert [s["sure"] for s in data["suggestions"]] == sorted((s["sure"] for s in data["suggestions"]),
                                                             key=lambda x: cf._RANK[x])


def test_a_last_name_at_two_streets_is_two_families(db):
    db.t["contacts"] = [dict(p) for p in PEOPLE] + [
        person(cid(90), "Lee Carter", address="9 Elm St, Muskegon, MI 49441"),
        person(cid(91), "Lou Carter", address="9 Elm Street"),
        person(cid(92), "Lyn Carter")]
    data = cf.suggestions(BIZ, TODAY)
    carters = [s for s in data["suggestions"] if s["name"] == "The Carter family" and s["sure"] == "sure"]
    assert len(carters) == 2 and {len(s["people"]) for s in carters} == {2}
    # Lyn has no address and Ava/Jaylen are children with none: one question, never a guess.
    loose = [s for s in data["suggestions"] if "two addresses" in s["ask"]]
    assert len(loose) == 1 and {p["contact_id"] for p in loose[0]["people"]} == {cid(92), JAYLEN, AVA}


def test_not_a_family_and_people_already_in_one_are_left_out(db):
    data = cf.suggestions(BIZ, TODAY)
    cf.dismiss(BIZ, _by_name(data, "The Bennett family")["key"])
    cf.dismiss(BIZ, _by_name(data, "The Bennett family")["key"])
    assert len(db.t["church_family_dismissals"]) == 1
    _home(db, "The Carter family", [CALVIN, DANA], [JAYLEN, AVA])
    again = cf.suggestions(BIZ, TODAY)
    names = [s["name"] for s in again["suggestions"]]
    assert "The Bennett family" not in names and "The Carter family" not in names
    assert {BEN, BETH}.issubset({p["contact_id"] for p in again["singles"]})
    assert again["in_families"] == 4
    with pytest.raises(HTTPException):
        cf.dismiss(BIZ, "not-a-key")


# ─── Accepting a family ──────────────────────────────────────────────

def test_accepting_makes_the_children_children_never_household_adults(db):
    out = cf.accept(BIZ, {"name": "The Carter family", "adults": [CALVIN, DANA], "children": [JAYLEN, AVA]}, today=TODAY)
    hid = out["household_id"]
    assert {a["contact_id"] for a in db.t["household_adults"] if a["household_id"] == hid} == {CALVIN, DANA}
    assert {a["relationship"] for a in db.t["household_adults"]} == {"parent"}
    kids = [k for k in db.t["children"] if k["household_id"] == hid]
    assert {(k["contact_id"], k["first_name"]) for k in kids} == {(JAYLEN, "Jaylen"), (AVA, "Ava")}
    assert all(k["last_name"] == "Carter" for k in kids)
    assert next(k for k in kids if k["contact_id"] == AVA)["birthdate"] == born(6)


def test_a_child_offered_as_an_adult_is_refused_and_nothing_is_saved(db):
    for body, word in (({"name": "X", "adults": [JAYLEN], "children": []}, "under 18"),
                       ({"name": "X", "adults": [], "children": [JAYLEN]}, "at least one adult"),
                       ({"name": "X", "adults": [CALVIN], "children": [DANA]}, "18 or older"),
                       ({"name": "X", "adults": [VIC], "children": []}, "isn't a member"),
                       ({"name": "X", "adults": [STRANGER], "children": []}, "isn't a member"),
                       ({"name": " ", "adults": [CALVIN], "children": []}, "name")):
        with pytest.raises(HTTPException) as e:
            cf.accept(BIZ, body, today=TODAY)
        assert e.value.status_code == 400 and word in e.value.detail
    assert db.t["households"] == [] and db.t["household_adults"] == [] and db.t["children"] == []
    cf.accept(BIZ, {"name": "The Carters", "adults": [CALVIN], "children": []}, today=TODAY)
    with pytest.raises(HTTPException) as e:
        cf.accept(BIZ, {"name": "Again", "adults": [CALVIN], "children": []}, today=TODAY)
    assert e.value.status_code == 409 and "already in a family" in e.value.detail
    assert db.t["household_adults"][0]["relationship"] == "other", "no children: not 'parent'"


def test_accept_the_ones_chief_is_sure_of(db):
    assert cf.accept_sure(BIZ, today=TODAY) == 1
    assert [h["name"] for h in db.t["households"]] == ["The Carter family"]
    assert len(db.t["children"]) == 2 and {a["contact_id"] for a in db.t["household_adults"]} == {CALVIN, DANA}


# ─── Who shepherds ───────────────────────────────────────────────────

def test_pastors_and_elders_shepherd_ministers_only_when_switched_on(db):
    st = dict(shep.DEFAULTS)
    rows = {r["def"]["key"]: r for r in shep.role_rows(DEFS, st)}
    assert set(rows) == {"pastor", "associate_pastor", "elders", "ministers", "stewards"}, "never deacons or welcome"
    assert [k for k, r in rows.items() if r["shepherds"]] == ["pastor", "associate_pastor", "elders"]
    assert rows["ministers"]["switch"] == "ministers" and rows["pastor"]["lead"]
    st["ministers"] = True
    assert shep.role_rows(DEFS, st)[3]["shepherds"] is True
    ctx = shep.load(BIZ)
    assert list(ctx["shepherds"]) == [KMJ, ANDRE, MARCUS, TANYA], "the Lead Pastor first; the invited elder not yet"
    assert ctx["shepherds"][KMJ]["cap"] == 10 and ctx["shepherds"][MARCUS]["cap"] == 12


def test_settings_default_and_are_checked(db):
    assert shep.settings(BIZ) == {"ministers": False, "cap": 12, "lead_cap": 10, "rhythm_days": 30}
    with pytest.raises(HTTPException):
        shep.save_settings(BIZ, {"cap": 0}, OWNER)
    assert shep.save_settings(BIZ, {"ministers": True, "cap": 8}, OWNER)["cap"] == 8
    shep.save_settings(BIZ, {"lead_cap": 4}, OWNER)
    assert len(db.t["church_shepherd_settings"]) == 1 and shep.settings(BIZ)["ministers"] is True


# ─── The proposal ────────────────────────────────────────────────────

def _setup_families(db):
    carters = _home(db, "The Carter family", [CALVIN, DANA], [JAYLEN, AVA])
    grants = _home(db, "The Grant family", [MARCUS, GRANT_W])
    return carters, grants


def _rows(view):
    return {r["name"]: r for r in view["proposal"]["rows"]}


def test_knows_them_then_close_by_then_even_and_never_their_own(db):
    carters, grants = _setup_families(db)
    view = shep.propose(BUSINESS, OWNER)
    rows = _rows(view)
    assert rows["The Carter family"]["shepherd_contact_id"] == MARCUS
    assert rows["The Carter family"]["reason"] == "knows"
    assert rows["The Carter family"]["why"] == "Leads Men of Valor, which Calvin is in"
    assert rows["Grace Nguyen"]["shepherd_contact_id"] == ANDRE and rows["Grace Nguyen"]["why"] == "Same part of town (49444)"
    assert rows["The Grant family"]["shepherd_contact_id"] not in (MARCUS, None), "an elder's own family goes elsewhere"
    assert rows["Kevin McCloud"]["shepherd_contact_id"] not in (KMJ, None)
    assert {r["reason"] for r in view["proposal"]["rows"]} <= {"knows", "close", "even"}
    loads = {s["contact_id"]: s["count"] for s in view["proposal"]["shepherds"]}
    assert max(loads.values()) - min(loads.values()) <= 2, loads
    assert "Jaylen Carter" not in rows and "Ava Carter" not in rows, "children are never shepherded on their own"
    assert "Vic Visitor" not in rows, "visitors stay with Welcome"
    assert db.t["church_shepherds"] == [], "nothing is written before approval"


def test_never_over_the_cap_the_lead_pastors_lower_and_full_means_waiting(db):
    shep.save_settings(BIZ, {"cap": 2, "lead_cap": 1}, OWNER)
    view = shep.propose(BUSINESS, OWNER)["proposal"]
    loads = {s["contact_id"]: s["count"] for s in view["shepherds"]}
    assert loads[KMJ] == 1 and all(loads[s] == 2 for s in (ANDRE, MARCUS, TANYA))
    waiting = [r for r in view["rows"] if not r["shepherd_contact_id"]]
    assert view["waiting"] == len(waiting) > 0 and waiting[0]["why"] == "No shepherd has room"
    assert view["over"] == []


def test_the_pastors_moves_survive_a_new_proposal_and_own_family_is_refused(db):
    carters, grants = _setup_families(db)
    shep.propose(BUSINESS, OWNER)
    view = shep.move_in_draft(BUSINESS, f"h:{carters}", TANYA, OWNER)
    assert _rows(view)["The Carter family"] == {**_rows(view)["The Carter family"], "shepherd_contact_id": TANYA,
                                                 "reason": "moved", "why": "You chose", "moved": True}
    with pytest.raises(HTTPException) as e:
        shep.move_in_draft(BUSINESS, f"h:{grants}", MARCUS, OWNER)
    assert "Marcus's own family" in e.value.detail
    with pytest.raises(HTTPException):
        shep.move_in_draft(BUSINESS, f"h:{grants}", REED, OWNER)   # a deacon doesn't shepherd
    again = shep.propose(BUSINESS, OWNER)
    assert _rows(again)["The Carter family"]["shepherd_contact_id"] == TANYA and _rows(again)["The Carter family"]["moved"]
    assert shep.proposal(BUSINESS)["proposal"]["made_at"] == again["proposal"]["made_at"]
    shep.discard(BUSINESS)
    assert shep.proposal(BUSINESS) == {"proposal": None}


def test_over_the_cap_by_the_pastors_choice_is_shown(db):
    shep.save_settings(BIZ, {"lead_cap": 1}, OWNER)
    view = shep.propose(BUSINESS, OWNER)["proposal"]
    extra = next(r for r in view["rows"] if r["shepherd_contact_id"] not in (KMJ, None) and r["name"] != "Kevin McCloud")
    view = shep.move_in_draft(BUSINESS, extra["unit"], KMJ, OWNER)["proposal"]
    assert view["over"] == [{"contact_id": KMJ, "name": "Kevin McCloud", "count": 2, "cap": 1}]


# ─── Approving ───────────────────────────────────────────────────────

def test_approving_writes_every_family_and_emails_each_shepherd_once(db, mail):
    carters, _ = _setup_families(db)
    shep.propose(BUSINESS, OWNER)
    out = shep.approve(BUSINESS, OWNER)
    told = asyncio.run(shep.tell_shepherds(BUSINESS, out["gained"], out["ctx"], "stamp"))
    assert out["failed"] == 0 and out["placed"] == len(db.t["church_shepherds"]) > 0
    assert db.t["church_shepherd_drafts"] == []
    # A member in no family became a family of one, with them as its adult.
    paul_home = next(h for h in db.t["households"] if h["name"] == "Paul Johnson")
    assert [a["contact_id"] for a in db.t["household_adults"] if a["household_id"] == paul_home["id"]] == [PAUL]
    assert any(s["household_id"] == paul_home["id"] for s in db.t["church_shepherds"])
    assert told == len(mail) == len({m["to"] for m in mail}) == len(out["gained"])
    marcus = next(m for m in mail if m["to"] == "marcus@example.com")
    assert "Kevin McCloud asked you to shepherd" in marcus["subject"]
    assert "https://lovecityc.com/my/lead/families" in marcus["body"] and "never shown to you" in marcus["body"]
    assert "Sunday" not in marcus["body"], "round 1 promises nothing about missed Sundays"
    after = shep.overview(BUSINESS)
    assert after["counts"]["waiting"] == 0 and after["counts"]["placed"] == out["placed"]
    assert after["families_empty"] is False and after["draft"] is None
    with pytest.raises(HTTPException):
        shep.approve(BUSINESS, OWNER)


def test_moving_a_family_after_approval_tells_the_new_shepherd(db, mail):
    carters, grants = _setup_families(db)
    shep.propose(BUSINESS, OWNER)
    shep.approve(BUSINESS, OWNER)
    out = shep.move(BUSINESS, carters, TANYA, OWNER)
    assert out["changed"] and asyncio.run(shep.tell_new_shepherd(BUSINESS, out["shepherd"], out["name"], out["ctx"]))
    assert mail[-1]["to"] == "tanya@example.com" and mail[-1]["subject"] == "Kevin McCloud asked you to shepherd the Carter family"
    assert next(s for s in db.t["church_shepherds"] if s["household_id"] == carters)["shepherd_contact_id"] == TANYA
    assert len([s for s in db.t["church_shepherds"] if s["household_id"] == carters]) == 1
    with pytest.raises(HTTPException):
        shep.move(BUSINESS, grants, MARCUS, OWNER)
    shep.move(BUSINESS, carters, None, OWNER)
    assert not [s for s in db.t["church_shepherds"] if s["household_id"] == carters]


def test_the_overview_counts_and_the_start_here_card(db):
    out = shep.overview(BUSINESS)
    assert out["families_empty"] is True and out["counts"]["households"] == 0
    assert out["counts"]["visitors"] == 1 and out["welcome"] == {"title": "Welcome Team lead", "names": ["Robert Hayes"]}
    assert out["care_titles"] == ["Deacons"]
    assert [r["key"] for r in out["roles"] if r["shepherds"]] == ["pastor", "associate_pastor", "elders"]
    assert out["counts"]["waiting"] == out["counts"]["units"] == len(out["waiting"])
    assert {s["contact_id"] for s in out["shepherds"]} == {KMJ, ANDRE, MARCUS, TANYA}


# ─── The office routes ───────────────────────────────────────────────

def test_only_the_office_reads_and_approves(db, mail, monkeypatch):
    import business_access as ba
    import church_router
    app = FastAPI()
    app.include_router(church_router.router)
    role = {"r": "manager"}
    monkeypatch.setattr(ba, "_resolve_role", lambda b, u: role["r"])
    monkeypatch.setattr(ba.billing_context, "set_current", lambda b: None)
    user = SimpleNamespace(user=SimpleNamespace(id=OWNER, user_metadata={}, email="kevin@example.com"))
    app.dependency_overrides[sb_clients.authed_request] = lambda: user
    t = TestClient(app)
    q = {"business_id": BIZ}
    assert t.get("/church/families/suggestions", params=q).json()["members"] > 0
    made = t.post("/church/families/accept", params=q, json={"name": "The Carter family", "adults": [CALVIN, DANA],
                                                             "children": [JAYLEN, AVA]})
    assert made.status_code == 200 and made.json()["ok"]
    assert t.get("/church/shepherding", params=q).json()["families_empty"] is False
    assert t.put("/church/shepherding/settings", params=q, json={"cap": 99}).status_code == 422
    assert t.post("/church/shepherding/propose", params=q).json()["proposal"]["rows"]
    done = t.post("/church/shepherding/approve", params=q).json()
    assert done["ok"] and done["placed"] > 0 and done["told"] == len(mail)
    hid = made.json()["household_id"]
    fam = t.get(f"/church/shepherding/family/{hid}", params=q).json()
    assert fam["name"] == "The Carter family" and {p["name"] for p in fam["people"]} >= {"Jaylen", "Calvin Carter"}
    role["r"] = "member"
    for call in (t.get("/church/shepherding", params=q), t.get("/church/families/suggestions", params=q),
                 t.post("/church/shepherding/approve", params=q)):
        assert call.status_code == 404


# ─── The shepherd's Lead tab ─────────────────────────────────────────

def _me(c):
    return next({"id": p["id"], "name": p["name"]} for p in PEOPLE if p["id"] == c)


@pytest.fixture
def shell(monkeypatch):
    import member_portal
    seen = {}

    def fake_shell(biz, site, title, body, **kw):
        seen.update(kw, title=title)
        return body
    monkeypatch.setattr(member_portal, "_shell", fake_shell)
    return seen


def _req(**q):
    return SimpleNamespace(query_params=q)


def _given(db):
    carters, grants = _setup_families(db)
    db.t["church_shepherds"] = [{"household_id": carters, "business_id": BIZ, "shepherd_contact_id": MARCUS,
                                 "assigned_at": "2026-10-01T12:00:00+00:00", "reason": ""}]
    kid = next(k for k in db.t["children"] if k["contact_id"] == JAYLEN)
    db.t["child_care_notes"].append({"child_id": kid["id"], "business_id": BIZ, "allergies": "PEANUTS",
                                     "medical": "INHALER", "custody": "NEVER RELEASE"})
    return carters


def test_a_shepherd_sees_their_families_the_unreached_first(db, shell):
    carters = _given(db)
    other = _home(db, "The Bennett family", [BEN, BETH])
    db.t["church_shepherds"].append({"household_id": other, "business_id": BIZ, "shepherd_contact_id": MARCUS,
                                     "assigned_at": "2026-10-01T12:00:00+00:00", "reason": ""})
    db.t["church_shepherd_touches"].append({"id": "t1", "business_id": BIZ, "household_id": other,
                                            "shepherd_contact_id": MARCUS, "kind": "call", "note": "",
                                            "needs_pastor": False, "created_at": cfu._iso(cfu._now() - timedelta(days=2))})
    html, status = asyncio.run(mpl.serve(_req(), BUSINESS, {}, _me(MARCUS), "/my/lead/families"))
    assert status == 200 and "Your families" in html
    assert html.index("The Carter family") < html.index("The Bennett family"), "never reached first"
    assert "Not reached yet" in html and "Reached in the last 30 days" in html and "1 of 2" in html
    assert "Kevin McCloud can read your notes" in html or "Andre Mills" in html
    people, _ = asyncio.run(mpl.serve(_req(), BUSINESS, {}, _me(MARCUS), "/my/lead"))
    assert "Families · 2" in people and 'href="/my/lead/families"' in people
    tanya, _ = asyncio.run(mpl.serve(_req(), BUSINESS, {}, _me(TANYA), "/my/lead/families"))
    assert "The Carter family" not in tanya


def test_one_family_shows_children_by_first_name_and_age_and_never_care_notes(db, shell):
    carters = _given(db)
    html, status = asyncio.run(mpl.serve(_req(), BUSINESS, {}, _me(MARCUS), f"/my/lead/family/{carters}"))
    assert status == 200 and shell["back"] == ("/my/lead/families", "Your families")
    assert "Calvin Carter" in html and "Child · 9" in html and "Jaylen" in html and "Jaylen Carter" not in html
    for secret in ("PEANUTS", "INHALER", "NEVER RELEASE"):
        assert secret not in html
    assert 'action="/my/lead/family/' + carters + '/touch"' in html and 'name="needs_pastor"' in html
    assert "goes to Kevin McCloud at once" in html and 'href="tel:2315550101"' in html
    other, status = asyncio.run(mpl.serve(_req(), BUSINESS, {}, _me(TANYA), f"/my/lead/family/{carters}"))
    assert status == 404 and "Calvin" not in other


@pytest.fixture
def lead(db, monkeypatch):
    who = {"me": _me(MARCUS), "unavailable": False}

    async def signed_in(request):
        return {"business": BUSINESS, "site": {}}, who["me"], who["unavailable"]
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda *a: True)
    app = FastAPI()
    app.include_router(mpl.router)
    c = TestClient(app)
    c.who = who
    return c


def _touch(c, hid, **data):
    return c.post(f"/my/lead/family/{hid}/touch", data=data, follow_redirects=False)


def test_logging_a_touch_and_asking_for_a_pastor(lead, db, mail):
    carters = _given(db)
    r = _touch(lead, carters, kind="visit", note="Calvin's job moved to Sundays.", needs_pastor="yes")
    assert r.headers["location"] == f"/my/lead/family/{carters}?done=pastor"
    t = db.t["church_shepherd_touches"][-1]
    assert (t["kind"], t["shepherd_contact_id"], t["needs_pastor"]) == ("visit", MARCUS, True)
    assert [m["to"] for m in mail] == ["kevin@example.com"], "the Lead Pastor only, never another member"
    assert "Marcus Grant asked for a pastor for the Carter family" == mail[0]["subject"]
    stamped = {p["id"] for p in db.t["contacts"] if p.get("last_interaction")}
    assert stamped == {CALVIN, DANA}
    r = _touch(lead, carters, kind="call")
    assert r.headers["location"] == f"/my/lead/family/{carters}?done=touched" and len(mail) == 1


def test_only_the_familys_shepherd_can_log_and_the_preview_never_writes(lead, db, mail):
    carters = _given(db)
    lead.who["me"] = _me(TANYA)
    assert _touch(lead, carters, kind="call").headers["location"] == "/my/lead/families?err=family_gone"
    lead.who["me"] = _me(CALVIN)                     # a member who leads nothing
    assert _touch(lead, carters, kind="call").headers["location"] == "/my/lead"
    lead.who.update(me=None, unavailable="preview")
    assert _touch(lead, carters, kind="call").headers["location"] == f"/my/lead/family/{carters}?err=preview"
    lead.who.update(me=_me(MARCUS), unavailable=False)
    assert _touch(lead, carters, kind="email").headers["location"] == f"/my/lead/family/{carters}?err=error"
    assert db.t["church_shepherd_touches"] == [] and mail == []


def test_a_redirect_never_leaves_the_lead_pages():
    assert mpl._go("/my/lead/families").headers["location"] == "/my/lead/families"
    fid = str(uuid.uuid4())
    assert mpl._go(f"/my/lead/family/{fid}").headers["location"] == f"/my/lead/family/{fid}"
    assert mpl._go("/my/lead/family/../../evil").headers["location"] == "/my/lead"
