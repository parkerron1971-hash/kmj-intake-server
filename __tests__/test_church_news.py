# __tests__/test_church_news.py
#
# The church's news in the member app (church_news.py + member_portal_news.py;
# the approved canvas "Church News & Celebrations", Kevin 2026-10-23). Pins:
#   1. who sees a post: a whole-church post reaches everyone; a ministry's
#      post only its people; a scheduled, waiting or removed post nobody;
#      the pinned post leads
#   2. reactions toggle, and only on a post the member can see
#   3. comments (Kevin: "allow people to comment"; teens too, because every
#      comment is checked first): closed until the church has two safety
#      officers; off on a post that says so; 'ok' shows, 'harm' is held
#      (only its writer sees it), 'self_harm' is held and the pastor told;
#      an unchecked comment never posts
#   4. one level of replies; a report goes to the officers; its writer or
#      whoever posted takes a comment down, nobody else
#   5. the pages: News, a post, Home's "From the church" (nothing at all
#      when there's no news), and "Checking it first…"
#   6. routes: the preview never writes; "back" can't leave the news pages
#   7. the office: posting needs a seat that edits, picking posters an admin

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
import test_member_portal_group_space as gs
from test_member_portal_group_space import BIZ, G, MONIQUE, ROCHELLE, TASHA, TEEN, _params, _req  # noqa: F401

BUSINESS = {"id": BIZ, "name": "Love City Church", "settings": {}}
P_CHURCH = "dddddddd-1111-0000-0000-000000000001"
P_GROUP = "dddddddd-1111-0000-0000-000000000002"
P_LATER = "dddddddd-1111-0000-0000-000000000003"
P_PINNED = "dddddddd-1111-0000-0000-000000000004"


def _post(pid, **k):
    row = {"id": pid, "business_id": BIZ, "kind": "announcement", "title": "Baptism Sunday is November 9",
           "body": "Sign up by November 2.", "group_id": None, "posted_by": None, "office_user": "u1",
           "author_label": "", "source": "office", "status": "posted", "pinned_until": None, "important": False,
           "comments": "on", "publish_at": None, "attach": {}, "person_id": None,
           "created_at": "2026-10-20T13:14:00+00:00", "removed_at": None}
    row.update(k)
    return row


@pytest.fixture
def fake(monkeypatch):
    f = gs.Fake()
    f.t.update(church_posts=[], church_post_reactions=[], church_post_seen=[], church_post_comments=[],
               church_post_comment_loves=[], church_post_reports=[], church_news_posters=[], sermons=[],
               ministry_care_requests=[])
    import sb_clients

    def delete(path):
        table, params = _params(path)
        f.t[table] = [r for r in f.t.get(table, []) if r not in f._rows(table, params)]
        return True
    monkeypatch.setattr(sb_clients, "sb_get_as_service", f.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", f.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", f.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", delete)
    monkeypatch.setattr(cn, "is_pastoral", lambda biz, cid: cid == TASHA)
    import messaging_router as mr
    f.officers = 2
    monkeypatch.setattr(mr, "officer_count", lambda biz: f.officers)
    import member_portal_messaging as mpm
    f.care = []
    monkeypatch.setattr(mpm, "care_alert", lambda biz, me: f.care.append(me["id"]))
    monkeypatch.setattr(mpc, "upcoming_for", lambda biz, me: [])
    return f


def _screen(monkeypatch, verdict):
    import msg_screen

    async def screen(biz, text):
        if verdict == "down":
            raise msg_screen.ScreenUnavailable("down")
        return verdict
    monkeypatch.setattr(msg_screen, "screen", screen)


def _me(cid, name="Someone"):
    return {"id": cid, "name": name}


# ── 1. who sees what ─────────────────────────────────────────────────

def test_a_ministry_post_reaches_only_its_people_and_the_pin_leads(fake):
    fake.t["church_posts"] += [
        _post(P_CHURCH),
        _post(P_GROUP, title="Sisters only", group_id=G, created_at="2026-10-21T10:00:00+00:00"),
        _post(P_LATER, title="Not yet", publish_at="2099-01-01T00:00:00+00:00"),
        _post(P_PINNED, title="Pinned word", pinned_until="2099-01-01T00:00:00+00:00", created_at="2026-10-01T10:00:00+00:00"),
        _post("dddddddd-1111-0000-0000-000000000005", title="Waiting", status="waiting"),
        _post("dddddddd-1111-0000-0000-000000000006", title="Down", status="removed", removed_at="2026-10-21T00:00:00+00:00"),
    ]
    in_group = [p["title"] for p in cn.feed(BIZ, MONIQUE)]
    outside = [p["title"] for p in cn.feed(BIZ, ROCHELLE)]
    assert in_group == ["Pinned word", "Sisters only", "Baptism Sunday is November 9"]
    assert outside == ["Pinned word", "Baptism Sunday is November 9"]
    assert cn.one(BIZ, ROCHELLE, P_GROUP) == {} and cn.one(BIZ, MONIQUE, P_LATER) == {}


def test_a_failed_read_is_try_again_never_no_news(fake):
    fake.fail.add("church_posts")
    assert cn.feed(BIZ, MONIQUE) is None
    html, status = mpn.render_news(BUSINESS, None, _req(), _me(MONIQUE), None, "", [], True)
    assert status == 503 and "couldn't load" in html


def test_filters_follow_what_a_post_carries(fake):
    fake.t["church_posts"] += [_post(P_CHURCH, attach={"event": "eeeeeeee-1111-0000-0000-000000000001"}),
                               _post(P_PINNED, title="Photos", kind="photos")]
    assert [p["id"] for p in cn.feed(BIZ, MONIQUE, "events")] == [P_CHURCH]
    assert [p["id"] for p in cn.feed(BIZ, MONIQUE, "photos")] == [P_PINNED]
    assert cn.feed(BIZ, MONIQUE, "celebrations") == []


# ── 2. reactions ─────────────────────────────────────────────────────

def test_a_reaction_toggles(fake):
    fake.t["church_posts"].append(_post(P_CHURCH))
    assert cn.react(BIZ, MONIQUE, P_CHURCH, "amen") == (True, "", P_CHURCH)
    p = cn.feed(BIZ, MONIQUE)[0]
    assert p["rx"]["amen"] == 1 and p["my_rx"] == ["amen"]
    # A write that reports success.
    assert "return=representation" in next(w[3] for w in fake.writes if w[1] == "church_post_reactions")
    assert cn.react(BIZ, MONIQUE, P_CHURCH, "amen")[0]
    assert cn.feed(BIZ, MONIQUE)[0]["rx"]["amen"] == 0


def test_no_reaction_on_a_post_they_cant_see(fake):
    fake.t["church_posts"].append(_post(P_GROUP, group_id=G))
    assert cn.react(BIZ, ROCHELLE, P_GROUP, "love") == (False, "news_gone", "")
    assert cn.react(BIZ, MONIQUE, P_GROUP, "shout")[:2] == (False, "error")
    assert fake.t["church_post_reactions"] == []


# ── 3. comments ──────────────────────────────────────────────────────

def _say(me, text, pid=P_CHURCH, reply=""):
    return asyncio.run(cn.comment(BUSINESS, me, pid, text, reply))


def test_comments_wait_for_two_safety_officers(fake, monkeypatch):
    _screen(monkeypatch, "ok")
    fake.t["church_posts"].append(_post(P_CHURCH))
    fake.officers = 1
    assert _say(_me(MONIQUE), "We'll be there!") == (False, "comments_closed", P_CHURCH)
    fake.officers = 2
    assert _say(_me(MONIQUE), "We'll be there!") == (True, "commented", P_CHURCH)


def test_a_post_with_comments_off_takes_none(fake, monkeypatch):
    _screen(monkeypatch, "ok")
    fake.t["church_posts"].append(_post(P_CHURCH, comments="off"))
    assert _say(_me(MONIQUE), "Hi") == (False, "comments_off", P_CHURCH)
    fake.t["church_posts"][0]["comments"] = "prayers"
    assert _say(_me(MONIQUE), "Hi")[1] == "comments_off"


def test_teens_comment_too_because_every_comment_is_checked(fake, monkeypatch):
    _screen(monkeypatch, "ok")
    fake.t["church_posts"].append(_post(P_CHURCH))
    assert _say(_me(TEEN, "Kayla Young"), "Can't wait!") == (True, "commented", P_CHURCH)
    thread = cn.one(BIZ, MONIQUE, P_CHURCH)["thread"]
    assert thread[0]["body"] == "Can't wait!"
    # A teen shows by first name.
    html, _ = mpn.render_post(BUSINESS, None, _req(), _me(MONIQUE), cn.one(BIZ, MONIQUE, P_CHURCH), [], True)
    assert "Kayla" in html and "Kayla Young" not in html


def test_a_held_comment_only_its_writer_sees(fake, monkeypatch):
    _screen(monkeypatch, "harm")
    fake.t["church_posts"].append(_post(P_CHURCH))
    assert _say(_me(MONIQUE), "something unkind") == (True, "comment_held", P_CHURCH)
    assert fake.t["church_post_comments"][0]["status"] == "held"
    mine = cn.one(BIZ, MONIQUE, P_CHURCH)
    assert [c["status"] for c in mine["thread"]] == ["held"]
    html, _ = mpn.render_post(BUSINESS, None, _req(), _me(MONIQUE), mine, [], True)
    assert "Only you see this until a safety officer looks at it." in html
    assert cn.one(BIZ, TASHA, P_CHURCH)["thread"] == []
    assert cn.feed(BIZ, TASHA)[0]["comment_n"] == 0


def test_crisis_words_are_held_and_the_pastor_told(fake, monkeypatch):
    _screen(monkeypatch, "self_harm")
    fake.t["church_posts"].append(_post(P_CHURCH))
    assert _say(_me(MONIQUE), "I don't want to be alive")[:2] == (True, "care")
    assert fake.t["church_post_comments"][0]["status"] == "held" and fake.care == [MONIQUE]


def test_an_unchecked_comment_never_posts(fake, monkeypatch):
    _screen(monkeypatch, "down")
    fake.t["church_posts"].append(_post(P_CHURCH))
    assert _say(_me(MONIQUE), "Amen") == (False, "comment_busy", P_CHURCH)
    assert fake.t["church_post_comments"] == []


# ── 4. replies, reports, taking down ─────────────────────────────────

def test_a_reply_to_a_reply_answers_the_comment(fake, monkeypatch):
    _screen(monkeypatch, "ok")
    fake.t["church_posts"].append(_post(P_CHURCH))
    _say(_me(MONIQUE), "Is the kids' class the same day?")
    top = fake.t["church_post_comments"][0]["id"]
    _say(_me(TASHA), "Yes, Nov 2 at 11:30.", reply=top)
    reply = fake.t["church_post_comments"][1]["id"]
    _say(_me(TEEN), "Thank you!", reply=reply)
    assert fake.t["church_post_comments"][2]["reply_to"] == top
    thread = cn.one(BIZ, MONIQUE, P_CHURCH)["thread"]
    assert [bool(c.get("is_reply")) for c in thread] == [False, True, True]


def test_a_report_goes_to_the_officers_and_not_on_your_own(fake, monkeypatch):
    _screen(monkeypatch, "ok")
    fake.t["church_posts"].append(_post(P_CHURCH))
    _say(_me(MONIQUE), "Hello")
    cid = fake.t["church_post_comments"][0]["id"]
    assert cn.report(BIZ, MONIQUE, cid)[:2] == (False, "error")
    assert cn.report(BIZ, TASHA, cid) == (True, "reported", P_CHURCH)
    assert fake.t["church_post_reports"][0]["reported_by"] == TASHA
    assert cn.one(BIZ, TASHA, P_CHURCH)["thread"][0]["i_reported"] is True


def test_only_the_writer_or_whoever_posted_takes_a_comment_down(fake, monkeypatch):
    _screen(monkeypatch, "ok")
    fake.t["church_posts"].append(_post(P_CHURCH, posted_by=TASHA, source="leader"))
    _say(_me(MONIQUE), "Hello")
    cid = fake.t["church_post_comments"][0]["id"]
    assert cn.remove_comment(BIZ, ROCHELLE, cid)[:2] == (False, "not_yours")
    assert cn.remove_comment(BIZ, TASHA, cid) == (True, "comment_down", P_CHURCH)
    assert fake.t["church_post_comments"][0]["removed_by"] == "poster"


# ── 5. the pages ─────────────────────────────────────────────────────

def test_the_news_page_reads_like_the_canvas(fake):
    fake.t["church_posts"] += [_post(P_PINNED, posted_by=TASHA, pinned_until="2099-01-01T00:00:00+00:00"),
                               _post(P_CHURCH, title="Fall Fest needs 20 helpers", author_label="Sis. Brenda",
                                     comments="off")]
    html, status = mpn.render_news(BUSINESS, None, _req(), _me(MONIQUE), cn.feed(BIZ, MONIQUE), "", [], True)
    assert status == 200
    for words in ("What's <em>happening.</em>", "From your church", ">Announcements<", ">Celebrations<",
                  'class="nw-post church"', "Tasha Williams", ">Pastor<", "pinned", "Sis. Brenda", ">Office<",
                  "Comments are off for this post", "every comment is checked before anyone sees it"):
        assert words in html, words


def test_a_post_page_names_who_reacted(fake):
    fake.t["church_posts"].append(_post(P_CHURCH))
    for who in (MONIQUE, TASHA, TEEN, ROCHELLE):
        cn.react(BIZ, who, P_CHURCH, "love")
    p = cn.one(BIZ, MONIQUE, P_CHURCH)
    assert p["reactors_n"] == 4
    html, _ = mpn.render_post(BUSINESS, None, _req(), _me(MONIQUE), p, [], True)
    assert "Monique, Tasha and 2 others reacted" in html


def test_a_post_page_checks_a_comment_first_and_says_so(fake):
    fake.t["church_posts"].append(_post(P_CHURCH))
    html, _ = mpn.render_post(BUSINESS, None, _req(), _me(MONIQUE), cn.one(BIZ, MONIQUE, P_CHURCH), [], True)
    assert "Checking it first…" in html and "Every comment is checked before the church sees it" in html
    assert 'action="/my/news/comment"' in html and "Love" in html and "Praying" in html and "Celebrate" in html
    closed, _ = mpn.render_post(BUSINESS, None, _req(), _me(MONIQUE), cn.one(BIZ, MONIQUE, P_CHURCH), [], False)
    assert "Comments aren't open at Love City Church yet" in closed and 'action="/my/news/comment"' not in closed


def test_home_shows_nothing_when_there_is_no_news(fake):
    assert mpn.home_block(BUSINESS, [], [], True) == ""
    fake.t["church_posts"] += [_post(P_CHURCH), _post(P_PINNED, title="Second")]
    posts, unseen = cn.home_view(BIZ, MONIQUE)
    block = mpn.home_block(BUSINESS, posts, [], True)
    assert "From the church" in block and "All news" in block and "Second" in block
    assert unseen == 2
    cn.mark_seen(BIZ, MONIQUE, [P_CHURCH])
    assert cn.home_view(BIZ, MONIQUE)[1] == 1


# ── 6. routes ────────────────────────────────────────────────────────

def _client(monkeypatch, me, unavailable=False):
    async def signed_in(request):
        return {"business": BUSINESS}, me, unavailable
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    monkeypatch.setattr(mpc, "_allowed", lambda church, who: True)
    app = FastAPI()
    app.include_router(mpn.router)
    return TestClient(app, follow_redirects=False)


def test_the_preview_never_writes(fake, monkeypatch):
    fake.t["church_posts"].append(_post(P_CHURCH))
    r = _client(monkeypatch, None, "preview").post("/my/news/react", data={"id": P_CHURCH, "kind": "love"})
    assert r.headers["location"] == "/my/news?err=preview"
    assert fake.t["church_post_reactions"] == []


def test_a_back_field_cannot_leave_the_news_pages(fake, monkeypatch):
    fake.t["church_posts"].append(_post(P_CHURCH))
    r = _client(monkeypatch, _me(MONIQUE)).post("/my/news/react",
                                                 data={"id": P_CHURCH, "kind": "love", "back": "https://evil.example"})
    assert r.headers["location"].startswith("/my/news")
    r = _client(monkeypatch, _me(MONIQUE)).post("/my/news/react", data={"id": P_CHURCH, "kind": "love", "back": "/my"})
    assert r.headers["location"] == f"/my#p-{P_CHURCH}"


def test_a_comment_route_lands_on_the_comments(fake, monkeypatch):
    _screen(monkeypatch, "ok")
    fake.t["church_posts"].append(_post(P_CHURCH))
    r = _client(monkeypatch, _me(MONIQUE)).post("/my/news/comment", data={"id": P_CHURCH, "body": "Amen"})
    assert r.headers["location"] == f"/my/news/{P_CHURCH}?done=commented#comments"


# ── 7. the office ────────────────────────────────────────────────────

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
    app.dependency_overrides[require_user] = lambda: _User()
    return TestClient(app)


def test_posting_needs_a_seat_that_edits(fake, monkeypatch):
    fake.t["businesses"] = [{"id": BIZ, "name": "Love City Church", "settings": {}, "owner_id": "o1"}]
    body = {"business_id": BIZ, "title": "Fall Fest", "body": "Oct 31", "pin": True}
    assert _office(monkeypatch, "viewer").post("/church/news", json=body).status_code == 403
    r = _office(monkeypatch, "member").post("/church/news", json=body)
    assert r.status_code == 200, r.text
    row = fake.t["church_posts"][0]
    assert row["source"] == "office" and row["pinned_until"] and row["status"] == "posted"


def test_the_office_page_counts_and_never_shows_a_comments_words(fake, monkeypatch):
    _screen(monkeypatch, "ok")
    fake.t["businesses"] = [{"id": BIZ, "name": "Love City Church", "settings": {}, "owner_id": "o1"}]
    fake.t["member_login_codes"] = [{"business_id": BIZ, "email": e, "succeeded": True} for e in ("a@x", "b@x", "a@x")]
    fake.t["church_posts"].append(_post(P_CHURCH, group_id=G))
    cn.mark_seen(BIZ, MONIQUE, [P_CHURCH])
    cn.react(BIZ, MONIQUE, P_CHURCH, "love")
    _say(_me(MONIQUE), "We'll be there")
    _screen(monkeypatch, "harm")
    _say(_me(TEEN), "something unkind")
    v = _office(monkeypatch, "viewer").get(f"/church/news?business_id={BIZ}").json()
    row = v["posts"][0]
    assert (row["seen"], row["reactions"], row["comment_n"], row["for"]) == (1, 1, 1, "Sisters in the City")
    assert v["app_people"] == 2 and v["safety"]["held_week"] == 1 and v["held"][0]["post_title"]
    assert "something unkind" not in str(v) and "We'll be there" not in str(v)
    # The leaders the church can pick: whoever leads a group, not yet picked.
    assert [c["contact_id"] for c in v["candidates"]] == [TASHA]


def test_only_a_safety_officer_reads_or_decides_a_held_comment(fake, monkeypatch):
    import messaging_router as mr
    from fastapi import HTTPException
    _screen(monkeypatch, "harm")
    fake.t["church_posts"].append(_post(P_CHURCH))
    _say(_me(MONIQUE), "something unkind")
    cid = fake.t["church_post_comments"][0]["id"]
    officer = {"yes": False}

    def require(biz, user):
        if not officer["yes"]:
            raise HTTPException(403, "Only the church's safety officers can open the Safety room.")
    monkeypatch.setattr(mr, "require_officer", require)
    client = _office(monkeypatch, "admin")
    assert client.get(f"/church/news/held?business_id={BIZ}").status_code == 403
    assert client.post(f"/church/news/held/{cid}", json={"business_id": BIZ, "show": True}).status_code == 403
    officer["yes"] = True
    words = client.get(f"/church/news/held?business_id={BIZ}").json()["held"]
    assert words[0]["body"] == "something unkind" and words[0]["name"] == "Monique Brown"
    assert client.post(f"/church/news/held/{cid}", json={"business_id": BIZ, "show": False}).status_code == 200
    assert fake.t["church_post_comments"][0]["status"] == "removed"


def test_picking_who_posts_to_the_whole_church_is_an_admins(fake, monkeypatch):
    body = {"business_id": BIZ, "add": [MONIQUE]}
    assert _office(monkeypatch, "member").post("/church/news/posters", json=body).status_code == 403
    assert _office(monkeypatch, "admin").post("/church/news/posters", json=body).status_code == 200
    assert cn.can_post(BIZ, MONIQUE)["church"] is True
    assert cn.can_post(BIZ, ROCHELLE)["church"] is False
    # A group's leader posts to their own group, by being its leader.
    assert [g["id"] for g in cn.can_post(BIZ, TASHA)["groups"]] == [G]
