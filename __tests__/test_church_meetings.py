"""Meetings & minutes, step 3's server half one (church_meetings.py and what
the board's code learned; docs/CHURCH_SCHEDULE.md section 10, PR S3-2). The
pastor, 2026-11-20, on the mock's five calls: one home for every meeting; a
meeting for every leader keeps itself up to date with the leaders list (and
one for the office); "I can't" needs no yes, with a short note only whoever
set the meeting, the keepers and whoever oversees the office read.

Pins, at Love City (church_three, made-up people) on the fake with step 3's
file (church_schedule_fake.build(meetings=True)), through the real routes:
  * the switch (off | owner | on, owner when unset, a typo off, only where
    CHURCH_BOARD is open) and the tables: closed, or before the file, every
    route here is a 404 with nothing of ours read, and the page keeps its
    old name; ready() reads "no such table" as no and a blip as the last
    answer
  * a group for every leader (or the office) is found or made by name:
    once, whatever its case, under a race (a 409 read as "made just now");
    only the keepers set one; the leaders list closed, boards only
  * keep_in_step: seats the list, lets go who left it (the row stays), seats
    them again, follows a login, never touches a board or a closed group,
    seats a person once under a race; a failed read is a 503 in plain words
  * a list seat reads and answers and never writes; add_member and
    edit_member are refused on a group for the list before any write
  * a meeting group is never a board: its people never give the board's yes
    on money (office or member app), it is never a board on the leaders map
    or the Board tab, its decisions are never in the board's log nor the
    housing allowance's vote
  * a meeting called off is never the next one, takes no step, no carry, no
    approving in it and no answer
  * answers: yes or I can't, a note with I can't only (200 at most), for the
    meeting's time (moved: not an answer any more), taken back; someone
    else's only by whoever may write the meeting; the note's readers and
    nobody else, in the office and the member app, never in the minutes
  * "End the meeting" marks an I can't excused; a meeting group's minutes go
    out to read and the keepers approve them; no quorum line unless a count
  * the fake refuses an on_conflict naming a partial index, as Postgres does
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_board as cb  # noqa: E402
import church_map  # noqa: E402
import church_meetings as cmt  # noqa: E402
import church_money_levels as cml  # noqa: E402
import church_over as co  # noqa: E402
import church_schedule_fake as fake  # noqa: E402
import church_three as c3  # noqa: E402
import housing_allowance as ha  # noqa: E402
import member_portal_board as mpb  # noqa: E402
import sb_clients  # noqa: E402
from church_schedule_fake import as_  # noqa: E402
from church_three import GRACE, LOVE_CITY  # noqa: E402
from fastapi import HTTPException  # noqa: E402

LC = LOVE_CITY
NEXT_WEEK = "2026-11-24T00:00:00+00:00"        # Monday, 7 PM in Detroit
LATER = "2026-12-01T00:00:00+00:00"
EARLIER_TODAY = "2026-11-18T14:00:00+00:00"   # an hour before NOW: started


@pytest.fixture
def db(monkeypatch):
    return fake.build(monkeypatch, meetings=True)


@pytest.fixture
def app(db):
    a = fake.meetings_client(db)
    as_(a, LC, "owner")
    return a


def ok(r):
    assert r.status_code == 200, r.text
    return r.json()


def who(db, handle):
    return db.who[LC][handle]


def church(db):
    return c3.church(db, LC)


def elder_board(db):
    return next(b for b in db.t["church_boards"] if b["business_id"] == LC and b["name"] == "Elder Board")


def set_meeting(app, who_="leaders", name="Leaders meeting", when=NEXT_WEEK, **kw):
    return app.post("/church/meetings", json={"business_id": LC, "who": who_, "name": name, "starts_at": when, **kw})


def seats(db, gid, *, active=None):
    return [s for s in db.t["church_board_members"] if s["board_id"] == gid
            and (active is None or (s.get("active") is not False) == active)]


def names(db, rows):
    return sorted(db.label[s["contact_id"]] for s in rows)


def answers(app, mid):
    return ok(app.get(f"/church/meetings/{mid}/answers?business_id={LC}"))


def answer(app, mid, **body):
    return app.put(f"/church/meetings/{mid}/answers", json={"business_id": LC, **body})


def seat_of(db, gid, handle):
    return next(s for s in db.t["church_board_members"] if s["board_id"] == gid and s["contact_id"] == who(db, handle))


def unlist(db, handle):
    db.t["church_schedule_people"].append({"business_id": LC, "contact_id": who(db, handle), "listed": "remove",
                                           "grp": None})


def relist(db, handle, grp="leaders"):
    db.t["church_schedule_people"] = [r for r in db.t["church_schedule_people"] if r["contact_id"] != who(db, handle)]
    if grp:
        db.t["church_schedule_people"].append({"business_id": LC, "contact_id": who(db, handle), "listed": "add",
                                               "grp": grp})


def open_page(app, mid):
    return ok(app.get(f"/church/board/meetings/{mid}?business_id={LC}"))


LEADERS = ["Andre", "Angela", "Cora", "Eve", "Gloria", "Jessica", "Kevin", "Laquesha", "Marcus", "Minnie", "Naiya",
           "Paul", "Ruth", "Shapretta", "Tanya", "Tasha", "Tiara", "Tyrone", "Yolanda"]
OFFICE = ["Jessica", "Laquesha", "Minnie", "Naiya", "Shapretta", "Tiara"]


# ─── The switch and the tables ────────────────────────────────────────

def test_before_the_tables_every_route_is_a_404_and_nothing_of_ours_is_read(monkeypatch):
    d = fake.build(monkeypatch)                                  # step 3's file not applied
    a = fake.meetings_client(d)
    as_(a, LC, "owner")
    assert cmt.ready() is False
    assert set_meeting(a).status_code == 404
    assert a.get(f"/church/meetings/{c3.uid(1, 1)}/answers?business_id={LC}").status_code == 404
    assert answer(a, c3.uid(1, 1), answer="yes").status_code == 404
    st = ok(a.get(f"/church/board/status?business_id={LC}"))
    assert st["name"] == "Board & minutes" and st["meetings"] is False
    page = ok(a.get(f"/church/board?business_id={LC}"))
    assert "kind" not in page["boards"][0] and "next" not in page
    # The board, the money levels, the map and the Board tab read as before:
    # nothing names a step 3 column or table (the fake would refuse it).
    me = {"biz": church(d), "_board_yes": {}}
    assert cml.board_people(me).keys() == {who(d, "marcus"), who(d, "tanya")}
    assert church_map.thing("board") == ("church_boards", "name", "&archived=eq.false")
    assert mpb.boards_of(LC, who(d, "marcus")) == {elder_board(d)["id"]}
    assert not [r for r in d.reads if "church_meeting" in r
                or r.lstrip("/").split("?")[0] in fake.BOARD_TABLES and fake.MEET_COLS.search(r.partition("?")[2])]
    assert not [w for w in d.refused if "step 3" in w], d.refused


@pytest.mark.parametrize("mode", ["off", "Off ", "nope"])
def test_closed_is_a_404_with_nothing_read(monkeypatch, mode):
    d = fake.build(monkeypatch, meetings=True, meetings_mode=mode)
    a = fake.meetings_client(d)
    as_(a, LC, "owner")
    d.reads.clear()
    assert set_meeting(a).status_code == 404
    assert a.get(f"/church/meetings/{c3.uid(1, 1)}/answers?business_id={LC}").status_code == 404
    assert d.reads == [], "closed: nothing read at all"
    st = ok(a.get(f"/church/board/status?business_id={LC}"))
    assert st["name"] == "Board & minutes" and st["meetings"] is False


def test_owner_mode_is_the_platform_owners_church_and_needs_the_board_open(monkeypatch):
    monkeypatch.delenv("CHURCH_MEETINGS", raising=False)
    d = fake.build(monkeypatch, meetings=True)
    monkeypatch.delenv("CHURCH_MEETINGS", raising=False)
    assert cmt.mode() == "owner"
    a = fake.meetings_client(d)
    as_(a, LC, "owner")
    assert ok(set_meeting(a))["board"]["name"] == "Leaders meeting"
    as_(a, GRACE, "owner")
    assert a.post("/church/meetings", json={"business_id": GRACE, "who": "leaders", "name": "Leaders meeting",
                                            "starts_at": NEXT_WEEK}).status_code == 404
    st = ok(a.get(f"/church/board/status?business_id={GRACE}"))
    assert st["name"] == "Board & minutes", "another church under owner keeps the old name"
    assert ha._page_name(GRACE) == "Board & minutes" and ha._page_name(LC) == "Meetings & minutes"
    monkeypatch.setenv("CHURCH_BOARD", "off")
    as_(a, LC, "owner")
    assert set_meeting(a).status_code == 404
    assert cmt.church_open(church(d)) is False


def test_ready_reads_no_such_table_as_no_and_a_blip_as_the_last_answer(monkeypatch):
    monkeypatch.setattr(cmt, "_FORCE", None)
    monkeypatch.setattr(cmt, "_STATE", {"yes": None, "at": 0.0})
    monkeypatch.setattr(sb_clients, "sb_url", lambda: "https://db.example")
    said = {"rows": None, "err": {"status": 404, "code": "PGRST205", "message": "not in the schema cache"}}
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **k: said["rows"])
    monkeypatch.setattr(sb_clients, "last_error", lambda: said["err"])
    assert cmt.ready() is False
    cmt._STATE["at"] = -1e9
    said.update(rows=[], err=None)
    assert cmt.ready() is True
    cmt._STATE["at"] = -1e9
    said.update(rows=None, err={"status": 503, "code": "", "message": "timeout"})
    assert cmt.ready() is True, "a blip keeps the last answer"
    cmt._STATE.update(yes=None, at=-1e9)
    assert cmt.ready() is False, "with no answer yet, a blip reads as not there"


def test_the_page_is_meetings_and_minutes_where_step_3_is_open(app, db):
    st = ok(app.get(f"/church/board/status?business_id={LC}"))
    assert st["name"] == "Meetings & minutes" and st["meetings"] is True
    assert cmt.name_for(biz=church(db)) == "Meetings & minutes"
    import church_my_week as mw
    assert mw.room_door(church(db), mw.DOOR["meetings"], {})["label"] == "Open Meetings & minutes"
    me = {"biz": church(db), "_board_yes": {}}
    assert cml._page_name(me) == "Meetings & minutes"
    assert ha._page_name(LC) == "Meetings & minutes"


# ─── A group for every leader, or the office ─────────────────────────

def test_a_group_for_every_leader_is_made_once_and_seats_the_list(app, db):
    got = ok(set_meeting(app, place="Fellowship hall", length_minutes=90))
    g = got["board"]
    assert (g["kind"], g["audience"], g["follows_list"]) == ("meeting", "leaders", True)
    assert g["quorum"] is None and g["quorum_words"] == "", "no quorum line for a meeting group"
    assert got["series"] is None and got["room"] is None
    assert got["meeting"]["length_minutes"] == 90 and got["meeting"]["place"] == "Fellowship hall"
    mine = seats(db, g["id"])
    assert names(db, mine) == LEADERS
    assert all(s["from_list"] and s["active"] for s in mine)
    # An office person's seat carries their login, so they read it in the office app.
    assert seat_of(db, g["id"], "tiara")["user_id"] == who(db, "tiara@")
    assert seat_of(db, g["id"], "andre")["user_id"] is None
    assert seat_of(db, g["id"], "kevin")["user_id"] is None, "the owner is no office seat"
    # Again, whatever its case and spacing: the same group, a second meeting.
    again = ok(set_meeting(app, name="  leaders   MEETING ", when=LATER))
    assert again["board"]["id"] == g["id"]
    groups = [b for b in db.t["church_boards"] if b.get("audience") == "leaders"]
    assert len(groups) == 1 and len(seats(db, g["id"])) == len(LEADERS), "nobody seated twice"
    assert len([m for m in db.t["church_board_meetings"] if m["board_id"] == g["id"]]) == 2


def test_a_group_for_the_office_is_the_office_and_its_leaders_with_a_login(app, db):
    g = ok(set_meeting(app, "office", "Office huddle"))["board"]
    assert g["audience"] == "office" and names(db, seats(db, g["id"])) == OFFICE
    assert "Andre" not in names(db, seats(db, g["id"]))
    # Its own name: a leaders group of the same name is another group.
    other = ok(set_meeting(app, "leaders", "Office huddle"))["board"]
    assert other["id"] != g["id"]


def test_two_presses_at_once_make_one_group(app, db, monkeypatch):
    real = cmt._open_list_groups
    calls = {"n": 0}

    def racing(biz, audience):
        calls["n"] += 1
        rows = real(biz, audience)
        if calls["n"] == 1:
            # The other press, on another replica, made it just after our read.
            db.t["church_boards"].append({"id": "77777777-7777-4777-8777-777777777777", "business_id": LC,
                                          "name": "Leaders Meeting", "kind": "meeting", "audience": "leaders",
                                          "quorum_kind": "majority", "quorum_count": None, "sort": 9,
                                          "archived": False, "created_by": None, "created_at": fake.NOW.isoformat()})
        return rows

    monkeypatch.setattr(cmt, "_open_list_groups", racing)
    got = ok(set_meeting(app))
    assert got["board"]["id"] == "77777777-7777-4777-8777-777777777777"
    assert len([b for b in db.t["church_boards"] if b.get("audience") == "leaders"]) == 1
    assert "unique: church_boards_one_list_name" in db.refused


def test_a_group_insert_that_fails_otherwise_is_a_503(app, db):
    db.fail = {"post": "/church_boards"}
    r = set_meeting(app)
    assert r.status_code == 503 and r.json()["detail"] == "That meeting didn't save. Try again."
    assert not [b for b in db.t["church_boards"] if b.get("audience") == "leaders"]


def test_only_the_keepers_set_one_for_every_leader(app, db):
    # The keepers: the owner, an Admin, the Manager holding the meetings duty.
    for handle in ("minnie", "naiya"):
        as_(app, LC, handle)
        assert set_meeting(app, name=f"Leaders {handle}").status_code == 200, handle
    for handle in ("tiara", "laquesha"):             # Managers without the meetings duty
        as_(app, LC, handle)
        r = set_meeting(app, name="Not mine")
        assert r.status_code == 403, (handle, r.text)
    u = fake.seat(db, LC, "andre", role="member")
    app.who.update(id=u, email="andre@lovecity.org")
    assert set_meeting(app, name="Not mine").status_code == 403
    assert not [b for b in db.t["church_boards"] if b["name"] == "Not mine"]


def test_bad_asks_are_400s_with_nothing_made(app, db):
    for body, word in (({"repeat": {"pattern": "weekly"}}, "repeats"), ({"space_id": c3.uid(1, 1)}, "room"),
                       ({"who": "everyone"}, "Pick who comes"), ({"name": "  "}, "Name the meeting"),
                       ({"when": "soon"}, "day and time"), ({"length_minutes": 2}, "minutes"),
                       ({"length_minutes": "long"}, "minutes")):
        kw = {"who_": body.pop("who", "leaders"), "name": body.pop("name", "Leaders meeting"),
              "when": body.pop("when", NEXT_WEEK), **body}
        r = set_meeting(app, **kw)
        assert r.status_code == 400 and word in r.json()["detail"], (kw, r.text)
    assert not [m for m in db.t["church_board_meetings"]]
    assert not [b for b in db.t["church_boards"] if b.get("audience") == "leaders"], "a bad day makes no group"


def test_with_the_leaders_list_closed_a_meeting_is_for_a_board_or_a_group(app, db, monkeypatch):
    monkeypatch.setenv("CHURCH_SCHEDULE", "off")
    r = set_meeting(app)
    assert r.status_code == 409 and r.json()["detail"] == cmt.NO_LIST
    got = ok(set_meeting(app, f"group:{elder_board(db)['id']}", "Budget night"))
    assert got["meeting"]["title"] == "Budget night" and got["board"]["kind"] == "board"


def test_a_meeting_for_a_group_follows_church_boards_own_rules(app, db):
    eb = elder_board(db)
    as_(app, LC, "tiara")                                         # on no board, no meetings duty
    assert app.post("/church/meetings", json={"business_id": LC, "who": f"group:{eb['id']}",
                                              "starts_at": NEXT_WEEK}).status_code == 403
    as_(app, LC, "owner")
    assert set_meeting(app, f"group:{c3.uid(1, 99)}").status_code == 404
    assert set_meeting(app, "group:nope").status_code == 400


# ─── Keeping the list in step ────────────────────────────────────────

def test_keep_in_step_lets_go_seats_again_and_follows_a_login(app, db):
    got = ok(set_meeting(app))
    gid, mid = got["board"]["id"], got["meeting"]["id"]
    gloria = seat_of(db, gid, "gloria")
    unlist(db, "gloria")
    relist(db, "calvin", "leaders")
    page = open_page(app, mid)                                    # the meeting page keeps it in step first
    assert seat_of(db, gid, "gloria")["active"] is False, "let go, as leaving a board is"
    assert seat_of(db, gid, "gloria")["id"] == gloria["id"], "the row stays, for old minutes"
    assert seat_of(db, gid, "calvin")["active"] is True and seat_of(db, gid, "calvin")["from_list"] is True
    assert "Gloria Hunt" not in [p["name"] for p in page["roster"]]
    assert "Calvin Owens" in [p["name"] for p in page["roster"]]
    relist(db, "gloria", None)
    open_page(app, mid)
    assert seat_of(db, gid, "gloria")["active"] is True and seat_of(db, gid, "gloria")["id"] == gloria["id"]
    # A leader who gets an office login: their seat follows it.
    u = fake.seat(db, LC, "andre", role="manager")
    ch = co.Church(church(db))
    assert ch.person_login[who(db, "andre")] == u
    assert cmt.keep_in_step(ch, cb._board({"biz": church(db), "boss": True, "mine": set()}, gid)) == \
        {"added": 0, "back": 0, "left": 0}
    assert seat_of(db, gid, "andre")["user_id"] == u


def test_keep_in_step_never_touches_a_board_or_a_closed_group(app, db):
    got = ok(set_meeting(app))
    ch = co.Church(church(db))
    eb = elder_board(db)
    before = [dict(s) for s in db.t["church_board_members"]]
    assert cmt.keep_in_step(ch, eb) == {"added": 0, "back": 0, "left": 0}
    g = next(b for b in db.t["church_boards"] if b["id"] == got["board"]["id"])
    unlist(db, "gloria")
    ok(app.patch(f"/church/board/boards/{g['id']}", json={"business_id": LC, "archived": True}))
    closed = next(b for b in db.t["church_boards"] if b["id"] == g["id"])
    assert cmt.keep_in_step(ch, closed) == {"added": 0, "back": 0, "left": 0}
    assert db.t["church_board_members"] == before


def test_two_replicas_seat_a_person_once(app, db, monkeypatch):
    got = ok(set_meeting(app))
    gid = got["board"]["id"]
    relist(db, "calvin", "leaders")
    real = db.post

    def racing(path, body, prefer=None, **k):
        if path == "/church_board_members" and body.get("contact_id") == who(db, "calvin"):
            # The other replica's insert lands first.
            real(path, dict(body), prefer, **k)
        return real(path, body, prefer, **k)

    monkeypatch.setattr(sb_clients, "sb_post_as_service", racing)
    open_page(app, got["meeting"]["id"])
    assert len([s for s in seats(db, gid) if s["contact_id"] == who(db, "calvin")]) == 1
    assert "unique: church_board_members_one_from_list" in db.refused


def test_a_failed_read_is_a_503_in_plain_words(app, db):
    got = ok(set_meeting(app))
    db.fail = {"get": "/church_board_members"}
    r = app.get(f"/church/board/meetings/{got['meeting']['id']}?business_id={LC}")
    assert r.status_code == 503 and "couldn't be read just now" in r.json()["detail"]
    db.fail = {"get": "/church_meeting_answers"}
    r = app.get(f"/church/meetings/{got['meeting']['id']}/answers?business_id={LC}")
    assert r.status_code == 503 and r.json()["detail"] == cmt.UNREAD
    db.fail = {"patch": "/church_board_members"}
    unlist(db, "gloria")
    r = app.get(f"/church/board/meetings/{got['meeting']['id']}?business_id={LC}")
    assert r.status_code == 503 and r.json()["detail"] == cmt.UNSAVED


# ─── A list seat reads and answers; nobody adds one by hand ──────────

def test_a_list_seat_reads_and_answers_and_never_writes(app, db):
    got = ok(set_meeting(app))
    gid, mid = got["board"]["id"], got["meeting"]["id"]
    as_(app, LC, "tiara")                                         # a Manager seat: a writer login
    page = open_page(app, mid)
    assert page["can"]["write"] is False and page["board"]["write"] is False
    assert app.post(f"/church/board/meetings/{mid}/items", json={"business_id": LC, "title": "Snacks"}).status_code == 403
    assert app.put(f"/church/board/meetings/{mid}/attendance",
                   json={"business_id": LC, "member_id": seat_of(db, gid, "tiara")["id"],
                         "status": "present"}).status_code == 403
    assert app.patch(f"/church/board/meetings/{mid}", json={"business_id": LC, "status": "in_progress"}).status_code == 403
    assert app.post("/church/meetings", json={"business_id": LC, "who": f"group:{gid}",
                                              "starts_at": LATER}).status_code == 403
    assert ok(answer(app, mid, answer="yes"))["mine"]["answer"] == "yes"
    # Someone else's answer is only for whoever may write the meeting.
    r = answer(app, mid, member_id=seat_of(db, gid, "andre")["id"], answer="cant")
    assert r.status_code == 403
    listed = ok(app.get(f"/church/board?business_id={LC}"))
    assert [b["write"] for b in listed["boards"] if b["id"] == gid] == [False]


def test_add_and_edit_member_are_refused_on_a_list_group_before_any_write(app, db):
    got = ok(set_meeting(app))
    gid = got["board"]["id"]
    db.posts.clear()
    writes = len(db.t["church_board_members"])
    r = app.post(f"/church/board/boards/{gid}/members", json={"business_id": LC, "contact_id": who(db, "calvin")})
    assert r.status_code == 409 and r.json()["detail"] == cmt.FOLLOWS_LIST
    seat = seat_of(db, gid, "andre")
    r = app.patch(f"/church/board/members/{seat['id']}", json={"business_id": LC, "active": False})
    assert r.status_code == 409 and r.json()["detail"] == cmt.FOLLOWS_LIST
    assert not [p for p in db.posts if p[0] == "/church_board_members"]
    assert len(db.t["church_board_members"]) == writes and seat_of(db, gid, "andre")["active"] is True
    # A board's own seats are as they always were.
    eb = elder_board(db)
    assert ok(app.post(f"/church/board/boards/{eb['id']}/members",
                       json={"business_id": LC, "contact_id": who(db, "calvin")}))["member"]["name"] == "Calvin Owens"


def test_the_fake_refuses_an_on_conflict_on_a_partial_index(db):
    g = {"business_id": LC, "name": "Leaders meeting", "kind": "meeting", "audience": "leaders"}
    assert sb_clients.sb_post_as_service("/church_boards?on_conflict=business_id,audience,name", g,
                                         prefer="resolution=ignore-duplicates") is None
    assert sb_clients.last_error()["code"] == "42P10"
    row = {"business_id": LC, "board_id": elder_board(db)["id"], "contact_id": who(db, "calvin"), "name": "Calvin",
           "from_list": False}
    assert sb_clients.sb_post_as_service("/church_board_members?on_conflict=board_id,contact_id", row,
                                         prefer="resolution=ignore-duplicates") is None
    assert sb_clients.last_error()["code"] == "42P10"
    # And the rules themselves: a list seat on a board, a hand seat on a list group.
    assert sb_clients.sb_post_as_service("/church_board_members", {**row, "from_list": True}) is None
    assert sb_clients.last_error()["code"] == "P0001"


# ─── A meeting group is never a board ────────────────────────────────

def _decide(app, mid, motion):
    item = ok(app.post(f"/church/board/meetings/{mid}/items", json={"business_id": LC, "title": motion}))["item"]
    ok(app.post(f"/church/board/items/{item}/decisions", json={"business_id": LC, "motion": motion,
                                                               "votes_for": 5, "result": "carried"}))
    return next(d["id"] for d in app.db.t["church_board_decisions"] if d["item_id"] == item)


def test_a_meeting_groups_people_never_give_the_boards_yes_on_money(app, db):
    got = ok(set_meeting(app))
    gid = got["board"]["id"]
    me = {"biz": church(db), "_board_yes": {}}
    assert cml._open_boards(me) == elder_board(db)["id"]
    assert set(cml.board_people(me)) == {who(db, "marcus"), who(db, "tanya")}
    assert who(db, "tiara@") not in cml.board({"biz": church(db), "_board_yes": {}}), "a list seat's login"
    assert seat_of(db, gid, "tiara")["user_id"] == who(db, "tiara@") and seat_of(db, gid, "andre")["active"]
    member = {"biz": church(db), "_board_yes": {}, "member": True, "contact_id": who(db, "andre")}
    assert "board" not in cml.steps_of(member)
    marcus = {"biz": church(db), "_board_yes": {}, "member": True, "contact_id": who(db, "marcus")}
    assert "board" in cml.steps_of(marcus)


def test_a_meeting_group_is_never_a_board_on_the_map_or_the_board_tab(app, db):
    got = ok(set_meeting(app))
    gid, eb = got["board"]["id"], elder_board(db)["id"]
    assert church_map.thing("board")[2] == "&archived=eq.false&kind=eq.board"
    assert church_map._things(LC, "board", [gid, eb]) == {eb: "Elder Board"}
    assert mpb.boards_of(LC, who(db, "andre")) == set(), "a leader gets no Board tab from the leaders meeting"
    assert mpb.boards_of(LC, who(db, "marcus")) == {eb}


def test_a_meeting_groups_decisions_are_not_the_boards_log_nor_the_housing_vote(app, db):
    got = ok(set_meeting(app))
    gid, mid = got["board"]["id"], got["meeting"]["id"]
    huddle = _decide(app, mid, "Paint the nursery")
    eb = elder_board(db)
    elders = ok(set_meeting(app, f"group:{eb['id']}", "Elders"))["meeting"]["id"]
    vote = _decide(app, elders, "Housing allowance of $24,000")
    log = ok(app.get(f"/church/board/decisions?business_id={LC}"))["decisions"]
    assert [d["id"] for d in log] == [vote]
    own = ok(app.get(f"/church/board/decisions?business_id={LC}&board_id={gid}"))["decisions"]
    assert [d["id"] for d in own] == [huddle], "read on its own page"
    with pytest.raises(HTTPException) as e:
        ha._check_links(LC, {"board_decision_id": huddle})
    assert e.value.status_code == 400 and e.value.detail == ha.NOT_BOARDS_VOTE
    ha._check_links(LC, {"board_decision_id": vote})
    # A decision whose row names the board but whose meeting is the huddle's.
    next(d for d in db.t["church_board_decisions"] if d["id"] == huddle)["board_id"] = eb["id"]
    with pytest.raises(HTTPException):
        ha._check_links(LC, {"board_decision_id": huddle})
    # The member app's log is the boards' too.
    assert {d["id"] for d in mpb.decisions_view(church(db), {"id": who(db, "marcus")})["decisions"]} <= {vote}


# ─── Called off ──────────────────────────────────────────────────────

def _call_off(db, mid):
    """Nothing calls a meeting off before S3-3: as the database would hold it."""
    m = next(x for x in db.t["church_board_meetings"] if x["id"] == mid)
    m.update(cancelled_at=fake.NOW.isoformat(), cancelled_by=c3.church(db, LC)["owner_id"])


def test_a_called_off_meeting_is_never_the_next_and_takes_no_step(app, db):
    eb = elder_board(db)["id"]
    soon = ok(set_meeting(app, f"group:{eb}", "Soon"))["meeting"]["id"]
    later = ok(set_meeting(app, f"group:{eb}", "Later", when=LATER))["meeting"]["id"]
    _call_off(db, soon)
    page = ok(app.get(f"/church/board?business_id={LC}"))
    assert page["next"][eb] == later
    off = next(m for m in page["meetings"] if m["id"] == soon)
    assert off["called_off"] is True and off["state_words"] == "Called off"
    view = mpb.board_view(church(db), {"id": who(db, "marcus")})
    assert [m["id"] for m in view["coming"]] == [later] and view["chosen"]["meeting"]["id"] == later
    r = app.patch(f"/church/board/meetings/{soon}", json={"business_id": LC, "status": "in_progress"})
    assert r.status_code == 409 and r.json()["detail"] == cmt.CALLED_OFF
    assert app.post(f"/church/board/meetings/{soon}/carry", json={"business_id": LC}).status_code == 409
    r = answer(app, soon, member_id=seat_of(db, eb, "marcus")["id"], answer="yes")
    assert r.status_code == 409 and r.json()["detail"] == cmt.CALLED_OFF
    # Minutes can't be approved in a meeting called off.
    first = ok(set_meeting(app, f"group:{eb}", "First", when="2026-11-01T00:00:00+00:00"))["meeting"]["id"]
    for step in ("in_progress", "drafted"):
        ok(app.patch(f"/church/board/meetings/{first}", json={"business_id": LC, "status": step}))
    r = app.post(f"/church/board/meetings/{first}/approve", json={"business_id": LC, "in_meeting_id": soon})
    assert r.status_code == 400 and "called off" in r.json()["detail"]
    ok(app.post(f"/church/board/meetings/{first}/approve", json={"business_id": LC, "in_meeting_id": later}))


def test_ending_a_meeting_carries_its_open_items_to_the_next_not_called_off(app, db):
    eb = elder_board(db)["id"]
    first = ok(set_meeting(app, f"group:{eb}", "First", when="2026-11-17T00:00:00+00:00"))["meeting"]["id"]
    off = ok(set_meeting(app, f"group:{eb}", "Off", when=NEXT_WEEK))["meeting"]["id"]
    nxt = ok(set_meeting(app, f"group:{eb}", "Next", when=LATER))["meeting"]["id"]
    _call_off(db, off)
    item = ok(app.post(f"/church/board/meetings/{first}/items", json={"business_id": LC, "title": "Roof bids"}))["item"]
    ok(app.patch(f"/church/board/items/{item}", json={"business_id": LC, "status": "tabled"}))
    ok(app.patch(f"/church/board/meetings/{first}", json={"business_id": LC, "status": "in_progress"}))
    ended = ok(app.patch(f"/church/board/meetings/{first}", json={"business_id": LC, "status": "drafted"}))
    assert ended["carried_on"] == 1
    carried = [i for i in db.t["church_board_items"] if i.get("carried_from") == item]
    assert [i["meeting_id"] for i in carried] == [nxt], "never into the one called off"


# ─── Answers and the note ────────────────────────────────────────────

def test_answers_and_who_reads_the_note(app, db):
    got = ok(set_meeting(app))
    gid, mid = got["board"]["id"], got["meeting"]["id"]
    lc = church(db)
    mine = cmt.person_answer(lc, who(db, "andre"), mid, "cant", "  Surgery that week  ")
    assert mine == {"meeting_id": mid, "answer": "cant", "note": "Surgery that week", "coming": 0, "open": True,
                    "why": None}
    cmt.person_answer(lc, who(db, "gloria"), mid, "yes")
    row = next(a for a in db.t["church_meeting_answers"] if a["member_id"] == seat_of(db, gid, "andre")["id"])
    assert row["by_contact_id"] == who(db, "andre") and row["by_user_id"] is None
    assert row["for_starts_at"] == NEXT_WEEK
    # Another person in the meeting, in the member app: their own answer and a count, never who can't.
    assert cmt.person_view(lc, who(db, "gloria"), mid) == {"meeting_id": mid, "answer": "yes", "note": None,
                                                           "coming": 1, "open": True, "why": None}

    def note_seen(handle):
        as_(app, LC, handle)
        a = answers(app, mid)
        andre = next(x for x in a["cant"] if x["contact_id"] == who(db, "andre"))
        assert [x["name"] for x in a["coming"]] == ["Gloria Hunt"]
        return andre.get("note")

    # The keepers (the owner, an Admin, the meetings duty) and whoever oversees the office.
    for handle in ("owner", "minnie", "naiya", "jessica"):
        assert note_seen(handle) == "Surgery that week", handle
    # Anyone else on the meeting reads the names, never the note.
    for handle in ("tiara", "laquesha", "shapretta"):
        assert note_seen(handle) is None, handle
    # The person who wrote one reads their own back; the others still don't.
    as_(app, LC, "tiara")
    assert ok(answer(app, mid, answer="cant", note="Kids camp"))["mine"]["note"] == "Kids camp"
    assert next(x for x in answers(app, mid)["cant"] if x["contact_id"] == who(db, "tiara"))["note"] == "Kids camp"
    as_(app, LC, "laquesha")
    assert "note" not in next(x for x in answers(app, mid)["cant"] if x["contact_id"] == who(db, "tiara"))
    as_(app, LC, "jessica")
    assert next(x for x in answers(app, mid)["cant"] if x["contact_id"] == who(db, "tiara"))["note"] == "Kids camp"
    assert cmt.person_view(lc, who(db, "gloria"), mid)["note"] is None
    # Waiting: everyone else (Andre, Gloria and Tiara answered).
    as_(app, LC, "owner")
    a = answers(app, mid)
    assert len(a["waiting"]) == len(LEADERS) - 3 and a["moved"] is False


def test_whoever_oversees_the_office_reads_the_note_without_keeping_the_meetings(app, db):
    import church_duties
    got = ok(set_meeting(app))
    mid = got["meeting"]["id"]
    cmt.person_answer(church(db), who(db, "andre"), mid, "cant", "Surgery that week")
    # The meetings duty moved to Naiya alone: Jessica oversees the office and keeps no meetings.
    db.t["church_duty_holders"].append({"business_id": LC, "duty": "meetings", "user_id": who(db, "naiya@")})
    church_duties._CACHE.clear()
    as_(app, LC, "jessica")
    from auth_supabase import AuthedUser
    me = cb._access(LC, AuthedUser(id=who(db, "jessica@"), email=app.who["email"], role="authenticated"))
    assert me["boss"] is False and who(db, "jessica@") in __import__("church_schedule").office_overseers(
        co.Church(church(db)))
    andre = next(x for x in answers(app, mid)["cant"] if x["contact_id"] == who(db, "andre"))
    assert andre["note"] == "Surgery that week"


def test_the_login_that_set_the_meeting_reads_the_note(app, db):
    lc = church(db)
    andre = fake.seat(db, LC, "andre", role="member")
    tasha = fake.seat(db, LC, "tasha", role="member")
    group = ok(app.post("/church/board/boards", json={"business_id": LC, "name": "Youth check-in",
                                                      "kind": "meeting"}))["board"]
    assert group["kind"] == "meeting" and group["audience"] == "members" and group["quorum"] is None
    for h in ("andre", "tasha", "gloria"):
        ok(app.post(f"/church/board/boards/{group['id']}/members", json={"business_id": LC, "contact_id": who(db, h)}))
    app.who.update(id=andre, email="andre@lovecity.org")
    mid = ok(set_meeting(app, f"group:{group['id']}", "Check-in"))["meeting"]["id"]
    assert next(m for m in db.t["church_board_meetings"] if m["id"] == mid)["created_by"] == andre
    cmt.person_answer(lc, who(db, "gloria"), mid, "cant", "Late shift")
    assert next(x for x in answers(app, mid)["cant"])["note"] == "Late shift"
    app.who.update(id=tasha, email="tasha@lovecity.org")
    assert "note" not in next(x for x in answers(app, mid)["cant"])
    # Tasha, a writer seat here, may mark someone's answer for them; by_user_id says who.
    ok(answer(app, mid, member_id=seat_of(db, group["id"], "andre")["id"], answer="yes"))
    row = next(a for a in db.t["church_meeting_answers"] if a["member_id"] == seat_of(db, group["id"], "andre")["id"])
    assert row["by_user_id"] == tasha and row["by_contact_id"] is None


def test_an_answer_is_yes_or_cant_with_a_short_note_on_cant_only(app, db):
    got = ok(set_meeting(app))
    mid = got["meeting"]["id"]
    for body, code, word in (({"answer": "maybe"}, 400, "I'll be there"), ({"answer": "yes", "note": "Hi"}, 400,
                                                                            "I can't"),
                             ({"answer": "cant", "note": "x" * 201}, 400, "200")):
        r = answer(app, mid, **body)
        assert r.status_code == code and word in r.json()["detail"], r.text
    assert db.t["church_meeting_answers"] == []
    assert ok(answer(app, mid, answer="cant", note="x" * 200))["mine"]["note"] == "x" * 200
    # Changed to yes: the note goes with it.
    a = ok(answer(app, mid, answer="yes"))
    assert a["mine"] == {"member_id": seat_of(db, got["board"]["id"], "kevin")["id"], "answer": "yes", "note": None}
    assert [x["note"] for x in db.t["church_meeting_answers"]] == [None]
    # Taken back.
    assert ok(answer(app, mid, answer=None))["mine"]["answer"] is None
    assert db.t["church_meeting_answers"] == []


def test_an_answer_counts_for_the_time_it_was_given_for(app, db):
    got = ok(set_meeting(app))
    gid, mid = got["board"]["id"], got["meeting"]["id"]
    ok(answer(app, mid, member_id=seat_of(db, gid, "andre")["id"], answer="cant", note="Away"))
    ok(app.patch(f"/church/board/meetings/{mid}", json={"business_id": LC, "starts_at": LATER}))
    a = answers(app, mid)
    assert a["moved"] is True and a["cant"] == []
    andre = next(x for x in a["waiting"] if x["contact_id"] == who(db, "andre"))
    assert andre["said_before"] == "cant" and "note" not in andre
    assert len(db.t["church_meeting_answers"]) == 1, "nothing is deleted"


def test_who_may_answer_and_when(app, db):
    got = ok(set_meeting(app))
    gid, mid = got["board"]["id"], got["meeting"]["id"]
    # Not in it.
    as_(app, LC, "minnie")
    ok(answer(app, mid, answer="yes"))                            # she is: the office is on the leaders list
    calvin = fake.seat(db, LC, "calvin", role="viewer")            # a login on no board, not on the list
    app.who.update(id=calvin, email="calvin@lovecity.org")
    r = app.put(f"/church/meetings/{mid}/answers", json={"business_id": LC, "answer": "yes"})
    assert r.status_code == 403
    as_(app, LC, "naiya")                                         # a keeper, with a seat of her own
    r = answer(app, mid, member_id=c3.uid(1, 77), answer="yes")
    assert r.status_code == 400 and r.json()["detail"] == cmt.THEY_NOT_IN
    as_(app, LC, "owner")
    # A seat that has left doesn't answer.
    unlist(db, "gloria")
    r = answer(app, mid, member_id=seat_of(db, gid, "gloria")["id"], answer="yes")
    assert r.status_code == 409 and r.json()["detail"] == cmt.LEFT
    # A meeting that has started, or is over, takes no answer.
    started = ok(set_meeting(app, when=EARLIER_TODAY))["meeting"]["id"]
    r = answer(app, started, answer="yes")
    assert r.status_code == 409 and r.json()["detail"] == cmt.STARTED
    assert answers(app, started)["open"] is False
    with pytest.raises(HTTPException) as e:
        cmt.person_answer(church(db), who(db, "andre"), started, "yes")
    assert e.value.status_code == 409
    # The member side: someone not in it, a 404; the switch closed, a 404.
    with pytest.raises(HTTPException) as e:
        cmt.person_view(church(db), who(db, "calvin"), mid)
    assert e.value.status_code == 404


def test_the_member_side_is_closed_with_the_switch(app, db, monkeypatch):
    mid = ok(set_meeting(app))["meeting"]["id"]
    monkeypatch.setenv("CHURCH_MEETINGS", "off")
    db.reads.clear()
    for fn in (lambda: cmt.person_view(church(db), who(db, "andre"), mid),
               lambda: cmt.person_answer(church(db), who(db, "andre"), mid, "yes")):
        with pytest.raises(HTTPException) as e:
            fn()
        assert e.value.status_code == 404
    assert db.reads == []


def test_a_failed_answer_write_is_a_503_and_nothing_changes(app, db):
    mid = ok(set_meeting(app))["meeting"]["id"]
    db.fail = {"post": "/church_meeting_answers"}
    r = answer(app, mid, answer="yes")
    assert r.status_code == 503 and r.json()["detail"] == cmt.UNSAVED
    assert db.t["church_meeting_answers"] == []


# ─── The end of a meeting, its minutes, its quorum ───────────────────

def test_i_cant_reads_as_excused_when_the_meeting_ends(app, db):
    got = ok(set_meeting(app))
    gid, mid = got["board"]["id"], got["meeting"]["id"]
    lc = church(db)
    cmt.person_answer(lc, who(db, "andre"), mid, "cant", "Surgery that week")
    cmt.person_answer(lc, who(db, "gloria"), mid, "yes")
    # Ruth said she can't for the old time: that's no answer now.
    cmt.person_answer(lc, who(db, "ruth"), mid, "cant")
    next(a for a in db.t["church_meeting_answers"]
         if a["member_id"] == seat_of(db, gid, "ruth")["id"])["for_starts_at"] = LATER
    ok(app.patch(f"/church/board/meetings/{mid}", json={"business_id": LC, "status": "in_progress"}))
    ok(app.patch(f"/church/board/meetings/{mid}", json={"business_id": LC, "status": "drafted"}))
    marks = {a["member_id"]: a["status"] for a in db.t["church_board_attendance"] if a["meeting_id"] == mid}
    assert marks[seat_of(db, gid, "andre")["id"]] == "excused"
    assert marks[seat_of(db, gid, "gloria")["id"]] == "absent", "unmarked: absent, as always"
    assert marks[seat_of(db, gid, "ruth")["id"]] == "absent"
    # The minutes go to its seats to read; the note is never in them.
    db.t["contacts"] = [dict(c, email=c.get("email") or "x@lovecity.org") for c in db.t["contacts"]]
    sent = ok(app.post(f"/church/board/meetings/{mid}/send", json={"business_id": LC}))
    assert sent["sent"] == len(LEADERS) == len(db.sent)
    assert all(m["subject"].startswith("Minutes: Leaders meeting") and m.get("reading") is True for m in db.sent)
    assert all("Surgery" not in m["text"] and "Quorum" not in m["text"] and "to read" in m["text"] for m in db.sent)
    # The keepers approve them with one press, no vote, no later meeting.
    as_(app, LC, "tiara")
    assert app.post(f"/church/board/meetings/{mid}/approve", json={"business_id": LC}).status_code == 403
    as_(app, LC, "naiya")
    assert ok(app.post(f"/church/board/meetings/{mid}/approve", json={"business_id": LC}))["meeting"]["status"] == \
        "approved"


def test_a_meeting_group_has_a_quorum_line_only_when_the_keepers_set_a_count(app, db):
    got = ok(set_meeting(app))
    gid, mid = got["board"]["id"], got["meeting"]["id"]
    assert open_page(app, mid)["quorum"] is None
    mark = ok(app.put(f"/church/board/meetings/{mid}/attendance",
                      json={"business_id": LC, "member_id": seat_of(db, gid, "andre")["id"], "status": "present"}))
    assert mark["quorum"] is None
    board = ok(app.patch(f"/church/board/boards/{gid}", json={"business_id": LC, "quorum_kind": "count",
                                                              "quorum_count": 5}))["board"]
    assert board["quorum"] == 5 and board["quorum_words"] == "5 present"
    assert open_page(app, mid)["quorum"]["needed"] == 5
    # The board's own line, as ever.
    eb = elder_board(db)["id"]
    assert ok(set_meeting(app, f"group:{eb}", "Elders"))["quorum"]["needed"] == 2


def test_a_group_for_the_list_keeps_its_kind_and_a_name_an_open_one_has(app, db):
    a = ok(set_meeting(app))["board"]
    b = ok(set_meeting(app, name="Leaders retreat"))["board"]
    r = app.patch(f"/church/board/boards/{b['id']}", json={"business_id": LC, "name": "LEADERS MEETING"})
    assert r.status_code == 409 and r.json()["detail"] == "There's already a meeting called LEADERS MEETING."
    ok(app.patch(f"/church/board/boards/{a['id']}", json={"business_id": LC, "archived": True}))
    ok(app.patch(f"/church/board/boards/{b['id']}", json={"business_id": LC, "name": "Leaders meeting"}))
    r = app.patch(f"/church/board/boards/{a['id']}", json={"business_id": LC, "archived": False})
    assert r.status_code == 409 and r.json()["detail"] == "There's already a meeting called Leaders meeting."
    r = app.patch(f"/church/board/boards/{b['id']}", json={"business_id": LC, "kind": "board"})
    assert r.status_code == 409
    assert next(x for x in db.t["church_boards"] if x["id"] == b["id"])["kind"] == "meeting"
    # A check-in is held to meeting by the server alone; making it a board is the keepers' choice.
    c = ok(app.post("/church/board/boards", json={"business_id": LC, "name": "Check-in", "kind": "meeting"}))["board"]
    assert ok(app.patch(f"/church/board/boards/{c['id']}", json={"business_id": LC, "kind": "board"}))["board"][
        "kind"] == "board"
    assert app.post("/church/board/boards", json={"business_id": LC, "name": "X", "kind": "club"}).status_code == 400


def test_the_routes_are_mounted_before_the_catch_all_and_need_a_sign_in():
    os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
    os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test")
    from fastapi.testclient import TestClient
    import kmj_intake_automation

    paths = [getattr(r, "path", "") for r in kmj_intake_automation.app.routes]
    for p in ("/church/meetings", "/church/meetings/{meeting_id}/answers"):
        assert p in paths and paths.index(p) < paths.index("/{path:path}"), p
    c = TestClient(kmj_intake_automation.app)
    assert c.get(f"/church/meetings/{c3.uid(1, 1)}/answers?business_id={LC}").status_code in (401, 403)
    assert c.post("/church/meetings", json={"business_id": LC}).status_code in (401, 403)
