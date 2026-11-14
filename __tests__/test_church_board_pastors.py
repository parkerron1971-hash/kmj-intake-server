"""A board's follow-ups follow the pastors-and-elders rule (church_board.make_tasks,
church_over.may_hand; docs/CHURCH_ASSIGNMENTS.md). Kevin, 2026-11-12: "admins
can not give work to elders and pastors": only the church's owner, or the
ministry chain on the leaders map, can. Until 2026-11-14 the board's "make
tasks" was a way around it: an office seat pressed it, and a pastor or an
elder was handed the task.

Pins, at Love City (church_three), through the real route:
  * an Admin: a follow-up for an elder, for a pastor with a login, and for the
    owner (the senior pastor) is still made, handed to no one, with their name
    in its title and why in its notes, and the answer lists it; a follow-up
    for someone who isn't a pastor or an elder is handed out as before
  * the owner hands every one out, as before
  * the ministry chain still counts: the Executive Pastor's login hands the
    elder who answers to her on the map his follow-up, and her own to herself;
    never the other elder's or the owner's
  * closed (CHURCH_ASSIGNMENTS off), the board hands them out as before and
    reads nothing more
  * who is a pastor that can't be read is a 503 with nothing made; twice makes
    each once
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_board as cb  # noqa: E402
import church_over as co  # noqa: E402
import church_three as c3  # noqa: E402
import sb_clients  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from church_three import LOVE_CITY  # noqa: E402

NOW = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)
MEETING = "b0a4d000-0000-4000-8000-000000000001"
# Who the board named for each follow-up: (handle, has a login on the board's row).
FOLLOW_UPS = (("marcus", "Plan the elders' retreat"),        # an elder, no login
              ("tanya", "Visit the Owens family"),           # an elder, no login, answers to no one on the map
              ("jessica", "Review the safety policy"),       # the Executive Pastor, a Manager login
              ("kevin", "Preach at the lodge"),              # the owner, Love City's senior pastor
              ("tasha", "Order the welcome gifts"),          # a team leader: not a pastor or an elder
              ("naiya", "Book the fellowship hall"))         # an office login: not a pastor or an elder


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "on")
    monkeypatch.setenv("CHURCH_LEADER_TASKS", "on")
    monkeypatch.setenv("CHURCH_BOARD", "on")
    d = c3.build(monkeypatch)
    monkeypatch.setattr(cb, "_now", lambda: NOW)
    monkeypatch.setattr(cb, "_tz", lambda biz: ZoneInfo("America/Detroit"))
    w = d.who[LOVE_CITY]
    board = next(b["id"] for b in d.t["church_boards"] if b["business_id"] == LOVE_CITY)
    members = d.t["church_board_members"]
    for n, r in enumerate(members):                                  # the fixture's two elders: rows as the route makes them
        r.update(id=r.get("id") or f"b0a4d000-0000-4000-8000-0000000001{n:02d}", title="",
                 created_at="2026-10-01T00:00:00+00:00")
    logins = {"jessica": w["jessica@"], "kevin": c3.church(d, LOVE_CITY)["owner_id"], "naiya": w["naiya@"]}
    for n, h in enumerate(("jessica", "kevin", "tasha", "naiya"), start=10):
        members.append({"id": f"b0a4d000-0000-4000-8000-0000000001{n:02d}", "business_id": LOVE_CITY,
                        "board_id": board, "contact_id": w[h], "user_id": logins.get(h), "name": "", "title": "",
                        "active": True, "created_at": "2026-10-02T00:00:00+00:00"})
    by = {r["contact_id"]: r["id"] for r in members if r["business_id"] == LOVE_CITY}
    d.t["church_board_meetings"] = [{
        "id": MEETING, "business_id": LOVE_CITY, "board_id": board, "title": "", "place": "", "video_url": "",
        "starts_at": "2026-11-10T23:00:00+00:00", "status": "planned", "sent_at": None, "sent_count": 0,
        "approved_at": None, "approved_by": None, "approved_in": None, "created_at": "2026-11-01T00:00:00+00:00"}]
    d.t["church_board_items"] = [{
        "id": f"b0a4d000-0000-4000-8000-0000000002{n:02d}", "business_id": LOVE_CITY, "meeting_id": MEETING,
        "position": n, "title": title, "notes": "", "minutes": "", "status": "follow_up", "documents": [],
        "carried_from": None, "follow_up_member": by[w[h]], "follow_up_due": "2026-11-20", "task_id": None,
        "created_at": "2026-11-10T23:30:00+00:00"} for n, (h, title) in enumerate(FOLLOW_UPS)]
    d.t["church_board_attendance"], d.t["church_board_decisions"] = [], []
    d.t["tasks"] = [t for t in d.t["tasks"] if t["business_id"] != LOVE_CITY]      # only what the board makes
    return d


def make(db, handle):
    u = c3.church(db, LOVE_CITY)["owner_id"] if handle == "owner" else db.who[LOVE_CITY][handle + "@"]
    seat = next((s for s in db.t["business_users"] if s["user_id"] == u), None)
    app = FastAPI()
    app.include_router(cb.router)
    app.dependency_overrides[require_user] = lambda: AuthedUser(
        id=u, email=seat["invited_email"] if seat else c3.OWNER_EMAIL[u], role="authenticated")
    return TestClient(app).post(f"/church/board/meetings/{MEETING}/tasks", json={"business_id": LOVE_CITY})


def tasks(db):
    return {t["title"]: t for t in db.t["tasks"] if t["business_id"] == LOVE_CITY}


def handed(t):
    return t.get("assigned_to") or t.get("assigned_contact_id")


def test_an_admin_makes_a_pastors_follow_up_but_never_hands_it_to_them(db):
    r = make(db, "minnie")
    assert r.status_code == 200, r.text
    got, by, w = r.json(), tasks(db), db.who[LOVE_CITY]
    assert got["made"] == 6 and len(by) == 6, "every follow-up is still made: the board's decision isn't lost"
    for title, name in (("Plan the elders' retreat", "Marcus Taylor"), ("Visit the Owens family", "Tanya Brooks"),
                        ("Review the safety policy", "Jessica McCloud"), ("Preach at the lodge", "Kevin McCloud")):
        t = by[f"{title} ({name})"]
        assert not handed(t) and not t.get("handed_by"), f"{name} is handed nothing by an office seat"
        assert t["due_date"] == "2026-11-20" and t["status"] == "todo"
        assert t["description"] == ("A follow-up from the Elder Board meeting of Tuesday, November 10, 2026. " +
                                    cb.NOT_HANDED.format(name=name))
    assert by["Order the welcome gifts"]["assigned_contact_id"] == w["tasha"], "not a pastor or an elder: as before"
    assert by["Book the fellowship hall"]["assigned_to"] == w["naiya@"], "an office login: as before"
    assert [(x["title"], x["name"]) for x in got["not_handed"]] == [
        ("Plan the elders' retreat", "Marcus Taylor"), ("Visit the Owens family", "Tanya Brooks"),
        ("Review the safety policy", "Jessica McCloud"), ("Preach at the lodge", "Kevin McCloud")]
    assert got["not_handed_text"].startswith("4 follow-ups are in Tasks with a name on each, but they aren't handed "
                                             "out: “Plan the elders' retreat” (Marcus Taylor), ")
    assert got["not_handed_text"].endswith("and “Preach at the lodge” (Kevin McCloud). " + cb.WHO_HANDS)
    assert got["meeting"]["id"] == MEETING and all(i["task_id"] for i in got["items"]), "the answer's shape is as it was"
    again = make(db, "minnie").json()
    assert again["made"] == 0 and again["not_handed"] == [] and again["not_handed_text"] == "" and len(tasks(db)) == 6


def test_one_left_for_the_owner_reads_as_one_line(db):
    db.t["church_board_items"] = [i for i in db.t["church_board_items"] if i["title"] == "Plan the elders' retreat"]
    got = make(db, "minnie").json()
    assert got["made"] == 1 and got["not_handed_text"] == (
        "“Plan the elders' retreat” is in Tasks with Marcus Taylor's name on it, but it isn't handed to them. "
        "Only the owner, or whoever is over them on the leaders map, gives a pastor or an elder work.")


def test_the_owner_hands_every_one_out_as_before(db):
    got, w = make(db, "owner").json(), db.who[LOVE_CITY]
    by = tasks(db)
    assert got["made"] == 6 and got["not_handed"] == [] and got["not_handed_text"] == ""
    assert by["Plan the elders' retreat"]["assigned_contact_id"] == w["marcus"]
    assert by["Visit the Owens family"]["assigned_contact_id"] == w["tanya"]
    assert by["Review the safety policy"]["assigned_to"] == w["jessica@"]
    assert by["Preach at the lodge"]["assigned_to"] == c3.church(db, LOVE_CITY)["owner_id"]
    assert all("isn't handed" not in t["description"] for t in by.values())


def test_the_ministry_chain_still_hands_an_elder_work_and_a_pastor_her_own(db):
    r = make(db, "jessica")
    assert r.status_code == 200, r.text
    got, by, w = r.json(), tasks(db), db.who[LOVE_CITY]
    assert by["Plan the elders' retreat"]["assigned_contact_id"] == w["marcus"], "Marcus answers to her on the map"
    assert by["Review the safety policy"]["assigned_to"] == w["jessica@"], "her own follow-up is hers"
    assert not handed(by["Visit the Owens family (Tanya Brooks)"]), "an elder who answers to no one under her"
    assert not handed(by["Preach at the lodge (Kevin McCloud)"]), "never the owner"
    assert [x["name"] for x in got["not_handed"]] == ["Tanya Brooks", "Kevin McCloud"]


def test_closed_the_board_hands_them_out_as_before_and_reads_nothing_more(db, monkeypatch):
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "off")
    monkeypatch.setattr(co, "Church", lambda biz: pytest.fail("closed: who is a pastor is never read"))
    got, w = make(db, "minnie").json(), db.who[LOVE_CITY]
    by = tasks(db)
    assert got["made"] == 6 and got["not_handed"] == []
    assert by["Plan the elders' retreat"]["assigned_contact_id"] == w["marcus"]
    assert by["Review the safety policy"]["assigned_to"] == w["jessica@"]


def test_who_is_a_pastor_that_cant_be_read_is_a_503_with_nothing_made(db, monkeypatch):
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/church_leader_roles") else real(path, **kw))
    r = make(db, "minnie")
    assert r.status_code == 503 and tasks(db) == {}
    assert all(not i["task_id"] for i in db.t["church_board_items"])


def test_may_hand_is_the_assignment_routes_decision(db):
    ch, w = co.Church(c3.church(db, LOVE_CITY)), db.who[LOVE_CITY]
    minnie, jess = co.who(co.LOGIN, w["minnie@"]), co.who(co.LOGIN, w["jessica@"])
    owner = co.who(co.LOGIN, ch.owner)
    marcus, tasha = co.who(co.PERSON, w["marcus"]), co.who(co.PERSON, w["tasha"])
    assert co.is_guarded(ch, marcus) and co.is_guarded(ch, jess) and co.is_guarded(ch, owner)
    assert not co.is_guarded(ch, tasha) and not co.is_guarded(ch, co.who(co.LOGIN, w["naiya@"]))
    assert co.may_hand(ch, owner, marcus) and co.may_hand(ch, minnie, tasha)
    for me in (minnie, jess):
        assert co.may_hand(ch, me, marcus) == co.is_over(ch, me, marcus)
    assert not co.may_hand(ch, minnie, jess, co.who(co.PERSON, w["jessica"])), "her login and her record: one person"
    assert co.may_hand(ch, jess, co.who(co.PERSON, w["jessica"])), "yourself, by your own record"
