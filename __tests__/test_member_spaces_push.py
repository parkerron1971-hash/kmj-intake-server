"""Youth and Kids on members' phones (Kevin, 2026-10-15): a youth leader's
post reaches teens and youth leaders; a child checked in, a child picked
up (and by whom), and a room's lesson reach the child's household adults.
Nothing without the church's switch; never the pickup code."""
import asyncio
from datetime import date

import pytest

import member_push as mp
import member_spaces as msp

BIZ = "11111111-1111-1111-1111-111111111111"
ON = {"member_portal": {"notifications": {k: True for k in mp.KIND_KEYS}}}
BUSINESS = {"id": BIZ, "name": "Love City Church", "settings": ON}


def born(years: int) -> str:
    return f"{date.today().year - years}-01-01"


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(mp, "send", lambda business, kind, **kw: out.append({"kind": kind, **kw}) or 1)
    return out


def _db(monkeypatch, tables):
    def get(path):
        return tables.get(path.split("?")[0].strip("/"))
    monkeypatch.setattr(mp.sb_clients, "sb_get_as_service", get)


def test_youth_and_kids_are_kinds_the_church_switches_on():
    assert "youth" in mp.KIND_KEYS and "kids" in mp.KIND_KEYS
    import member_portal
    kinds = {k["key"]: k for k in member_portal._notifications_payload({"settings": {}})["kinds"]}
    assert kinds["kids"]["label"] == "Kids check-in" and kinds["youth"]["on"] is False   # off until switched on


def test_each_person_sees_only_their_boxes():
    plain = mp.visible_kinds({})
    assert "youth" not in plain and "kids" not in plain and {"messages", "live", "sermons"} <= plain
    assert "youth" in mp.visible_kinds({"youth": True}) and "kids" not in mp.visible_kinds({"youth": True})
    assert "youth" in mp.visible_kinds({"leader": {"youth": {}}})
    assert "kids" in mp.visible_kinds({"kids_parent": True}) and "youth" not in mp.visible_kinds({"kids_parent": True})
    assert "kids" not in mp.visible_kinds({"leader": {"kids": {}}})     # a leader hears nothing about other people's kids


def test_the_notifications_page_lists_only_my_boxes(monkeypatch):
    from starlette.requests import Request
    monkeypatch.setattr(mp, "ready", lambda: True)
    req = Request({"type": "http", "path": "/my/notifications", "query_string": b"", "headers": []})
    me = {"id": "m1", "name": "Jess Carter"}
    try:
        msp.CURRENT.set({"space": "church", "kids_parent": True, "options": ["church", "kids"]})
        page = mp.render_page(BUSINESS, None, req, me, set())
        assert 'name="k_kids"' in page and 'name="k_youth"' not in page and 'name="k_messages"' in page
        msp.CURRENT.set({"space": "youth", "youth": True, "options": []})
        page = mp.render_page(BUSINESS, None, req, me, set())
        assert 'name="k_youth"' in page and 'name="k_kids"' not in page
    finally:
        msp.CURRENT.set({})


def _form(body: bytes):
    from starlette.requests import Request

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    return Request({"type": "http", "method": "POST", "path": "/my/notifications", "query_string": b"",
                    "headers": [(b"content-type", b"application/x-www-form-urlencoded")]}, receive)


def test_saving_keeps_the_choice_for_a_box_i_wasnt_shown(monkeypatch):
    import member_portal_church as mpc
    saved = {}

    async def signed_in(request):
        return {"business": BUSINESS}, {"id": "m1"}, False
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    monkeypatch.setattr(mpc, "_allowed", lambda c, m: True)
    monkeypatch.setattr(mp, "save_turned_off", lambda b, c, off: saved.setdefault("off", set(off)) is not None)
    monkeypatch.setattr(mp, "turned_off", lambda b, c: {"kids"})
    monkeypatch.setattr(msp, "resolve", lambda b, me, wanted="": {"space": "church", "options": ["church"]})
    asyncio.run(mp.my_notifications_save(_form(b"k_messages=on&k_live=on")))
    assert "kids" in saved["off"] and "youth" not in saved["off"]           # untouched, not newly turned off
    assert "messages" not in saved["off"] and "sermons" in saved["off"]     # what they unticked
    saved.clear()
    monkeypatch.setattr(msp, "resolve", lambda b, me, wanted="": {"space": "kids", "kids_parent": True})
    asyncio.run(mp.my_notifications_save(_form(b"k_kids=on")))
    assert "kids" not in saved["off"]                                       # a parent turns it back on


def test_a_youth_post_reaches_teens_and_youth_leaders(monkeypatch, sent):
    _db(monkeypatch, {
        "member_push_subscriptions": [{"contact_id": c} for c in ("teen", "adult", "author", "lead", "lead")],
        "contacts": [{"id": "teen", "birthdate": born(15)}, {"id": "adult", "birthdate": born(40)},
                     {"id": "lead", "birthdate": born(35)}],
        "space_leaders": [{"contact_id": "lead"}, {"contact_id": "no-device"}],
    })
    mp._tell_youth_post(BUSINESS, "p1", {"id": "author", "name": "Marcus Taylor"})
    assert len(sent) == 1 and sent[0]["kind"] == "youth"
    assert sent[0]["contact_ids"] == ["lead", "teen"] and sent[0]["ref_id"] == "youth-post:p1"
    assert sent[0]["body"] == "New post from Marcus. Open the app to see it." and sent[0]["url"] == "/my/space?to=youth"
    called = []
    monkeypatch.setattr(mp, "_later", lambda fn, *a, **k: called.append(fn))
    mp.tell_youth_post({**BUSINESS, "settings": {}}, "p1", {"id": "author"})
    assert called == []                                                      # the church's switch is off


def test_parents_hear_check_in_and_pickup_never_the_code(monkeypatch, sent):
    _db(monkeypatch, {"businesses": [BUSINESS], "household_adults": [{"contact_id": "mom"}, {"contact_id": "dad"}]})
    kids = [{"child_id": "k2", "first_name": "Eli", "room": "Nursery"},
            {"child_id": "k1", "first_name": "Ava", "room": "Room 2"}]
    mp._tell_kids_in(BIZ, "h1", "e1", kids)
    note = sent[-1]
    assert note["kind"] == "kids" and note["contact_ids"] == ["dad", "mom"]
    assert note["title"] == "Eli and Ava are checked in" and note["body"] == "Nursery and Room 2. Your pickup code is in the app."
    assert note["ref_id"] == "kids-in:e1:k1,k2" and note["url"] == "/my/space?to=kids"
    mp._tell_kids_out(BIZ, "h1", ["Ava"], "Linda Lee", ["c2", "c1"])
    note = sent[-1]
    assert note["title"] == "Ava was picked up" and note["body"].startswith("By Linda Lee at ")
    assert note["body"].endswith(("AM.", "PM.")) and note["ref_id"] == "kids-out:c1,c2"
    for n in sent:
        assert "7KXA" not in n["title"] + n["body"]
    _db(monkeypatch, {"businesses": [{**BUSINESS, "settings": {}}], "household_adults": [{"contact_id": "mom"}]})
    before = len(sent)
    mp._tell_kids_in(BIZ, "h1", "e1", kids)
    mp._tell_kids_out(BIZ, "h1", ["Ava"], "Linda Lee", ["c1"])
    assert len(sent) == before                                              # switch off: nothing


def test_a_lesson_reaches_the_parents_of_that_room(monkeypatch, sent):
    seen = []

    def get(path):
        seen.append(path)
        table = path.split("?")[0].strip("/")
        if table == "children":
            return [{"household_id": "h1", "room": "Room 2"}, {"household_id": "h2", "room": "room 2 "},
                    {"household_id": "h3", "room": "Nursery"}]
        if table == "household_adults":
            return [{"contact_id": f"adult-of-{h}"} for h in ("h1", "h2", "h3") if h in path]
        return None
    monkeypatch.setattr(mp.sb_clients, "sb_get_as_service", get)
    mp._tell_kids_lesson(BUSINESS, "L1", "Room 2", "David and Goliath")
    assert sent[-1]["contact_ids"] == ["adult-of-h1", "adult-of-h2"] and sent[-1]["title"] == "This week in Room 2"
    assert sent[-1]["body"] == "David and Goliath. See what they learned." and sent[-1]["ref_id"] == "kids-lesson:L1"
    mp._tell_kids_lesson(BUSINESS, "L2", "", "Noah")
    assert len(sent[-1]["contact_ids"]) == 3 and sent[-1]["title"] == "This week in Kids"


def test_check_in_and_release_tell_the_family(monkeypatch):
    import kids_checkin as kc
    told = {}
    monkeypatch.setattr(mp, "tell_kids_in", lambda *a: told.setdefault("in", a))
    monkeypatch.setattr(mp, "tell_kids_out", lambda *a: told.setdefault("out", a))
    fam_id, kid = "22222222-2222-2222-2222-222222222222", "33333333-3333-3333-3333-333333333333"
    entry = {"id": "44444444-4444-4444-4444-444444444444", "data": {"title": "Sunday"}}
    monkeypatch.setattr(kc, "_one", lambda path, msg: {"id": fam_id, "name": "The Carters"})

    def get(path):
        if path.startswith("/children"):
            return [{"id": kid, "first_name": "Ava", "room": "Room 2"}]
        return []
    monkeypatch.setattr(kc, "_get", get)
    monkeypatch.setattr(kc.sb_clients, "sb_post_as_service", lambda path, rows: [dict(r, id="ci1") for r in rows])
    monkeypatch.setattr(kc, "_shape", lambda rows, b, private: [])
    asyncio.run(kc.do_checkin(BIZ, entry, fam_id, [(kid, "")], None, False, "staff", None, False))
    assert told["in"][1:3] == (fam_id, entry["id"]) and told["in"][3] == [{"child_id": kid, "first_name": "Ava", "room": "Room 2"}]
    monkeypatch.setattr(kc, "_waiting", lambda b, e, c: [{"id": "55555555-5555-5555-5555-555555555555", "household_id": fam_id}])
    monkeypatch.setattr(kc, "_shape", lambda rows, b, m: [{"custody_alert": False, "first_name": "Ava"}])
    monkeypatch.setattr(kc, "_pickup_list", lambda b, h: [{"name": "Linda Lee"}])
    monkeypatch.setattr(kc.sb_clients, "sb_patch_as_service",
                        lambda p, body: [{"id": "55555555-5555-5555-5555-555555555555"}])
    kc.do_release(BIZ, entry, "7KXA", ["55555555-5555-5555-5555-555555555555"], "Linda Lee", False, None)
    assert told["out"] == (BIZ, fam_id, ["Ava"], "Linda Lee", ["55555555-5555-5555-5555-555555555555"])


def test_a_youth_post_and_a_lesson_tell_their_people(monkeypatch):
    import member_portal_church as mpc
    import member_spaces_kids as mk
    import msg_screen
    told = []
    monkeypatch.setattr(mp, "tell_youth_post", lambda b, pid, author: told.append(("youth", pid, author["id"])))
    monkeypatch.setattr(mp, "tell_kids_lesson", lambda b, pid, room, title: told.append(("kids", pid, room, title)))
    lead = {"id": "l1", "name": "Denise Moore", "birthdate": born(40)}

    async def signed_in(request):
        return {"business": BUSINESS, "site": None}, lead, False

    async def ok(b, t):
        return "ok"
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    monkeypatch.setattr(mpc, "_allowed", lambda c, m: True)
    monkeypatch.setattr(msg_screen, "screen", ok)
    monkeypatch.setattr(msp, "leader_rows", lambda b, c: {"youth": {}, "kids": {"rooms": ["Room 2"]}})
    monkeypatch.setattr(msp, "has_children", lambda b, c: False)
    monkeypatch.setattr(msp.sb_clients, "sb_post_as_service", lambda path, body, **k: [{"id": "P9"}])
    asyncio.run(msp.youth_post(_form(b"body=Rides+at+6")))
    asyncio.run(mk.lesson_post(_form(b"room=Room+2&title=David&body=Be+brave")))
    assert told == [("youth", "P9", "l1"), ("kids", "P9", "Room 2", "David")]
    msp.CURRENT.set({})
