# __tests__/test_group_prayer.py
#
# A church group's prayer wall (group_prayer.py + the group page's Prayer
# tab; part 3 of the approved canvas "Church Groups, Together"). Pins:
#   1. "This group" puts a request on the wall, by first name, and tells the
#      group; "Only the pastors" goes to Prayer & care and never to the wall
#   2. words about harm, abuse or a death never reach the wall: a pastor gets
#      them, and the wall shows only that a pastor has one (without a name)
#   3. a request the check refuses never goes up; one it can't check waits
#   4. "I'm praying" toggles, tells the asker (never the asker about their
#      own), and only people in the group can press it
#   5. the asker marks it answered with a word of praise; then "Praise God"
#   6. the asker takes theirs down; a leader takes any down; nobody else
#   7. the Prayer tab, its filter, its count; the routes come back to it

import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import group_prayer as gp
import member_portal_groups as mpg
import test_member_portal_group_space as gs
from test_member_portal_group_space import (BIZ, BUSINESS, G, G_OPEN, MONIQUE, ROCHELLE, TASHA, TEEN,  # noqa: F401
                                            _client, _me, _req, _screen, fake)


@pytest.fixture
def wall(fake, monkeypatch):
    import church_prayer
    import member_push
    import sb_clients
    fake.t.update(group_prayers=[], group_prayer_marks=[], ministry_care_requests=[])
    told = []
    monkeypatch.setattr(member_push, "tell_group_prayer", lambda biz, g, pid, me: told.append(("prayer", g["id"], pid)))
    monkeypatch.setattr(member_push, "tell_group_praying", lambda biz, gid, pid, asker: told.append(("praying", pid, asker)))
    monkeypatch.setattr(church_prayer, "on_new", lambda biz, row: None)

    def delete(path):
        table, params = gs._params(path)
        fake.t[table] = [r for r in fake.t.get(table, []) if r not in fake._rows(table, params)]
        return True
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", delete)
    _screen(monkeypatch, "ok")
    fake.prayed = told
    return fake


def _ask(me, body, pastors=False):
    g = mpg.group_row(BIZ, G)
    return asyncio.run(gp.ask(BUSINESS, me, g, body, pastors))


def _wall_of(who, answered=False):
    return gp.wall(BIZ, G, who, answered=answered)


def _page(who, qs=b""):
    data = mpg.space(BIZ, G, _me(who, "x"), tab="prayer")
    data["prayer"] = gp.wall(BIZ, G, who, answered=b"answered" in qs)
    html, status = mpg.render(BUSINESS, None, _req(qs), _me(who, "x"), data, "prayer")
    return html


# ── 1. who sees it ───────────────────────────────────────────────────

def test_a_request_to_the_group_goes_on_the_wall(wall):
    assert _ask(_me(MONIQUE, "Monique Brown"), "Job interview Friday at 10. Peace either way.") == (True, "prayer_up")
    row = wall.t["group_prayers"][0]
    assert row["body"].startswith("Job interview") and row["contact_id"] == MONIQUE and not row.get("to_pastor")
    assert wall.prayed == [("prayer", G, row["id"])]
    w = _wall_of(TASHA)
    assert w["items"][0]["asker"]["name"] == "Monique Brown" and not w["items"][0]["mine"]
    html = _page(TASHA)
    assert "Job interview Friday" in html and "Monique" in html and "Brown" not in html.split("Job interview")[0][-300:]
    assert "I’m praying" in html


def test_only_the_pastors_never_reaches_the_wall(wall):
    assert _ask(_me(MONIQUE, "Monique Brown"), "Something just for the pastors", pastors=True) == (True, "prayer_pastors")
    assert wall.t["group_prayers"] == []
    care = wall.t["ministry_care_requests"][0]
    assert care["submission"]["confidential"] == "yes" and care["submission"]["source"] == "Group: Sisters in the City"
    assert wall.prayed == []


# ── 2. a pastor first ────────────────────────────────────────────────

def test_danger_words_go_to_a_pastor_and_the_wall_shows_only_that(wall):
    assert _ask(_me(MONIQUE, "Monique Brown"), "My husband hits me when he drinks") == (True, "prayer_pastor_first")
    card = wall.t["group_prayers"][0]
    assert card["to_pastor"] is True and card.get("body") is None
    assert wall.t["ministry_care_requests"][0]["submission"]["prayer_request"].startswith("My husband")
    assert wall.prayed == []                                   # the group isn't told
    assert _wall_of(TASHA)["items"][0]["asker"] is None        # who asked never leaves the server
    other = _page(TASHA)
    assert "A pastor has a request from this group" in other and "hits me" not in other and "Monique" not in other.split("gp-list")[1]
    assert "went to them, not the wall" in _page(MONIQUE)


def test_a_crisis_verdict_also_goes_to_a_pastor(wall, monkeypatch):
    _screen(monkeypatch, "self_harm")
    assert _ask(_me(MONIQUE, "Monique"), "I can't do this anymore")[1] == "prayer_pastor_first"


# ── 3. the check ─────────────────────────────────────────────────────

@pytest.mark.parametrize("verdict,code", [("harm", "prayer_no"), ("down", "post_busy")])
def test_a_refused_or_unchecked_request_never_goes_up(wall, monkeypatch, verdict, code):
    _screen(monkeypatch, verdict)
    assert _ask(_me(MONIQUE, "Monique"), "something") == (False, code)
    assert wall.t["group_prayers"] == [] and wall.t["ministry_care_requests"] == []


def test_an_empty_request(wall):
    assert _ask(_me(MONIQUE, "Monique"), "   ") == (False, "empty")


# ── 4. I'm praying ───────────────────────────────────────────────────

def _member_of(who):
    return lambda gid: mpg._is_member(BIZ, gid, who)


def test_praying_toggles_and_tells_the_asker(wall):
    _ask(_me(MONIQUE, "Monique"), "Surgery Thursday")
    pid = wall.t["group_prayers"][0]["id"]
    assert gp.mark(BUSINESS, _me(TASHA, "Tasha"), pid, "praying", _member_of(TASHA))[:2] == (True, "praying")
    assert ("praying", pid, MONIQUE) in wall.prayed
    w = _wall_of(TASHA)["items"][0]
    assert w["praying_n"] == 1 and w["i_pray"]
    assert gp.mark(BUSINESS, _me(TASHA, "Tasha"), pid, "praying", _member_of(TASHA))[:2] == (True, "unmarked")
    assert _wall_of(TASHA)["items"][0]["praying_n"] == 0
    assert _wall_of(TASHA)["prayed_month"] == 0


def test_the_asker_praying_for_their_own_tells_nobody(wall):
    _ask(_me(MONIQUE, "Monique"), "Surgery Thursday")
    pid = wall.t["group_prayers"][0]["id"]
    gp.mark(BUSINESS, _me(MONIQUE, "Monique"), pid, "praying", _member_of(MONIQUE))
    assert not any(t[0] == "praying" for t in wall.prayed)


def test_only_people_in_the_group_pray_on_its_wall(wall):
    _ask(_me(MONIQUE, "Monique"), "Surgery Thursday")
    pid = wall.t["group_prayers"][0]["id"]
    assert gp.mark(BUSINESS, _me(ROCHELLE, "Rochelle"), pid, "praying", _member_of(ROCHELLE))[:2] == (False, "not_in_group")
    assert wall.t["group_prayer_marks"] == []


def test_a_pastor_card_cant_be_marked(wall):
    _ask(_me(MONIQUE, "Monique"), "My husband hits me")
    pid = wall.t["group_prayers"][0]["id"]
    assert gp.mark(BUSINESS, _me(TASHA, "Tasha"), pid, "praying", _member_of(TASHA))[:2] == (False, "prayer_gone")


# ── 5. answered ──────────────────────────────────────────────────────

def test_the_asker_marks_it_answered_and_the_group_praises(wall):
    _ask(_me(MONIQUE, "Monique"), "My son's recovery")
    pid = wall.t["group_prayers"][0]["id"]
    assert gp.mark(BUSINESS, _me(TASHA, "Tasha"), pid, "praise", _member_of(TASHA))[:2] == (False, "error")   # not yet
    assert gp.answer(BIZ, _me(TASHA, "Tasha"), pid, "x")[:2] == (False, "not_yours")
    assert gp.answer(BIZ, _me(MONIQUE, "Monique"), pid, "He walked into church with no brace.")[:2] == (True, "answered")
    assert _wall_of(TASHA)["items"] == [] and _wall_of(TASHA)["answered_n"] == 1
    done = _wall_of(TASHA, answered=True)["items"][0]
    assert done["praise"] == "He walked into church with no brace."
    assert gp.mark(BUSINESS, _me(TASHA, "Tasha"), pid, "praise", _member_of(TASHA))[:2] == (True, "praised")
    html = _page(TASHA, b"view=answered")
    assert "Praise God" in html and "no brace" in html and "Answered · 1" in html


# ── 6. taking it down ────────────────────────────────────────────────

def _leader_of(who):
    return lambda gid: mpg._is_leader(BIZ, gid, who)


def test_the_asker_or_a_leader_takes_it_down(wall):
    _ask(_me(MONIQUE, "Monique"), "one")
    _ask(_me(MONIQUE, "Monique"), "two")
    one, two = (r["id"] for r in wall.t["group_prayers"])
    assert gp.remove(BIZ, _me(TEEN, "Kayla"), one, _leader_of(TEEN))[:2] == (False, "not_yours")
    assert gp.remove(BIZ, _me(MONIQUE, "Monique"), one, _leader_of(MONIQUE))[:2] == (True, "prayer_down")
    assert gp.remove(BIZ, _me(TASHA, "Tasha"), two, _leader_of(TASHA))[:2] == (True, "prayer_down")   # Tasha leads
    assert _wall_of(TASHA)["items"] == []


# ── 7. the tab and the routes ────────────────────────────────────────

def test_the_tab_is_in_the_group_nav_and_home(wall):
    data = mpg.space(BIZ, G, _me(MONIQUE, "Monique"))
    html, _ = mpg.render(BUSINESS, None, _req(), _me(MONIQUE, "Monique"), data, "")
    assert f'href="/my/groups/{G}/prayer"' in html and "Prayer wall" in html
    page = _page(MONIQUE)
    assert 'action="/my/groups/prayer"' in page and "Only the pastors" in page and "prayers prayed this month" in page


def test_routes_land_back_on_the_wall(wall, monkeypatch):
    c = _client(monkeypatch, _me(MONIQUE, "Monique Brown"))
    r = c.post("/my/groups/prayer", data={"group_id": G, "body": "Pray for my mom", "to": "group"})
    assert r.headers["location"] == f"/my/groups/{G}/prayer?done=prayer_up"
    pid = wall.t["group_prayers"][0]["id"]
    r = _client(monkeypatch, _me(TASHA, "Tasha")).post("/my/groups/prayer/mark", data={"id": pid, "kind": "praying"})
    assert r.headers["location"] == f"/my/groups/{G}/prayer?done=praying"
    r = _client(monkeypatch, _me(ROCHELLE, "Rochelle")).post("/my/groups/prayer", data={"group_id": G, "body": "hi"})
    assert r.headers["location"] == f"/my/groups/{G}?err=not_in_group"
    r = _client(monkeypatch, _me(MONIQUE, "Monique")).post("/my/groups/prayer/remove", data={"id": "not-a-uuid"})
    assert r.headers["location"].startswith("/my/groups?err=")


def test_the_wall_is_in_the_export_and_never_reimported():
    import account_lifecycle as al
    t = al.BUSINESS_CHILD_TABLES
    assert t.index("group_prayer_marks") < t.index("group_prayers") < t.index("groups") < t.index("contacts")
    assert {"group_prayers", "group_prayer_marks"} <= set(al._IMPORT_SKIP)
