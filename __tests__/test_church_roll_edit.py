"""Changing the roll (church_roll_edit.py). Kevin, 2026-11-20: "the ability
to edited names and enter new people is off", "build and push to churches
as well", and: a number with no name stays in its own list until it has a
profile, and members are recognized as members and not lost. Pins:
  · a person's page edits in place: name as first / last / goes by (the
    roll files them by the new last name at once), status in church words
    (Member is confirmed by the office; Inactive keeps its reason), every
    About line, a child's grade and allergies, and their family;
  · naming a number makes them a guest, never a member;
  · adding one person or a whole family, children in it with their care
    notes, and "use that record" for someone already there;
  · merging keeps everything: their texts, notes and Sundays move, the
    number becomes the kept record's mobile, and the other record is kept,
    hidden, never deleted;
  · Tidy up finds numbers with no name, names in small letters, records
    holding two people, people on twice and members with no reason on file,
    and each fix does what it says;
  · the gate is the roll's, and CHURCH_ROLL_EDIT off makes the page
    read-only."""
from __future__ import annotations

import os
import sys
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.dirname(os.path.abspath(__file__))):
    if p not in sys.path:
        sys.path.insert(0, p)

import business_access as ba  # noqa: E402
import church_keys  # noqa: E402
import church_roll as cr  # noqa: E402
import church_roll_edit as cre  # noqa: E402
import sb_clients  # noqa: E402
from test_church_roll import (  # noqa: E402,F401
    BIZ, CALVIN, DANA, OWNER, OWNER_EMAIL, VIC, _every_sunday, _p, _roll, clock, db)

NUMBER = "33333333-0000-0000-0000-000000000001"
SHOUT = "33333333-0000-0000-0000-000000000002"
TWO = "33333333-0000-0000-0000-000000000003"
TWICE = "33333333-0000-0000-0000-000000000004"
LOOSE = "33333333-0000-0000-0000-000000000005"
Q = {"business_id": BIZ}


def _add(db, cid, name, *, status="active", phone="", email="", meta=None, source=""):
    db.t["contacts"].append({"id": cid, "business_id": BIZ, "name": name, "status": status, "phone": phone,
                             "email": email, "birthdate": None, "tags": [], "metadata": meta or {}, "source": source,
                             "created_at": "2026-10-01T12:00:00+00:00"})


def _c(db, cid):
    return next(c for c in db.t["contacts"] if c["id"] == cid)


@pytest.fixture
def church(db, monkeypatch):
    monkeypatch.setenv("CHURCH_ROLL_EDIT", "on")
    monkeypatch.setattr(church_keys, "is_open", lambda b, u, area: True)
    import business_collaborators_router as bcr
    monkeypatch.setattr(bcr, "is_active_accountant", lambda b, u: False)
    for t in ("child_care_notes", "agent_queue", "serve_assignments", "church_pledges"):
        db.t.setdefault(t, [])
    _add(db, NUMBER, "+15550142290", status="active", phone="+15550142290")
    db.t["sms_messages"] += [
        {"id": "s1", "business_id": BIZ, "contact_id": NUMBER, "direction": "inbound", "message": "DAILY",
         "status": "received", "created_at": "2026-10-20T12:00:00+00:00"},
        {"id": "s2", "business_id": BIZ, "contact_id": NUMBER, "direction": "inbound", "message": "Thanks! - Renee",
         "status": "received", "created_at": "2026-10-21T12:00:00+00:00"}]
    _add(db, SHOUT, "keisha o'neal mcallister", meta={"imported_from": "Subsplash"})
    _add(db, TWO, "Liyah And Meyah Tornes", status="lead")
    _add(db, LOOSE, "Ruth Loose", status="active")                       # a member with no reason on file
    _every_sunday(db, lambda d: [CALVIN])
    return db


def _client(monkeypatch, role="manager", email=OWNER_EMAIL):
    app = FastAPI()
    app.include_router(cr.router)
    app.include_router(cre.router)
    monkeypatch.setattr(ba, "_resolve_role", lambda b, u: role)
    monkeypatch.setattr(ba.billing_context, "set_current", lambda b: None)
    user = SimpleNamespace(user=SimpleNamespace(id=OWNER, user_metadata={}, email=email))
    app.dependency_overrides[sb_clients.authed_request] = lambda: user
    return TestClient(app)


# ─── names ────────────────────────────────────────────────────────────

def test_capitals_and_two_in_one_and_a_guess_from_the_texts():
    assert cre.cased("keisha o'neal mcallister") == "Keisha O'Neal McAllister"
    assert cre.cased("maria de la cruz") == "Maria de la Cruz"
    assert cre.cased("Diane clayta- trigge") == "Diane Clayta- Trigge"
    assert cre.cased("JOHN SMITH JR") == "John Smith Jr"
    assert cre.cased("DeShawn LaToya Price") == "DeShawn LaToya Price"     # already capitalised: as typed
    assert not cre.needs_case("+15550142290") and not cre.needs_case("Ruth Loose")
    assert cre.split_two("Liyah And Meyah Tornes") == ("Liyah Tornes", "Meyah Tornes")
    assert cre.split_two("Mia & Leo Santos") == ("Mia Santos", "Leo Santos")
    assert cre.split_two("Elevation of Grace") is None
    assert cre.guess_name(["DAILY", "Thanks! - Renee"]) == "Renee"
    assert cre.guess_name(["hi this is marcus from the 9am"]) == "Marcus"
    assert cre.guess_name(["I'm coming sunday"]) == ""
    assert cr.is_number("+1 (555) 014-2290") and not cr.is_number("Room 12")


# ─── the person's page ────────────────────────────────────────────────

def test_the_page_says_what_it_edits_and_the_switch_makes_it_read_only(church, monkeypatch):
    t = _client(monkeypatch)
    page = t.get(f"/church/roll/person/{CALVIN}", params=Q).json()
    assert page["can_edit"] is True
    e = page["edit"]
    assert (e["first"], e["last"], e["status"], e["noname"]) == ("Calvin", "Carter", "member", False)
    assert e["address"].startswith("2948 Mason Blvd") and e["confirmed"] is True   # came over in an import
    monkeypatch.setenv("CHURCH_ROLL_EDIT", "off")
    page = t.get(f"/church/roll/person/{CALVIN}", params=Q).json()
    assert page["can_edit"] is False and "edit" not in page
    assert t.patch(f"/church/roll/person/{CALVIN}", params=Q, json={"first": "Cal"}).status_code == 404
    assert "tidy" not in t.get("/church/roll", params=Q).json()


def test_a_name_saves_as_first_last_and_goes_by_and_the_roll_files_it_at_once(church, monkeypatch):
    t = _client(monkeypatch)
    r = t.patch(f"/church/roll/person/{CALVIN}", params=Q, json={"first": "Cal", "last": "Whitfield", "goes_by": "CJ"})
    assert r.status_code == 200 and r.json()["saved"] == ["name", "goes_by"]
    c = _c(church, CALVIN)
    assert c["name"] == "Cal Whitfield" and c["metadata"]["last_name"] == "Whitfield" and c["metadata"]["goes_by"] == "CJ"
    roll = t.get("/church/roll", params=Q).json()
    assert _p(roll, CALVIN)["last"] == "Whitfield"
    page = t.get(f"/church/roll/person/{CALVIN}", params={**Q, "fresh": 1}).json()
    assert page["name"] == "Cal Whitfield" and page["edit"]["goes_by"] == "CJ"
    assert t.patch(f"/church/roll/person/{CALVIN}", params=Q, json={"first": "  "}).status_code == 400
    assert any(e["event_type"] == "contact_edited" and e["contact_id"] == CALVIN for e in church.t["events"])


def test_naming_a_number_makes_a_guest_never_a_member(church, monkeypatch):
    t = _client(monkeypatch)
    page = t.get(f"/church/roll/person/{NUMBER}", params=Q).json()
    assert page["edit"]["noname"] is True and page["edit"]["guess"] == "Renee"
    assert page["edit"]["said"]["t"] == "DAILY"
    assert "nobody has put a name to it" in page["chief"]["text"]
    assert t.patch(f"/church/roll/person/{NUMBER}", params=Q, json={"first": "Renee", "last": "Jackson"}).status_code == 200
    c = _c(church, NUMBER)
    assert c["name"] == "Renee Jackson" and c["status"] == "lead"


def test_status_in_church_words_member_is_confirmed_and_inactive_keeps_why(church, monkeypatch):
    t = _client(monkeypatch)
    assert t.patch(f"/church/roll/person/{VIC}", params=Q, json={"status": "member"}).status_code == 200
    v = _c(church, VIC)
    assert v["status"] == "active" and v["metadata"]["member_confirmed"]["by"] == OWNER
    assert t.patch(f"/church/roll/person/{VIC}", params=Q, json={"status": "inactive", "inactive_reason": "Moved away"}).status_code == 200
    v = _c(church, VIC)
    assert v["status"] == "inactive" and v["metadata"]["inactive_reason"] == "Moved away"
    assert any(e["event_type"] == "contact_status_changed" and e["data"].get("reason") == "Moved away" for e in church.t["events"])
    assert t.patch(f"/church/roll/person/{VIC}", params=Q, json={"status": "lead"}).status_code == 400


def test_every_about_line_saves_and_bad_input_is_refused(church, monkeypatch):
    t = _client(monkeypatch)
    body = {"mobile": "(555) 201-4478", "email": "cal@example.com", "birthday": "1984-04-14", "address": "1418 Willow Bend Dr",
            "gender": "man", "marital": "married", "anniversary": "2007-06-09", "emergency": "Dana · (555) 201-4479"}
    assert t.patch(f"/church/roll/person/{CALVIN}", params=Q, json=body).status_code == 200
    c = _c(church, CALVIN)
    assert c["phone"] == "(555) 201-4478" and c["email"] == "cal@example.com" and c["birthdate"] == "1984-04-14"
    assert c["metadata"]["address"] == "1418 Willow Bend Dr" and c["metadata"]["marital_status"] == "married"
    e = t.get(f"/church/roll/person/{CALVIN}", params={**Q, "fresh": 1}).json()["edit"]
    assert (e["gender"], e["anniversary"], e["emergency"]) == ("man", "2007-06-09", "Dana · (555) 201-4479")
    assert t.patch(f"/church/roll/person/{CALVIN}", params=Q, json={"email": "nope"}).status_code == 400
    assert t.patch(f"/church/roll/person/{CALVIN}", params=Q, json={"birthday": "14/04/1984"}).status_code == 400
    assert t.patch(f"/church/roll/person/{CALVIN}", params=Q, json={"mobile": "12"}).status_code == 400
    assert t.patch(f"/church/roll/person/{CALVIN}", params=Q, json={"birthday": ""}).status_code == 200
    assert _c(church, CALVIN)["birthdate"] is None


def test_a_family_from_the_page_start_join_and_leave(church, monkeypatch):
    t = _client(monkeypatch)
    assert t.patch(f"/church/roll/person/{CALVIN}", params=Q, json={"family": {"start": "The Carter family"}}).status_code == 200
    hid = next(a["household_id"] for a in church.t["household_adults"] if a["contact_id"] == CALVIN)
    assert next(h for h in church.t["households"] if h["id"] == hid)["name"] == "The Carter family"
    assert t.patch(f"/church/roll/person/{DANA}", params=Q, json={"family": {"join": hid}}).status_code == 200
    assert {a["contact_id"] for a in church.t["household_adults"] if a["household_id"] == hid} == {CALVIN, DANA}
    assert t.patch(f"/church/roll/person/{DANA}", params=Q, json={"family": {"leave": True}}).status_code == 200
    assert not any(a["contact_id"] == DANA for a in church.t["household_adults"])
    assert t.patch(f"/church/roll/person/{DANA}", params=Q, json={"family": {"join": str(uuid.uuid4())}}).status_code == 404


# ─── adding people ────────────────────────────────────────────────────

def test_adding_a_whole_family_with_a_child_and_her_allergies(church, monkeypatch):
    t = _client(monkeypatch)
    r = t.post("/church/roll/people", params=Q, json={
        "people": [{"first": "Jordan", "last": "Price", "kind": "adult", "mobile": "(555) 018-3321"},
                   {"first": "Jayla", "last": "Price", "kind": "adult", "email": "jayla@example.com"},
                   {"first": "Kai", "last": "Price", "kind": "child", "birthday": "2017-05-12", "allergies": "Peanuts"}],
        "family": {"name": "Price", "address": "22 Marlow Ct"}, "status": "first_time", "first_sunday": "2026-11-15",
        "found": "friend"})
    assert r.status_code == 200, r.text
    ids, hid = r.json()["ids"], r.json()["household_id"]
    assert len(ids) == 3 and hid
    assert next(h for h in church.t["households"] if h["id"] == hid)["name"] == "The Price family"
    jordan, kai = _c(church, ids[0]), _c(church, ids[2])
    assert jordan["status"] == "lead" and jordan["metadata"]["found_us"] == "Friend or family"
    assert jordan["metadata"]["address"] == "22 Marlow Ct" and jordan["metadata"]["first_sunday"] == "2026-11-15"
    child = next(k for k in church.t["children"] if k.get("contact_id") == ids[2])
    assert child["household_id"] == hid and kai["birthdate"] == "2017-05-12"
    assert next(n for n in church.t["child_care_notes"] if n["child_id"] == child["id"])["allergies"] == "Peanuts"
    roll = t.get("/church/roll", params=Q).json()
    assert _p(roll, ids[0])["family"]["id"] == hid


def test_one_member_added_is_confirmed_and_use_that_record_fills_it_in(church, monkeypatch):
    t = _client(monkeypatch)
    r = t.post("/church/roll/people", params=Q, json={"people": [{"first": "Grace", "last": "Kim"}], "family": None,
                                                      "status": "member"})
    gid = r.json()["ids"][0]
    assert r.json()["household_id"] is None and _c(church, gid)["metadata"]["member_confirmed"]
    _c(church, VIC)["phone"] = ""
    r = t.post("/church/roll/people", params=Q, json={"people": [{"use_id": VIC, "first": "Vic", "mobile": "(555) 300-1111"}],
                                                      "family": None, "status": "first_time"})
    had = _c(church, VIC)["phone"]
    assert r.json()["ids"] == [VIC]
    assert _c(church, VIC)["phone"] == (had or "(555) 300-1111")          # fills a gap, never overwrites
    assert t.post("/church/roll/people", params=Q, json={"people": [{"first": ""}], "status": "first_time"}).status_code == 400
    assert t.post("/church/roll/people", params=Q, json={"people": [{"first": "A"}], "status": "vip"}).status_code == 400


# ─── merging ──────────────────────────────────────────────────────────

def test_this_number_is_her_its_texts_move_and_the_record_is_kept_hidden(church, monkeypatch):
    t = _client(monkeypatch)
    _add(church, TWICE, "Ruth Abner", status="active", meta={"imported_from": "Subsplash"})     # no phone on file
    r = t.post("/church/roll/merge", params=Q, json={"keep": TWICE, "drop": NUMBER, "use_number": True})
    assert r.status_code == 200, r.text
    keep, drop = _c(church, TWICE), _c(church, NUMBER)
    assert keep["phone"] == "+15550142290" and keep["status"] == "active"
    assert drop["status"] == "inactive" and drop["metadata"]["merged_into"] == TWICE
    assert {m["contact_id"] for m in church.t["sms_messages"] if m["id"] in ("s1", "s2")} == {TWICE}
    roll = t.get("/church/roll", params=Q).json()
    assert not any(p["id"] == NUMBER for p in roll["people"])
    assert t.post("/church/roll/merge", params=Q, json={"keep": TWICE, "drop": NUMBER}).status_code == 409
    assert t.post("/church/roll/merge", params=Q, json={"keep": TWICE, "drop": TWICE}).status_code == 400
    assert any(e["event_type"] == "contact_merged" for e in church.t["events"])


# ─── Tidy up ──────────────────────────────────────────────────────────

def test_tidy_up_lists_what_needs_it_and_the_roll_counts_it(church, monkeypatch):
    t = _client(monkeypatch)
    _add(church, TWICE, "Calvin Carter Sr", phone=_c(church, CALVIN).get("phone") or "+15557778888")
    _c(church, CALVIN)["phone"] = _c(church, TWICE)["phone"]
    tidy = t.get("/church/roll/tidy", params=Q).json()
    assert [n["id"] for n in tidy["numbers"]] == [NUMBER] and tidy["numbers"][0]["guess"] == "Renee"
    assert tidy["numbers"][0]["said"] == "DAILY"
    assert {c["id"]: c["fixed"] for c in tidy["caps"]}[SHOUT] == "Keisha O'Neal McAllister"
    assert tidy["two"] == [{"id": TWO, "name": "Liyah And Meyah Tornes", "a": "Liyah Tornes", "b": "Meyah Tornes"}]
    pair = next(s for s in tidy["same"] if {s["a"]["id"], s["b"]["id"]} == {CALVIN, TWICE})
    assert pair["why"] == "same mobile" and pair["a"]["id"] == CALVIN          # the one with Sundays is kept
    assert {c["id"] for c in tidy["confirm"]} == {LOOSE, TWICE}              # everyone else came over in the import
    roll = t.get("/church/roll", params=Q).json()
    assert roll["tidy"]["numbers"] == 1 and roll["tidy"]["two"] == 1
    assert _p(roll, NUMBER)["noname"] is True and _p(roll, LOOSE)["confirmed"] is False
    assert _p(roll, CALVIN)["confirmed"] is True


def test_each_tidy_fix_does_what_it_says(church, monkeypatch):
    t = _client(monkeypatch)
    assert t.post("/church/roll/tidy/caps", params=Q, json={"ids": [SHOUT]}).json() == {"fixed": 1}
    assert _c(church, SHOUT)["name"] == "Keisha O'Neal McAllister"
    ids = t.post("/church/roll/tidy/split", params=Q, json={"id": TWO}).json()["ids"]
    assert _c(church, ids[0])["name"] == "Liyah Tornes" and _c(church, ids[1])["name"] == "Meyah Tornes"
    homes = {a["household_id"] for a in church.t["household_adults"] if a["contact_id"] in ids}
    assert len(homes) == 1
    assert t.post("/church/roll/tidy/numbers-guests", params=Q, json={}).json() == {"filed": 1}
    assert _c(church, NUMBER)["status"] == "lead"
    assert t.post("/church/roll/tidy/confirm", params=Q, json={"id": LOOSE, "keep": True}).status_code == 200
    assert _c(church, LOOSE)["metadata"]["member_confirmed"]
    assert LOOSE not in [c["id"] for c in t.get("/church/roll/tidy", params=Q).json()["confirm"]]
    _add(church, TWICE, "Dana Two", phone="+15559990000")
    _add(church, "33333333-0000-0000-0000-000000000006", "Dana Three", phone="+15559990000")
    _add(church, "33333333-0000-0000-0000-000000000007", "Jordan Price", phone="+15558880000")
    _add(church, "33333333-0000-0000-0000-000000000008", "Jayla Price", phone="+15558880000")
    same = t.get("/church/roll/tidy", params=Q).json()["same"]
    assert any(s["why"] == "same mobile" and TWICE in (s["a"]["id"], s["b"]["id"]) for s in same)
    # A family shares a phone: Jordan and Jayla are two people.
    assert not any("33333333-0000-0000-0000-000000000007" in (s["a"]["id"], s["b"]["id"]) for s in same)
    t.post("/church/roll/tidy/not-same", params=Q, json={"a": TWICE, "b": "33333333-0000-0000-0000-000000000006"})
    assert not any(TWICE in (s["a"]["id"], s["b"]["id"]) for s in t.get("/church/roll/tidy", params=Q).json()["same"])
    assert t.post("/church/roll/tidy/confirm", params=Q, json={"id": LOOSE, "keep": False}).status_code == 200
    assert _c(church, LOOSE)["status"] == "lead"


def test_history_tabs_notes_texts_emails(church, monkeypatch):
    t = _client(monkeypatch)
    church.t["events"] += [{"id": "e1", "business_id": BIZ, "contact_id": NUMBER, "event_type": "contact_note",
                            "data": {"note": "Asked about Wednesday."}, "created_at": "2026-10-22T12:00:00+00:00"},
                           {"id": "e2", "business_id": BIZ, "contact_id": NUMBER, "event_type": "email_sent",
                            "data": {"subject": "Welcome to church"}, "created_at": "2026-10-23T12:00:00+00:00"}]
    notes = t.get(f"/church/roll/person/{NUMBER}/history", params={**Q, "kind": "notes"}).json()["items"]
    assert notes[0]["t"] == "Asked about Wednesday."
    texts = t.get(f"/church/roll/person/{NUMBER}/history", params={**Q, "kind": "texts"}).json()["items"]
    assert [x["t"].split(": ", 1)[1] for x in texts] == ["Thanks! - Renee", "DAILY"]
    emails = t.get(f"/church/roll/person/{NUMBER}/history", params={**Q, "kind": "emails"}).json()["items"]
    assert emails[0]["t"] == "Welcome to church"
    assert t.get(f"/church/roll/person/{NUMBER}/history", params={**Q, "kind": "files"}).status_code == 400


def test_a_number_never_counts_in_this_week(church, monkeypatch):
    v = _roll(church)
    assert _p(v, NUMBER)["noname"] is True
    assert all(n != "+15550142290" for n in v["week"]["new_guests"]["names"])


def test_a_seat_below_staff_cannot_change_the_roll(church, monkeypatch):
    # business_access refuses a seat below manager before the roll's gate runs.
    t = _client(monkeypatch, role="member")
    assert t.patch(f"/church/roll/person/{CALVIN}", params=Q, json={"first": "X"}).status_code == 404
    assert t.post("/church/roll/people", params=Q, json={"people": [{"first": "X"}], "status": "first_time"}).status_code == 404


# ─── a write that fails says so (the fake answers as Supabase does) ───

def test_a_family_move_that_fails_never_leaves_them_in_no_family(church, monkeypatch):
    t = _client(monkeypatch)
    assert t.patch(f"/church/roll/person/{CALVIN}", params=Q, json={"family": {"start": "The Carter family"}}).status_code == 200
    old = next(a["household_id"] for a in church.t["household_adults"] if a["contact_id"] == CALVIN)
    import church_families
    monkeypatch.setattr(church_families, "make_family", lambda *a, **k: None)
    assert t.patch(f"/church/roll/person/{CALVIN}", params=Q, json={"family": {"start": "Another"}}).status_code == 503
    assert [a["household_id"] for a in church.t["household_adults"] if a["contact_id"] == CALVIN] == [old]
    monkeypatch.setattr(church_families, "join_family", lambda *a, **k: False)
    other = church.t["households"][0]["id"] if church.t["households"][0]["id"] != old else None
    hid = other or str(uuid.uuid4())
    if not other:
        church.t["households"].append({"id": hid, "business_id": BIZ, "name": "The Others"})
    assert t.patch(f"/church/roll/person/{CALVIN}", params=Q, json={"family": {"join": hid}}).status_code == 503
    assert [a["household_id"] for a in church.t["household_adults"] if a["contact_id"] == CALVIN] == [old]
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", lambda path: False)
    assert t.patch(f"/church/roll/person/{CALVIN}", params=Q, json={"family": {"leave": True}}).status_code == 503


def test_a_family_move_writes_the_new_family_before_leaving_the_old(church, monkeypatch):
    t = _client(monkeypatch)
    t.patch(f"/church/roll/person/{CALVIN}", params=Q, json={"family": {"start": "The Carter family"}})
    t.patch(f"/church/roll/person/{DANA}", params=Q, json={"family": {"start": "The Dana family"}})
    dana_home = next(a["household_id"] for a in church.t["household_adults"] if a["contact_id"] == DANA)
    assert t.patch(f"/church/roll/person/{CALVIN}", params=Q, json={"family": {"join": dana_home}}).status_code == 200
    assert [a["household_id"] for a in church.t["household_adults"] if a["contact_id"] == CALVIN] == [dana_home]


def test_a_grade_that_didnt_save_is_not_saved(church, monkeypatch):
    t = _client(monkeypatch)
    hid = str(uuid.uuid4())
    church.t["households"].append({"id": hid, "business_id": BIZ, "name": "The Carter family"})
    church.t["children"].append({"id": "kid-1", "business_id": BIZ, "household_id": hid, "contact_id": DANA,
                                 "grade": "", "birthdate": None, "active": True})
    real = sb_clients.sb_patch_as_service
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body, **k: None if path.startswith("/children") else real(path, body, **k))
    r = t.patch(f"/church/roll/person/{DANA}", params=Q, json={"grade": "4th"})
    assert r.status_code == 503 and "grade" in r.json()["detail"]


def test_a_childs_allergies_that_didnt_save_come_back_as_a_warning(church, monkeypatch):
    t = _client(monkeypatch)
    real = sb_clients.sb_post_as_service
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda path, body, prefer="return=representation", **k: None if path == "/child_care_notes"
                        else real(path, body, prefer, **k))
    r = t.post("/church/roll/people", params=Q, json={
        "people": [{"first": "Jordan", "last": "Price"}, {"first": "Kai", "last": "Price", "kind": "child", "allergies": "Peanuts"}],
        "family": {"name": "Price"}, "status": "first_time"})
    assert r.status_code == 200 and r.json()["household_id"]
    assert "Kai’s allergies didn’t save" in r.json()["warning"]


def test_a_merge_hides_the_other_record_before_anything_moves(church, monkeypatch):
    t = _client(monkeypatch)
    _add(church, TWICE, "Ruth Abner", status="active", meta={"imported_from": "Subsplash"})
    real = sb_clients.sb_patch_as_service
    order = []

    def patch(path, body, **k):
        order.append(path.split("?")[0] + (":merged" if isinstance(body.get("metadata"), dict) and body["metadata"].get("merged_into") else ""))
        return None if path.startswith("/sms_messages") else real(path, body, **k)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)
    r = t.post("/church/roll/merge", params=Q, json={"keep": TWICE, "drop": NUMBER})
    assert r.status_code == 200 and "sms_messages" in r.json()["left"]
    assert order.index("/contacts:merged") < order.index("/events")
    assert _c(church, NUMBER)["metadata"]["merged_into"] == TWICE
    # The texts that didn't move stay on the hidden record, and a retry is refused.
    assert t.post("/church/roll/merge", params=Q, json={"keep": TWICE, "drop": NUMBER}).status_code == 409
