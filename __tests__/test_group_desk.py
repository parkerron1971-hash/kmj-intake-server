# __tests__/test_group_desk.py
#
# The leader's desk on a computer (group_desk + member_portal_lead; the
# approved canvas "Church Groups, Together", board Desk). Pins:
#   1. My group carries the desk's three columns; the phone keeps My group
#      as it is (it's the right column), with the next gathering on top
#   2. the left and middle columns come from GET /my/lead/groups/<id>/desk,
#      only for that group's own leader, fetched only on a wide screen; the
#      page alone never marks the chat read
#   3. the middle is the group's chat: what's sent there comes back to the desk
#   4. the left is the leader's chats, grouped, with unread counts

import asyncio
import pathlib
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import group_desk as gd
import member_portal_lead as mpl
import member_portal_messaging as mpm
from test_group_lead import _page, lead  # noqa: F401
from test_group_gatherings import meet  # noqa: F401
from test_member_portal_group_space import BIZ, G, MONIQUE, TASHA, TEEN, fake  # noqa: F401
from test_chat_polls import polls  # noqa: F401
from test_member_group_chat import _msg, church  # noqa: F401
from test_member_messaging import ANA, BEN, CARL, GRP, HOST, JSON, ORIGIN, YOUTH, _group_tid, _send, env  # noqa: F401


# ── 1. the page ──────────────────────────────────────────────────────

def test_my_group_carries_the_desk(lead):
    html, status = _page(TASHA)
    assert status == 200 and '<div class="gd">' in html
    assert 'id="gd-side"' in html and 'id="gd-mid"' in html and '<div class="gd-rail">' in html
    assert f'href="/my/groups/{G}/chat">Open the chat</a>' in html                     # without the script, where the chat is
    assert "matchMedia('(min-width:1240px)')" in html and f"'/my/lead/groups/'+\"{G}\"+'/desk'" in html
    rail = html.split('<div class="gd-rail">')[1]
    assert "Needs you" in rail and "Quick" in rail                                     # My group, as the phone has it
    assert ".gd-side,.gd-mid{display:none;}" in html                                   # a phone never shows the columns


def test_the_next_gathering_tops_the_rail(lead):
    html, _ = _page(TASHA)                                     # Thursdays at 7, 412 Maple Ave (the meet fixture)
    rail = html.split('<div class="gd-rail">')[1]
    card = rail.split('class="gd-meet"')[1].split("</section>")[0]
    assert rail.index('class="gd-meet"') < rail.index("Needs you")
    assert "412 Maple Ave" in card and "7:00 PM" in card and "no answer" in card and "<small>THU</small>" in card


def test_the_gathering_card_counts():
    g = {"id": G, "meet_time": "19:00:00", "meet_address": "At Renée's"}
    from datetime import date
    v = {"meet": {"next": date(2026, 10, 22), "rsvps": {"a": "going", "b": "going", "c": "maybe", "d": "no"}, "today": True},
         "data": {"people": [{"id": x} for x in "abcdef"]}}
    html = gd.gathering(g, v, esc=lambda s: str(s), ic=lambda n, s=18: "")
    assert "<span><b>2</b>going</span>" in html and "<span><b>1</b>maybe</span>" in html
    assert "<span><b>1</b>can’t</span>" in html and "<span><b>2</b>no answer</span>" in html
    assert "Take attendance" in html and "<b>Today</b>" in html and "At Renée's" in html and "7:00 PM" in html
    v["meet"]["today"] = False
    assert "Take attendance" not in gd.gathering(g, v, esc=str, ic=lambda n, s=18: "")
    v["meet"]["next"] = None
    assert gd.gathering(g, v, esc=str, ic=lambda n, s=18: "") == ""


# ── 2-4. the desk's columns ──────────────────────────────────────────

def _desk(env, who, gid, qs=""):
    env.who["id"] = who
    app = FastAPI()
    app.include_router(mpl.router)
    return TestClient(app, base_url=f"https://{HOST}").get(f"/my/lead/groups/{gid}/desk{qs}", headers={"Accept": "application/json"})


@pytest.fixture
def desk(polls, monkeypatch):
    import church_follow_up as cfu
    import member_portal as mp
    import member_portal_church as mpc
    monkeypatch.setattr(cfu, "roles_for", lambda b, c: [])

    async def signed_in(request):
        c = next(x for x in polls.t["contacts"] if x["id"] == polls.who["id"])
        return {"business": polls.biz, "site": None}, dict(c), False
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    for t in ("group_prayers", "group_studies", "sermons", "group_bring", "group_posts", "group_rsvps", "group_meetings",
              "group_meeting_attendance", "group_join_requests", "group_live_sessions"):
        polls.t.setdefault(t, [])
    return polls


def test_the_desk_is_the_leaders(desk):
    _group_tid(desk, ANA, GRP)
    r = _desk(desk, BEN, GRP)                                                          # Ben leads Tuesday Night
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    d = r.json()
    assert set(d) == {"side", "middle", "script"}
    assert _desk(desk, ANA, GRP).status_code == 404                                    # Ana is a member, not its leader
    assert _desk(desk, CARL, GRP).status_code == 404                                   # Carl leads another group
    assert _desk(desk, BEN, "not-an-id").status_code == 404


def test_the_middle_is_the_groups_chat_and_comes_back_to_the_desk(desk):
    tid = _group_tid(desk, ANA, GRP)
    _send(desk, ANA, tid, "Who has the slow cooker?")
    d = _desk(desk, BEN, GRP).json()
    assert "Who has the slow cooker?" in d["middle"] and 'id="gc-compose"' in d["middle"]
    assert f'name="back" value="/my/lead/groups/{GRP}"' in d["middle"]
    assert f'href="/my/groups/{GRP}/board#post"' in d["middle"] and f'href="/my/groups/{GRP}/chat" aria-current=page' in d["middle"]
    assert not d["script"].lstrip().startswith("<script>") and "gc-compose" in d["script"]
    desk.who["id"] = BEN
    app = FastAPI()
    app.include_router(mpm.router)
    r = TestClient(app, base_url=f"https://{HOST}").post(f"/my/messages/{tid}/send", data={"body": "Jasmine has it.", "back": f"/my/lead/groups/{GRP}"},
                                                         headers=ORIGIN, follow_redirects=False)
    assert r.headers["location"].startswith(f"/my/lead/groups/{GRP}?done=sent")
    assert _msg(desk, "Jasmine has it.")["status"] == "delivered"


def test_the_poll_form_opens_on_the_desk(desk):
    _group_tid(desk, ANA, GRP)
    d = _desk(desk, BEN, GRP, "?make=poll").json()
    assert 'id="gc-pollform"' in d["middle"] and f'value="/my/lead/groups/{GRP}"' in d["middle"]


def test_the_page_alone_never_marks_the_chat_read(desk, monkeypatch):
    seen = []
    monkeypatch.setattr(mpm, "mark_read", lambda b, t, c: seen.append(c))
    _group_tid(desk, ANA, GRP)
    seen.clear()
    from test_group_lead import _req
    from test_member_messaging import BIZ as MBIZ  # noqa: F401
    desk.who["id"] = BEN
    html, status = asyncio.run(mpl.serve_groups(_req(), desk.biz, None, dict(next(c for c in desk.t["contacts"] if c["id"] == BEN)), GRP))
    assert status == 200 and seen == []                                                # the phone's My group
    _desk(desk, BEN, GRP)
    assert seen == [BEN]                                                               # the desk, when it's shown


def test_the_left_is_the_leaders_chats(desk):
    tid = _group_tid(desk, ANA, GRP)
    adults = "00000000-0000-4000-8000-0000000000e9"
    desk.t["groups"].append({**desk.t["groups"][0], "id": adults, "name": "Men's Breakfast"})
    desk.t["group_members"] += [{"group_id": adults, "contact_id": CARL, "business_id": BIZ, "role": "leader"},
                                {"group_id": adults, "contact_id": BEN, "business_id": BIZ, "role": "member"}]
    ytid = _group_tid(desk, BEN, adults)
    assert _send(desk, CARL, ytid, "Breakfast is Saturday").json()["ok"]
    _send(desk, ANA, tid, "hello")
    side = _desk(desk, BEN, GRP).json()["side"]
    lead_part = side.split("You lead")[1].split("You’re in")[0]
    assert f'href="/my/lead/groups/{GRP}"' in lead_part and "aria-current=page" in lead_part   # this desk
    assert 'aria-label="1 unread"' not in lead_part                                           # it's open: no badge
    youth = side.split("You’re in")[1]
    assert f'href="/my/groups/{adults}/chat"' in youth and "Breakfast is Saturday" in youth and 'aria-label="1 unread"' in youth
    assert 'href="/my/messages">All messages</a>' in side


def test_inbox_rows_know_their_group(desk):
    _group_tid(desk, ANA, GRP)
    chats, _ = mpm.inbox_rows(BIZ, ANA)
    assert [r["group_id"] for r in chats if r["kind"] == "group"] == [GRP]


def test_a_desk_address_is_a_safe_way_back():
    import member_portal_church as mpc
    ok = mpc._back(f"/my/lead/groups/{GRP}", done="sent")
    assert ok.headers["location"] == f"/my/lead/groups/{GRP}?done=sent"
    assert mpc._back("/my/lead/groups/evil", done="sent").headers["location"] == "/my?done=sent"
    assert mpm._GROUP_BACK.match(f"/my/lead/groups/{GRP}") and not mpm._GROUP_BACK.match("/my/lead/groups/x/../../admin")
