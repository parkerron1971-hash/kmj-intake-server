"""church_board.py's checklist for step 3 (docs/CHURCH_SCHEDULE.md 10.2, PR
S3-2): each function the design names, in its reader table and in the first
four of "What the old code must learn", has a test here with a meeting group
(the leaders meeting, which follows the leaders list) and with a meeting
called off, or says why one of the two can't apply to it. CHECKLIST is the
list; test_the_checklist_is_whole holds it to church_board.py and to the
tests in this file.

Made-up people at Love City (church_three), on the fake with step 3's file
(church_schedule_fake.build(meetings=True)). Nothing calls a meeting off
before S3-3, so a meeting is called off here as the database would hold it.
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
import church_meetings as cmt  # noqa: E402
import church_schedule_fake as fake  # noqa: E402
import church_three as c3  # noqa: E402
import member_portal_board as mpb  # noqa: E402
from church_schedule_fake import as_  # noqa: E402
from church_three import LOVE_CITY as LC  # noqa: E402

NEXT_WEEK = "2026-11-24T00:00:00+00:00"
LATER = "2026-12-01T00:00:00+00:00"
LAST_WEEK = "2026-11-10T00:00:00+00:00"

# function -> (its test with a meeting group, its test with a meeting called off)
# A string that isn't a test's name says why that half can't apply.
CHECKLIST = {
    "_access": ("test_a_list_seat_is_mine_and_listed", "n/a: who a login is, before any meeting"),
    "groups_of_login": ("test_a_list_seat_is_mine_and_listed", "n/a: seats, not meetings"),
    "_boards": ("test_groups_carry_kind_and_audience", "n/a: groups, not meetings"),
    "_board": ("test_groups_carry_kind_and_audience", "n/a: groups, not meetings"),
    "may_write": ("test_a_list_seat_is_mine_and_listed", "n/a: groups, not meetings"),
    "board_view": ("test_no_quorum_line_for_a_meeting_group", "n/a: groups, not meetings"),
    "add_member": ("test_seats_on_a_list_group_are_the_lists", "n/a: seats, not meetings"),
    "edit_member": ("test_seats_on_a_list_group_are_the_lists", "n/a: seats, not meetings"),
    "meeting_fields": ("test_page_and_summary", "test_page_and_summary"),
    "meeting_summary": ("test_page_and_summary", "test_page_and_summary"),
    "page": ("test_page_and_summary", "test_page_and_summary"),
    "meeting_page": ("test_no_quorum_line_for_a_meeting_group", "test_a_called_off_meeting_page"),
    "quorum_of": ("test_no_quorum_line_for_a_meeting_group", "n/a: a group's quorum, not a meeting's"),
    "mark": ("test_no_quorum_line_for_a_meeting_group", "n/a: attendance answers the group's quorum"),
    "minutes_text": ("test_send_minutes", "n/a: a meeting called off has no minutes (it is planned)"),
    "send_minutes": ("test_send_minutes", "test_send_minutes"),
    "decisions_log": ("test_decisions_log", "test_decisions_log"),
    "edit_meeting": ("test_edit_meeting", "test_edit_meeting"),
    "approve": ("test_approve", "test_approve"),
    "carry_forward": ("test_carry", "test_carry"),
    "carry_on": ("test_carry", "test_carry"),
    "_mark_rest_absent": ("test_end_marks_cant_excused", "n/a: a meeting called off can't be ended (edit_meeting)"),
    "add_meeting": ("test_add_meeting_on_a_list_group", "n/a: a new meeting is never called off"),
}


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


def who(db, h):
    return db.who[LC][h]


def elder_board(db):
    return next(b for b in db.t["church_boards"] if b["business_id"] == LC and b["name"] == "Elder Board")


def leaders(app, when=NEXT_WEEK):
    return ok(app.post("/church/meetings", json={"business_id": LC, "who": "leaders", "name": "Leaders meeting",
                                                 "starts_at": when}))


def board_meeting(app, gid, when=NEXT_WEEK, title=""):
    return ok(app.post("/church/meetings", json={"business_id": LC, "who": f"group:{gid}", "name": title,
                                                 "starts_at": when}))["meeting"]["id"]


def call_off(db, mid):
    m = next(x for x in db.t["church_board_meetings"] if x["id"] == mid)
    m.update(cancelled_at=fake.NOW.isoformat(), cancelled_by=c3.church(db, LC)["owner_id"])


def seats_of(db, gid):
    return [s for s in db.t["church_board_members"] if s["board_id"] == gid and s.get("active") is not False]


def seat(db, gid, h):
    return next(s for s in db.t["church_board_members"] if s["board_id"] == gid and s["contact_id"] == who(db, h))


def steps(app, mid, *to):
    for s in to:
        ok(app.patch(f"/church/board/meetings/{mid}", json={"business_id": LC, "status": s}))


def test_the_checklist_is_whole():
    names = dict(globals())
    for fn, halves in CHECKLIST.items():
        assert callable(getattr(cb, fn, None)), f"church_board.{fn} is gone: the checklist follows the code"
        for h in halves:
            assert h.startswith("n/a: ") and len(h) > 12 or callable(names.get(h)), (fn, h)
    assert any(not h.startswith("n/a") for halves in CHECKLIST.values() for h in halves[1:])


def test_a_list_seat_is_mine_and_listed(app, db):
    g = leaders(app)["board"]
    as_(app, LC, "tiara")
    me = cb._access(LC, cb_user(app))
    assert g["id"] in me["mine"] and g["id"] in me["listed"] and cb.groups_of_login(LC, who(db, "tiara@")) == {g["id"]}
    assert cb.may_write(me, g["id"]) is False, "a seat the list gave reads, never writes"
    as_(app, LC, "naiya")
    keeper = cb._access(LC, cb_user(app))
    assert keeper["boss"] and cb.may_write(keeper, g["id"])
    # A member seat on a board still writes it, as ever.
    andre = fake.seat(db, LC, "andre", role="member")
    as_(app, LC, "owner")
    eb = elder_board(db)
    ok(app.post(f"/church/board/boards/{eb['id']}/members", json={"business_id": LC, "contact_id": who(db, "andre")}))
    app.who.update(id=andre, email="andre@lovecity.org")
    me = cb._access(LC, cb_user(app))
    assert cb.may_write(me, eb["id"]) and not cb.may_write(me, g["id"])


def cb_user(app):
    from auth_supabase import AuthedUser
    return AuthedUser(id=app.who["id"], email=app.who["email"], role="authenticated")


def test_groups_carry_kind_and_audience(app, db):
    g = leaders(app)["board"]
    me = cb._access(LC, cb_user(app))
    got = {b["id"]: (b["kind"], b["audience"]) for b in cb._boards(me)}
    assert got == {elder_board(db)["id"]: ("board", "members"), g["id"]: ("meeting", "leaders")}
    assert cb._board(me, g["id"])["audience"] == "leaders" and me["audience"][g["id"]] == "leaders"
    page = ok(app.get(f"/church/board?business_id={LC}"))
    assert {(b["kind"], b["audience"], b["follows_list"]) for b in page["boards"]} == {
        ("board", "members", False), ("meeting", "leaders", True)}


def test_seats_on_a_list_group_are_the_lists(app, db):
    g = leaders(app)["board"]
    r = app.post(f"/church/board/boards/{g['id']}/members", json={"business_id": LC, "contact_id": who(db, "calvin")})
    assert r.status_code == 409 and r.json()["detail"] == cmt.FOLLOWS_LIST
    r = app.patch(f"/church/board/members/{seat(db, g['id'], 'andre')['id']}", json={"business_id": LC, "title": "X"})
    assert r.status_code == 409 and seat(db, g["id"], "andre")["title"] == ""


def test_page_and_summary(app, db):
    g = leaders(app)
    eb = elder_board(db)["id"]
    off = board_meeting(app, eb, NEXT_WEEK, "Off")
    nxt = board_meeting(app, eb, LATER, "Next")
    call_off(db, off)
    me = cb._access(LC, cb_user(app))
    m = cb._meeting(me, off)
    assert {"cancelled_at", "series_id", "series_day", "length_minutes"} <= set(m), "meeting_fields names them"
    assert cb.meeting_fields().endswith(cmt.MEETING_COLS)
    page = cb.page(me)
    assert page["next"] == {eb: nxt, g["board"]["id"]: g["meeting"]["id"]}
    s = {x["id"]: x for x in page["meetings"]}
    assert s[off]["called_off"] and s[off]["state_words"] == "Called off"
    assert not s[nxt]["called_off"] and s[nxt]["state_words"] == "Planned"
    # The member Board tab: never "the next meeting".
    view = mpb.board_view(c3.church(db, LC), {"id": who(db, "marcus")})
    assert [x["id"] for x in view["coming"]] == [nxt]
    assert mpb.boards_of(LC, who(db, "andre")) == set(), "the leaders meeting is no Board tab"


def test_no_quorum_line_for_a_meeting_group(app, db):
    g = leaders(app)
    gid, mid = g["board"]["id"], g["meeting"]["id"]
    assert g["board"]["quorum_shown"] is False and g["quorum_shown"] is False
    assert set(g["quorum"]) == {"kind", "count", "needed", "present", "total", "met"} and g["quorum"]["total"] == len(seats_of(db, gid))
    mark = ok(app.put(f"/church/board/meetings/{mid}/attendance",
                      json={"business_id": LC, "member_id": seat(db, gid, "andre")["id"], "status": "present"}))
    assert mark["quorum_shown"] is False and set(mark["quorum"]) == {"kind", "count", "needed", "present", "total", "met"}
    me = cb._access(LC, cb_user(app))
    assert cb.quorum_of({"kind": "meeting", "quorum_kind": "count", "quorum_count": 3}, 10, 2)["needed"] == 3
    assert cb.has_quorum(cb._board(me, gid)) is False and cb.quorum_of(cb._board(me, gid), 10, 2)["needed"] == 6
    assert cb.has_quorum({"kind": "meeting", "quorum_kind": "count", "quorum_count": 3}) is True
    assert cb.quorum_of(elder_board(db), 2, 2)["met"] is True


def test_a_called_off_meeting_page(app, db):
    eb = elder_board(db)["id"]
    mid = board_meeting(app, eb)
    call_off(db, mid)
    page = ok(app.get(f"/church/board/meetings/{mid}?business_id={LC}"))
    assert page["meeting"]["called_off"] is True and page["can"]["notice"] is False


def test_send_minutes(app, db):
    g = leaders(app)
    mid = g["meeting"]["id"]
    steps(app, mid, "in_progress")
    sent = ok(app.post(f"/church/board/meetings/{mid}/send", json={"business_id": LC}))
    assert sent["sent"] > 0 and all(m.get("reading") is True and m["subject"].startswith("Minutes: ") for m in db.sent)
    assert all("The minutes, to read" in m["text"] and "Quorum" not in m["text"] for m in db.sent)
    db.sent.clear()
    eb = elder_board(db)["id"]
    board = board_meeting(app, eb, LAST_WEEK)
    steps(app, board, "in_progress")
    ok(app.post(f"/church/board/meetings/{board}/send", json={"business_id": LC}))
    assert db.sent and all("reading" not in m and m["subject"].startswith("Draft minutes: ") for m in db.sent)
    assert all("Draft, for the board's approval" in m["text"] and "Quorum:" in m["text"] for m in db.sent)
    off = board_meeting(app, eb, LATER)
    call_off(db, off)
    assert app.post(f"/church/board/meetings/{off}/send", json={"business_id": LC}).status_code == 409


def _decide(app, mid, motion):
    item = ok(app.post(f"/church/board/meetings/{mid}/items", json={"business_id": LC, "title": motion}))["item"]
    ok(app.post(f"/church/board/items/{item}/decisions", json={"business_id": LC, "motion": motion,
                                                               "result": "carried"}))
    return next(d["id"] for d in app.db.t["church_board_decisions"] if d["item_id"] == item)


def test_decisions_log(app, db):
    g = leaders(app)
    huddle = _decide(app, g["meeting"]["id"], "Paint the nursery")
    eb = elder_board(db)["id"]
    off = board_meeting(app, eb, NEXT_WEEK)
    recorded = _decide(app, off, "Roof deposit")
    call_off(db, off)
    log = ok(app.get(f"/church/board/decisions?business_id={LC}"))["decisions"]
    assert [d["id"] for d in log] == [recorded], "the boards' log: never the huddle's; a decision stays recorded"
    own = ok(app.get(f"/church/board/decisions?business_id={LC}&board_id={g['board']['id']}"))["decisions"]
    assert [d["id"] for d in own] == [huddle]


def test_edit_meeting(app, db):
    g = leaders(app)
    mid = g["meeting"]["id"]
    as_(app, LC, "tiara")
    assert app.patch(f"/church/board/meetings/{mid}", json={"business_id": LC, "title": "Mine"}).status_code == 403
    as_(app, LC, "owner")
    ok(app.patch(f"/church/board/meetings/{mid}", json={"business_id": LC, "length_minutes": 45}))
    assert next(m for m in db.t["church_board_meetings"] if m["id"] == mid)["length_minutes"] == 45
    off = board_meeting(app, elder_board(db)["id"], LATER)
    call_off(db, off)
    for to in ("in_progress", "drafted"):
        r = app.patch(f"/church/board/meetings/{off}", json={"business_id": LC, "status": to})
        assert r.status_code == 409 and r.json()["detail"] == cmt.CALLED_OFF
    assert not [w for w in db.refused if "called_off" in w], "refused in plain words before the database's check"


def test_approve(app, db):
    g = leaders(app, LAST_WEEK)
    mid = g["meeting"]["id"]
    steps(app, mid, "in_progress", "drafted")
    as_(app, LC, "tiara")
    assert app.post(f"/church/board/meetings/{mid}/approve", json={"business_id": LC}).status_code == 403
    as_(app, LC, "minnie")
    ok(app.post(f"/church/board/meetings/{mid}/approve", json={"business_id": LC}))
    # A check-in's own writer seat runs the meeting, but its minutes are the keepers' to approve.
    andre = fake.seat(db, LC, "andre", role="member")
    as_(app, LC, "owner")
    group = ok(app.post("/church/board/boards", json={"business_id": LC, "name": "Youth check-in",
                                                      "kind": "meeting"}))["board"]
    ok(app.post(f"/church/board/boards/{group['id']}/members", json={"business_id": LC, "contact_id": who(db, "andre")}))
    app.who.update(id=andre, email="andre@lovecity.org")
    check = board_meeting(app, group["id"], LAST_WEEK)
    steps(app, check, "in_progress", "drafted")
    r = app.post(f"/church/board/meetings/{check}/approve", json={"business_id": LC})
    assert r.status_code == 403 and "approves a meeting's minutes" in r.json()["detail"]
    as_(app, LC, "naiya")
    assert ok(app.post(f"/church/board/meetings/{check}/approve",
                       json={"business_id": LC}))["meeting"]["status"] == "approved"
    as_(app, LC, "owner")
    eb = elder_board(db)["id"]
    first = board_meeting(app, eb, LAST_WEEK)
    off = board_meeting(app, eb, NEXT_WEEK)
    steps(app, first, "in_progress", "drafted")
    call_off(db, off)
    r = app.post(f"/church/board/meetings/{first}/approve", json={"business_id": LC, "in_meeting_id": off})
    assert r.status_code == 400 and "called off" in r.json()["detail"]


def test_carry(app, db):
    g = leaders(app, LAST_WEEK)
    gid, first = g["board"]["id"], g["meeting"]["id"]
    item = ok(app.post(f"/church/board/meetings/{first}/items", json={"business_id": LC, "title": "Snacks rota"}))["item"]
    ok(app.patch(f"/church/board/items/{item}", json={"business_id": LC, "status": "follow_up"}))
    off = leaders(app, NEXT_WEEK)["meeting"]["id"]
    copy = next(i for i in db.t["church_board_items"] if i.get("carried_from") == item)
    assert copy["meeting_id"] == off, "the huddle's open items carry within the huddle"
    call_off(db, off)
    # Tabled after the next one was made: still open, not yet carried anywhere.
    late = ok(app.post(f"/church/board/meetings/{first}/items", json={"business_id": LC, "title": "Parking"}))["item"]
    ok(app.patch(f"/church/board/items/{late}", json={"business_id": LC, "status": "tabled"}))
    r = app.post(f"/church/board/meetings/{off}/carry", json={"business_id": LC})
    assert r.status_code == 409 and r.json()["detail"] == cmt.CALLED_OFF
    me = cb._access(LC, cb_user(app))
    assert cb.carry_forward(me, cb._meeting(me, off)) == 0, "a meeting called off takes nothing"
    assert not [i for i in db.t["church_board_items"] if i.get("carried_from") == late]
    # What was carried into the meeting called off carries on to the next, with what waited.
    nxt = leaders(app, LATER)["meeting"]["id"]
    on = [i for i in db.t["church_board_items"] if i.get("carried_from") in (copy["id"], late)]
    assert sorted((i["meeting_id"], i["title"]) for i in on) == [(nxt, "Parking"), (nxt, "Snacks rota")]
    assert all(m["board_id"] == gid for m in db.t["church_board_meetings"] if m["id"] in (first, off, nxt))


def test_end_marks_cant_excused(app, db):
    g = leaders(app)
    gid, mid = g["board"]["id"], g["meeting"]["id"]
    cmt.person_answer(c3.church(db, LC), who(db, "andre"), mid, "cant", "Away")
    next(m for m in db.t["church_board_meetings"] if m["id"] == mid)["starts_at"] = NEXT_WEEK
    steps(app, mid, "in_progress", "drafted")
    marks = {a["member_id"]: a["status"] for a in db.t["church_board_attendance"] if a["meeting_id"] == mid}
    assert marks[seat(db, gid, "andre")["id"]] == "excused" and marks[seat(db, gid, "tanya")["id"]] == "absent"


def test_add_meeting_on_a_list_group(app, db):
    g = leaders(app)["board"]
    as_(app, LC, "tiara")
    r = app.post("/church/board/meetings", json={"business_id": LC, "board_id": g["id"], "starts_at": LATER})
    assert r.status_code == 403
    as_(app, LC, "owner")
    assert ok(app.post("/church/board/meetings", json={"business_id": LC, "board_id": g["id"],
                                                       "starts_at": LATER}))["meeting"]["called_off"] is False


# ─── Before the file: the same flows read and answer as they always did ───

def _flow(monkeypatch, force):
    """Board & minutes end to end on the database before step 3's file:
    a board and its people, two meetings, an agenda carried, a decision,
    the end, the minutes sent and approved, the log, and every reader that
    means a board. `force` False is the tables pinned as not there (the
    old reads, nothing named); None is production, which names step 3's
    columns and falls back when the database says they aren't there."""
    import church_map
    import church_money_levels as cml
    import housing_allowance as ha
    d = fake.build(monkeypatch, meetings=False)
    monkeypatch.setattr(cmt, "_FORCE", force)
    monkeypatch.setattr(cmt, "_STATE", {"yes": None, "at": 0.0})
    a = fake.meetings_client(d)
    as_(a, LC, "owner")
    out = {}
    board = ok(a.post("/church/board/boards", json={"business_id": LC, "name": "Deacons"}))["board"]
    bid = board["id"]
    r = a.post("/church/board/boards", json={"business_id": LC, "name": "Huddle", "kind": "meeting"})
    out["meeting_kind"] = (r.status_code, r.json())
    r = a.patch(f"/church/board/boards/{bid}", json={"business_id": LC, "kind": "meeting"})
    out["edit_kind"] = (r.status_code, r.json())
    seat = ok(a.post(f"/church/board/boards/{bid}/members", json={"business_id": LC, "contact_id": who(d, "marcus")}))
    ok(a.post(f"/church/board/boards/{bid}/members", json={"business_id": LC, "contact_id": who(d, "tanya")}))
    out["edit_member"] = ok(a.patch(f"/church/board/members/{seat['member']['id']}",
                                    json={"business_id": LC, "title": "Chair"}))
    out["edit_board"] = ok(a.patch(f"/church/board/boards/{bid}", json={"business_id": LC, "name": "Deacons"}))
    first = ok(a.post("/church/board/meetings", json={"business_id": LC, "board_id": bid, "starts_at": LAST_WEEK}))
    fid = first["meeting"]["id"]
    item = ok(a.post(f"/church/board/meetings/{fid}/items", json={"business_id": LC, "title": "Roof bids"}))["item"]
    ok(a.patch(f"/church/board/items/{item}", json={"business_id": LC, "status": "tabled"}))
    vote = ok(a.post(f"/church/board/meetings/{fid}/items", json={"business_id": LC, "title": "Housing"}))["item"]
    out["decided"] = ok(a.post(f"/church/board/items/{vote}/decisions",
                               json={"business_id": LC, "motion": "Housing allowance", "result": "carried"}))
    nxt = ok(a.post("/church/board/meetings", json={"business_id": LC, "board_id": bid, "starts_at": NEXT_WEEK}))
    out["next_made"] = nxt
    out["carry"] = ok(a.post(f"/church/board/meetings/{nxt['meeting']['id']}/carry", json={"business_id": LC}))
    ok(a.put(f"/church/board/meetings/{fid}/attendance",
             json={"business_id": LC, "member_id": seat["member"]["id"], "status": "present"}))
    out["started"] = ok(a.patch(f"/church/board/meetings/{fid}", json={"business_id": LC, "status": "in_progress"}))
    out["ended"] = ok(a.patch(f"/church/board/meetings/{fid}", json={"business_id": LC, "status": "drafted"}))
    out["sent"] = ok(a.post(f"/church/board/meetings/{fid}/send", json={"business_id": LC}))
    out["approved"] = ok(a.post(f"/church/board/meetings/{fid}/approve",
                                json={"business_id": LC, "in_meeting_id": nxt["meeting"]["id"]}))
    out["page"] = ok(a.get(f"/church/board?business_id={LC}"))
    out["meeting_page"] = ok(a.get(f"/church/board/meetings/{fid}?business_id={LC}"))
    out["log"] = ok(a.get(f"/church/board/decisions?business_id={LC}"))
    out["status"] = ok(a.get(f"/church/board/status?business_id={LC}"))
    decision = next(x["id"] for x in d.t["church_board_decisions"] if x["item_id"] == vote)
    out["housing"] = ha._check_links(LC, {"board_decision_id": decision})
    me = {"biz": c3.church(d, LC), "_board_yes": {}}
    out["money"] = (cml._open_boards(me), cml.board_people(me), cml.board({"biz": c3.church(d, LC), "_board_yes": {}}))
    out["tab"] = sorted(mpb.boards_of(LC, who(d, "marcus")))
    out["map"] = church_map._things(LC, "board", [b["id"] for b in d.t["church_boards"]])
    out["attendance"] = sorted((x["member_id"], x["status"]) for x in d.t["church_board_attendance"])
    out["mail"] = [{k: v for k, v in m.items() if k != "key"} for m in d.sent]
    return d, out


def _same_shape(x):
    """Ids made fresh on each run (a carried item, an attendance mark) read
    as their order of first appearance."""
    import json
    import re
    seen = {}
    text = json.dumps(x, sort_keys=True, default=str)
    return re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                  lambda m: seen.setdefault(m.group(0), f"id{len(seen)}"), text)


def test_before_the_file_every_flow_reads_and_answers_as_it_always_did(monkeypatch):
    pinned, old = _flow(monkeypatch, False)
    assert not [w for w in pinned.refused if "step 3" in w], pinned.refused
    news = [r for r in pinned.reads if r.lstrip("/").split("?")[0] in fake.BOARD_TABLES
            and fake.MEET_COLS.search(r.partition("?")[2])]
    assert news == [], "nothing names a step 3 column"
    # The old shapes: no kind, no called off, no quorum flag, no next; I can't marks nobody excused.
    assert "kind" not in old["page"]["boards"][0] and "next" not in old["page"]
    assert "called_off" not in old["meeting_page"]["meeting"] and "quorum_shown" not in old["meeting_page"]
    assert "carried_on" not in old["ended"] and old["carry"]["carried"] == 0, "carried as the next was made"
    assert old["next_made"]["carried"] == 1
    assert {s for _m, s in old["attendance"]} == {"present", "absent"}
    assert old["meeting_kind"][0] == 409 and old["edit_kind"][0] == 409
    assert old["status"]["name"] == "Board & minutes" and old["status"]["meetings"] is False
    assert old["housing"] is None and old["tab"] and old["money"][0]
    assert all(m["subject"].startswith("Draft minutes") and "reading" not in m for m in old["mail"])
    assert [d["motion"] for d in old["log"]["decisions"]] == ["Housing allowance"]
    # Production before the file names step 3's columns, is told they aren't there, and reads the
    # old way: every answer the same.
    probing, new = _flow(monkeypatch, None)
    assert [w for w in probing.refused if "step 3" in w], "it asked with the columns first"
    assert _same_shape(new) == _same_shape(old)
