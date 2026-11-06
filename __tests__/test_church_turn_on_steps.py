"""A church's setup list names what it has to switch on.

Kevin, 2026-11-06, on the member app, messaging, the website assistant and
Sunday check-in all starting off: "they might not know to turn them on."
A step has to do three things, and each is pinned here:
  1. appear for a church, and never for a business;
  2. tick itself off from the same setting the feature reads, so it can't
     say done while the feature stays off;
  3. open the screen where the switch is, and say only what's true.
"""
from __future__ import annotations

import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))

import pytest  # noqa: E402

import business_track_actions as bta  # noqa: E402
import business_track_router as btr  # noqa: E402
import member_portal_messaging as mpm  # noqa: E402
import member_push  # noqa: E402

STEPS = ("member_app", "member_alerts", "sunday_checkin", "messaging")


@pytest.fixture
def db(monkeypatch):
    rows = {"checkin": [], "tracks": []}

    def get(path):
        if path.startswith("/church_checkin_settings"):
            return rows["checkin"]
        if path.startswith("/business_tracks"):
            return rows["tracks"]
        return []

    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    return rows


def _church(**settings):
    return {"id": "b1", "type": "church", "settings": settings}


def _by_key(biz):
    return {p["key"]: p for p in btr.resolve_plugins(biz)}


# ─── 1. who sees them ────────────────────────────────────────────────

def test_a_church_sees_every_step(db):
    items = _by_key(_church())
    for key in STEPS + ("concierge",):
        assert key in items, key


@pytest.mark.parametrize("kind", ["barber", "coach", "therapist", "nonprofit"])
def test_nobody_else_does(kind):
    keys = bta.plugins_for_vertical(kind)
    assert not set(STEPS) & set(keys), kind


def test_a_coachs_plan_cant_hide_them(db):
    db["tracks"] = [{"first_30_days": {"plugins": ["site", "brand"]}, "operations_map": {}}]
    items = _by_key(_church())
    assert {"site", "brand"} <= set(items)
    for key in STEPS + ("concierge",):
        assert key in items, key


def test_they_come_before_the_nice_to_haves(db):
    keys = bta.plugins_for_vertical("church")
    assert keys.index("member_app") < keys.index("site") < keys.index("concierge") < keys.index("bank")
    assert keys.index("import_contacts") < keys.index("member_app")


# ─── 2. done means the feature is on ─────────────────────────────────

def test_nothing_is_done_on_a_new_church(db):
    items = _by_key(_church())
    assert not any(items[k]["done"] for k in STEPS)


def test_the_member_app_is_done_when_the_portal_is_on(db):
    assert _by_key(_church(member_portal={"enabled": True}))["member_app"]["done"] is True
    assert _by_key(_church(member_portal={"enabled": False}))["member_app"]["done"] is False


def test_alerts_are_done_only_when_a_kind_the_sender_reads_is_on(db):
    settings = {"member_portal": {"notifications": {"news": True}}}
    assert member_push.church_kinds(settings) == {"news"}
    assert _by_key(_church(**settings))["member_alerts"]["done"] is True
    assert _by_key(_church(member_portal={"notifications": {"news": False}}))["member_alerts"]["done"] is False


def test_check_in_is_done_when_it_is_enabled(db):
    assert _by_key(_church())["sunday_checkin"]["done"] is False
    db["checkin"] = [{"business_id": "b1"}]
    assert _by_key(_church())["sunday_checkin"]["done"] is True


def test_messaging_reads_the_setting_the_feature_reads(db):
    biz = _church(messaging={"enabled": True})
    assert mpm.turned_on(biz) is True
    assert _by_key(biz)["messaging"]["done"] is True


def test_alerts_wait_for_the_member_app(db):
    item = _by_key(_church())["member_alerts"]
    assert item["blocked_by"] == ["member_app"]
    assert _by_key(_church(member_portal={"enabled": True}))["member_alerts"]["blocked_by"] == []


# ─── 3. where they lead and what they say ───────────────────────────

def test_the_assistant_step_opens_on_its_own_section(db):
    item = _by_key(_church())["concierge"]
    assert item["nav"] == {"tab": "build", "page": "settings", "section": "concierge"}
    assert item["title"] == "Turn on your website assistant"


def test_a_business_keeps_its_concierge_words(db):
    item = btr.resolve_plugins({"id": "b2", "type": "barber", "settings": {}})
    assert next(p for p in item if p["key"] == "concierge")["title"] == "Turn on the website concierge"


def test_messaging_says_what_it_needs():
    import messaging_router
    assert messaging_router.MIN_OFFICERS == 2
    assert "two safety officers" in bta.PLUGIN_CATALOG["messaging"]["why"]


@pytest.mark.parametrize("key", STEPS + ("concierge",))
def test_no_business_words(db, key):
    item = _by_key(_church())[key]
    text = f'{item["title"]} {item["why"]}'.lower()
    for word in ("client", "invoice", "customer", "your business"):
        assert word not in text, (key, word)
