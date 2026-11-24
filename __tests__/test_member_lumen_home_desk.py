# __tests__/test_member_lumen_home_desk.py
#
# Kevin's Home plan (2026-11-21, "yes to everything"): the owner's desk
# strip on the new look's Home, after This week, before the feed.
#   - Only the church's owner (their preview, or their own member record:
#     settings.church_owner_contact_id) gets it; nobody else reads for it.
#   - What waits in the office's News room, as its Waiting for you counts
#     it: good news members shared ("1 good news post is waiting", "It came
#     in today. Approve it and Grace Fellowship's feed begins. Only you see
#     this."), members' group posts and comments the check held; each with
#     Review, to the office's News room (?nav=operate:news).
#   - At a church with no news yet, the owner's "Post the church's first
#     news" moves from the feed into the desk.
#   - Two reads, kept a minute per church; a failed read leaves the counts
#     out (never "nothing waits"), and isn't kept.

import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import member_portal_lumen as mlp
import test_church_threads as tct
from test_church_threads import fake  # noqa: F401  (the fixture)
from test_member_lumen_home import _client, _main, church  # noqa: F401


def _ago(**kw):
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat()


def _desk(html):
    if 'class="lm-desk"' not in html:
        return ""
    i = html.index('<section class="lm-desk"')
    return html[i:html.index("</section>", i)]


@pytest.fixture
def owner(church, fake, monkeypatch):  # noqa: F811
    """Ana is the church's owner (her own member record); one good news post
    came in two hours ago; nothing reaches Home yet."""
    fake.biz[tct.BIZ]["settings"]["church_owner_contact_id"] = tct.ANA
    fake.t.setdefault("church_posts", [])
    fake.t.setdefault("church_post_comments", [])
    fake.add("church_posts", id=tct.cid(2501), business_id=tct.BIZ, source="member", status="waiting", group_id=None,
             removed_at=None, kind="good_news", attach={"share": "baby"}, created_at=_ago(hours=2))
    monkeypatch.setattr(mlp, "_DESK", None)
    monkeypatch.setattr(mlp, "_CLASS", None)
    monkeypatch.setattr(mlp, "_STREAMS", None)
    return church


def test_the_owner_sees_what_waits(owner, fake, monkeypatch):  # noqa: F811
    html = _client(fake, monkeypatch).get("/my").text
    desk = _desk(html)
    assert "<b>1 good news post is waiting</b>" in desk
    assert "It came in " in desk                                                # today, or yesterday by the scene's clock
    # Good news is approved in the app now: My serving's To approve
    # (news_approvers, the canvas "Good News Approvals").
    assert ". Approve it in Serve and Grace Fellowship&#x27;s feed begins. Only you see this." in desk
    assert '<a class="lm-dkb" href="/my/serving#approve">Approve</a>' in desk
    main = _main(html)
    assert main.index('id="lm-wk-h"') < main.index('class="lm-desk"') < main.index('class="lm-hcp"')


def test_nobody_else_sees_it_or_reads_for_it(owner, fake, monkeypatch):  # noqa: F811
    fake.biz[tct.BIZ]["settings"]["church_owner_contact_id"] = tct.BEN
    c = _client(fake, monkeypatch)
    fake.gets.clear()
    html = c.get("/my").text
    assert 'class="lm-desk"' not in html
    assert not any(g.startswith("/church_post_comments") for g in fake.gets)
    assert not any(g.startswith("/church_posts") and "status=eq.waiting" in g for g in fake.gets)


def test_held_comments_and_posts(owner, fake, monkeypatch):  # noqa: F811
    fake.t["church_posts"].clear()
    fake.add("church_posts", id=tct.cid(2502), business_id=tct.BIZ, source="member", status="waiting",
             group_id=tct.GROUP, removed_at=None, attach={"held": "harm"}, created_at=_ago(hours=1))
    fake.add("church_post_comments", id=tct.cid(2503), business_id=tct.BIZ, status="held", post_id=tct.cid(2504))
    fake.add("church_post_comments", id=tct.cid(2505), business_id=tct.BIZ, status="held", post_id=tct.cid(2504))
    desk = _desk(_client(fake, monkeypatch).get("/my").text)
    assert "<b>2 comments and 1 post are held</b>" in desk and "for a safety officer to read." in desk
    assert "good news" not in desk


def test_the_first_news_moves_into_the_desk(owner, fake, monkeypatch):  # noqa: F811
    fake.t["church_posts"].clear()
    fake.t.setdefault("church_news_posters", []).append({"business_id": tct.BIZ, "contact_id": tct.ANA})
    html = _client(fake, monkeypatch).get("/my").text
    desk = _desk(html)
    assert "<b>Post the church&#x27;s first news</b>" in desk and 'href="/my/news/write">Post</a>' in desk
    assert html.count("Post the church&#x27;s first news") == 1                 # not in the feed as well
    # Someone else who may post still finds it in the feed.
    fake.biz[tct.BIZ]["settings"]["church_owner_contact_id"] = tct.BEN
    html = _client(fake, monkeypatch).get("/my").text
    assert 'class="lm-desk"' not in html and "Post the church&#x27;s first news" in html


def test_the_counts_are_kept_a_minute(owner, fake, monkeypatch):  # noqa: F811
    c = _client(fake, monkeypatch)
    c.get("/my")
    fake.gets.clear()
    c.get("/my")
    assert not any(g.startswith("/church_post_comments") for g in fake.gets)


def test_a_failed_read_leaves_the_counts_out_and_isnt_kept(owner, fake, monkeypatch):  # noqa: F811
    fake.down.add("church_post_comments")
    c = _client(fake, monkeypatch)
    assert "good news post" not in _desk(c.get("/my").text)
    fake.down.discard("church_post_comments")
    assert "<b>1 good news post is waiting</b>" in _desk(c.get("/my").text)


def test_a_failed_read_keeps_the_first_news_in_the_feed(owner, fake, monkeypatch):  # noqa: F811
    # The strip can't tell what waits: it says nothing, and the owner's way
    # to post stays where it was, in the feed.
    fake.t["church_posts"].clear()
    fake.t.setdefault("church_news_posters", []).append({"business_id": tct.BIZ, "contact_id": tct.ANA})
    fake.down.add("church_post_comments")
    html = _client(fake, monkeypatch).get("/my").text
    assert 'class="lm-desk"' not in html and html.count("Post the church&#x27;s first news") == 1


def test_many_group_posts_never_crowd_out_the_good_news(owner, fake, monkeypatch):  # noqa: F811
    for i in range(70):
        fake.add("church_posts", id=tct.cid(2600 + i), business_id=tct.BIZ, source="member", status="waiting",
                 group_id=tct.GROUP, removed_at=None, attach={}, created_at=_ago(minutes=i))
    desk = _desk(_client(fake, monkeypatch).get("/my").text)
    assert "<b>1 good news post is waiting</b>" in desk and "held" not in desk


def test_old_good_news_and_nothing_waiting(owner, fake, monkeypatch):  # noqa: F811
    fake.t["church_posts"][0]["created_at"] = _ago(days=45)   # past the office list's 30 days
    assert 'class="lm-desk"' not in _client(fake, monkeypatch).get("/my").text


def test_the_words():
    import member_lumen_home as lh
    from zoneinfo import ZoneInfo
    now = datetime(2026, 11, 21, 18, 45, tzinfo=ZoneInfo("America/New_York"))
    html = lh.desk({"good": 3, "good_at": "2026-11-19T15:00:00+00:00", "held_posts": 0, "held_comments": 1},
                   church="Love City Church", short="Love City", office="https://app/?nav=operate:news", now=now)
    assert "<b>3 good news posts are waiting</b>" in html and "The newest came in on Thursday." in html
    assert "Approve them to post them. Only you see this." in html
    assert "<b>1 comment is held</b>" in html and "The check held it for a safety officer to read.</p>" in html
    assert lh.desk(None, church="x", short="x", office="o", now=now, first_news=True) == ""
    many = lh.desk({"good": 60, "good_more": True, "good_at": "", "held_posts": 1, "held_comments": 59,
                    "held_more": True}, church="x", short="x", office="o", now=now)
    assert "<b>60+ good news posts are waiting</b>" in many and "<b>60+ comments and posts are held</b>" in many
    assert lh.desk({"good": 0, "held_posts": 0, "held_comments": 0}, church="x", short="x", office="o", now=now) == ""
