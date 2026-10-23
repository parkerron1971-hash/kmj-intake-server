# __tests__/test_news_write.py
#
# Posting to News from a phone (member_portal_write.py; the approved canvas
# "Church News & Celebrations" board 7, Kevin 2026-10-23: "leaders should be
# able to post to their own ministry anyways but if I pick them for this,
# they can post to the entire church. like an admin."). Pins:
#   1. who posts where: someone the church picked, the whole church; a
#      group's leader, their own group; nobody else, anywhere — not even by
#      sending the form by hand
#   2. what a post carries is checked: an event this person can see, a
#      published sermon, an https link, up to four photos each checked first
#      (one turned down, or one that couldn't be checked, posts nothing)
#   3. Sunday at 7 is the church's own Sunday morning
#   4. whoever posted edits their own post, never someone else's; its photos stay
#   5. Sign me up: one tap puts the member on the event's list, only from a
#      post that offers it and that they can see
#   6. the pages: Post on News only for posters, the form, "It's out.",
#      Chief's sign-up words; the office's photo upload and what a post may
#      carry

import asyncio
import pathlib
import sys
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import church_news as cn
import member_portal_church as mpc
import member_portal_news as mpn
import member_portal_write as mpw
import test_member_portal_group_space as gs
from test_church_news import BUSINESS, _me, _post
from test_member_portal_group_space import BIZ, G, MONIQUE, ROCHELLE, TASHA, _params, _req  # noqa: F401

EV = "eeeeeeee-7777-0000-0000-000000000001"
SERMON = "ffffffff-7777-0000-0000-000000000001"
OCC = [{"entry_id": EV, "title": "Baptism Sunday", "date": "2099-11-09", "date_label": "Sunday, November 9",
        "location": "11:00 AM", "attending": 14, "mine": None}]


@pytest.fixture
def fake(monkeypatch):
    f = gs.Fake()
    f.t.update(church_posts=[], church_post_reactions=[], church_post_seen=[], church_post_comments=[],
               church_post_comment_loves=[], church_post_reports=[], sermons=[
                   {"id": SERMON, "business_id": BIZ, "title": "Built to Last", "published": True, "preached_on": "2026-10-19"}],
               # ROCHELLE is someone the church picked to post to everyone.
               church_news_posters=[{"business_id": BIZ, "contact_id": ROCHELLE}],
               businesses=[{"id": BIZ, "name": "Love City Church", "settings": {}, "owner_id": "o1"}])
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", f.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", f.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", f.patch)
    monkeypatch.setattr(cn, "is_pastoral", lambda biz, cid: False)
    import messaging_router as mr
    monkeypatch.setattr(mr, "officer_count", lambda biz: 2)
    monkeypatch.setattr(mpc, "upcoming_for", lambda biz, me: [dict(o) for o in OCC])
    f.rsvps = []
    monkeypatch.setattr(mpc, "member_rsvp", lambda biz, me, entry, action, role="": f.rsvps.append((me["id"], entry, action))
                        or (True, "coming"))
    import chat_photos
    import member_photos
    import storage_links
    f.stored, f.dropped, f.verdicts = [], [], []
    monkeypatch.setattr(chat_photos, "prepare", lambda raw: (b"webp-" + raw, 1600, 1200))
    monkeypatch.setattr(chat_photos, "drop", lambda path: f.dropped.append(path))
    monkeypatch.setattr(member_photos, "_put", lambda path, data: f.stored.append(path) or True)

    async def screen(biz, webp, **kw):
        assert kw.get("policy") == mpw.POLICY
        v = f.verdicts.pop(0) if f.verdicts else "ok"
        if v == "down":
            raise member_photos.ScreenUnavailable("down")
        return v
    monkeypatch.setattr(member_photos, "screen", screen)
    monkeypatch.setattr(storage_links, "signed_url_sync", lambda bucket, path, ttl=0: f"https://signed.example/{path}")
    return f


def _write(me_id, **form):
    data = {"title": "Baptism Sunday is November 9", "body": "Sign up by November 2.", "to": "all", "kind": "announcement",
            "comments": "on", "when": "now", **form}
    photos = data.pop("photos", [])
    return asyncio.run(mpw.write({"id": BIZ, "name": "Love City Church", "settings": {}, "owner_id": "o1"},
                                 _me(me_id), data, photos))


# ── 1. who posts where ───────────────────────────────────────────────

def test_a_picked_poster_posts_to_the_whole_church(fake):
    ok, code, pid = _write(ROCHELLE)
    assert (ok, code) == (True, "posted")
    row = fake.t["church_posts"][0]
    assert (row["source"], row["posted_by"], row["group_id"], row["status"]) == ("leader", ROCHELLE, None, "posted")
    assert [p["id"] for p in cn.feed(BIZ, MONIQUE)] == [pid]


def test_a_leader_posts_to_their_own_group_only(fake):
    assert _write(TASHA)[:2] == (False, "write_who")              # not picked: not the whole church
    ok, _code, pid = _write(TASHA, to=G)
    assert ok and fake.t["church_posts"][0]["group_id"] == G
    assert cn.feed(BIZ, ROCHELLE) == [] and [p["id"] for p in cn.feed(BIZ, MONIQUE)] == [pid]
    assert _write(TASHA, to="aaaaaaaa-0000-0000-0000-000000000002")[:2] == (False, "write_who")


def test_a_member_posts_nowhere_even_by_hand(fake):
    assert _write(MONIQUE)[:2] == (False, "write_who")
    assert _write(MONIQUE, to=G)[:2] == (False, "write_who")
    assert fake.t["church_posts"] == []


# ── 2. what a post carries ───────────────────────────────────────────

def test_an_event_a_sermon_and_a_link_are_checked(fake):
    ok, _c, _pid = _write(ROCHELLE, event=EV, signup="1", sermon=SERMON, link="https://lovecityc.com/baptism")
    assert ok
    assert fake.t["church_posts"][0]["attach"] == {"event": EV, "signup": True, "sermon": SERMON, "link": "https://lovecityc.com/baptism"}
    _write(ROCHELLE, event="eeeeeeee-7777-0000-0000-000000000099", signup="1", sermon="ffffffff-0000-0000-0000-000000000000")
    assert fake.t["church_posts"][1]["attach"] == {}                # not theirs to see, not published
    for bad in ("http://lovecityc.com", "javascript:alert(1)", "https://nodot", "lovecityc.com"):
        assert _write(ROCHELLE, link=bad)[:2] == (False, "write_link"), bad
    assert _write(ROCHELLE, title="", body="")[:2] == (False, "write_none")


def test_photos_are_checked_first_and_one_no_posts_nothing(fake):
    ok, _c, _pid = _write(ROCHELLE, photos=[b"a", b"b"])
    assert ok and [p["w"] for p in fake.t["church_posts"][0]["attach"]["pics"]] == [1600, 1600] and len(fake.stored) == 2
    fake.verdicts = ["ok", "no"]
    assert _write(ROCHELLE, photos=[b"c", b"d"])[:2] == (False, "photo_no")
    fake.verdicts = ["down"]
    assert _write(ROCHELLE, photos=[b"e"])[:2] == (False, "photo_busy")
    assert _write(ROCHELLE, photos=[b"x"] * (mpw.PHOTOS_MAX + 1))[:2] == (False, "write_photos")
    assert len(fake.t["church_posts"]) == 1 and len(fake.stored) == 2   # nothing more was kept


# ── 3. Sunday at 7 ───────────────────────────────────────────────────

def test_sunday_at_7_is_the_churchs_own_sunday_morning(fake, monkeypatch):
    import celebrations as cel
    from zoneinfo import ZoneInfo
    detroit = ZoneInfo("America/Detroit")
    monkeypatch.setattr(cel, "local_now", lambda biz: datetime(2026, 10, 23, 15, 0, tzinfo=detroit))   # a Friday
    at = mpw.sunday_at_7({"id": BIZ})
    assert at.astimezone(detroit) == datetime(2026, 10, 25, 7, 0, tzinfo=detroit) and at.tzinfo == timezone.utc
    monkeypatch.setattr(cn, "_now", lambda: datetime(2026, 10, 23, 19, 0, tzinfo=timezone.utc))
    ok, _c, pid = _write(ROCHELLE, when="sunday")
    assert ok and fake.t["church_posts"][0]["publish_at"] == at.isoformat()
    assert cn.feed(BIZ, MONIQUE) == []                              # not up yet


# ── 4. editing their own ─────────────────────────────────────────────

def test_whoever_posted_edits_it_and_its_photos_stay(fake):
    _ok, _c, pid = _write(ROCHELLE, photos=[b"a"])
    ok, code, _ = _write(ROCHELLE, edit=pid, title="Baptism Sunday moved to November 16", body="New day.", comments="prayers",
                         event=EV, signup="1")
    assert (ok, code) == (True, "edited")
    row = fake.t["church_posts"][0]
    assert (row["title"], row["body"], row["comments"]) == ("Baptism Sunday moved to November 16", "New day.", "prayers")
    assert row["attach"]["signup"] is True and len(row["attach"]["pics"]) == 1
    assert _write(TASHA, edit=pid, title="Mine now")[:2] == (False, "write_gone")
    assert fake.t["church_posts"][0]["title"] == "Baptism Sunday moved to November 16"


# ── 5. Sign me up ────────────────────────────────────────────────────

def _client(monkeypatch, me):
    async def signed_in(request):
        return {"business": BUSINESS}, me, False
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    monkeypatch.setattr(mpc, "_allowed", lambda church, who: True)
    app = FastAPI()
    app.include_router(mpw.router)
    return TestClient(app, follow_redirects=False)


def test_sign_me_up_puts_them_on_the_event_list(fake, monkeypatch):
    fake.t["church_posts"] += [_post("dddddddd-7777-0000-0000-000000000001", attach={"event": EV, "signup": True}),
                               _post("dddddddd-7777-0000-0000-000000000002", attach={"event": EV}),
                               _post("dddddddd-7777-0000-0000-000000000003", attach={"event": EV, "signup": True}, group_id=G)]
    c = _client(monkeypatch, _me(MONIQUE))
    r = c.post("/my/news/signup", data={"id": "dddddddd-7777-0000-0000-000000000001", "back": "/my/news"})
    assert r.headers["location"] == "/my/news?done=signed_up#p-dddddddd-7777-0000-0000-000000000001"
    assert fake.rsvps == [(MONIQUE, EV, "coming")]
    r = c.post("/my/news/signup", data={"id": "dddddddd-7777-0000-0000-000000000002"})
    assert "err=news_gone" in r.headers["location"]                 # no sign-up on that post
    r = _client(monkeypatch, _me(ROCHELLE)).post("/my/news/signup", data={"id": "dddddddd-7777-0000-0000-000000000003"})
    assert "err=news_gone" in r.headers["location"]                 # not their group's
    assert len(fake.rsvps) == 1


def test_a_full_event_says_so(fake, monkeypatch):
    fake.t["church_posts"].append(_post("dddddddd-7777-0000-0000-000000000001", attach={"event": EV, "signup": True}))
    monkeypatch.setattr(mpc, "member_rsvp", lambda biz, me, entry, action, role="": (False, "full"))
    r = _client(monkeypatch, _me(MONIQUE)).post("/my/news/signup", data={"id": "dddddddd-7777-0000-0000-000000000001"})
    assert "err=signup_full" in r.headers["location"] and "full" in mpn.ERRORS["signup_full"]


def test_the_card_offers_sign_me_up_and_then_says_signed_up(fake):
    p = {"id": "dddddddd-7777-0000-0000-000000000001", "attach": {"event": EV, "signup": True, "link": "https://www.lovecityc.com/pantry"}}
    html = mpn._attachments(p, mpn._occasions(OCC))
    assert 'action="/my/news/signup"' in html and "Sign me up" in html
    assert ">lovecityc.com<" in html and 'rel="noopener nofollow ugc"' in html
    mine = [{**OCC[0], "mine": {"status": "yes"}}]
    html = mpn._attachments(p, mpn._occasions(mine))
    assert "Sign me up" not in html and "You're signed up" in html


# ── 6. pages and the office ──────────────────────────────────────────

def test_news_offers_post_only_to_posters(fake):
    html, _ = mpn.render_news(BUSINESS, None, _req(), _me(ROCHELLE), [], "", [], True, poster=True)
    assert 'href="/my/news/write"' in html
    html, _ = mpn.render_news(BUSINESS, None, _req(), _me(MONIQUE), [], "", [], True)
    assert 'href="/my/news/write"' not in html


def test_the_write_page_reads_like_the_canvas(fake):
    rights = {"church": True, "pastoral": False, "groups": [{"id": G, "name": "Sisters in the City"}]}
    auds = mpw.audiences({"id": BIZ}, rights)
    assert [a[:2] for a in auds] == [("all", "Whole church"), (G, "Sisters in the City")]
    html, status = mpw.render_write(BUSINESS, None, _req(), _me(ROCHELLE), rights, auds, OCC, [], None)
    assert status == 200
    for words in ("Posting as yourself, to News", "Who it's for", "Whole church · ", "Sisters in the City · ", "What kind",
                  "Announcement", "Praise report", "Headline", "Message", "Photos", "Event", "Sermon", "Link",
                  "Add a Sign me up button", "Pin it to the top", "Prayers only", "Sunday, 7 AM", "Post to the whole church"):
        assert words.replace("'", "&#x27;") in html or words in html, words
    # Someone who posts nowhere is told who does, and offered Share good news.
    html, _ = mpw.render_write(BUSINESS, None, _req(), _me(MONIQUE), {"church": False, "groups": []}, [], OCC, [], None)
    assert 'name="title"' not in html and "/my/news/share" in html


def test_chief_offers_the_sign_up_only_when_the_words_ask(fake):
    for yes in ("Sign up by November 2", "sign-up sheet is out", "Register at the table", "RSVP by Friday", "save your spot"):
        assert mpw.SIGNUP_RE.search(yes), yes
    for no in ("Thank you for coming", "Signature dish potluck", "We signed the lease"):
        assert not mpw.SIGNUP_RE.search(no), no
    assert "re=/sign[\\s-]?" in mpw.WRITE_JS                       # one backslash in the page's own script


def _office(monkeypatch, role):
    import kids_router
    from auth_supabase import require_user

    class _User:
        id = "u1"
        email = "office@example.com"
        role = "authenticated"
    monkeypatch.setattr(kids_router, "role_for", lambda biz, user: role)
    app = FastAPI()
    app.include_router(cn.router)
    app.dependency_overrides[require_user] = lambda: _User()
    return TestClient(app)


def test_the_office_uploads_a_checked_photo(fake, monkeypatch):
    files = {"photo": ("a.jpg", b"jpeg", "image/jpeg")}
    assert _office(monkeypatch, "viewer").post("/church/news/photo", data={"business_id": BIZ}, files=files).status_code == 403
    r = _office(monkeypatch, "member").post("/church/news/photo", data={"business_id": BIZ}, files=files)
    assert r.status_code == 200 and r.json()["path"].startswith(f"{BIZ}/news-photos/") and r.json()["url"].startswith("https://")
    fake.verdicts = ["no"]
    r = _office(monkeypatch, "member").post("/church/news/photo", data={"business_id": BIZ}, files=files)
    assert r.status_code == 422 and len(fake.stored) == 1


def test_a_post_carries_only_this_churchs_own_photos(fake):
    mine = f"{BIZ}/news-photos/{'a' * 20}.webp"
    att = cn._attach(BIZ, {"pics": [{"path": mine, "w": 10, "h": 10}, {"path": f"{gs.OTHER}/news-photos/{'b' * 20}.webp"},
                                    {"path": f"{BIZ}/chat-photos/x/{'c' * 16}.webp"}],
                           "signup": True, "link": "https://lovecityc.com"})
    assert att == {"pics": [{"path": mine, "w": 10, "h": 10}], "link": "https://lovecityc.com"}  # no sign-up without an event
    assert cn._attach(BIZ, {"event": EV, "signup": True})["signup"] is True
