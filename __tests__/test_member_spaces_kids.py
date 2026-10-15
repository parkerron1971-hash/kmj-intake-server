"""The Kids space (Kevin approved the concept and its five calls 2026-10-15):
a parent's family and Sunday pass, Kids mode with a three-second hold out,
and a Kids leader's room — first names and allergies only, pickup by the
station's rules, lessons for parents."""
import asyncio
import json
from datetime import date

import pytest

import member_spaces as msp
import member_spaces_kids as mk

BIZ = "11111111-1111-1111-1111-111111111111"
ENTRY = "33333333-3333-3333-3333-333333333333"
CI1, CI2 = "44444444-0000-4000-8000-000000000001", "44444444-0000-4000-8000-000000000002"
LESSON_ID = "55555555-0000-4000-8000-0000000000b1"


def born(years: int) -> str:
    return f"{date.today().year - years}-01-01"


MOM = {"id": "m1", "name": "Jessica Carter", "birthdate": born(36)}
LEAD = {"id": "l1", "name": "Denise Moore", "birthdate": born(47)}
TEEN = {"id": "t1", "name": "Tia Carter", "birthdate": born(15)}
KIDS_ROW = {"space": "kids", "rooms": ["Room 2"], "background_check_on": "2026-08-12"}
FAM = {"households": ["h1"], "children": [
    {"id": "k-ava", "first_name": "Ava", "last_name": "Carter", "birthdate": born(7), "room": "Room 2", "allergies": "Peanuts"},
    {"id": "k-eli", "first_name": "Eli <b>", "last_name": "Carter", "birthdate": born(4), "room": "Nursery", "allergies": ""}],
    "pickups": [{"name": "Jessica Carter", "relationship": "mom"}, {"name": "Linda Lee", "relationship": "grandma"}]}
LESSON = {"id": LESSON_ID, "room": "Room 2", "title": "David and Goliath", "body": "Being brave because God is with you.",
          "scripture": "1 Samuel 17", "verse": "Be strong and of a good courage; be not afraid. Joshua 1:9",
          "questions": "What was David's giant?\n- When do you need to be brave?\n", "video_url": "",
          "posted_by": "l1", "author": "Denise", "created_at": "2026-10-12T15:00:00+00:00"}
BIZROW = {"id": BIZ, "name": "Love City Church", "settings": {}}
PARENT_CTX = {"space": "kids", "youth": False, "leader": {}, "kids_parent": True, "options": ["church", "kids"]}
LEADER_CTX = {"space": "kids", "youth": False, "leader": {"kids": KIDS_ROW}, "kids_parent": False, "options": ["church", "kids"]}


@pytest.fixture(autouse=True)
def _clean_space():
    yield
    msp.CURRENT.set({})


@pytest.fixture
def people(monkeypatch):
    state = {"leaders": {}, "parents": set()}
    monkeypatch.setattr(msp, "leader_rows", lambda b, c: state["leaders"].get(c, {}))
    monkeypatch.setattr(msp, "has_children", lambda b, c: c in state["parents"])
    return state


# ─── who gets Kids ───────────────────────────────────────────────────


def test_kids_is_for_parents_and_approved_kids_leaders(people, monkeypatch):
    assert msp.resolve(BIZ, MOM, "kids")["options"] == ["church"]          # not a parent yet
    people["parents"].add("m1")
    ctx = msp.resolve(BIZ, MOM, "kids")
    assert ctx["space"] == "kids" and ctx["kids_parent"] is True and ctx["options"] == ["church", "kids"]
    people["leaders"]["l1"] = {"kids": KIDS_ROW}
    ctx = msp.resolve(BIZ, LEAD, "kids")
    assert ctx["space"] == "kids" and ctx["kids_parent"] is False and mk.leader_rooms(ctx) == ["Room 2"]
    people["parents"].add("t1")
    people["leaders"]["t1"] = {"kids": KIDS_ROW}
    assert msp.resolve(BIZ, TEEN, "kids")["space"] == "youth"              # a teen is in Youth, always
    monkeypatch.setattr(msp, "KIDS_READY", False)
    assert msp.resolve(BIZ, MOM, "kids")["options"] == ["church"]


def test_a_leader_of_every_room_has_no_room_list():
    assert mk.leader_rooms(PARENT_CTX) is None
    assert mk.leader_rooms({"leader": {"kids": {"rooms": []}}}) == []
    assert mk.in_rooms("room 2 ", ["Room 2"]) and not mk.in_rooms("Nursery", ["Room 2"]) and mk.in_rooms("Nursery", [])


# ─── what's read ─────────────────────────────────────────────────────


def _fake_db(monkeypatch, tables, seen=None):
    def get(path):
        if seen is not None:
            seen.append(path)
        table = path.split("?")[0].strip("/")
        return tables.get(table)
    monkeypatch.setattr(mk.sb_clients, "sb_get_as_service", get)


def test_a_parent_sees_allergies_never_medical_or_custody(monkeypatch):
    seen = []
    _fake_db(monkeypatch, {
        "household_adults": [{"household_id": "h1", "contact_id": "m1", "relationship": "mom"},
                             {"household_id": "h1", "contact_id": "d1", "relationship": "dad"}],
        "children": [{"id": "k-ava", "first_name": "Ava", "last_name": "Carter", "birthdate": "2019-04-02",
                      "room": "Room 2", "household_id": "h1"}],
        "household_pickups": [{"name": "Linda Lee", "relationship": "grandma"}, {"name": "jessica carter", "relationship": ""}],
        "child_care_notes": [{"child_id": "k-ava", "allergies": " Peanuts "}],
        "contacts": [{"id": "m1", "name": "Jessica Carter"}, {"id": "d1", "name": "Marcus Carter"}]}, seen)
    fam = mk.family(BIZ, "m1")
    assert fam["households"] == ["h1"] and fam["children"][0]["allergies"] == "Peanuts"
    assert [p["name"] for p in fam["pickups"]] == ["Jessica Carter", "Marcus Carter", "Linda Lee"]   # no duplicates
    notes = next(p for p in seen if p.startswith("/child_care_notes"))
    assert notes.endswith("select=child_id,allergies") and "medical" not in notes and "custody" not in notes
    assert all("active=eq.true" in p for p in seen if p.startswith("/children"))
    _fake_db(monkeypatch, {"household_adults": None})
    assert mk.family(BIZ, "m1") is None                                     # a failed read is not "no family"


def test_lessons_for_rooms_with_spaces_are_quoted(monkeypatch):
    seen = []
    _fake_db(monkeypatch, {"space_posts": [dict(LESSON)], "contacts": [{"id": "l1", "name": "Denise Moore"}]}, seen)
    got = mk.lessons(BIZ, ["Room 2", "Nursery"])
    assert "room=in.(%22Room%202%22,%22Nursery%22,%22%22)" in seen[0] and "space=eq.kids&kind=eq.lesson" in seen[0]
    assert got[0]["author"] == "Denise"
    mk.lessons(BIZ, None)
    assert "room=" not in seen[-2]                                          # a leader of every room sees all
    assert mk.lesson_for([{**LESSON, "room": "Nursery"}, LESSON], "room 2")["id"] == LESSON_ID
    assert mk.lesson_for([{**LESSON, "room": ""}], "Room 9")["room"] == ""  # an every-room lesson fits anyone


def test_the_roster_shows_a_leaders_rooms_without_codes_or_notes(monkeypatch):
    import kids_checkin as kc
    monkeypatch.setattr(mk, "todays", lambda b: [{"id": ENTRY, "title": "Kids Church"}])
    rows = [{"id": CI1, "room": "Room 2", "entry_id": ENTRY}, {"id": CI2, "room": "Nursery", "entry_id": ENTRY}]
    _fake_db(monkeypatch, {"child_checkins": rows})
    shaped_with = {}

    def shape(r, b, private):
        shaped_with["private"] = private
        return [{"id": x["id"], "first_name": "Ava", "code": "7KXA", "custody": "note", "custody_alert": True} for x in r]
    monkeypatch.setattr(kc, "_shape", shape)
    out = mk.roster(BIZ, ["Room 2"])
    assert [r["id"] for r in out["rows"]] == [CI1] and shaped_with["private"] is False
    assert "code" not in out["rows"][0] and "custody" not in out["rows"][0] and out["rows"][0]["custody_alert"] is True
    assert out["rows"][0]["occasion"] == "Kids Church"
    monkeypatch.setattr(mk, "todays", lambda b: None)
    assert mk.roster(BIZ, ["Room 2"]) is None


# ─── the week's story ────────────────────────────────────────────────


def test_a_verse_keeps_its_reference_out_of_the_game():
    assert mk.split_ref("Be strong and of a good courage; be not afraid. Joshua 1:9") == (
        "Be strong and of a good courage; be not afraid.", "Joshua 1:9")
    assert mk.split_ref("The LORD is my shepherd (Psalm 23:1)") == ("The LORD is my shepherd", "Psalm 23:1")
    assert mk.split_ref("Obey your parents. 1 John 2:3-5") == ("Obey your parents.", "1 John 2:3-5")
    assert mk.split_ref("Peace, be still.") == ("Peace, be still.", "")
    assert mk.split_ref("Psalm 23") == ("Psalm 23", "")


def test_the_story_is_the_rooms_lesson_or_one_of_ours():
    st = mk.as_story(LESSON)
    assert st["from_leader"] and st["verse_ref"] == "Joshua 1:9" and st["verse"].endswith("be not afraid.")
    assert st["questions"] == ["What was David's giant?", "When do you need to be brave?"]
    ours = mk.as_story(None, date(2026, 10, 18))
    assert not ours["from_leader"] and ours in [{**s, "from_leader": False} for s in mk.STORIES]
    assert mk.story_of_week(date(2026, 10, 18)) == mk.story_of_week(date(2026, 10, 14))   # same week, same story
    for s in mk.STORIES:
        assert s["verse"] and s["verse_ref"] and len(s["questions"]) == 2 and s["story"]


# ─── a parent's pages ────────────────────────────────────────────────


def _parent_home(live_rows):
    msp.CURRENT.set(PARENT_CTX)
    return mk.render_home(BIZROW, None, me=MOM, ctx=PARENT_CTX, fam=FAM, live_rows=live_rows,
                          occasions=[{"title": "Sunday Worship", "date": "2026-10-18"}], all_lessons=[LESSON], ros=None)


def test_the_sunday_pass_shows_the_live_code_while_a_child_is_in():
    html = _parent_home([{"id": CI1, "child_id": "k-ava", "room": "Room 2", "code": "7KXA",
                          "checked_in_at": "2026-10-18T13:52:00+00:00", "entry_id": ENTRY}])
    assert "<b>7</b><b>K</b><b>X</b><b>A</b>" in html and "Show this code at pickup" in html
    assert "Room 2 · in at 9:52 AM" in html                                 # the church's clock, not UTC
    assert "Eli &lt;b&gt;" in html and "Eli <b>" not in html
    assert "This week Ava learned" in html and "David and Goliath" in html and 'href="/my/kids/play"' in html
    assert ">Kids<" in html and ">Sundays<" in html and ">Family<" in html and "/my/give" not in html
    quiet = _parent_home([])
    assert "Pickup code" not in quiet and "Sunday Worship" in quiet and "kiosk" in quiet
    assert "We're here" not in quiet                                         # no check-in from a phone


def test_family_and_sundays_pages():
    msp.CURRENT.set(PARENT_CTX)
    fam = mk.render_family(BIZROW, None, me=MOM, fam=FAM)
    assert "Peanuts" in fam and "No allergies on record." in fam and "Linda Lee" in fam and "grandma" in fam
    assert "Medical and custody notes are kept by the office only." in fam
    past = [{"child_id": "k-ava", "room": "Room 2", "checked_in_at": "2026-10-11T13:50:00+00:00",
             "checked_out_at": "2026-10-11T15:32:00+00:00", "released_to": "Linda Lee", "title": "Sunday Worship"}]
    sun = mk.render_sundays(BIZROW, None, me=MOM, ctx=PARENT_CTX, fam=FAM, past=past)
    assert "Sun Oct 11 · Sunday Worship" in sun and "home 11:32 AM with Linda Lee" in sun
    assert "couldn" in mk.render_sundays(BIZROW, None, me=MOM, ctx=PARENT_CTX, fam=FAM, past=None)


def test_kids_mode_is_the_childs_screen_with_a_hold_to_leave():
    msp.CURRENT.set(PARENT_CTX)
    who = mk.render_play(BIZROW, None, me=MOM, fam=FAM, all_lessons=[LESSON])
    assert "Who's playing?" in who and 'href="/my/kids/play?child=k-ava"' in who
    evil = {**LESSON, "body": "</script><script>alert(1)</script>"}
    html = mk.render_play(BIZROW, None, me=MOM, fam=FAM, all_lessons=[evil], child_id="k-ava")
    assert "Hi, Ava!" in html and 'id="k-hold"' in html and "hold to leave Kids mode" in html
    assert "setTimeout(function(){location.href='/my';},3000)" in html
    data = html.split('<script type="application/json" id="k-data">')[1].split("</script>")[0]
    assert json.loads(data)["verse"] == "Be strong and of a good courage; be not afraid."
    assert "<script>alert(1)" not in html                                  # escaped in the page and the data
    assert 'class="mb-nav' not in html and 'class="mb-top"' not in html     # no tab bar, no top bar
    body = html.split("<body", 1)[1]
    assert 'href="http' not in body and "/my/messages" not in body          # no links out, no messages


# ─── a leader's room ─────────────────────────────────────────────────


ROSTER = {"occasions": [{"id": ENTRY, "title": "Kids Church"}], "rows": [
    {"id": CI1, "first_name": "Ava", "last_name": "Carter", "room": "Room 2", "allergies": "Peanuts", "custody_alert": False,
     "checked_in_at": "2026-10-18T13:52:00+00:00", "checked_out_at": None, "occasion": "Kids Church"},
    {"id": CI2, "first_name": "Sam", "last_name": "Wells", "room": "Room 2", "allergies": "", "custody_alert": True,
     "checked_in_at": "2026-10-18T14:01:00+00:00", "checked_out_at": None, "occasion": "Kids Church"},
    {"id": "x3", "first_name": "Mia", "last_name": "Ross", "room": "Room 2", "allergies": "", "custody_alert": False,
     "checked_in_at": "2026-10-18T13:49:00+00:00", "checked_out_at": "2026-10-18T15:20:00+00:00", "released_to": "Tanya Ross",
     "occasion": "Kids Church"}]}


def test_the_leaders_room():
    msp.CURRENT.set(LEADER_CTX)
    html = mk.render_home(BIZROW, None, me=LEAD, ctx=LEADER_CTX, fam=None, live_rows=[], occasions=[], all_lessons=[], ros=ROSTER)
    assert "Room 2<br><span>Kids Church</span>" in html and "2 kids in" in html
    assert "<b>Ava C.</b>" in html and "Carter" not in html                 # first name and an initial
    assert 'k-allergy" title="Peanuts">Peanuts' in html and "Office at pickup" in html and "Home with Tanya" in html
    assert 'action="/my/kids/pickup"' in html and "Medical and custody" in html and "August 2026" in html
    assert ">Room<" in html and ">Family<" not in html and ">Sundays<" not in html   # not a parent: three tabs
    assert "couldn" in mk.render_home(BIZROW, None, me=LEAD, ctx=LEADER_CTX, fam=None, live_rows=[], occasions=[],
                                      all_lessons=[], ros=None)


FOUND = {"code": "7KXA", "family": "The Carter family", "custody_alert": False, "children": [
    {"id": CI1, "first_name": "Ava", "last_name": "Carter", "room": "Room 2", "allergies": "Peanuts"},
    {"id": CI2, "first_name": "Eli", "last_name": "Carter", "room": "Nursery", "allergies": ""}],
    "allowed": [{"name": "Jessica Carter", "relationship": "mom", "phone": "+12165550100"}]}


def test_pickup_releases_only_from_the_leaders_rooms_and_never_a_custody_family():
    msp.CURRENT.set(LEADER_CTX)
    html = mk.render_pickup(BIZROW, None, me=LEAD, code="7KXA", found=FOUND, entry_id=ENTRY, rooms=["Room 2"])
    assert f'value="{CI1}" checked' in html and CI2 not in html and "Eli (Nursery): pickup is at their room." in html
    assert 'name="released_to" value="Jessica Carter"' in html and "+1216" not in html   # no phone numbers
    assert '<em class="k-flag k-allergy">Peanuts</em>' in html and 'action="/my/kids/release"' in html
    held = mk.render_pickup(BIZROW, None, me=LEAD, code="7KXA", found={**FOUND, "custody_alert": True}, entry_id=ENTRY,
                            rooms=["Room 2"])
    assert "/my/kids/release" not in held and "A manager releases these children" in held


def _form(path, body: bytes):
    from starlette.requests import Request

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    return Request({"type": "http", "method": "POST", "path": path, "query_string": b"",
                    "headers": [(b"content-type", b"application/x-www-form-urlencoded")]}, receive)


@pytest.fixture
def room(monkeypatch, people):
    import kids_checkin as kc
    import member_portal_church as mpc
    import msg_screen
    state = {"me": LEAD, "verdict": "ok", "released": [], "saved": [], "deleted": [], "today": [{"id": ENTRY, "title": "Kids Church"}]}

    async def signed_in(request):
        return {"business": BIZROW, "site": None}, state["me"], False

    async def screen(b, text):
        if state["verdict"] == "down":
            raise msg_screen.ScreenUnavailable("x")
        return state["verdict"]
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    monkeypatch.setattr(mpc, "_allowed", lambda church, me: True)
    monkeypatch.setattr(msg_screen, "screen", screen)
    monkeypatch.setattr(mk, "todays", lambda b: state["today"])
    monkeypatch.setattr(mk, "find_code", lambda b, code: ({"id": ENTRY}, None) if code == "7KXA" else (None, "not_found"))
    monkeypatch.setattr(kc, "do_lookup", lambda b, entry, code, manager: dict(FOUND))

    def release(b, entry, code, ids, to, manager, by_user, by_contact=None):
        state["released"].append({"ids": ids, "to": to, "manager": manager, "by_user": by_user, "by_contact": by_contact})
        return {"released": ids}
    monkeypatch.setattr(kc, "do_release", release)
    monkeypatch.setattr(mk.sb_clients, "sb_post_as_service", lambda p, b: state["saved"].append((p, b)) or [{"id": "p1"}])
    monkeypatch.setattr(mk.sb_clients, "sb_delete_as_service", lambda p: state["deleted"].append(p) or True)
    people["leaders"]["l1"] = {"kids": KIDS_ROW}
    return state


def _run(fn, path, body):
    return asyncio.run(fn(_form(path, body)))


def test_only_an_approved_kids_leader_checks_a_code(room, people):
    resp = _run(mk.pickup_check, "/my/kids/pickup", b"code=7kxa")
    assert resp.status_code == 200 and b'action="/my/kids/release"' in resp.body
    assert b"No child is waiting" in _run(mk.pickup_check, "/my/kids/pickup", b"code=ZZZZ").body
    assert b"four letters" in _run(mk.pickup_check, "/my/kids/pickup", b"code=12").body
    room["me"] = MOM                                                        # a parent, not a leader
    assert _run(mk.pickup_check, "/my/kids/pickup", b"code=7KXA").headers["location"] == "/my?err=not_kids_leader"
    people["leaders"]["t1"] = {"kids": KIDS_ROW}
    room["me"] = TEEN                                                       # never a teen, whatever the table says
    assert _run(mk.pickup_check, "/my/kids/pickup", b"code=7KXA").headers["location"] == "/my?err=not_kids_leader"


def test_release_goes_through_the_stations_rules(room):
    ok = f"code=7KXA&entry_id={ENTRY}&checkin_id={CI1}&released_to=Jessica+Carter".encode()
    assert _run(mk.pickup_release, "/my/kids/release", ok).headers["location"] == "/my?done=released"
    assert room["released"] == [{"ids": [CI1], "to": "Jessica Carter", "manager": False, "by_user": None, "by_contact": "l1"}]
    other_room = f"code=7KXA&entry_id={ENTRY}&checkin_id={CI2}&released_to=Jessica+Carter".encode()
    assert b"in your rooms" in _run(mk.pickup_release, "/my/kids/release", other_room).body
    room["today"] = [{"id": "another-day"}]
    assert b"another day" in _run(mk.pickup_release, "/my/kids/release", ok).body
    assert len(room["released"]) == 1


def test_a_lesson_is_checked_and_kept_to_the_leaders_rooms(room):
    go = lambda body: _run(mk.lesson_post, "/my/kids/lesson", body).headers["location"]  # noqa: E731
    full = b"room=room+2&title=David&body=Be+brave&verse=Psalm+56%3A3&questions=One%0ATwo"
    assert go(b"room=Room+2&title=&body=x") == "/my/kids/stories?err=lesson_incomplete"
    assert go(full + b"&video_url=javascript%3Aalert(1)") == "/my/kids/stories?err=lesson_link"
    assert go(full.replace(b"room+2", b"Nursery")) == "/my/kids/stories?err=lesson_room"
    room["verdict"] = "no"
    assert go(full) == "/my/kids/stories?err=post_no"
    room["verdict"] = "down"
    assert go(full) == "/my/kids/stories?err=post_busy"
    assert room["saved"] == []
    room["verdict"] = "ok"
    assert go(full + b"&video_url=https%3A%2F%2Fyoutu.be%2Fabc") == "/my/kids/stories?done=lesson_posted"
    path, body = room["saved"][0]
    assert path == "/space_posts" and body["space"] == "kids" and body["kind"] == "lesson"
    assert body["room"] == "Room 2" and body["posted_by"] == "l1" and body["video_url"] == "https://youtu.be/abc"
    room["me"] = MOM
    assert go(full) == "/my/kids/stories?err=not_kids_leader"


def test_only_the_author_removes_a_lesson(room):
    go = lambda body: _run(mk.lesson_remove, "/my/kids/lesson/remove", body).headers["location"]  # noqa: E731
    assert go(f"id={LESSON_ID}".encode()) == "/my/kids/stories?done=lesson_removed"
    assert room["deleted"] == [f"/space_posts?id=eq.{LESSON_ID}&business_id=eq.{BIZ}&space=eq.kids&posted_by=eq.l1"]


def test_a_leaders_release_is_recorded_and_a_stations_is_unchanged(monkeypatch):
    import kids_checkin as kc
    sent = []
    monkeypatch.setattr(kc, "_waiting", lambda b, e, c: [{"id": CI1, "household_id": "h1"}])
    monkeypatch.setattr(kc, "_shape", lambda rows, b, m: [{"custody_alert": False}])
    monkeypatch.setattr(kc, "_pickup_list", lambda b, h: [{"name": "Jessica Carter"}])
    monkeypatch.setattr(kc.sb_clients, "sb_patch_as_service", lambda p, body: sent.append(body) or [{"id": CI1}])
    kc.do_release(BIZ, {"id": ENTRY}, "7KXA", [CI1], "Jessica Carter", False, None, "l1")
    assert sent[-1]["released_by_contact"] == "l1"
    kc.do_release(BIZ, {"id": ENTRY}, "7KXA", [CI1], "Jessica Carter", False, None)
    assert "released_by_contact" not in sent[-1]                             # stations and team seats: as before


def test_kids_pages_are_only_for_who_they_are_for(monkeypatch):
    from member_portal import _page  # noqa: F401
    church = {"business": BIZROW, "site": None}
    monkeypatch.setattr(mk, "family", lambda b, c: FAM)
    monkeypatch.setattr(mk, "lessons", lambda b, rooms, limit=12: [LESSON])
    monkeypatch.setattr(mk, "history", lambda b, h: [])

    def go(ctx, sub):
        async def run():
            msp.CURRENT.set(ctx)
            from starlette.requests import Request
            return await mk.serve(Request({"type": "http", "path": sub, "query_string": b"", "headers": []}), church, MOM, sub)
        return asyncio.run(run())
    assert go({"space": "church"}, "/my/kids/play").headers["location"] == "/my"
    assert go(LEADER_CTX, "/my/kids/family").headers["location"] == "/my"   # a leader isn't shown a family
    assert b"Hi, Ava!" in go(PARENT_CTX, "/my/kids/play").body or b"Who's playing?" in go(PARENT_CTX, "/my/kids/play").body
    assert b"Who can pick up" in go(PARENT_CTX, "/my/kids/family").body


def test_the_kids_look():
    import member_app_ui as ui
    p = ui.palette(BIZROW, {}, "kids")
    assert p["bg"] == "#fff8ec" and ui.contrast(p["accent"], p["bg"]) >= 4.5
    assert "kids" not in ui.BASES                                          # not a base a church picks
    css = ui.css(BIZROW, {}, "kids")
    assert "body.sp-kids" in css and ".k-hold.on::before{width:100%;transition:width 3s linear;}" in css
    assert "family=Fredoka" in ui.FONTS


def test_the_kids_routes_are_mounted_before_the_catch_all():
    import kmj_intake_automation as app_mod
    import member_portal_church as mpc
    paths = [getattr(r, "path", "") for r in app_mod.app.routes]
    catch = next(i for i, p in enumerate(paths) if "{full_path" in p or p.endswith("{path:path}"))
    for p in ("/my/kids/pickup", "/my/kids/release", "/my/kids/lesson", "/my/kids/lesson/remove"):
        assert p in paths and paths.index(p) < catch
    assert mpc._back("/my/kids/stories", done="x").headers["location"] == "/my/kids/stories?done=x"
