# __tests__/test_member_posts.py
#
# Members post (member_posts.py), the way Kevin approved Look 5.1:
#   - members post freely inside their own groups (a church_posts row for the
#     group: only its people see it), never in a group they're not in, never
#     in another church's group, and not while the church has member posting
#     off or lacks its two safety officers;
#   - every post is checked like a comment: shown, held for a safety officer
#     (the writer sees it marked; nobody else does; the officers find it with
#     the held comments and decide it), or care with 988; if the check can't
#     run, nothing posts;
#   - teens follow messaging's rules: a birthdate, a teen's messaging switch,
#     two adult leaders in a group with a teen, no photos into a group with teens;
#   - its writer or a leader of its group takes it down; nobody else;
#   - the whole church goes through a pastor: good news waits in the existing
#     queue, a prayer request goes to the pastors; the good-news queue never
#     shows a held group post;
#   - the owner turns member posting off from their preview; nobody else can;
#   - with the new look off, nothing here writes.

import pathlib
import sys
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import church_news as cn
import member_posts as mpo
import messaging_router as mr
import news_share as ns
import test_member_messaging as tmm
from test_member_group_chat import church as gchurch  # noqa: F401  (fixture)
from test_member_messaging import env  # noqa: F401  (fixture)

OTHER_GRP = "00000000-0000-4000-8000-0000000000e9"


@pytest.fixture
def world(gchurch, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    monkeypatch.setattr(mr, "officer_count", lambda b: 2)
    gchurch.t.setdefault("church_posts", [])
    gchurch.t["groups"].append({"id": OTHER_GRP, "business_id": "22222222-2222-2222-2222-222222222222", "name": "Elsewhere",
                                "active": True, "kind": "small_group", "join_mode": "open", "name_display": "full"})
    cared = []
    import member_portal_messaging as mpm
    monkeypatch.setattr(mpm, "care_alert", lambda b, me: cared.append(me["id"]))
    gchurch.cared = cared
    import member_portal_write as mpw

    async def photos(biz_id, files):
        return [{"path": f"{biz_id}/news-photos/p{i}.webp", "w": 800, "h": 600} for i, _ in enumerate(files)], ""
    monkeypatch.setattr(mpw, "_photos", photos)
    return gchurch


def _client(env, who, preview=False):
    env.who.update(id=who, preview=preview)
    app = FastAPI()
    app.include_router(mpo.router)
    return TestClient(app, base_url=f"https://{tmm.HOST}")


def _post(env, who, data, files=None):
    return _client(env, who).post("/my/post", data=data, files=files, headers=tmm.ORIGIN, follow_redirects=False)


def _posts(env):
    return [r for r in env.t.get("church_posts", []) if r.get("source") == "member"]


# ─── in their own group ──────────────────────────────────────────────


def test_a_member_posts_in_their_own_group(world):
    r = _post(world, tmm.ANA, {"type": "praise", "to": tmm.GRP, "body": "God provided the rent this month!",
                               "comments": "prayers"})
    assert r.status_code == 303 and r.headers["location"] == f"/my/groups/{tmm.GRP}?done=posted"
    (p,) = _posts(world)
    assert p["group_id"] == tmm.GRP and p["posted_by"] == tmm.ANA and p["status"] == "posted"
    assert p["kind"] == "praise" and p["comments"] == "prayers" and p["attach"] == {"member": "praise"}
    assert p["alerted_at"]                                   # never rings phones
    # Only the group's people see it (church_news.reaches).
    assert cn.reaches(p, {tmm.GRP}, tmm.BEN) and not cn.reaches(p, set(), tmm.CARL)


def test_not_in_a_group_they_are_not_in(world):
    r = _post(world, tmm.CARL, {"type": "praise", "to": tmm.GRP, "body": "Hello"})
    assert "err=post_not_member" in r.headers["location"] and not _posts(world)


def test_not_in_another_churchs_group(world):
    world.t["group_members"].append({"group_id": OTHER_GRP, "contact_id": tmm.ANA, "business_id": tmm.BIZ, "role": "member"})
    r = _post(world, tmm.ANA, {"type": "praise", "to": OTHER_GRP, "body": "Hello"})
    assert "err=post_not_member" in r.headers["location"] and not _posts(world)


def test_not_while_the_church_has_it_off(world):
    world.biz["settings"].setdefault("member_portal", {})["member_posts"] = False
    r = _post(world, tmm.ANA, {"type": "praise", "to": tmm.GRP, "body": "Hello"})
    assert "err=post_off" in r.headers["location"] and not _posts(world)


def test_not_before_the_two_safety_officers(world, monkeypatch):
    monkeypatch.setattr(mr, "officer_count", lambda b: 1)
    r = _post(world, tmm.ANA, {"type": "praise", "to": tmm.GRP, "body": "Hello"})
    assert "err=post_officers" in r.headers["location"] and not _posts(world)


def test_photos_up_to_four(world):
    pics = [("photos", (f"p{i}.jpg", b"x", "image/jpeg")) for i in range(2)]
    r = _post(world, tmm.ANA, {"type": "photo", "to": tmm.GRP, "body": "Game night"}, files=pics)
    assert "done=posted" in r.headers["location"]
    (p,) = _posts(world)
    assert p["kind"] == "photos" and len(p["attach"]["pics"]) == 2
    many = [("photos", (f"p{i}.jpg", b"x", "image/jpeg")) for i in range(5)]
    r = _post(world, tmm.ANA, {"type": "photo", "to": tmm.GRP, "body": ""}, files=many)
    assert "err=post_photos" in r.headers["location"] and len(_posts(world)) == 1


# ─── the check ───────────────────────────────────────────────────────


def test_a_held_post_shows_only_to_its_writer_and_the_officers(world):
    world.verdict = "harm"
    r = _post(world, tmm.ANA, {"type": "praise", "to": tmm.GRP, "body": "Something unkind"})
    assert "done=post_held" in r.headers["location"]
    (p,) = _posts(world)
    assert p["status"] == "waiting" and p["attach"]["held"] == "harm"
    assert not cn.is_live(p)                                # never in anyone's feed
    mine = mpo.group_feed(tmm.BIZ, tmm.GRP, tmm.ANA)
    theirs = mpo.group_feed(tmm.BIZ, tmm.GRP, tmm.BEN)
    assert [x["id"] for x in mine] == [p["id"]] and mine[0]["held"] and theirs == []
    held = mpo.held_posts(tmm.BIZ)
    assert [h["id"] for h in held] == [p["id"]] and held[0]["body"] == "Something unkind"
    assert held[0]["post_title"] == "their own post in Tuesday Night"
    # Never in the good-news queue.
    assert ns.mine(tmm.BIZ, tmm.ANA) == []
    # A safety officer lets it through.
    assert mpo.decide_held(tmm.BIZ, p["id"], True) is True
    assert _posts(world)[0]["status"] == "posted"
    assert mpo.decide_held(tmm.BIZ, p["id"], True) is False   # already decided


def test_crisis_words_are_held_and_the_pastor_is_told(world):
    world.verdict = "self_harm"
    r = _post(world, tmm.ANA, {"type": "praise", "to": tmm.GRP, "body": "I don't want to be here"})
    assert "done=care" in r.headers["location"] and world.cared == [tmm.ANA]
    assert _posts(world)[0]["status"] == "waiting" and _posts(world)[0]["attach"]["held"] == "care"
    assert "988" in mpo.DONE["care"]


def test_when_the_check_cant_run_nothing_posts(world):
    world.verdict = "down"
    r = _post(world, tmm.ANA, {"type": "praise", "to": tmm.GRP, "body": "Hello"})
    assert "err=post_busy" in r.headers["location"] and not _posts(world)


# ─── teens ───────────────────────────────────────────────────────────


def test_a_group_with_a_teen_needs_two_adult_leaders(world):
    r = _post(world, tmm.TEEN, {"type": "praise", "to": tmm.YOUTH, "body": "Hi"})
    assert "err=post_two_adults" in r.headers["location"]
    world.t["group_members"].append({"group_id": tmm.YOUTH, "contact_id": tmm.BEN, "business_id": tmm.BIZ, "role": "leader"})
    r = _post(world, tmm.TEEN, {"type": "praise", "to": tmm.YOUTH, "body": "Hi"})
    assert "done=posted" in r.headers["location"]


def test_a_teen_needs_messaging_on_and_no_photos_go_to_teens(world):
    world.t["group_members"].append({"group_id": tmm.YOUTH, "contact_id": tmm.BEN, "business_id": tmm.BIZ, "role": "leader"})
    r = _post(world, tmm.CARL, {"type": "photo", "to": tmm.YOUTH, "body": "Trip"},
              files=[("photos", ("a.jpg", b"x", "image/jpeg"))])
    assert "err=post_teen_photos" in r.headers["location"]
    for m in world.t["msg_members"]:
        if m["contact_id"] == tmm.TEEN:
            m["enabled"] = False
    r = _post(world, tmm.TEEN, {"type": "praise", "to": tmm.YOUTH, "body": "Hi"})
    assert "err=post_teen_off" in r.headers["location"] and not _posts(world)


def test_someone_without_a_birthdate_cant_post_yet(world):
    world.t["group_members"].append({"group_id": tmm.GRP, "contact_id": tmm.NOBIRTH, "business_id": tmm.BIZ, "role": "member"})
    r = _post(world, tmm.NOBIRTH, {"type": "praise", "to": tmm.GRP, "body": "Hi"})
    assert "err=post_birthday" in r.headers["location"]


# ─── taking one down ─────────────────────────────────────────────────


def test_its_writer_or_a_group_leader_takes_it_down(world):
    _post(world, tmm.ANA, {"type": "praise", "to": tmm.GRP, "body": "One"})
    _post(world, tmm.ANA, {"type": "praise", "to": tmm.GRP, "body": "Two"})
    one, two = _posts(world)
    c = _client(world, tmm.CARL)                             # not in the group
    r = c.post("/my/post/remove", data={"id": one["id"]}, headers=tmm.ORIGIN, follow_redirects=False)
    assert "err=post_gone" in r.headers["location"] and not one.get("removed_at")
    c = _client(world, tmm.BEN)                              # the group's leader
    r = c.post("/my/post/remove", data={"id": one["id"]}, headers=tmm.ORIGIN, follow_redirects=False)
    assert r.headers["location"] == f"/my/groups/{tmm.GRP}?done=removed"
    c = _client(world, tmm.ANA)                              # its writer
    c.post("/my/post/remove", data={"id": two["id"]}, headers=tmm.ORIGIN, follow_redirects=False)
    assert all(p["status"] == "removed" and p["removed_at"] for p in _posts(world))


# ─── the whole church, through a pastor ──────────────────────────────


def test_good_news_for_the_whole_church_waits_for_a_pastor(world):
    r = _post(world, tmm.ANA, {"type": "praise", "to": "church", "share_kind": "job", "body": "I got the job!"})
    assert r.headers["location"] == "/my/post?done=shared"
    (p,) = _posts(world)
    assert p["kind"] == "good_news" and p["status"] == "waiting" and not p.get("group_id")
    r = _post(world, tmm.ANA, {"type": "praise", "to": "church", "body": "No kind chosen"})
    assert "err=post_kind" in r.headers["location"]


def test_a_prayer_for_the_whole_church_goes_to_the_pastors(world, monkeypatch):
    import church_prayer
    monkeypatch.setattr(church_prayer, "on_new", lambda b, row: None)
    r = _post(world, tmm.ANA, {"type": "prayer", "to": "church", "body": "My dad's surgery"})
    assert r.headers["location"] == "/my/post?done=prayer_sent"
    (req,) = world.t["ministry_care_requests"]
    assert req["submission"]["prayer_request"] == "My dad's surgery" and req["submission"]["confidential"] == "yes"
    assert not _posts(world)


# ─── the switch, the look ────────────────────────────────────────────


def test_only_the_owner_turns_member_posting_off(world, monkeypatch):
    c = _client(world, tmm.ANA)
    r = c.post("/my/post/switch", data={"on": "0"}, headers=tmm.ORIGIN, follow_redirects=False)
    assert r.headers["location"] == "/my" and mpo.on(world.biz)
    world.t["businesses"][0]["settings"] = world.biz["settings"]
    import member_portal as mp
    monkeypatch.setattr(mp, "_session_for", lambda req, church: {"preview": True, "claims": {"own": tmm.OWNER},
                                                                "me": {"id": tmm.ANA}, "people": []})
    r = c.post("/my/post/switch", data={"on": "0"}, headers=tmm.ORIGIN, follow_redirects=False)
    assert r.headers["location"] == "/my/post?done=switch_off"
    assert world.t["businesses"][0]["settings"]["member_portal"]["member_posts"] is False
    assert not mpo.on({"settings": world.t["businesses"][0]["settings"]})


def test_the_preview_saves_no_post(world):
    r = _client(world, tmm.ANA, preview=True).post("/my/post", data={"type": "praise", "to": tmm.GRP, "body": "Hi"},
                                                   headers=tmm.ORIGIN, follow_redirects=False)
    assert "err=preview" in r.headers["location"] and not _posts(world)


def test_with_the_new_look_off_nothing_writes(world, monkeypatch):
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    r = _post(world, tmm.ANA, {"type": "praise", "to": tmm.GRP, "body": "Hi"})
    assert r.headers["location"] == "/my" and not _posts(world)


def test_the_switch_defaults_on_like_comments():
    assert mpo.on({"settings": {}}) and mpo.on({"settings": {"member_portal": {}}})
    assert not mpo.on({"settings": {"member_portal": {"member_posts": False}}})


# ─── where the posts show: the group's page, the composer ────────────


def _page(env, who, path):
    import member_portal as mp
    env.who.update(id=who, preview=False)
    app = FastAPI()

    @app.get("/my/{rest:path}")
    async def page(rest: str, request: mp.Request):
        return await mp.serve(request, "/my/" + rest)
    return TestClient(app, base_url=f"https://{tmm.HOST}").get(path, follow_redirects=False)


def test_the_groups_page_shows_its_posts_and_hides_the_held_ones(world):
    _post(world, tmm.ANA, {"type": "praise", "to": tmm.GRP, "body": "Answered prayer this week"})
    world.verdict = "harm"
    _post(world, tmm.ANA, {"type": "praise", "to": tmm.GRP, "body": "Held words here"})
    ben = _page(world, tmm.BEN, f"/my/groups/{tmm.GRP}").text
    assert "Answered prayer this week" in ben and "Held words here" not in ben
    assert ben.count('action="/my/post/remove"') == 1           # the group's leader may take it down
    ana = _page(world, tmm.ANA, f"/my/groups/{tmm.GRP}").text
    assert "Held words here" in ana and "Only you can see it until then." in ana
    assert ana.count('action="/my/post/remove"') == 2           # its writer, both
    assert 'action="/my/news/react"' in ana and f'name="back" value="/my/groups/{tmm.GRP}"' in ana
    assert "lm-share" not in ana                                # members' posts never get a share


def test_the_composer_picks_the_group_and_the_owner_sees_the_switch(world):
    html = _page(world, tmm.ANA, f"/my/post?group={tmm.GRP}").text
    assert '<form class="lm-mpform" id="lm-post" method="post" action="/my/post"' in html
    assert f'name="to" value="{tmm.GRP}" checked' in html and 'name="to" value="church"' in html
    assert "Prayer request" in html and 'name="photos"' in html and "/my/post/switch" not in html
    world.biz["settings"].setdefault("member_portal", {})["member_posts"] = False
    html = _page(world, tmm.ANA, "/my/post").text
    assert "Posting in groups is off at your church right now." in html
    assert f'name="to" value="{tmm.GRP}"' not in html and 'name="to" value="church" checked' in html


def test_the_composer_is_the_new_looks_only(world, monkeypatch):
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    r = _page(world, tmm.ANA, "/my/post")
    assert r.status_code == 303 and r.headers["location"] == "/my"
