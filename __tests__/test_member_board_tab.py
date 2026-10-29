"""The Board tab in the member app (member_portal_board.py). Kevin 2026-10-28:
"The 7 office logins are for the office only ... Everyone else uses the
member app, by role", then "lets build the board tab".

Pins:
  * only the church's people on a board get the tab, and only their own
    boards: not an archived board, not a seat they left, not another
    church's
  * a meeting's minutes, votes and who came show once they're sent for
    approval (or approved); before then, the agenda alone
  * the decisions log shows only decisions whose minutes are out, on their
    own boards
  * the tab bar: Board last for a board member; one with Serve keeps Serve,
    and finds the Board in a computer's sidebar and at the top of Serve
  * the tab follows CHURCH_BOARD (owner and off: no tab, the pages go Home),
    and a read that fails is a 503 page, never a 500 or an empty board
  * whatever the secretary typed is escaped
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest
from fastapi import HTTPException
from starlette.requests import Request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import member_portal_board as mpb  # noqa: E402
from test_church_board import (BIZ, ELLIS, HAYES, MOORE, OTHER, REED, _board, _deacons,  # noqa: E402,F401
                               _decide, _item, _mark, _meeting, _member, _patch_item, _status, client, db, ok)


def person(cid, name="Darnell Hayes", email="deacon@lovecity.org"):
    return {"id": cid, "name": name, "email": email}


def church(db):
    return dict(db.t["businesses"][0])


def req(path="/my/board", qs=b""):
    return Request({"type": "http", "method": "GET", "path": path, "query_string": qs, "headers": [],
                    "server": ("x", 443), "scheme": "https"})


def run(coro):
    return asyncio.run(coro)


def test_only_the_boards_a_person_sits_on(db):
    deacons, ids = _deacons()                       # Hayes, Moore, Price
    elders = _board("Elders")
    ok(_member(elders["id"], contact_id=REED))
    old = _board("Trustees")
    ok(_member(old["id"], contact_id=HAYES))
    ok(client("owner").patch(f"/church/board/boards/{old['id']}", json={"business_id": BIZ, "archived": True}))
    assert mpb.boards_of(BIZ, HAYES) == {deacons["id"]}, "an archived board is no one's tab"
    assert mpb.boards_of(BIZ, REED) == {elders["id"]}
    assert mpb.boards_of(BIZ, ELLIS) == set(), "a member on no board"
    assert mpb.boards_of(OTHER, HAYES) == set(), "another church"
    assert mpb.boards_of(BIZ, "not-a-person") == set()
    ok(client("owner").patch(f"/church/board/members/{ids['moore']}", json={"business_id": BIZ, "active": False}))
    assert mpb.boards_of(BIZ, MOORE) == set(), "a seat they left"

    # Asking for a board they aren't on shows their own.
    view = mpb.board_view(church(db), person(HAYES), elders["id"])
    assert view["board"]["id"] == deacons["id"] and [b["id"] for b in view["boards"]] == [deacons["id"]]
    for who in (ELLIS, MOORE):
        with pytest.raises(HTTPException) as e:
            mpb.board_view(church(db), person(who))
        assert e.value.status_code == 403
        with pytest.raises(HTTPException) as e:
            mpb.decisions_view(church(db), person(who))
        assert e.value.status_code == 403


def test_the_minutes_votes_and_who_came_show_once_sent(db):
    deacons, ids = _deacons()
    m = _meeting(deacons["id"], title="<script>alert(1)</script>", place="Fellowship Hall")["meeting"]
    roof = _item(m["id"], "The roof <b>bids</b>", notes="Three bids came in.")
    _status(m["id"], "in_progress")
    assert _patch_item(roof["id"], minutes="Discussed the bids. <img src=x onerror=alert(1)>").status_code == 200
    assert _decide(roof["id"], moved_by=ids["hayes"], seconded_by=ids["moore"]).status_code == 200
    _mark(m["id"], ids["hayes"], "present")
    _mark(m["id"], ids["moore"], "present")

    # In the meeting: the agenda, never the notes, the vote or who came.
    view = mpb.board_view(church(db), person(HAYES))
    mp = view["chosen"]
    assert mp["hidden"] and mp["meeting"]["id"] == m["id"] and not view["asked"]
    assert mp["items"][0]["minutes"] == "" and mp["items"][0]["decisions"] == []
    assert all(p["status"] is None for p in mp["roster"])
    html = mpb.render_board(church(db), {}, person(HAYES), view)
    assert "The agenda" in html and "Three bids came in." in html and "Discussed the bids" not in html
    assert "Motion:" not in html and "Who came" not in html
    assert "<script>alert(1)" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "The roof &lt;b&gt;bids&lt;/b&gt;" in html
    assert 'class="ld-grid"' in html, "a phone opens on the list, a computer on the meeting beside it"
    assert ' data-shown=""' in html and 'aria-current="page" data-shown' not in html, "marked on a computer only"

    # Ended but not sent: still the agenda.
    _status(m["id"], "drafted")
    assert mpb.board_view(church(db), person(HAYES))["chosen"]["hidden"]

    # Sent for approval: the minutes, the motion and who came.
    assert client("owner").post(f"/church/board/meetings/{m['id']}/send", json={"business_id": BIZ}).status_code == 200
    view = mpb.board_view(church(db), person(HAYES), meeting_id=m["id"])
    mp = view["chosen"]
    assert not mp.get("hidden") and view["asked"]
    assert mp["items"][0]["minutes"].startswith("Discussed the bids")
    assert mp["items"][0]["decisions"][0]["moved_by_name"] == "Darnell Hayes"
    html = mpb.render_board(church(db), {}, person(HAYES), view)
    assert "The minutes, for approval" in html and "Discussed the bids. &lt;img src=x onerror=alert(1)&gt;" in html
    assert "Motion:" in html and "Moved by Darnell Hayes, seconded by Dana Moore" in html and "Carried" in html
    assert "Who came" in html and 'class="ld-grid has-sel"' in html and 'aria-current="page" data-shown' in html
    assert "Minutes to read" in html


def test_the_next_meeting_says_which_minutes_to_read_first(db):
    deacons, _ = _deacons()
    last = _meeting(deacons["id"], "2026-10-01T23:00:00+00:00")["meeting"]
    _item(last["id"], "Budget")
    _status(last["id"], "in_progress")
    assert client("owner").post(f"/church/board/meetings/{last['id']}/send", json={"business_id": BIZ}).status_code == 200
    nxt = _meeting(deacons["id"], "2026-11-05T00:00:00+00:00", video_url="https://meet.example.com/deacons")["meeting"]
    view = mpb.board_view(church(db), person(HAYES))
    assert view["chosen"]["meeting"]["id"] == nxt["id"], "it opens on the next meeting"
    assert [str(w["id"]) for w in view["chosen"]["read_first"]] == [last["id"]]
    html = mpb.render_board(church(db), {}, person(HAYES), view)
    assert "Read before this meeting" in html and "Join the video call" in html
    assert 'href="https://meet.example.com/deacons"' in html and 'rel="noopener noreferrer"' in html


def test_the_decisions_log_shows_only_minutes_that_are_out(db):
    deacons, ids = _deacons()
    sent = _meeting(deacons["id"], "2026-10-01T23:00:00+00:00")["meeting"]
    a = _item(sent["id"], "Roof")
    _status(sent["id"], "in_progress")
    assert _decide(a["id"], motion="Fix the roof.").status_code == 200
    assert client("owner").post(f"/church/board/meetings/{sent['id']}/send", json={"business_id": BIZ}).status_code == 200
    open_ = _meeting(deacons["id"])["meeting"]
    b = _item(open_["id"], "Pastor's raise")
    _status(open_["id"], "in_progress")
    assert _decide(b["id"], motion="A private matter.").status_code == 200
    elders = _board("Elders")
    ok(_member(elders["id"], contact_id=REED))
    em = _meeting(elders["id"], "2026-10-02T23:00:00+00:00")["meeting"]
    c = _item(em["id"], "Elders only")
    _status(em["id"], "in_progress")
    assert _decide(c["id"], motion="An elders' decision.").status_code == 200
    assert client("owner").post(f"/church/board/meetings/{em['id']}/send", json={"business_id": BIZ}).status_code == 200

    motions = [d["motion"] for d in mpb.decisions_view(church(db), person(HAYES))["decisions"]]
    assert motions == ["Fix the roof."], "not one still being written, not another board's"
    assert [d["motion"] for d in mpb.decisions_view(church(db), person(HAYES), q="private")["decisions"]] == []
    assert [d["motion"] for d in mpb.decisions_view(church(db), person(HAYES), board_id=elders["id"])["decisions"]] == \
        ["Fix the roof."], "a board they aren't on is ignored"
    view = mpb.decisions_view(church(db), person(HAYES), q="roof")
    html = mpb.render_decisions(church(db), {}, person(HAYES), view)
    assert "Fix the roof." in html and "What the board <em>decided</em>" in html and 'value="roof"' in html
    none = mpb.render_decisions(church(db), {}, person(HAYES), {**view, "decisions": [], "q": "<x>"})
    assert "Nothing matches “&lt;x&gt;”." in none


def test_the_tab_bar_the_sidebar_and_serve(db):
    import member_app_ui as ui
    import member_portal as mp
    import member_spaces as msp
    biz = church(db)
    alone = ui.nav("home", board=True, biz=biz)
    assert 'href="/my/board"' in alone and alone.index('href="/my/board"') > alone.index('href="/my"')
    assert 'href="/my/board" aria-current="page"' in ui.nav("board", board=True, biz=biz)
    both = ui.nav("board", lead=True, board=True, biz=biz)
    assert 'href="/my/board"' not in both, "the phone's bar holds six: Serve stays"
    assert 'href="/my/lead" aria-current="page"' in both, "the Board sits at the top of Serve"
    assert 'href="/my/board"' not in ui.nav("home", biz=biz)
    _, tail = mp._side(biz, "board", "church", "Love City", None, "", board=True)
    assert 'href="/my/board" aria-current="page"' in tail
    assert 'href="/my/board"' not in mp._side(biz, "home", "church", "Love City", None, "")[1]

    token = msp.CURRENT.set({"board": True, "lead": True})
    try:
        assert 'href="/my/board"' in mpb.serve_door()
        msp.CURRENT.set({"board": True, "lead": False})
        assert mpb.serve_door() == "", "a Board tab of their own"
        msp.CURRENT.set({"board": False, "lead": True})
        assert mpb.serve_door() == ""
    finally:
        msp.CURRENT.reset(token)


def test_the_pages_follow_the_switch_and_send_others_home(db, monkeypatch):
    deacons, _ = _deacons()
    _meeting(deacons["id"], title="October meeting")
    place = {"business": church(db), "site": {}}
    monkeypatch.setattr(mpb, "shown_here", lambda request, biz: False)
    got = run(mpb.serve(req(), place, person(HAYES), "/my/board"))
    assert got.status_code == 200 and "Deacons" in got.body.decode() and "October meeting" in got.body.decode()
    assert "check request" not in got.body.decode(), "no approvals row while check requests don't show"
    got = run(mpb.serve(req("/my/board/decisions", b"q=roof"), place, person(HAYES), "/my/board/decisions"))
    assert got.status_code == 200 and "Nothing matches" in got.body.decode()
    for who in (ELLIS, MOORE + "x"):
        got = run(mpb.serve(req(), place, person(who), "/my/board"))
        assert got.status_code == 303 and got.headers["location"] == "/my"
    assert run(mpb.on_board(church(db), person(HAYES))) is True
    assert run(mpb.on_board(church(db), person(ELLIS))) is False

    # The approvals row, while check requests show here: what waits on them.
    monkeypatch.setattr(mpb, "shown_here", lambda request, biz: True)
    monkeypatch.setattr(mpb.cml, "member_view", lambda biz, me: {"waiting": [{"mine": False}, {"mine": True}],
                                                                  "said": [], "email": ""})
    body = run(mpb.serve(req(), place, person(HAYES), "/my/board")).body.decode()
    assert "1 check request waits on your yes" in body and 'href="/my/board/approvals"' in body

    # The switch: owner and off show no tab, and the pages go Home (or to
    # the approvals, which were all there was before the tab).
    for m in ("owner", "off"):
        monkeypatch.setenv("CHURCH_BOARD", m)
        assert run(mpb.on_board(church(db), person(HAYES))) is False
        got = run(mpb.serve(req(), place, person(HAYES), "/my/board"))
        assert got.status_code == 303 and got.headers["location"] == "/my/board/approvals"
        got = run(mpb.serve(req("/my/board/decisions"), place, person(HAYES), "/my/board/decisions"))
        assert got.status_code == 303 and got.headers["location"] == "/my"
    monkeypatch.setattr(mpb, "shown_here", lambda request, biz: False)
    assert run(mpb.serve(req(), place, person(HAYES), "/my/board")).headers["location"] == "/my"

    # A read that fails: no tab, and a page that says so (never a 500).
    monkeypatch.setenv("CHURCH_BOARD", "on")
    db.missing = True
    assert run(mpb.on_board(church(db), person(HAYES))) is False
    got = run(mpb.serve(req(), place, person(HAYES), "/my/board"))
    assert got.status_code == 503 and "couldn’t load" in got.body.decode()
