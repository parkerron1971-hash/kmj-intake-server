"""Posts on Home and alerts for everyone (Kevin, 2026-11-24, canvas "Posts and
Alerts" 1hEhJN7ysjiWyTUyctm5b6): the main alert kinds are on for every church
from member_push.DEFAULT_ON_FROM; approved good news shows on Home; News and
New post sit under the Home tab."""
from __future__ import annotations

import pathlib
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import church_news as cn  # noqa: E402
import member_lumen_ui as lm  # noqa: E402
import member_push  # noqa: E402
import news_approvers as nap  # noqa: E402
from test_member_portal_group_space import BIZ, ROCHELLE  # noqa: E402,F401
from test_news_share import fake, _share  # noqa: E402,F401


def _by_date(monkeypatch, day):
    monkeypatch.delenv("MEMBER_ALERTS_DEFAULTS", raising=False)
    monkeypatch.setattr(member_push, "_today", lambda: day)


def _settings(**kinds):
    return {"member_portal": {"notifications": kinds}} if kinds else {}


def test_before_thursday_a_kind_is_on_only_where_the_church_turned_it_on(monkeypatch):
    _by_date(monkeypatch, date(2026, 11, 25))
    assert member_push.church_kinds({}) == set()
    assert member_push.church_kinds(_settings(live=True)) == {"live"}


def test_from_thursday_every_church_has_the_main_kinds_on(monkeypatch):
    _by_date(monkeypatch, date(2026, 11, 26))
    assert member_push.church_kinds({}) == set(member_push.DEFAULT_ON)
    assert member_push.church_kinds(None) == set(member_push.DEFAULT_ON)
    assert {"news", "messages", "prayer"} <= set(member_push.DEFAULT_ON)
    # Serving, live and the rest stay the church's choice.
    assert "serving" not in member_push.church_kinds({}) and "live" not in member_push.church_kinds({})


def test_a_church_that_turned_one_off_keeps_it_off(monkeypatch):
    _by_date(monkeypatch, date(2026, 12, 1))
    got = member_push.church_kinds(_settings(news=False, live=True))
    assert "news" not in got and "live" in got and "messages" in got


def test_the_switch_overrides_the_date(monkeypatch):
    monkeypatch.setattr(member_push, "_today", lambda: date(2026, 12, 1))
    monkeypatch.setenv("MEMBER_ALERTS_DEFAULTS", "off")
    assert member_push.church_kinds({}) == set()
    monkeypatch.setattr(member_push, "_today", lambda: date(2026, 11, 1))
    monkeypatch.setenv("MEMBER_ALERTS_DEFAULTS", "on")
    assert member_push.church_kinds({}) == set(member_push.DEFAULT_ON)


def test_home_offers_turn_on_where_it_can_work(monkeypatch):
    monkeypatch.setenv("MEMBER_ALERTS_DEFAULTS", "on")
    monkeypatch.setattr(member_push, "ready", lambda: True)
    card = member_push.lumen_home_card({"settings": {}})
    assert 'id="lm-npc"' in card and "hidden" in card and 'href="/my/notifications">Turn on</a>' in card
    assert ">Not now</button>" in card
    monkeypatch.setattr(member_push, "ready", lambda: False)
    assert member_push.lumen_home_card({"settings": {}}) == ""
    monkeypatch.setattr(member_push, "ready", lambda: True)
    monkeypatch.setenv("MEMBER_ALERTS_DEFAULTS", "off")
    assert member_push.lumen_home_card({"settings": {}}) == ""


def test_news_and_new_post_sit_under_home():
    assert lm.TAB_OF["news"] == "home"


def test_approved_good_news_shows_on_home(fake):  # noqa: F811
    _ok, _code, pid = _share()
    assert cn.home_view(BIZ, ROCHELLE)[0] == []                # waiting: nobody sees it yet
    business = {"id": BIZ, "name": "Love City Church", "owner_id": "o1", "settings": {}}
    assert nap.settle(business, pid, "post", decided_by="o1")[0] == "posted"
    posts, _n = cn.home_view(BIZ, ROCHELLE)
    assert [p["id"] for p in posts] == [pid]


def test_a_milestone_stays_off_home(fake):  # noqa: F811
    fake.t["church_posts"].append({
        "id": "eeeeeeee-0000-0000-0000-00000000aaaa", "business_id": BIZ, "kind": "milestone", "title": "Finished a class",
        "body": "", "person_id": ROCHELLE, "posted_by": ROCHELLE, "source": "office", "status": "posted",
        "publish_at": "2026-10-22T12:00:00+00:00", "created_at": "2026-10-22T12:00:00+00:00", "removed_at": None,
        "group_id": None, "attach": {}, "comments": "on"})
    assert cn.home_view(BIZ, ROCHELLE)[0] == []
