"""One Visitor flow room (Kevin, 2026-11-21, picked from three options).

"The new room takes the name 'Visitor flow' and its spot. The old chart
moves into its Scorecard tab. The Guests row goes away. Follow-up board
stays for baptism, serve and other cards, and stops listing guests (they're
worked in Visitor flow)." The server's part, pinned here on made-up people:

  1. The board leaves first-time guests to Visitor flow (church_follow_up.board
     skip_guests): not listed, not counted, not in a leader's load, and says
     how many are open there; without it, the board as it always was.
  2. The route asks for that only with guests=room and only for a login that
     has the room (church_guests.room_open); an older app gets today's board.
     leaders_only=true is the Hand to list alone (a guest's sheet hands them
     on through the board's own reassign).
  3. Who has the room: People & care's areas as before, and now whoever makes
     the welcome calls (First-time guests, or the caller of an open guest's
     call), since every guest call's link opens it; a failed read is a 503 in
     the room and a no for the board (which then keeps its guests).
  4. Every link about a guest's call opens Visitor flow: guest_calls' push and
     email (nav operate:guests, "Open Visitor flow"), its words, the sweep's
     office alerts and emails for a guest's follow-up while the path is on,
     My week's First-time guests door and its guests' lines, and Chief's
     place for First-time guests. With the path off, the board, as before.
  5. The room's old id lands on the Visitor flow row (system_destinations),
     and Chief's map reads operate:guests as Visitor flow.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_follow_up as cfu  # noqa: E402
import church_guests as cg  # noqa: E402
import church_router  # noqa: E402
import guest_calls as gc  # noqa: E402
import guest_path  # noqa: E402
from test_church_follow_up import (  # noqa: E402
    ANDRE, BIZ, DANA, KEISHA, MARCUS, OWNER, PASTOR, ROBERT, TASHA, db, outbox)  # noqa: F401

STEPS = [{"title": "Reach out", "rule": "within 2 days", "days": 2},
         {"title": "Invite to a next step", "rule": "a class, a group, or a team", "days": 14}]
CHURCH = {"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": OWNER}


def _fu(db, contact, card_key, *, kind="connect", status="open", leader=ROBERT, late=False, card_name="Card"):
    now = cfu._now()
    row = {"id": str(uuid.uuid4()), "business_id": BIZ, "contact_id": contact, "card_key": card_key,
           "card_name": card_name, "path_kind": kind, "answers": [], "steps": STEPS, "step": 0, "status": status,
           "leader_contact_id": leader, "leader_role": "welcome_lead" if leader else "", "late_level": 0,
           "due_at": cfu._iso(now - timedelta(hours=3) if late else now + timedelta(days=2)),
           "assigned_at": cfu._iso(now), "created_at": cfu._iso(now), "done_at": None, "reason": "",
           "leader_told_at": cfu._iso(now)}
    db.t["church_follow_ups"].append(row)
    return row


@pytest.fixture
def mixed(db):
    """Two guests (the website card, a Plan your visit form) and two other
    cards (a baptism, a serve), with Robert holding the welcome role."""
    return {
        "web": _fu(db, MARCUS, "web:connect_card", late=True),
        "visit": _fu(db, DANA, "form:f-visit", kind="visit", leader=None),
        "baptism": _fu(db, KEISHA, "form:f-baptism", kind="baptism", leader=PASTOR, card_name="Baptism"),
        "serve": _fu(db, ANDRE, "form:f-serve", kind="serve", leader=ROBERT, card_name="Serve with us"),
    }


# ─── 1. The board ─────────────────────────────────────────────────────

def test_the_board_as_it_always_was_lists_every_card(db, mixed):
    b = cfu.board(BIZ)
    assert {i["card_key"] for i in b["follow_ups"]} == {"web:connect_card", "form:f-visit", "form:f-baptism", "form:f-serve"}
    assert b["counts"] == {"open": 4, "with_no_one": 1, "late": 1, "done": 0}
    assert "guests_in_room" not in b
    assert next(l for l in b["leaders"] if l["contact_id"] == ROBERT)["open"] == 2


def test_guests_left_to_visitor_flow_are_not_listed_counted_or_in_a_load(db, mixed):
    b = cfu.board(BIZ, skip_guests=True)
    assert {i["card_key"] for i in b["follow_ups"]} == {"form:f-baptism", "form:f-serve"}
    assert b["counts"] == {"open": 2, "with_no_one": 0, "late": 0, "done": 0}, "the late guest and the guest with no one are Visitor flow's"
    assert b["guests_in_room"] == {"open": 2}
    assert next(l for l in b["leaders"] if l["contact_id"] == ROBERT)["open"] == 1, "Robert's serve card only"
    ids = {i["id"] for i in b["follow_ups"]}
    assert mixed["web"]["id"] not in ids and mixed["visit"]["id"] not in ids


def test_every_guest_door_is_left_off_and_a_general_form_stays(db):
    for key, kind in (("text:new_here", "general"), ("app:new_here", "general"), ("checkin:first", "general"),
                      ("web:connect_card", "connect"), ("form:f-c", "connect"), ("form:f-v", "visit")):
        _fu(db, MARCUS, key, kind=kind)
    _fu(db, MARCUS, "form:f-contact", kind="general")
    b = cfu.board(BIZ, skip_guests=True)
    assert [i["card_key"] for i in b["follow_ups"]] == ["form:f-contact"]
    assert b["guests_in_room"] == {"open": 6}


def test_a_finished_guest_is_not_counted_as_open_in_the_room(db):
    _fu(db, MARCUS, "web:connect_card", status="done")
    db.t["church_follow_ups"][-1]["done_at"] = cfu._iso(cfu._now())
    b = cfu.board(BIZ, skip_guests=True)
    assert b["follow_ups"] == [] and b["guests_in_room"] == {"open": 0} and b["counts"]["done"] == 0


def test_the_hand_to_list_alone_reads_no_card_or_note(db, mixed, monkeypatch):
    read = []
    real = cfu._rows
    monkeypatch.setattr(cfu, "_rows", lambda path: read.append(path) or real(path))
    out = cfu.board(BIZ, leaders_only=True)
    assert set(out) == {"leaders", "leaders_only"}
    assert {l["contact_id"] for l in out["leaders"]} == {
        r["contact_id"] for r in db.t["church_leader_roles"] if r["status"] == "active"}, "everyone holding a role"
    assert next(l for l in out["leaders"] if l["contact_id"] == ROBERT)["open"] == 2, "guests count toward a load here"
    assert not any("church_follow_up_notes" in p or "select=*" in p for p in read), "no card or note is read"


def test_a_board_read_that_fails_is_none(db, mixed, monkeypatch):
    monkeypatch.setattr(cfu, "roles", lambda biz: None)
    assert cfu.board(BIZ, skip_guests=True) is None and cfu.board(BIZ, leaders_only=True) is None


# ─── 2. The route ─────────────────────────────────────────────────────

def _route(monkeypatch, *, room, guests=None, leaders_only=False):
    import church_keys
    monkeypatch.setattr(church_keys, "is_open", lambda *a, **k: True)
    asked = []
    monkeypatch.setattr(cg, "room_open", lambda biz, user: asked.append(1) or room)
    out = church_router.follow_ups(business_id=BIZ, guests=guests, leaders_only=leaders_only, biz=dict(CHURCH),
                                   session=SimpleNamespace(user=SimpleNamespace(id=OWNER, user_metadata={})))
    return out, asked


def test_the_route_leaves_guests_off_only_when_asked_and_the_room_is_theirs(db, mixed, monkeypatch):
    out, asked = _route(monkeypatch, room=True, guests="room")
    assert out["guests_in_room"] == {"open": 2} and len(out["follow_ups"]) == 2 and asked
    out, _ = _route(monkeypatch, room=False, guests="room")
    assert "guests_in_room" not in out and len(out["follow_ups"]) == 4, "no room: today's board"
    out, asked = _route(monkeypatch, room=True)
    assert "guests_in_room" not in out and len(out["follow_ups"]) == 4 and not asked, "an older app: today's board"
    out, _ = _route(monkeypatch, room=True, guests="all")
    assert len(out["follow_ups"]) == 4


def test_the_route_answers_the_hand_to_list(db, mixed, monkeypatch):
    out, asked = _route(monkeypatch, room=True, guests="room", leaders_only=True)
    assert set(out) == {"leaders", "leaders_only"} and not asked


def test_the_route_called_directly_takes_its_query_defaults_as_no(db, mixed, monkeypatch):
    import church_keys
    from fastapi import Query
    monkeypatch.setattr(church_keys, "is_open", lambda *a, **k: True)
    out = church_router.follow_ups(business_id=BIZ, guests=Query(None), leaders_only=Query(False), biz=dict(CHURCH),
                                   session=SimpleNamespace(user=SimpleNamespace(id=OWNER, user_metadata={})))
    assert len(out["follow_ups"]) == 4


def test_the_route_takes_the_params_over_http(db, mixed, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import business_access as ba
    import church_keys
    import sb_clients
    app = FastAPI()
    app.include_router(church_router.router)
    monkeypatch.setattr(ba, "_resolve_role", lambda b, u: "manager")
    monkeypatch.setattr(ba.billing_context, "set_current", lambda b: None)
    monkeypatch.setattr(church_keys, "is_open", lambda *a, **k: True)
    monkeypatch.setattr(cg, "room_open", lambda biz, user: True)
    user = SimpleNamespace(user=SimpleNamespace(id=OWNER, user_metadata={}, email="pastor@example.org"))
    app.dependency_overrides[sb_clients.authed_request] = lambda: user
    t = TestClient(app)
    assert t.get("/church/follow-ups", params={"business_id": BIZ, "guests": "room"}).json()["guests_in_room"] == {"open": 2}
    assert "guests_in_room" not in t.get("/church/follow-ups", params={"business_id": BIZ}).json()
    lo = t.get("/church/follow-ups", params={"business_id": BIZ, "leaders_only": "true"}).json()
    assert set(lo) == {"leaders", "leaders_only"}


# ─── 3. Who has the room ──────────────────────────────────────────────

@pytest.fixture
def gate(monkeypatch):
    import church_areas
    import church_duties
    state = {"on": True, "mode": "on", "view": {"areas": ["worship_media"]}, "duty": False, "person": ""}
    monkeypatch.setattr(guest_path, "switched_on", lambda b: state["on"])
    monkeypatch.setattr(church_areas, "mode", lambda: state["mode"])
    monkeypatch.setattr(church_areas, "my_areas", lambda b, u, r: state["view"])

    def holds(b, u, d):
        if state["duty"] == "broken":
            raise HTTPException(503, "no")
        return bool(state["duty"]) and d == guest_path.FIRST_GUESTS
    monkeypatch.setattr(church_duties, "holds", holds)
    monkeypatch.setattr(cg, "_person_of", lambda b, u: state["person"])
    return state


def _biz(role="manager"):
    return dict(CHURCH, _caller_role=role)


USER = SimpleNamespace(id="u-media")


def test_people_and_cares_areas_have_the_room_as_before(db, gate):
    gate["view"] = {"areas": ["people_care"]}
    assert cg.room_ok(_biz(), USER) and cg.room_open(_biz(), USER)
    gate["view"] = {"areas": None}
    assert cg.room_open(_biz(), USER)
    gate["view"] = {"areas": ["worship_media"]}
    assert cg.room_open(_biz("admin"), USER) and cg.room_open(_biz("owner"), USER)
    assert not cg.room_open(_biz(), USER), "a Worship & media manager who makes no calls"


def test_whoever_does_first_time_guests_has_the_room(db, gate):
    gate["duty"] = True
    assert cg.room_open(_biz(), USER)


def test_the_caller_of_an_open_guests_call_has_the_room(db, gate):
    gate["person"] = TASHA
    assert not cg.room_open(_biz(), USER), "nothing of theirs open"
    _fu(db, MARCUS, "form:f-baptism", kind="baptism", leader=TASHA)
    assert not cg.room_open(_biz(), USER), "a baptism card isn't a guest's call"
    row = _fu(db, MARCUS, "web:connect_card", leader=TASHA)
    assert cg.room_open(_biz(), USER)
    row["status"] = "handed_back"
    assert cg.room_open(_biz(), USER), "a guest they handed back is still theirs to see"
    row["status"] = "done"
    assert not cg.room_open(_biz(), USER)


def test_the_room_off_or_not_a_church_is_never_open(db, gate):
    gate["view"] = {"areas": ["people_care"]}
    gate["on"] = False
    assert not cg.room_open(_biz(), USER)
    gate["on"] = True
    assert not cg.room_open(dict(_biz(), type="coaching"), USER)


def test_a_read_that_fails_is_a_503_in_the_room_and_a_no_for_the_board(db, gate):
    gate["view"] = None
    with pytest.raises(HTTPException) as e:
        cg.room_ok(_biz(), USER)
    assert e.value.status_code == 503
    assert cg.room_open(_biz(), USER) is False
    gate["view"], gate["duty"] = {"areas": ["worship_media"]}, "broken"
    with pytest.raises(HTTPException):
        cg.room_ok(_biz(), USER)
    assert cg.room_open(_biz(), USER) is False
    gate["duty"], gate["person"] = False, TASHA
    db.t.pop("church_follow_ups")
    import sb_clients
    real = sb_clients.sb_get_as_service
    try:
        sb_clients.sb_get_as_service = lambda path, **k: None if path.startswith("/church_follow_ups") else real(path)
        with pytest.raises(HTTPException) as e:
            cg.room_ok(_biz(), USER)
        assert e.value.status_code == 503
    finally:
        sb_clients.sb_get_as_service = real


def test_the_room_says_its_name_when_it_refuses(db, gate, monkeypatch):
    with pytest.raises(HTTPException) as e:
        cg._gate(_biz(), SimpleNamespace(user=USER))
    assert e.value.status_code == 403 and "Visitor flow" in e.value.detail


def test_people_and_care_and_first_time_guests_read_every_brief_a_caller_only_their_own(db, gate):
    import guest_brief
    row = {"leader_contact_id": ""}            # (a caller's own guest is guest_brief's own check, pinned there)
    gate["duty"] = True
    assert guest_brief.may_read(_biz(), USER, row), "whoever does First-time guests"
    gate["duty"] = False
    assert not guest_brief.may_read(_biz(), USER, row)
    gate["view"] = {"areas": ["people_care"]}
    assert guest_brief.may_read(_biz(), USER, row), "People & care's areas"
    gate["view"], gate["person"] = {"areas": ["worship_media"]}, TASHA
    _fu(db, MARCUS, "web:connect_card", leader=TASHA)
    assert cg.room_open(_biz(), USER), "a caller sees the room"
    assert not guest_brief.may_read(_biz(), USER, row), "but not another guest's brief"


# ─── 4. Every link about a guest's call opens Visitor flow ────────────

def test_guest_calls_links_and_words_point_at_visitor_flow():
    assert gc.NAV == "operate:guests" and gc.LABEL == "Open Visitor flow"
    import inspect
    assert inspect.signature(gc.tell_login).parameters["label"].default == "Open Visitor flow"
    assert inspect.signature(gc.office_alert).parameters["action"].default == "Open Visitor flow"
    words = [gc.new_guest_words("Marcus Taylor", "filled in the website card today", "Tuesday by 6 PM", "", "Renee"),
             gc.remind_words("Marcus Taylor", "today by 6 PM", "Renee"),
             gc.backup_words("Marcus Taylor", "Renee Ellis", "Angela"),
             gc.handed_on_words("Marcus Taylor", "Angela Price", "Renee"),
             gc.pastor_words("Marcus Taylor", "Angela Price")]
    for w in words:
        said = " ".join(w.values())
        assert "Follow-up board" not in said and "Reach out" not in said, said
    assert "open them in Visitor flow and press How did it go?" in words[0]["text"]
    assert "in Visitor flow" in words[4]["body"] and "in Visitor flow" in words[4]["text"]
    assert "tell Angela Price so it’s noted in Visitor flow" in words[3]["text"]


def test_tell_login_pushes_and_emails_visitor_flow_by_default(monkeypatch):
    import church_assignments as cas
    import church_leader_tasks as clt
    import church_office_tasks as cot
    import push_notifications
    pushes, mails = [], []
    monkeypatch.setattr(push_notifications, "send_to_user", lambda uid, **kw: pushes.append(kw["nav"]) or 1)
    monkeypatch.setattr(cas, "_login_email", lambda ch, uid: "renee@example.com")
    monkeypatch.setattr(cot, "render", lambda biz, text, title, link, label: f"{link}|{label}")
    monkeypatch.setattr(clt, "deliver", lambda biz, to, name, subject, html, ref, reply_to=None: mails.append(html))
    monkeypatch.setattr(clt, "_office_email", lambda biz: "")
    ctx = SimpleNamespace(ch=SimpleNamespace(b=BIZ, business=dict(CHURCH)), conf={"tell": {"app": True, "email": True}})
    assert gc.tell_login(ctx, "u-renee", {"title": "t", "body": "b", "subject": "s", "text": "x"}, "ref")
    assert pushes == ["operate:guests"] and mails[0].endswith("/?nav=operate:guests|Open Visitor flow")


def test_the_sweeps_alert_about_a_guest_opens_visitor_flow_while_the_path_is_on(monkeypatch):
    said = []

    async def alert(biz_id, title, body, key, person_id, action=cfu.BOARD_LABEL):
        said.append(action)
        return True
    monkeypatch.setattr(cfu, "_office_alert", alert)
    guest = {"card_key": "web:connect_card", "path_kind": "connect"}
    card = {"card_key": "form:f-baptism", "path_kind": "baptism"}
    monkeypatch.setattr(guest_path, "switched_on", lambda b: True)
    asyncio.run(cfu._alert_on(guest, BIZ, "t", "b", "k", None))
    asyncio.run(cfu._alert_on(card, BIZ, "t", "b", "k", None))
    monkeypatch.setattr(guest_path, "switched_on", lambda b: False)
    asyncio.run(cfu._alert_on(guest, BIZ, "t", "b", "k", None))
    assert said == ["Open Visitor flow", "Open the Follow-up board", "Open the Follow-up board"]
    monkeypatch.setattr(guest_path, "switched_on", lambda b: True)
    assert cfu.where_worked(BIZ, guest) == "in Visitor flow" and cfu.where_worked(BIZ, card) == "on the Follow-up board"


def test_a_guest_with_no_one_raises_an_alert_that_opens_visitor_flow(db, monkeypatch):
    """Through the real sweep: a guest's follow-up the path didn't route
    (made before it was on) with no one, and a baptism card with no one."""
    said = []

    async def alert(biz_id, title, body, key, person_id, action=cfu.BOARD_LABEL):
        said.append((title, action))
        return True

    async def email(*a, **k):
        return True
    monkeypatch.setattr(cfu, "_office_alert", alert)
    monkeypatch.setattr(cfu, "_email", email)
    monkeypatch.setattr(guest_path, "switched_on", lambda b: True)
    import church_first_visit
    import sample_church

    async def no_first_visits(now):
        return 0
    monkeypatch.setattr(church_first_visit, "sweep", no_first_visits)
    monkeypatch.setattr(sample_church, "exclude", lambda: "")
    monkeypatch.setattr(sample_church, "drop_samples", lambda rows: rows)
    for r in (_fu(db, MARCUS, "web:connect_card", leader=None), _fu(db, KEISHA, "form:f-baptism", kind="baptism", leader=None)):
        r["leader_told_at"] = None
    asyncio.run(cfu.sweep())
    assert ("Marcus Taylor has no one yet", "Open Visitor flow") in said
    assert ("Keisha Morgan has no one yet", "Open the Follow-up board") in said


def test_my_weeks_first_time_guests_opens_visitor_flow_while_the_path_is_on(monkeypatch):
    import church_my_week as mw
    monkeypatch.setattr(guest_path, "switched_on", lambda b: True)
    assert mw.door_of("first_guests", CHURCH) == {"area": "operate", "id": "guests", "label": "Open Visitor flow"}
    assert mw.door_of("care_visits", CHURCH) == mw.DOOR["care_visits"]
    monkeypatch.setattr(guest_path, "switched_on", lambda b: False)
    assert mw.door_of("first_guests", CHURCH) == mw.DOOR["first_guests"]
    assert mw.DOOR["first_guests"]["id"] == "follow-up", "the static door stays the board: every church's"


def test_chiefs_place_for_first_time_guests_follows_the_path(monkeypatch):
    import chief_office
    monkeypatch.setattr(guest_path, "switched_on", lambda b: True)
    on = chief_office.place("first_guests", CHURCH)
    assert on.startswith("People › New and in need › Visitor flow") and "Follow-up board" not in on
    assert "New here" in on, "the second page stays"
    monkeypatch.setattr(guest_path, "switched_on", lambda b: False)
    assert "Follow-up board → Hand to" in chief_office.place("first_guests", CHURCH)
    assert "Follow-up board → Hand to" in chief_office.place("first_guests")


# ─── 5. The old id and the map ────────────────────────────────────────

def test_the_rooms_old_id_lands_on_the_visitor_flow_row():
    import system_destinations as sd
    assert sd.destination("operate", "guests") == {"tab": "grow", "sub": "funnel"}


def test_chiefs_map_reads_the_rooms_old_id_as_visitor_flow():
    import church_findway as way
    page = way.page("operate", "guests")
    assert page and page["key"] == "grow:funnel" and page["where"] == "People › New and in need › Visitor flow"
    assert not any(p["key"] == "operate:guests" for p in way.pages()), "no Guests row on the map"
    words = set(way.page("grow", "funnel")["words"])
    assert {"visitor flow", "guests", "first-time guests", "welcome call"} <= words
