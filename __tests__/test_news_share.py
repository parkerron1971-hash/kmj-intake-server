# __tests__/test_news_share.py
#
# Share good news (news_share.py + member_portal_share.py; the approved
# canvas "Church News & Celebrations" board 5, Kevin 2026-10-23: "members can
# share good news since they have to be approved by me or admins"). Pins:
#   1. a share waits for the owner or an admin: never on News until posted,
#      under the member's own name, with what happened as its title
#   2. its words are checked like a comment — harm and an unchecked one are
#      marked for whoever reads it first (a person reads every one), crisis
#      words tell the pastor and show 988
#   3. its photo is checked first: one the check turns down, or one it
#      couldn't check, means nothing is saved at all
#   4. no more than three waiting at once; "just my groups" needs a group
#   5. who sees it: "just my groups" reaches only the people in those
#      groups; the member sees their own; its photo follows the post
#   6. deciding is the owner's or an admin's: Post it (as written or
#      edited), Not now (saved, never a no); posting tells their phone
#   7. the pages: Share good news, Sent, "Have good news?" on News, the
#      celebration page; the routes, and the preview never writes

import asyncio
import pathlib
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import church_news as cn
import member_portal_church as mpc
import member_portal_news as mpn
import member_portal_share as mps
import news_share as ns
import test_member_portal_group_space as gs
from test_church_news import BUSINESS, _me, _post
from test_member_portal_group_space import BIZ, G, MONIQUE, ROCHELLE, TASHA, _params, _req  # noqa: F401

PATH = f"{BIZ}/news-photos/abc.webp"


@pytest.fixture
def fake(monkeypatch):
    f = gs.Fake()
    f.t.update(church_posts=[], church_post_reactions=[], church_post_seen=[], church_post_comments=[],
               church_post_comment_loves=[], church_post_reports=[], church_news_posters=[], sermons=[],
               ministry_care_requests=[], member_push_subscriptions=[],
               businesses=[{"id": BIZ, "name": "Love City Church", "settings": {}, "owner_id": "o1"}])
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", f.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", f.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", f.patch)
    monkeypatch.setattr(cn, "is_pastoral", lambda biz, cid: cid == TASHA)
    import messaging_router as mr
    monkeypatch.setattr(mr, "officer_count", lambda biz: 2)
    import member_portal_messaging as mpm
    f.care = []
    monkeypatch.setattr(mpm, "care_alert", lambda biz, me: f.care.append(me["id"]))
    monkeypatch.setattr(mpc, "upcoming_for", lambda biz, me: [])
    # The photo: made ready, checked, stored and linked without the network.
    import chat_photos
    import member_photos
    import storage_links
    f.stored, f.dropped, f.photo_verdict = [], [], "ok"
    monkeypatch.setattr(chat_photos, "prepare", lambda raw: (b"webp", 1200, 900))
    monkeypatch.setattr(chat_photos, "drop", lambda path: f.dropped.append(path))
    monkeypatch.setattr(member_photos, "_put", lambda path, data: f.stored.append(path) or True)

    async def photo_screen(biz, webp, **kw):
        assert kw.get("policy") == ns.POLICY
        if f.photo_verdict == "down":
            raise member_photos.ScreenUnavailable("down")
        return f.photo_verdict
    monkeypatch.setattr(member_photos, "screen", photo_screen)
    monkeypatch.setattr(storage_links, "signed_url_sync", lambda bucket, path, ttl=0: f"https://signed.example/{path}")
    import member_push
    f.pushed = []
    monkeypatch.setattr(member_push, "send", lambda business, kind, **kw: f.pushed.append((kind, kw)) or 1)
    # Alerts run inline here, so nothing outlives the test (news_alerts).
    monkeypatch.setattr(member_push, "_later", lambda fn, *a, **k: fn(*a, **k))
    _screen(monkeypatch, f, "ok")
    # The fake's rows carry fixed October dates; the 14- and 30-day windows
    # are read on this clock, never the real one.
    from datetime import datetime, timezone
    monkeypatch.setattr(ns, "_now", lambda: datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(cn, "_now", lambda: datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc))
    return f


def _screen(monkeypatch, f, verdict):
    import msg_screen
    f.text_verdict = verdict

    async def screen(biz, text):
        if f.text_verdict == "down":
            raise msg_screen.ScreenUnavailable("down")
        return f.text_verdict
    monkeypatch.setattr(msg_screen, "screen", screen)


def _share(me_id=MONIQUE, kind="grad", text="Imani graduated from nursing school!", who="all", photo=None):
    return asyncio.run(ns.share(BUSINESS, _me(me_id, "Monique Brown"), kind, text, who, photo))


# ── 1. it waits ──────────────────────────────────────────────────────

def test_a_share_waits_under_the_members_own_name(fake):
    ok, code, pid = _share()
    assert (ok, code) == (True, "shared")
    row = fake.t["church_posts"][0]
    assert (row["status"], row["source"], row["kind"]) == ("waiting", "member", "good_news")
    assert row["posted_by"] == MONIQUE and row["person_id"] == MONIQUE
    assert row["title"] == "A graduation" and row["attach"] == {"share": "grad"}
    # Nobody sees it on News until the owner or an admin posts it.
    assert cn.feed(BIZ, ROCHELLE) == [] and cn.feed(BIZ, MONIQUE) == []
    assert cn.one(BIZ, MONIQUE, pid) == {}


def test_an_unknown_kind_or_no_words_is_turned_back(fake):
    assert _share(kind="lottery")[:2] == (False, "share_kind")
    assert _share(text="   ")[:2] == (False, "share_empty")
    assert _share(text="x" * (ns.TEXT_MAX + 1))[:2] == (False, "share_long")
    assert fake.t["church_posts"] == []


# ── 2. its words are checked ─────────────────────────────────────────

def test_harm_and_an_unchecked_share_are_marked_for_the_reader(fake, monkeypatch):
    _screen(monkeypatch, fake, "harm")
    assert _share()[:2] == (True, "shared")
    _screen(monkeypatch, fake, "down")
    assert _share(me_id=ROCHELLE)[:2] == (True, "shared")
    flags = [r["attach"].get("flag") for r in fake.t["church_posts"]]
    assert flags == ["harm", "unchecked"] and fake.care == []


def test_crisis_words_tell_the_pastor_and_show_988(fake, monkeypatch):
    _screen(monkeypatch, fake, "self_harm")
    assert _share()[:2] == (True, "care")
    assert fake.care == [MONIQUE] and fake.t["church_posts"][0]["attach"]["flag"] == "care"
    assert "988" in mps.DONE["care"]


# ── 3. its photo is checked first ────────────────────────────────────

def test_a_checked_photo_is_kept_privately(fake):
    assert _share(photo=b"jpeg")[:2] == (True, "shared")
    pic = fake.t["church_posts"][0]["attach"]["pics"][0]
    assert pic["path"].startswith(f"{BIZ}/news-photos/") and (pic["w"], pic["h"]) == (1200, 900)
    assert fake.stored == [pic["path"]]


@pytest.mark.parametrize("verdict,code", [("no", "photo_no"), ("down", "photo_busy")])
def test_a_photo_the_check_turns_down_or_cant_check_saves_nothing(fake, verdict, code):
    fake.photo_verdict = verdict
    assert _share(photo=b"jpeg")[:2] == (False, code)
    assert fake.t["church_posts"] == [] and fake.stored == []


# ── 4. limits ────────────────────────────────────────────────────────

def test_three_waiting_at_once_is_enough(fake):
    for _ in range(ns.WAITING_MAX):
        assert _share()[0]
    assert _share()[:2] == (False, "share_many")
    assert len(fake.t["church_posts"]) == ns.WAITING_MAX


def test_just_my_groups_needs_a_group(fake):
    assert _share(me_id=ROCHELLE, who="groups")[:2] == (False, "share_groups")
    assert _share(me_id=MONIQUE, who="groups")[0]
    assert fake.t["church_posts"][0]["attach"]["groups"] == [G]


# ── 5. who sees it ───────────────────────────────────────────────────

def _post_it(fake, pid):
    for r in fake.t["church_posts"]:
        if r["id"] == pid:
            r.update(status="posted", publish_at="2026-10-23T11:00:00+00:00")


def test_just_my_groups_reaches_only_those_groups(fake):
    _ok, _code, pid = _share(who="groups", photo=b"jpeg")
    _post_it(fake, pid)
    assert [p["id"] for p in cn.feed(BIZ, TASHA)] == [pid]       # in the group
    assert cn.feed(BIZ, ROCHELLE) == [] and cn.one(BIZ, ROCHELLE, pid) == {}
    assert cn.unseen(BIZ, ROCHELLE) == 0 and cn.unseen(BIZ, TASHA) == 1
    assert cn.react(BIZ, ROCHELLE, pid, "cheer")[0] is False
    assert ns.photo_link(BIZ, pid, 0, ROCHELLE) == ""
    assert ns.photo_link(BIZ, pid, 0, TASHA).startswith("https://signed.example/")
    post = cn.feed(BIZ, TASHA)[0]
    assert post["for_groups"] == ["Sisters in the City"]
    assert "for Sisters in the City" in mpn.card(BUSINESS, post, {}, back="/my/news", open_=True)


def test_a_waiting_photo_is_only_its_senders(fake):
    _ok, _code, pid = _share(photo=b"jpeg")
    assert ns.photo_link(BIZ, pid, 0, MONIQUE).startswith("https://signed.example/")
    assert ns.photo_link(BIZ, pid, 0, ROCHELLE) == ""
    assert ns.photo_link(BIZ, pid, 1, MONIQUE) == ""            # no second photo
    _post_it(fake, pid)
    assert ns.photo_link(BIZ, pid, 0, ROCHELLE).startswith("https://signed.example/")


def test_a_photo_outside_the_churchs_own_folder_is_never_linked(fake):
    fake.t["church_posts"].append(_post("dddddddd-6666-0000-0000-000000000001", kind="good_news", source="member",
                                        attach={"pics": [{"path": "someone-else/news-photos/x.webp", "w": 1, "h": 1}]}))
    assert ns.photo_link(BIZ, "dddddddd-6666-0000-0000-000000000001", 0, MONIQUE) == ""


# ── 6. the owner or an admin decides ─────────────────────────────────

class _User:
    id = "u1"
    email = "office@example.com"
    role = "authenticated"


def _office(monkeypatch, role):
    import kids_router
    from auth_supabase import require_user
    monkeypatch.setattr(kids_router, "role_for", lambda biz, user: role)
    app = FastAPI()
    app.include_router(cn.router)
    app.include_router(ns.router)
    app.dependency_overrides[require_user] = lambda: _User()
    return TestClient(app)


def test_only_the_owner_or_an_admin_posts_what_a_member_shared(fake, monkeypatch):
    _ok, _code, pid = _share()
    body = {"business_id": BIZ, "action": "post"}
    assert _office(monkeypatch, "manager").post(f"/church/news/shared/{pid}", json=body).status_code == 403
    assert fake.t["church_posts"][0]["status"] == "waiting"
    r = _office(monkeypatch, "admin").post(f"/church/news/shared/{pid}", json={**body, "body": "Imani is a nurse now!"})
    assert r.status_code == 200 and r.json() == {"ok": True, "told": True}
    row = fake.t["church_posts"][0]
    assert row["status"] == "posted" and row["publish_at"] and row["body"] == "Imani is a nurse now!"
    kind, kw = fake.pushed[0]
    assert kind == "news" and kw["contact_ids"] == [MONIQUE] and kw["url"] == f"/my/news/{pid}"
    assert row["told_at"]
    assert [p["id"] for p in cn.feed(BIZ, ROCHELLE)] == [pid]
    # Decided once.
    assert _office(monkeypatch, "admin").post(f"/church/news/shared/{pid}", json=body).status_code == 404


def test_not_now_saves_it_and_tells_no_one(fake, monkeypatch):
    _ok, _code, pid = _share()
    r = _office(monkeypatch, "owner").post(f"/church/news/shared/{pid}", json={"business_id": BIZ, "action": "later"})
    assert r.status_code == 200 and fake.t["church_posts"][0]["status"] == "declined" and fake.pushed == []
    # Still in Waiting for you (after what's waiting), and still the member's "With your pastors".
    v = _office(monkeypatch, "viewer").get(f"/church/news?business_id={BIZ}").json()
    assert [s["status"] for s in v["shared"]] == ["declined"] and v["posts"] == []
    assert [w["id"] for w in ns.mine(BIZ, MONIQUE)] == [pid]


def test_waiting_for_you_shows_the_words_the_photo_and_who_its_for(fake, monkeypatch):
    _share(who="groups", photo=b"jpeg")
    _screen(monkeypatch, fake, "harm")
    _share(me_id=ROCHELLE, kind="pray", text="Prayer answered")
    v = _office(monkeypatch, "viewer").get(f"/church/news?business_id={BIZ}").json()
    first, second = v["shared"]
    assert (first["name"], first["what"], first["for"]) == ("Monique Brown", "A graduation", "Sisters in the City")
    assert first["photos"][0].startswith("https://signed.example/") and first["flag"] == ""
    assert (second["for"], second["flag"]) == ("the whole church", "harm")
    assert v["posts"] == []                                       # waiting shares aren't rows of posts


# ── 7. pages and routes ──────────────────────────────────────────────

def test_the_share_page_reads_like_the_canvas(fake):
    html, status = mps.render_share(BUSINESS, None, _req(), _me(MONIQUE), [{"id": G, "name": "Sisters in the City"}], [], False)
    assert status == 200
    for words in ("Tell us what <em>God did.</em>", "What happened?", "A new baby", "A graduation",
                  "Married or an anniversary", "A new job", "Baptized or saved", "An answered prayer", "Tell the church",
                  "Add a photo", "The whole church", "Just my groups", "Only Sisters in the City sees it",
                  "Your pastors read it first.", "Send to the pastors"):
        assert words in html, words
    # Not in a group: there's no "Just my groups" to pick.
    html, _ = mps.render_share(BUSINESS, None, _req(), _me(ROCHELLE), [], [], False)
    assert "Just my groups" not in html


def test_sent_says_how_they_will_hear(fake):
    req = _req(b"sent=all")
    phone, _ = mps.render_share(BUSINESS, None, req, _me(MONIQUE), [], [], True)
    no_phone, _ = mps.render_share(BUSINESS, None, req, _me(MONIQUE), [], [], False)
    assert "We can't wait to <em>celebrate.</em>" in phone and "get a note the moment it" in phone
    assert "note" not in no_phone.split("Your pastors have it")[1].split("</small>")[0]


def test_news_offers_have_good_news_and_shows_it_under_their_name(fake):
    _ok, _code, pid = _share(photo=b"jpeg")
    _post_it(fake, pid)
    posts = cn.feed(BIZ, ROCHELLE)
    html, _ = mpn.render_news(BUSINESS, None, _req(), _me(ROCHELLE), posts, "", [], True)
    assert "Have good news?" in html and 'href="/my/news/share"' in html
    assert "Good news from Monique Brown" in html and f"/my/news/{pid}/photo/0" in html
    assert cn.matches(posts[0], "photos") and cn.matches(posts[0], "celebrations")


def _client(monkeypatch, me, unavailable=False):
    async def signed_in(request):
        return {"business": BUSINESS}, me, unavailable
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    monkeypatch.setattr(mpc, "_allowed", lambda church, who: True)
    app = FastAPI()
    app.include_router(mps.router)
    return TestClient(app, follow_redirects=False)


def test_the_share_route_sends_and_says_sent(fake, monkeypatch):
    r = _client(monkeypatch, _me(MONIQUE)).post(
        "/my/news/share", data={"kind": "baby", "body": "Our son Josiah came Tuesday!", "who": "groups"},
        files={"photo": ("josiah.jpg", b"jpeg", "image/jpeg")})
    assert r.status_code == 303 and r.headers["location"] == "/my/news/share?sent=groups"
    row = fake.t["church_posts"][0]
    assert row["attach"]["share"] == "baby" and row["attach"]["groups"] == [G] and row["attach"]["pics"]
    r = _client(monkeypatch, _me(MONIQUE)).post("/my/news/share", data={"kind": "baby", "body": ""})
    assert r.headers["location"] == "/my/news/share?err=share_empty"


def test_a_member_takes_back_their_own_before_its_posted(fake, monkeypatch):
    _ok, _code, pid = _share(photo=b"jpeg")
    path = fake.t["church_posts"][0]["attach"]["pics"][0]["path"]
    r = _client(monkeypatch, _me(ROCHELLE)).post("/my/news/share/take-back", data={"id": pid})
    assert r.headers["location"] == "/my/news/share?err=share_gone"            # not hers
    r = _client(monkeypatch, _me(MONIQUE)).post("/my/news/share/take-back", data={"id": pid})
    assert r.headers["location"] == "/my/news/share?done=taken_back"
    row = fake.t["church_posts"][0]
    assert row["status"] == "removed" and row["removed_at"] and fake.dropped == [path]
    assert ns.mine(BIZ, MONIQUE) == [] and _office(monkeypatch, "viewer").get(f"/church/news?business_id={BIZ}").json()["shared"] == []
    # Once it's posted, it's the church's to take down.
    _ok, _code, pid2 = _share()
    _post_it(fake, pid2)
    assert ns.take_back(BIZ, MONIQUE, pid2) == (False, "share_gone")


def test_the_preview_never_shares(fake, monkeypatch):
    r = _client(monkeypatch, None, "preview").post("/my/news/share", data={"kind": "grad", "body": "Hi"})
    assert r.headers["location"] == "/my/news/share?err=preview"
    assert fake.t["church_posts"] == []
