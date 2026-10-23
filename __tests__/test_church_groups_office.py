# __tests__/test_church_groups_office.py
#
# The office's Groups page (church_groups_office.py; the approved canvas
# "Church Groups, Together", board Office: "Every group, alive. … You never
# see their private chat."). Pins:
#   1. health is counts only: messages in each group's chat this week, Board
#      posts and prayers this month, and the safety picture; never a word of
#      the chat; a failed read is an outage, never a quiet group
#   2. a word to every group lands on each Board from "Your pastors", a note
#      goes to every phone in a group and an email to adults without one;
#      to the group leaders only, only leaders see it; only a seat that can
#      edit sends it
#   3. a nudge to a group's leaders about people waiting, once a day
#   4. any seat reads; no seat, nothing

import asyncio
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import church_groups_office as cgo
import member_push
from test_member_messaging import (ANA, BEN, BIZ, CARL, GRP, OWNER, TEEN, TEEN2, YOUTH, _group_tid, _send,  # noqa: F401
                                   _User, env)

VIEWER = "77777777-7777-4777-8777-777777777777"
EDITOR = "88888888-8888-4888-8888-888888888888"
STRANGER = "66666666-6666-4666-8666-666666666666"
NOW = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)     # the fake stamps messages on Oct 2


@pytest.fixture
def office(env, monkeypatch):
    t = env.t
    t["business_users"] = [{"business_id": BIZ, "user_id": VIEWER, "status": "active", "role": "viewer"},
                           {"business_id": BIZ, "user_id": EDITOR, "status": "active", "role": "member"}]
    for g in t["groups"]:
        g.update(active=True, kind="small_group", description="", meets="", location="", capacity=None,
                 open_to_join=True, join_mode="ask", name_display="full", youth=False, chat_on=True, chat_writers="all")
    t["businesses"][0]["name"] = "First Light Church"
    t["businesses"][0]["settings"]["member_portal"] = {"enabled": True, "notifications": {"groups": True}}
    t.update(group_posts=[], group_prayers=[], group_join_requests=[], member_push_subscriptions=[], group_post_seen=[])
    for c in t["contacts"]:
        c["email"] = f"{c['name'].split()[0].lower()}@example.com"
    monkeypatch.setattr(cgo, "_now", lambda: NOW)
    env.pushed = []
    monkeypatch.setattr(member_push, "send", lambda biz, kind, **k: env.pushed.append((kind, k)) or len(k.get("contact_ids") or []))
    env.emails = []

    async def resend(**k):
        env.emails.append(k)
    import email_sender
    monkeypatch.setattr(email_sender, "send_via_resend", resend)
    import group_email
    monkeypatch.setattr(group_email, "app_url", lambda b: "https://first-light.example")
    return env


def _office(uid):
    from auth_supabase import require_user
    app = FastAPI()
    app.include_router(cgo.router)
    app.dependency_overrides[require_user] = lambda: _User(uid)
    return TestClient(app)


def _ago(**kw):
    return (NOW - timedelta(**kw)).isoformat()


# ── 1. how each group is doing ───────────────────────────────────────

def test_counts_only_never_the_chat(office):
    tid = _group_tid(office, ANA, GRP)
    _send(office, ANA, tid, "See you Thursday")
    _send(office, BEN, tid, "Bring chairs")
    office.t["msg_messages"].append({"id": "old-1", "business_id": BIZ, "thread_id": tid, "sender_contact_id": ANA,
                                     "body": "Last month", "status": "delivered", "created_at": _ago(days=9)})
    office.verdict = "harm"
    _send(office, ANA, tid, "something held")
    office.t["group_posts"] += [{"id": "p1", "business_id": BIZ, "group_id": GRP, "removed_at": None, "created_at": _ago(days=3)},
                                {"id": "p2", "business_id": BIZ, "group_id": GRP, "removed_at": None, "created_at": _ago(days=40)},
                                {"id": "p3", "business_id": BIZ, "group_id": None, "removed_at": None, "created_at": _ago(days=1)}]
    office.t["group_prayers"] += [{"group_id": GRP, "business_id": BIZ, "to_pastor": False, "created_at": _ago(days=2)},
                                  {"group_id": GRP, "business_id": BIZ, "to_pastor": True, "created_at": _ago(days=2)}]
    office.t["msg_reports"].append({"id": "r1", "business_id": BIZ, "status": "open"})
    r = _office(VIEWER).get(f"/church/groups/health?business_id={BIZ}")
    assert r.status_code == 200
    body = r.json()
    assert body["groups"][GRP] == {"talk_week": 2, "posts_month": 1, "prayers_month": 1}
    assert body["safety"] == {"messaging_on": True, "officers": 0, "min_officers": 2, "held_week": 1, "reports_open": 1,
                              "to_pastor_week": 1}
    assert "See you Thursday" not in r.text and "Bring chairs" not in r.text


def test_a_failed_read_is_an_outage_not_a_quiet_group(office, monkeypatch):
    import sb_clients
    _group_tid(office, ANA, GRP)
    real = office.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: None if path.startswith("/msg_messages") else real(path))
    r = _office(VIEWER).get(f"/church/groups/health?business_id={BIZ}")
    assert r.status_code == 503


def test_no_seat_no_page(office):
    assert _office(STRANGER).get(f"/church/groups/health?business_id={BIZ}").status_code == 403


# ── 2. a word to every group ─────────────────────────────────────────

def test_a_word_to_every_group(office):
    office.t["member_push_subscriptions"] = [{"business_id": BIZ, "contact_id": ANA}]
    r = _office(EDITOR).post("/church/groups/word", json={"business_id": BIZ, "title": "Consecrate Your Focus",
                                                          "body": "Starting Monday, every group reads it together."})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["people"] == 5 and out["groups"] == 2 and out["phones"] == 5
    post = office.t["group_posts"][0]
    assert post["group_id"] is None and post["posted_by"] is None and post["audience"] == "all" and post["ask_ack"] is True
    kind, k = office.pushed[0]
    assert kind == "groups" and sorted(k["contact_ids"]) == sorted([ANA, BEN, CARL, TEEN, TEEN2])
    assert k["body"] == "From your pastors: Consecrate Your Focus" and k["ref_id"] == f"church-word:{post['id']}"
    # Email to the adults with no phone: Ben and Carl (Ana has a phone; teens never get email).
    assert sorted(e["to_email"] for e in office.emails) == ["ben@example.com", "carl@example.com"]
    assert out["emailed"] == 2 and post["emailed"] == 2
    assert "Open your groups" in office.emails[0]["body"] and office.emails[0]["from_name"] == "First Light Church"


def test_on_each_board_from_your_pastors(office):
    import member_portal_groups as mpg
    _office(OWNER).post("/church/groups/word", json={"business_id": BIZ, "body": "Grace to you"})
    board = mpg.posts_for(BIZ, GRP, ANA, False, 2)
    assert board[0]["church"] and board[0]["body"] == "Grace to you"
    html = mpg._post_card(board[0], {"id": GRP, "name_display": "full"}, leader=False, me_id=ANA, size=2, back="/my/groups")
    assert "Your pastors" in html and "to every group" in html


def test_to_the_leaders_only(office):
    import member_portal_groups as mpg
    r = _office(OWNER).post("/church/groups/word", json={"business_id": BIZ, "audience": "leaders", "body": "Leaders, a word"})
    assert r.json()["people"] == 2 and sorted(office.pushed[0][1]["contact_ids"]) == sorted([BEN, CARL])
    assert office.t["group_posts"][0]["audience"] == "leaders"
    assert mpg.posts_for(BIZ, GRP, ANA, False, 2) == []                 # a member doesn't see it
    lead = mpg.posts_for(BIZ, GRP, BEN, True, 2)
    assert lead and lead[0]["body"] == "Leaders, a word"
    html = mpg._post_card(lead[0], {"id": GRP, "name_display": "full"}, leader=True, me_id=BEN, size=2, back="/my/groups")
    assert "to every group leader" in html


def test_an_archived_groups_people_arent_told(office):
    next(g for g in office.t["groups"] if g["id"] == YOUTH)["active"] = False
    r = _office(OWNER).post("/church/groups/word", json={"business_id": BIZ, "body": "Hello"})
    assert r.json()["groups"] == 1 and sorted(office.pushed[0][1]["contact_ids"]) == sorted([ANA, BEN])


def test_only_a_seat_that_edits_sends(office):
    r = _office(VIEWER).post("/church/groups/word", json={"business_id": BIZ, "body": "Hi"})
    assert r.status_code == 403 and office.t["group_posts"] == [] and office.pushed == []
    r = _office(EDITOR).post("/church/groups/word", json={"business_id": BIZ, "body": "   "})
    assert r.status_code == 422 and office.t["group_posts"] == []


def test_nobody_to_send_to(office):
    office.t["group_members"] = []
    r = _office(OWNER).post("/church/groups/word", json={"business_id": BIZ, "body": "Hello"})
    assert r.status_code == 409 and office.t["group_posts"] == []


def _news(office, monkeypatch):
    import news_alerts
    office.t["church_posts"] = []
    office.rang = []
    monkeypatch.setattr(news_alerts, "alert_later", lambda business, post: office.rang.append(post["id"]))


def test_a_word_can_go_on_news_too(office, monkeypatch):
    # Kevin, 2026-10-23: "if I want to post to news feed i can choose so or
    # not because not everyone possibly is in a group".
    _news(office, monkeypatch)
    r = _office(EDITOR).post("/church/groups/word", json={"business_id": BIZ, "title": "Consecrate Your Focus",
                                                          "body": "Starting Monday, we read it together.", "news": True})
    assert r.status_code == 200, r.text
    news = office.t["church_posts"]
    assert len(news) == 1 and r.json()["news_post_id"] == news[0]["id"] and office.rang == [news[0]["id"]]
    assert (news[0].get("group_id"), news[0]["source"], news[0]["status"], news[0]["title"], news[0]["body"]) == (
        None, "office", "posted", "Consecrate Your Focus", "Starting Monday, we read it together.")
    assert len(office.t["group_posts"]) == 1 and r.json()["people"] == 5          # the groups still get it


def test_not_on_news_unless_chosen_and_never_a_leaders_only_word(office, monkeypatch):
    _news(office, monkeypatch)
    assert _office(OWNER).post("/church/groups/word", json={"business_id": BIZ, "body": "Hello"}).json()["news_post_id"] is None
    r = _office(OWNER).post("/church/groups/word", json={"business_id": BIZ, "audience": "leaders", "body": "Leaders", "news": True})
    assert r.json()["news_post_id"] is None and office.t["church_posts"] == [] and office.rang == []


def test_with_nobody_in_a_group_news_still_takes_it(office, monkeypatch):
    _news(office, monkeypatch)
    office.t["group_members"] = []
    r = _office(OWNER).post("/church/groups/word", json={"business_id": BIZ, "body": "Hello, church", "news": True})
    assert r.status_code == 200 and r.json()["people"] == 0 and r.json()["news_post_id"]
    assert office.t["group_posts"] == [] and office.pushed == [] and len(office.t["church_posts"]) == 1


# ── 3. a nudge to a leader ───────────────────────────────────────────

def test_remind_the_leaders_once_a_day(office):
    office.t["group_join_requests"].append({"id": "j1", "business_id": BIZ, "group_id": GRP, "contact_id": CARL, "status": "waiting"})
    r = _office(EDITOR).post("/church/groups/remind", json={"business_id": BIZ, "group_id": GRP})
    assert r.status_code == 200 and r.json()["phones"] == 1
    kind, k = office.pushed[0]
    assert kind == "groups" and k["contact_ids"] == [BEN] and k["body"].startswith("1 person is waiting to join")
    assert k["ref_id"] == f"join-remind:{GRP}:2026-10-03"


def test_remind_only_when_someone_waits_and_someone_leads(office):
    r = _office(EDITOR).post("/church/groups/remind", json={"business_id": BIZ, "group_id": GRP})
    assert r.status_code == 409
    office.t["group_join_requests"].append({"id": "j1", "business_id": BIZ, "group_id": GRP, "contact_id": CARL, "status": "waiting"})
    office.t["group_members"] = [m for m in office.t["group_members"] if m["role"] != "leader"]
    r = _office(EDITOR).post("/church/groups/remind", json={"business_id": BIZ, "group_id": GRP})
    assert r.status_code == 409 and office.pushed == []
    assert _office(VIEWER).post("/church/groups/remind", json={"business_id": BIZ, "group_id": GRP}).status_code == 403


def test_remind_says_when_group_news_is_off(office):
    office.t["businesses"][0]["settings"]["member_portal"] = {"enabled": True, "notifications": {}}
    office.t["group_join_requests"].append({"id": "j1", "business_id": BIZ, "group_id": GRP, "contact_id": CARL, "status": "waiting"})
    r = _office(EDITOR).post("/church/groups/remind", json={"business_id": BIZ, "group_id": GRP})
    assert r.json() == {"ok": True, "phones": 0, "why": "off"} and office.pushed == []


def test_the_router_is_mounted():
    src = (pathlib.Path(__file__).resolve().parent.parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert "app.include_router(church_groups_office_router)" in src
