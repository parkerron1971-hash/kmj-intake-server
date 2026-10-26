"""The Serve tab (Who sees what, Kevin 2026-10-26: "go with your picks" — the
tab is called Serve). With CHURCH_AREAS on, the member app's Lead tab is the
Serve tab, for every part the church has given someone:

  * it's called Serve, on the same route, and Lead with the switch off
  * a place on a Sunday team, or a kids room, gets the tab too, not only a
    role or a group
  * someone whose only part is serving opens on their Sundays; someone who
    serves in Kids is shown the way to the Kids room; the section switcher
    offers both beside their people and prayer
  * My serving lives under Serve
  * a read that fails is no part, never a broken page
  * a part on ChurchSavvy's Sunday team (booth, media, worship, planner)
    gets the tab too, with a door to ChurchSavvy that says the part
"""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.dirname(os.path.abspath(__file__))):
    if p not in sys.path:
        sys.path.insert(0, p)

import member_app_ui as ui  # noqa: E402
import member_portal_lead as mpl  # noqa: E402
from test_church_follow_up import BIZ, DANA, MARCUS, ROBERT, NAMES, db  # noqa: E402,F401
from test_member_portal_lead import BUSINESS, _me, _req, shell  # noqa: E402,F401


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("CHURCH_AREAS", "on")


def _parts(monkeypatch, serving=False, kids=False, team=()):
    monkeypatch.setattr(mpl, "parts", lambda biz, me_id, email=None: {"serving": serving, "kids": kids, "team": list(team)})


def test_the_tab_is_called_serve_with_the_switch_on_and_lead_without(monkeypatch):
    monkeypatch.setenv("CHURCH_AREAS", "owner")
    assert ">Lead<" in ui.nav("lead", lead=True) and ">Serve<" not in ui.nav("lead", lead=True)
    monkeypatch.setenv("CHURCH_AREAS", "on")
    bar = ui.nav("lead", lead=True)
    assert ">Serve<" in bar and 'href="/my/lead" aria-current="page"' in bar


def test_a_place_on_a_sunday_team_or_a_kids_room_gets_the_tab(db, on, monkeypatch):
    import member_portal
    _parts(monkeypatch, serving=True)
    assert asyncio.run(member_portal._leads(BIZ, DANA, BUSINESS, _me(DANA))) is True
    _parts(monkeypatch, kids=True)
    assert asyncio.run(member_portal._leads(BIZ, DANA, BUSINESS, _me(DANA))) is True
    _parts(monkeypatch)
    assert asyncio.run(member_portal._leads(BIZ, DANA, BUSINESS, _me(DANA))) is False


def test_without_the_switch_serving_alone_is_no_tab(db, monkeypatch):
    import member_portal
    monkeypatch.setenv("CHURCH_AREAS", "owner")
    _parts(monkeypatch, serving=True, kids=True)
    assert asyncio.run(member_portal._leads(BIZ, DANA, BUSINESS, _me(DANA))) is False


def test_someone_who_only_serves_opens_on_their_sundays(db, on, shell, monkeypatch):
    import member_portal_serving
    import sunday_serving as ss
    _parts(monkeypatch, serving=True)
    monkeypatch.setattr(ss, "mine", lambda biz, cid: {"me": "mine"})
    monkeypatch.setattr(ss, "hearing", lambda biz, cid: {})
    monkeypatch.setattr(member_portal_serving, "render_page",
                        lambda biz, site, request, me, m, sub, door="": f"MY SERVING for {m['me']}{door}")
    html, status = asyncio.run(mpl.serve(_req(), BUSINESS, {}, _me(DANA), "/my/lead"))
    assert status == 200 and html == "MY SERVING for mine"


def test_someone_who_serves_in_kids_is_shown_the_kids_room(db, on, shell, monkeypatch):
    _parts(monkeypatch, kids=True)
    html, status = asyncio.run(mpl.serve(_req(), BUSINESS, {}, _me(DANA), "/my/lead"))
    assert status == 200 and "Serve, <em>Dana</em>" in html
    assert 'href="/my/space?to=kids"' in html and "Open the Kids room" in html
    assert "You don’t lead anything" not in html
    assert shell["tab"] == "lead"


def test_a_leader_who_also_serves_gets_both_in_the_section_switcher(db, on, shell, monkeypatch):
    _parts(monkeypatch, serving=True, kids=True)
    html, status = asyncio.run(mpl.serve(_req(), BUSINESS, {}, _me(ROBERT), "/my/lead"))
    assert status == 200 and "Serve, <em>Robert</em>" in html, "the welcome lead"
    assert 'href="/my/serving">Serving</a>' in html and 'href="/my/space?to=kids">Kids room</a>' in html
    assert 'aria-label="Serve"' in html


def test_my_serving_lives_under_serve(on):
    import member_portal_serving
    assert member_portal_serving._tab() == "lead"


def test_with_the_switch_off_the_page_says_lead(db, shell, monkeypatch):
    monkeypatch.setenv("CHURCH_AREAS", "owner")
    html, _ = asyncio.run(mpl.serve(_req(), BUSINESS, {}, _me(MARCUS), "/my/lead"))
    assert "Lead, <em>Marcus</em>" in html and "Serving" not in html


def test_a_read_that_fails_is_no_part(db, monkeypatch):
    import sb_clients
    import sunday_serving as ss
    monkeypatch.setattr(ss, "serves", lambda biz, cid: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **kw: None)
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    assert mpl.parts(BUSINESS, DANA, "dana@example.com") == {"serving": False, "kids": False, "team": []}


@pytest.fixture
def savvy(db, on, monkeypatch):
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    monkeypatch.setenv("CHURCHSAVVY_APP_URL", "https://churchsavvy.example")
    db.t.setdefault("worship_team", []).append(
        {"business_id": BIZ, "name": "Dana", "email": "Dana@Example.com", "roles": ["booth", "worship"], "status": "active"})
    return db


def test_a_part_on_churchsavvys_team_is_read_by_email_while_churchsavvy_is_on(savvy, monkeypatch):
    assert mpl.team_parts(BUSINESS, "dana@example.com") == ["booth", "worship"]
    assert mpl.team_parts(BUSINESS, "someone@else.org") == []
    monkeypatch.setenv("WORSHIP_SONGS", "owner")
    assert mpl.team_parts(BUSINESS, "dana@example.com") == [], "not until ChurchSavvy is on for every church"


def test_churchsavvys_team_alone_gets_the_serve_tab_and_a_door_to_the_booth(savvy, shell, monkeypatch):
    import member_portal
    import sunday_serving as ss
    monkeypatch.setattr(ss, "serves", lambda biz, cid: False)
    me = dict(_me(DANA), email="dana@example.com")
    assert asyncio.run(member_portal._leads(BIZ, DANA, BUSINESS, me)) is True
    html, status = asyncio.run(mpl.serve(_req(), BUSINESS, {}, me, "/my/lead"))
    assert status == 200 and "Serve, <em>Dana</em>" in html
    assert 'href="https://churchsavvy.example"' in html and "Open the booth" in html
    assert "Your part on Sunday: the screens and the songs" in html
    assert "You don’t lead anything" not in html


def test_someone_who_only_serves_and_runs_the_booth_sees_the_door_on_their_sundays(savvy, shell, monkeypatch):
    import member_portal_serving
    import sunday_serving as ss
    monkeypatch.setattr(ss, "serves", lambda biz, cid: True)
    monkeypatch.setattr(ss, "mine", lambda biz, cid: {"me": "mine"})
    monkeypatch.setattr(ss, "hearing", lambda biz, cid: {})
    monkeypatch.setattr(member_portal_serving, "render_page",
                        lambda biz, site, request, me, m, sub, door="": f"MY SERVING{door}")
    html, status = asyncio.run(mpl.serve(_req(), BUSINESS, {}, dict(_me(DANA), email="dana@example.com"), "/my/lead"))
    assert status == 200 and html.startswith("MY SERVING") and "Open the booth" in html


def test_the_door_says_churchsavvy_for_a_part_that_isnt_the_booth():
    door = mpl.savvy_door(["media"])
    assert "Open ChurchSavvy" in door and "sermons, live and clips" in door
    assert mpl.savvy_door([]) == ""
