"""Church, Youth and Kids spaces (Kevin, 2026-10-15: teens and kids "should
have their own access point", and adult group leaders "the ability to
access each side"). The five calls he approved: teens 13-17 land in Youth,
under 13 only through a parent; the office approves leaders with a
background-check date; leaders are adults; Youth's colour is the church's
pick, volt green by default."""
import asyncio
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

import member_spaces as msp

BIZ = "11111111-1111-1111-1111-111111111111"
CID = "22222222-2222-2222-2222-222222222222"
TODAY = date(2026, 10, 15)


def born(years: int) -> str:
    """A birthdate that is `years` old today (whenever the tests run)."""
    return f"{date.today().year - years}-01-01"


ADULT = {"id": "a1", "name": "Marcus Taylor", "birthdate": born(38)}
TEEN = {"id": "t1", "name": "Tia Carter", "birthdate": born(15)}
CHILD = {"id": "k1", "name": "Ava Carter", "birthdate": born(8)}
NO_AGE = {"id": "n1", "name": "No Birthdate", "birthdate": None}
YOUTH_ROW = {"space": "youth", "rooms": [], "background_check_on": "2026-08-12", "approved_at": "2026-10-15T00:00:00+00:00"}


def test_ages_draw_the_lines_kevin_approved():
    assert msp.is_child({"birthdate": "2014-01-01"}, TODAY) and not msp.is_youth({"birthdate": "2014-01-01"}, TODAY)
    assert msp.is_youth({"birthdate": "2013-10-15"}, TODAY)               # 13 today
    assert msp.is_youth({"birthdate": "2008-10-16"}, TODAY)               # 17, 18 tomorrow
    assert msp.is_adult({"birthdate": "2008-10-15"}, TODAY)               # 18 today
    for f in (msp.is_child, msp.is_youth, msp.is_adult):
        assert not f({"birthdate": None}, TODAY) and not f(None, TODAY)   # no birthdate: none of them


@pytest.fixture
def people(monkeypatch):
    state = {"leaders": {}, "parent": False}
    monkeypatch.setattr(msp, "leader_rows", lambda b, c: state["leaders"].get(c, {}))
    monkeypatch.setattr(msp, "has_children", lambda b, c: state["parent"])
    return state


def test_a_teen_is_always_in_youth(people):
    people["leaders"]["t1"] = {"youth": YOUTH_ROW}                         # even a bad row can't make them a leader
    ctx = msp.resolve(BIZ, TEEN, "church")
    assert ctx["space"] == "youth" and ctx["youth"] and ctx["options"] == [] and ctx["leader"] == {}


def test_a_leader_switches_only_to_spaces_they_lead(people):
    assert msp.resolve(BIZ, ADULT, "youth") == {"space": "church", "youth": False, "leader": {},
                                                "kids_parent": False, "options": ["church"]}
    people["leaders"]["a1"] = {"youth": YOUTH_ROW}
    ctx = msp.resolve(BIZ, ADULT, "youth")
    assert ctx["space"] == "youth" and ctx["options"] == ["church", "youth"] and ctx["leader"]["youth"] == YOUTH_ROW
    assert msp.resolve(BIZ, ADULT, "")["space"] == "church"
    assert msp.resolve(BIZ, ADULT, "kids")["space"] == "church"           # not theirs: Church
    people["leaders"]["n1"] = {"youth": YOUTH_ROW}
    ctx = msp.resolve(BIZ, NO_AGE, "youth")                                # leaders must be adults
    assert ctx["space"] == "church" and ctx["leader"] == {} and ctx["options"] == ["church"]


def test_kids_waits_for_its_own_change(people, monkeypatch):
    people["parent"] = True
    people["leaders"]["a1"] = {"kids": {**YOUTH_ROW, "space": "kids"}}
    assert "kids" not in msp.resolve(BIZ, ADULT, "kids")["options"]
    monkeypatch.setattr(msp, "KIDS_READY", True)
    ctx = msp.resolve(BIZ, ADULT, "kids")
    assert ctx["space"] == "kids" and ctx["kids_parent"] is True and ctx["options"] == ["church", "kids"]


def test_children_under_13_never_sign_in_themselves(monkeypatch):
    import member_portal as mp
    monkeypatch.setattr(mp, "contacts_for_email", lambda b, e: [ADULT, CHILD, TEEN])
    assert [p["id"] for p in mp.contacts_for_ident(BIZ, "family@example.com")] == ["a1", "t1"]
    monkeypatch.setattr(mp, "contacts_for_email", lambda b, e: [CHILD])
    assert mp.contacts_for_ident(BIZ, "ava@example.com") == []            # no code, no session
    monkeypatch.setattr(mp, "contacts_for_email", lambda b, e: None)
    assert mp.contacts_for_ident(BIZ, "x@example.com") is None             # a failed read stays a failed read


def test_the_switcher_shows_only_for_someone_with_two_spaces():
    assert msp.switcher({"space": "church", "options": ["church"]}, "Love City Church") == ""
    assert msp.switcher({"space": "youth", "options": []}, "Love City Church") == ""
    html = msp.switcher({"space": "church", "options": ["church", "youth"], "leader": {"youth": YOUTH_ROW}},
                        "Love City <Church>")
    assert '<details class="mb-spaces">' in html and 'href="/my/space?to=youth"' in html
    assert 'href="/my/space?to=church" aria-current="true"' in html and "Love City &lt;Church&gt;" in html
    assert '<span class="mb-sp-lead">Leader</span>' in html and "Background check on file, August 2026." in html


def _space_req(to):
    from starlette.requests import Request
    return Request({"type": "http", "method": "GET", "path": "/my/space", "query_string": f"to={to}".encode(),
                    "headers": []})


def test_switching_remembers_only_a_space_that_is_theirs():
    import member_portal as mp
    church = {"business": {"id": BIZ, "name": "Love City Church", "settings": {}}, "site": None}
    sess = {"me": ADULT, "people": [ADULT], "claims": {}}

    async def go(to, options):
        msp.CURRENT.set({"space": "church", "options": options})
        return await mp._serve_page(_space_req(to), church, sess, "/my/space")
    resp = asyncio.run(go("youth", ["church", "youth"]))
    assert resp.status_code == 303 and resp.headers["location"] == "/my"
    cookie = resp.headers["set-cookie"]
    assert "sol_space=youth" in cookie and "HttpOnly" in cookie and "Secure" in cookie
    resp = asyncio.run(go("youth", ["church"]))
    assert resp.headers["location"] == "/my" and "set-cookie" not in resp.headers


def test_youth_has_its_own_tab_bar_and_colour():
    import member_app_ui as ui
    bar = ui.nav("messages", space="youth")
    for label in ("Home", "Watch", "Bible", "Chats", "Crew"):
        assert f">{label}<" in bar
    assert 'href="/my/messages" aria-current="page"' in bar and "/my/give" not in bar
    assert "/my/give" in ui.nav("home")                                     # Church keeps Give
    assert msp.youth_colour({"settings": {}}) == "#d4ff3a"
    assert msp.youth_colour({"settings": {"member_portal": {"youth_color": "#ff3d81"}}}) == "#ff3d81"
    assert msp.youth_colour({"settings": {"member_portal": {"youth_color": "red;}"}}}) == "#d4ff3a"


def _youth_home(me, leader=None, posts=None):
    biz = {"id": BIZ, "name": "Love City Church", "settings": {}}
    occ = [{"entry_id": "e1", "title": "Youth Night", "date": "2026-10-23", "location": "Youth room", "attending": 23},
           {"entry_id": "e2", "title": "Sunday Worship", "date": "2026-10-18"}]
    groups = {"mine": [{"id": "g1", "name": "Next Gen Girls", "meets": "Tuesdays 7 pm", "leaders": ["Tasha"],
                        "role": "leader" if leader else "member", "youth": True}], "open": []}
    msp.CURRENT.set({"space": "youth", "youth": not leader, "leader": {"youth": leader} if leader else {},
                     "options": ["church", "youth"] if leader else []})
    try:
        return msp.render_youth_home(biz, None, me=me, occasions=occ, groups=groups, youth_posts=posts or [],
                                     reading="", leader=leader)
    finally:
        msp.CURRENT.set({})


def test_youth_home_for_a_teen():
    post = {"id": "55555555-0000-4000-8000-0000000000a1", "author": "Marcus", "posted_by": "a1",
            "body": "Rides leave at 6:30 <b>Friday</b>", "created_at": "2026-10-15T18:00:00+00:00"}
    html = _youth_home(TEEN, posts=[post])
    assert "What's up,<br><span>Tia</span>" in html and "Youth Night" in html and 'class="sp-youth"' in html
    assert "Rides leave at 6:30 &lt;b&gt;Friday&lt;/b&gt;" in html and "/my/youth/post/remove" not in html
    assert 'href="/my/prayer?for=youth"' in html and "Talk to a youth leader" in html
    assert 'action="/my/youth/post"' not in html                            # teens don't post to Youth
    assert ">Chats<" in html and ">Crew<" in html and "Sunday Worship" not in html


def test_youth_home_for_a_leader():
    post = {"id": "55555555-0000-4000-8000-0000000000a1", "author": "Marcus", "posted_by": "a1",
            "body": "Rides leave at 6:30", "created_at": "2026-10-15T18:00:00+00:00"}
    html = _youth_home(ADULT, leader=YOUTH_ROW, posts=[post])
    assert 'action="/my/youth/post"' in html and f'maxlength="{msp.POST_MAX}"' in html
    assert 'action="/my/youth/post/remove"' in html                         # their own post
    assert "never one to one" in html and "August 2026" in html and "23 coming" in html
    assert 'href="/my/space?to=youth" aria-current="true"' in html          # the switcher, on Youth


def _form_req(path, body: bytes):
    from starlette.requests import Request

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    return Request({"type": "http", "method": "POST", "path": path, "query_string": b"",
                    "headers": [(b"content-type", b"application/x-www-form-urlencoded")]}, receive)


@pytest.fixture
def poster(monkeypatch, people):
    import member_portal_church as mpc
    import msg_screen
    state = {"session": ({"business": {"id": BIZ}}, ADULT, False), "verdict": "ok", "saved": [], "deleted": []}

    async def signed_in(request):
        return state["session"]

    async def screen(b, text):
        if state["verdict"] == "down":
            raise msg_screen.ScreenUnavailable("x")
        return state["verdict"]
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    monkeypatch.setattr(mpc, "_allowed", lambda church, me: True)
    monkeypatch.setattr(msg_screen, "screen", screen)
    monkeypatch.setattr(msp.sb_clients, "sb_post_as_service",
                        lambda path, body, **kw: state["saved"].append((path, body)) or [{"id": "p1"}])
    monkeypatch.setattr(msp.sb_clients, "sb_delete_as_service", lambda path: state["deleted"].append(path) or True)
    return state


def _post(body=b"body=Rides+leave+at+6%3A30"):
    return asyncio.run(msp.youth_post(_form_req("/my/youth/post", body))).headers["location"]


def test_only_an_approved_adult_leader_posts_to_youth(poster, people):
    assert _post() == "/my?err=not_leader" and poster["saved"] == []
    people["leaders"]["a1"] = {"youth": YOUTH_ROW}
    assert _post(b"body=+++") == "/my?err=empty_post"
    poster["verdict"] = "no"
    assert _post() == "/my?err=post_no"
    poster["verdict"] = "down"
    assert _post() == "/my?err=post_busy"
    assert poster["saved"] == []                                            # nothing unchecked goes out
    poster["verdict"] = "ok"
    assert _post() == "/my?done=posted"
    assert poster["saved"] == [("/space_posts", {"business_id": BIZ, "space": "youth", "kind": "post",
                                                 "body": "Rides leave at 6:30", "posted_by": "a1"})]
    people["leaders"]["t1"] = {"youth": YOUTH_ROW}
    poster["session"] = ({"business": {"id": BIZ}}, TEEN, False)            # a teen, whatever the table says
    assert _post() == "/my?err=not_leader"
    poster["session"] = ({"business": {"id": BIZ}}, None, "preview")        # the owner's preview never posts
    assert _post() == "/my?err=preview" and len(poster["saved"]) == 1


def test_only_the_author_removes_a_post(poster):
    pid = "55555555-0000-4000-8000-0000000000a1"
    go = lambda body: asyncio.run(msp.youth_post_remove(_form_req("/my/youth/post/remove", body))).headers["location"]  # noqa: E731
    assert go(f"id={pid}".encode()) == "/my?done=post_removed"
    assert poster["deleted"] == [f"/space_posts?id=eq.{pid}&business_id=eq.{BIZ}&posted_by=eq.a1"]
    assert go(b"id=1%27%20or%201%3D1") == "/my" and len(poster["deleted"]) == 1


@pytest.fixture
def office(monkeypatch):
    state = {"person": [{"id": CID, "name": "Marcus Taylor", "birthdate": born(38)}], "saved": []}
    monkeypatch.setattr(msp.sb_clients, "sb_get_as_service", lambda path: state["person"])

    def save(path, body, prefer=None):
        state["saved"].append((path, body, prefer))
        return [{**body}]
    monkeypatch.setattr(msp.sb_clients, "sb_post_as_service", save)
    return state


def _approve(body):
    return msp.approve_leader(BIZ, body, biz={"id": BIZ}, user=SimpleNamespace(id="office-user"))


def test_the_office_approves_an_adult_with_a_background_check(office):
    ok = {"contact_id": CID, "space": "youth", "background_check_on": "2026-08-12"}
    for bad, code in (({**ok, "contact_id": "x"}, 400), ({**ok, "space": "church"}, 400),
                      ({**ok, "background_check_on": ""}, 400),
                      ({**ok, "background_check_on": (date.today() + timedelta(days=1)).isoformat()}, 400)):
        with pytest.raises(msp.HTTPException) as e:
            _approve(bad)
        assert e.value.status_code == code
    office["person"] = [{"id": CID, "name": "Tia Carter", "birthdate": born(15)}]
    with pytest.raises(msp.HTTPException) as e:
        _approve(ok)
    assert "18 or older" in e.value.detail
    office["person"] = [{"id": CID, "name": "No Birthdate", "birthdate": None}]
    with pytest.raises(msp.HTTPException):
        _approve(ok)                                                        # no birthdate: not yet
    office["person"] = []
    with pytest.raises(msp.HTTPException) as e:
        _approve(ok)
    assert e.value.status_code == 404
    assert office["saved"] == []
    office["person"] = [{"id": CID, "name": "Marcus Taylor", "birthdate": born(38)}]
    out = _approve({**ok, "rooms": ["Room 2"]})
    path, body, prefer = office["saved"][-1]
    assert path == "/space_leaders?on_conflict=business_id,contact_id,space" and "merge-duplicates" in prefer
    assert body["rooms"] == [] and body["approved_by"] == "office-user"     # Youth has no rooms
    assert body["background_check_on"] == "2026-08-12" and out["leader"]["name"] == "Marcus Taylor"
    _approve({**ok, "space": "kids", "rooms": [" Room  2 ", "room 2", "Nursery", ""]})
    assert office["saved"][-1][1]["rooms"] == ["Room 2", "Nursery"]
    with pytest.raises(msp.HTTPException):
        _approve({**ok, "space": "kids", "rooms": "Room 2"})


def test_leader_routes_need_a_signed_in_office_seat():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(msp.router)
    c = TestClient(app)
    assert c.get(f"/member-portal/{BIZ}/leaders").status_code in (401, 403)
    assert c.post(f"/member-portal/{BIZ}/leaders", json={}).status_code in (401, 403)
    assert c.delete(f"/member-portal/{BIZ}/leaders/{CID}/youth").status_code in (401, 403)


def test_the_space_routes_are_mounted_before_the_catch_all():
    import kmj_intake_automation as app_mod
    paths = [getattr(r, "path", "") for r in app_mod.app.routes]
    catch = next(i for i, p in enumerate(paths) if "{full_path" in p or p.endswith("{path:path}"))
    for p in ("/my/youth/post", "/my/youth/post/remove", "/member-portal/{business_id}/leaders",
              "/member-portal/{business_id}/leaders/{contact_id}/{space}"):
        assert p in paths and paths.index(p) < catch


def test_a_teen_can_ask_for_a_youth_leader(monkeypatch):
    import member_portal_church as mpc
    from starlette.requests import Request
    req = Request({"type": "http", "method": "GET", "path": "/my/prayer", "query_string": b"for=youth", "headers": []})
    html = mpc.render_prayer({"id": BIZ, "name": "Love City Church", "settings": {}}, None, req, who=TEEN)
    assert "<h1>Talk to a youth leader</h1>" in html and '<input type="hidden" name="for" value="youth">' in html
    saved = []
    monkeypatch.setattr(mpc.sb_clients, "sb_post_as_service", lambda p, b: saved.append(b) or [{"id": "r1"}])
    assert mpc.save_prayer(BIZ, TEEN, "I need to talk", False, youth=True)
    assert saved[0]["submission"]["source"] == "Member page, Youth"
    mpc.save_prayer(BIZ, ADULT, "Pray for my mom", False)
    assert saved[1]["submission"]["source"] == "Member page"
