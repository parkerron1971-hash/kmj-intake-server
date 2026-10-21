# __tests__/test_group_post_later.py
#
# A leader's Board post that goes out later (group_post_later; the approved
# canvas "Church Groups, Together", board Post: "Send later"). Pins:
#   1. a time on the church's clock, from 5 minutes to 30 days ahead; it's
#      checked when it's written; an after-hours alert or a pin waits too
#   2. until then only the group's leaders see it (Scheduled, Send now, Take
#      it down); members see nothing, and nobody is told
#   3. at its time it's on the Board, and the job sends the note and the
#      emails once; Send now does the same right away
#   4. the 7 PM chat note's sweep reaches a church with only New messages on

import asyncio
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import group_post_later as gpl
import member_portal_groups as mpg
from test_member_portal_group_space import (BIZ, BUSINESS, G, MONIQUE, TASHA, TEEN, _client, _me, _req,  # noqa: F401
                                            _screen, fake)

DETROIT = ZoneInfo("America/Detroit")
NOW = datetime(2026, 10, 20, 14, 0, tzinfo=timezone.utc)          # 10 AM in Detroit


@pytest.fixture
def later(fake, monkeypatch):
    import group_gatherings as gg
    monkeypatch.setattr(gg, "zone", lambda business: DETROIT)
    clock = {"now": NOW}
    monkeypatch.setattr(gpl, "_now", lambda: clock["now"])
    fake.clock = clock
    _screen(monkeypatch, "ok")
    fake.t["businesses"] = [{"id": BIZ, "name": "Love City Church", "settings": {}, "owner_id": None}]
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fake.patch)
    fake.emailed = []

    async def email_rest(business, g, post, author):
        fake.emailed.append(post["id"])
        return 1
    import group_email
    monkeypatch.setattr(group_email, "email_rest", email_rest)
    return fake


def _write(who, send_at="", **k):
    return asyncio.run(mpg.create_post(BUSINESS, _me(who, "Tasha Williams"), G, k.get("title", "Potluck moved"),
                                       k.get("body", "We'll eat on the 19th."), k.get("pin", False), True,
                                       k.get("after_hours", False), k.get("email", False), send_at))


def _board(who, leader):
    return mpg.posts_for(BIZ, G, who, leader, 3)


# ── 1. writing it ────────────────────────────────────────────────────

def test_a_time_on_the_churchs_clock(later):
    assert _write(TASHA, "2026-10-22T09:00") == (True, "post_later")
    p = later.t["group_posts"][0]
    assert p["publish_at"] == datetime(2026, 10, 22, 13, 0, tzinfo=timezone.utc).isoformat()     # 9 AM Detroit, kept in UTC
    assert later.told == []                                           # nobody hears yet


def test_too_soon_or_too_far_or_nonsense(later):
    assert _write(TASHA, "2026-10-20T10:03") == (False, "later_bad")  # 3 minutes from now
    assert _write(TASHA, "2026-12-01T09:00") == (False, "later_bad")  # past 30 days
    assert _write(TASHA, "next thursday") == (False, "later_bad")
    assert later.t["group_posts"] == []
    assert _write(MONIQUE, "2026-10-22T09:00") == (False, "not_group_leader")


def test_checked_when_written(later, monkeypatch):
    _screen(monkeypatch, "harm")
    assert _write(TASHA, "2026-10-22T09:00") == (False, "post_no")
    assert later.t["group_posts"] == []


def test_an_alert_or_a_pin_waits(later, monkeypatch):
    later.t["group_posts"].append({"id": "eeeeeeee-0000-0000-0000-0000000000a1", "business_id": BIZ, "group_id": G, "title": "Old",
                                   "body": "Pinned before", "pinned": True, "ask_ack": False, "posted_by": TASHA,
                                   "removed_at": None, "created_at": "2026-10-19T12:00:00+00:00"})
    import member_push
    monkeypatch.setattr(member_push, "quiet_hour", lambda b: True)
    _write(TASHA, "2026-10-22T09:00", pin=True, after_hours=True)
    new = later.t["group_posts"][-1]
    assert not new.get("after_hours")                                 # an alert is for now
    assert later.t["group_posts"][0]["pinned"] is True                # the old pin holds until it goes out


# ── 2. until then ────────────────────────────────────────────────────

def test_only_leaders_see_it_until_then(later):
    _write(TASHA, "2026-10-22T09:00")
    assert _board(MONIQUE, False) == []
    lead = _board(TASHA, True)
    assert lead and lead[0]["later"] and lead[0]["later_label"] == "Thursday, October 22 · 9:00 AM"
    html = mpg._post_card(lead[0], {"id": G, "name_display": "full"}, leader=True, me_id=TASHA, size=3, back="/my/groups")
    assert "Scheduled" in html and "Goes out Thursday, October 22 · 9:00 AM" in html and "Send now" in html
    assert "gs-ack" not in html and "Seen by" not in html


def test_the_compose_offers_it(later):
    html = gpl.compose_later(BUSINESS, mpg._ic)
    assert 'name="send_at"' in html and 'min="2026-10-20T10:05"' in html and 'max="2026-11-19T10:00"' in html


# ── 3. going out ─────────────────────────────────────────────────────

def test_at_its_time_once(later):
    _write(TASHA, "2026-10-22T09:00", email=True, pin=True)
    later.t["group_posts"].insert(0, {"id": "eeeeeeee-0000-0000-0000-0000000000a1", "business_id": BIZ, "group_id": G,
                                      "title": "Old", "body": "Pinned before", "pinned": True, "ask_ack": False,
                                      "posted_by": TASHA, "removed_at": None, "created_at": "2026-10-19T12:00:00+00:00"})
    assert gpl.sweep_tick(datetime(2026, 10, 22, 12, 59, tzinfo=timezone.utc)) == 0     # 8:59 in Detroit
    later.clock["now"] = datetime(2026, 10, 22, 13, 1, tzinfo=timezone.utc)
    assert gpl.sweep_tick(later.clock["now"]) == 1
    post = later.t["group_posts"][-1]
    assert [t for t in later.told if t[0] == "post"] == [("post", G, post["id"], "Potluck moved")]
    assert later.emailed == [post["id"]] and post["told_at"]
    assert later.t["group_posts"][0]["pinned"] is False and post["pinned"] is True        # it takes the top now
    assert gpl.sweep_tick(later.clock["now"]) == 0                                         # once
    assert _board(MONIQUE, False)[0]["id"] == post["id"]


def test_send_now(later, monkeypatch):
    _write(TASHA, "2026-10-22T09:00")
    pid = later.t["group_posts"][0]["id"]
    assert gpl.send_now(BUSINESS, _me(MONIQUE, "x"), pid) == (False, "not_group_leader", G)
    r = _client(monkeypatch, _me(TASHA, "Tasha")).post("/my/groups/post/now", data={"id": pid})
    assert r.headers["location"] == f"/my/groups/{G}/board?done=post_up"
    assert later.t["group_posts"][0]["told_at"] and len([t for t in later.told if t[0] == "post"]) == 1
    assert _board(MONIQUE, False)[0]["id"] == pid
    assert gpl.sweep_tick(datetime(2026, 10, 22, 13, 1, tzinfo=timezone.utc)) == 0         # not twice


def test_a_post_taken_down_never_goes_out(later):
    _write(TASHA, "2026-10-22T09:00")
    later.t["group_posts"][0]["removed_at"] = "2026-10-21T00:00:00+00:00"
    assert gpl.sweep_tick(datetime(2026, 10, 22, 13, 1, tzinfo=timezone.utc)) == 0 and later.told == []


def test_the_route_passes_the_time(later, monkeypatch):
    r = _client(monkeypatch, _me(TASHA, "Tasha")).post(
        "/my/groups/post", data={"group_id": G, "body": "Later", "send_at": "2026-10-22T09:00"})
    assert r.headers["location"] == f"/my/groups/{G}/board?done=post_later"


# ── 4. the evening note reaches a messages-only church ───────────────

def test_the_sweep_reads_churches_with_only_messages_on():
    src = (pathlib.Path(__file__).resolve().parent.parent / "member_push.py").read_text(encoding="utf-8")
    assert "settings->member_portal->notifications->>messages.eq.true" in src


def test_every_code_has_words_and_the_job():
    import member_portal_church as mpc
    assert "post_later" in mpc.DONE and {"later_bad", "post_gone"} <= set(mpc.ERRORS)
    src = (pathlib.Path(__file__).resolve().parent.parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert 'g("group_post_later", _group_post_later.sweep_tick)' in src


def test_two_runs_at_once_tell_once(later):
    # Two workers that both read the post before either claimed it.
    _write(TASHA, "2026-10-22T09:00")
    now = datetime(2026, 10, 22, 13, 1, tzinfo=timezone.utc)
    row = dict(later.t["group_posts"][0])
    assert gpl._go_out(dict(row), now) is True
    assert gpl._go_out(dict(row), now) is False
    assert len([t for t in later.told if t[0] == "post"]) == 1


def test_taken_down_between_the_read_and_the_send(later):
    _write(TASHA, "2026-10-22T09:00")
    row = dict(later.t["group_posts"][0])
    later.t["group_posts"][0]["removed_at"] = "2026-10-22T12:59:00+00:00"
    assert gpl._go_out(row, datetime(2026, 10, 22, 13, 1, tzinfo=timezone.utc)) is False and later.told == []
