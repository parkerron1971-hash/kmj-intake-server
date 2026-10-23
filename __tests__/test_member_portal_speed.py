# __tests__/test_member_portal_speed.py
#
# Member app tabs read what they can at once (2026-10-20). Kevin: tabs were
# "slow in changing"; each tab waited on 8-16 database reads one after
# another (0.9-1.8 s on the server). Pins:
#   1. the church and its site are ONE read (every page, icon and the
#      service worker start there)
#   2. a member's space (leader of a space? a parent?) and the Lead tab
#      (a church role? a group they lead?) are read at once, and the Lead
#      tab still follows the same rules
#   3. Home, Connect and Watch read their parts at once
# "At once" is proven, not timed: each faked read waits at a barrier that
# opens only when every one of them has started. Read one after another,
# the first never gets past it and the barrier breaks.

import asyncio
import pathlib
import sys
import threading

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import member_portal as mp
import sb_clients
from starlette.requests import Request

BIZ = "11111111-1111-1111-1111-111111111111"
ME = {"id": "22222222-2222-2222-2222-222222222222", "name": "Ana Reyes", "email": "ana@example.com",
      "birthdate": "1980-05-01"}
TEEN = {"id": "33333333-3333-3333-3333-333333333333", "name": "Kai Reyes", "email": "kai@example.com",
        "birthdate": "2011-05-01"}
BUSINESS = {"id": BIZ, "name": "First Light Church", "type": "church", "settings": {}, "stripe_account_id": None}


def _request(path="/my", host="first-light.mysolutionist.app", cookies=""):
    headers = [(b"host", host.encode())]
    if cookies:
        headers.append((b"cookie", cookies.encode()))
    return Request({"type": "http", "method": "GET", "path": path, "raw_path": path.encode(), "query_string": b"",
                    "scheme": "https", "server": (host, 443), "client": ("127.0.0.1", 1), "root_path": "",
                    "headers": headers})


def _at_once(n):
    """A read that returns `value` only once all n reads are in flight."""
    gate = threading.Barrier(n, timeout=5)

    def read(value):
        def fn(*a, **k):
            gate.wait()
            return value
        return fn
    return read


# ── 1. the church and its site: one read ─────────────────────────────

def test_the_church_and_its_site_are_one_read(monkeypatch):
    asked = []

    def get(path, **k):
        asked.append(path)
        return [{"slug": "first-light", "business_id": BIZ, "site_config": {}, "business": dict(BUSINESS)}]
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    church = mp._church_for_request(_request())
    assert len(asked) == 1 and asked[0].startswith("/business_sites?slug=eq.first-light")
    assert "business:businesses(id,name,type,settings,stripe_account_id)" in asked[0]
    assert church == {"business": BUSINESS, "site": {"slug": "first-light", "business_id": BIZ, "site_config": {}}}


def test_a_custom_domain_finds_its_church_the_same_way(monkeypatch):
    asked = []

    def get(path, **k):
        asked.append(path)
        return [{"slug": "first-light", "business_id": BIZ, "site_config": {"custom_domain": "firstlight.org"},
                 "business": dict(BUSINESS)}]
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    church = mp._church_for_request(_request(host="www.firstlight.org"))
    assert len(asked) == 1 and "site_config->>custom_domain=eq.firstlight.org" in asked[0]
    assert church["business"]["id"] == BIZ


@pytest.mark.parametrize("row", [
    None,                                                                             # the read failed
    [],                                                                               # no such site
    [{"slug": "x", "business_id": BIZ, "site_config": {"offline": True}, "business": dict(BUSINESS)}],
    [{"slug": "x", "business_id": BIZ, "site_config": {}, "business": None}],         # church gone
])
def test_no_church_is_no_church(monkeypatch, row):
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **k: row)
    assert mp._church_for_request(_request()) is None


# ── 2. the space and the Lead tab, at once ───────────────────────────

@pytest.fixture
def app(monkeypatch):
    """member_portal.serve for one signed-in member, every read faked."""
    import church_follow_up as cfu
    import giving_router
    who = {"me": dict(ME), "preview": False}
    monkeypatch.setattr(mp, "_church_for_request", lambda req: {"business": dict(BUSINESS), "site": {"slug": "first-light"}})
    monkeypatch.setattr(mp, "portal_active", lambda b: True)
    monkeypatch.setattr(mp, "_session_for", lambda req, church: {
        "claims": {}, "people": [who["me"]], "me": who["me"], "preview": who["preview"]})
    monkeypatch.setattr(cfu, "is_church", lambda b: True)
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: False)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **k: [])
    return who


def _serve(path, cookies=""):
    return asyncio.run(mp.serve(_request(path, cookies=cookies), path))


def _lead_reads(monkeypatch, *, leaders=None, parent=False, roles=(), led=()):
    import church_follow_up as cfu
    import group_lead
    import member_spaces as msp
    read = _at_once(4)
    monkeypatch.setattr(msp, "leader_rows", read(leaders or {}))
    monkeypatch.setattr(msp, "has_children", read(parent))
    monkeypatch.setattr(cfu, "roles_for", read(list(roles) if roles is not None else None))
    monkeypatch.setattr(group_lead, "led_groups", read(list(led) if led is not None else None))


def test_the_space_and_the_lead_tab_are_read_at_once(app, monkeypatch):
    _lead_reads(monkeypatch, roles=[{"id": "r1", "role": "deacon"}])
    html = _serve("/my/prayer").body.decode()
    assert 'href="/my/lead"' in html


@pytest.mark.parametrize("roles, led, tab", [
    ([{"id": "r1"}], [], True),            # a church role
    ([], [{"id": "g1", "name": "Sisters"}], True),   # leads a group, no role
    (None, [{"id": "g1", "name": "Sisters"}], True),  # the roles read failed; still leads a group
    ([], [], False),                        # leads nothing
    (None, None, False),                    # both reads failed
])
def test_who_gets_the_lead_tab_is_unchanged(app, monkeypatch, roles, led, tab):
    _lead_reads(monkeypatch, roles=roles, led=led)
    assert ('href="/my/lead"' in _serve("/my/prayer").body.decode()) is tab


def test_the_owners_preview_never_reads_roles(app, monkeypatch):
    import church_follow_up as cfu
    import group_lead
    import member_spaces as msp
    app["preview"] = True
    read = _at_once(2)
    monkeypatch.setattr(msp, "leader_rows", read({}))
    monkeypatch.setattr(msp, "has_children", read(False))

    def never(*a, **k):
        raise AssertionError("the preview read roles")
    monkeypatch.setattr(cfu, "roles_for", never)
    monkeypatch.setattr(group_lead, "led_groups", never)
    assert 'href="/my/lead"' not in _serve("/my/prayer").body.decode()


def test_a_teen_reads_nothing_for_spaces_or_roles(app, monkeypatch):
    import church_follow_up as cfu
    import group_lead
    import member_spaces as msp
    app["me"] = dict(TEEN)

    def never(*a, **k):
        raise AssertionError("read for a teen")
    for mod, name in ((msp, "leader_rows"), (msp, "has_children"), (cfu, "roles_for"), (group_lead, "led_groups")):
        monkeypatch.setattr(mod, name, never)
    resp = _serve("/my/prayer")
    assert resp.status_code == 200 and 'href="/my/lead"' not in resp.body.decode()


def test_in_the_kids_space_there_is_no_lead_tab(app, monkeypatch):
    import member_spaces as msp
    _lead_reads(monkeypatch, parent=True, roles=[{"id": "r1"}])
    seen = {}
    real = msp.resolve_async

    async def spy(*a, **k):
        seen["ctx"] = await real(*a, **k)
        return seen["ctx"]
    monkeypatch.setattr(msp, "resolve_async", spy)
    _serve("/my/prayer", cookies=f"{msp.COOKIE}=kids")
    assert seen["ctx"]["space"] == "kids"
    assert 'href="/my/lead"' not in _serve("/my/prayer", cookies=f"{msp.COOKIE}=kids").body.decode()


def test_resolve_and_resolve_async_agree(monkeypatch):
    import member_spaces as msp
    for leaders, parent, wanted in (({}, False, ""), ({"youth": {"space": "youth"}}, False, "youth"),
                                    ({}, True, "kids"), ({"kids": {"space": "kids"}}, False, "youth")):
        monkeypatch.setattr(msp, "leader_rows", lambda b, c, v=leaders: v)
        monkeypatch.setattr(msp, "has_children", lambda b, c, v=parent: v)
        for who in (ME, TEEN, {"id": "x", "name": "No Birthday"}):
            assert asyncio.run(msp.resolve_async(BIZ, who, wanted)) == msp.resolve(BIZ, who, wanted)


# ── 3. Home, Connect and Watch read their parts at once ──────────────

def test_home_reads_everything_at_once(app, monkeypatch):
    import church_checkin as cc
    import live_router as lr
    import member_portal_church as mpc
    import member_portal_devotionals as mpd
    import member_portal_sermons as mps
    import reading_plans as rp
    _no_lead(monkeypatch)
    read = _at_once(7)
    monkeypatch.setattr(mpc, "upcoming_for", read([]))
    monkeypatch.setattr(mpc, "groups_for", read({"mine": [], "open": []}))
    monkeypatch.setattr(mps, "load_library", read({"sermons": [], "series": []}))
    monkeypatch.setattr(lr, "current", read({}))
    monkeypatch.setattr(rp, "read_days", read(set()))
    monkeypatch.setattr(cc, "card", read({"state": "off"}))
    extras = read(("", None, None))

    async def home_extras(*a, **k):
        return await asyncio.to_thread(extras)
    monkeypatch.setattr(mpd, "home_extras", home_extras)
    monkeypatch.setattr(rp, "current", lambda biz: {"key": "x"})
    monkeypatch.setattr(rp, "today_for", lambda biz: {"day": 3, "of": 30, "label": "John 3", "href": "/my/bible",
                                                      "title": "The Gospels", "key": "x", "start": "2026-10-18"})
    resp = _serve("/my")
    assert resp.status_code == 200 and "John 3" in resp.body.decode()


def test_connect_reads_the_groups_and_the_leaders_room_at_once(app, monkeypatch):
    import member_portal_church as mpc
    import member_portal_classes as mcl
    import member_portal_messaging as mpm
    _no_lead(monkeypatch)
    monkeypatch.setattr(mcl, "classes_on", lambda b: False)
    monkeypatch.setattr(mpm, "turned_on", lambda b: True)
    read = _at_once(2)
    sisters = {"id": "55555555-5555-5555-5555-555555555555", "name": "Sisters in the City", "leaders": []}
    monkeypatch.setattr(mpc, "groups_for", read({"mine": [sisters], "open": []}))
    monkeypatch.setattr(mpm, "in_leaders_room", read(True))
    resp = _serve("/my/groups")
    assert resp.status_code == 200 and 'href="/my/groups/leaders"' in resp.body.decode()


def test_connect_shows_no_leaders_room_when_the_groups_didnt_load(app, monkeypatch):
    import member_portal_church as mpc
    import member_portal_classes as mcl
    import member_portal_messaging as mpm
    _no_lead(monkeypatch)
    monkeypatch.setattr(mcl, "classes_on", lambda b: False)
    monkeypatch.setattr(mpm, "turned_on", lambda b: True)
    monkeypatch.setattr(mpc, "groups_for", lambda b, me: None)
    monkeypatch.setattr(mpm, "in_leaders_room", lambda b, c: True)
    html = _serve("/my/groups").body.decode()
    assert "Groups couldn" in html and 'href="/my/groups/leaders"' not in html


def test_watch_reads_the_sermons_live_and_whats_next_at_once(app, monkeypatch):
    import live_router as lr
    import member_portal_church as mpc
    import member_portal_sermons as mps
    _no_lead(monkeypatch)
    read = _at_once(3)
    monkeypatch.setattr(mps, "load_library", read({"sermons": [], "series": []}))
    monkeypatch.setattr(lr, "current", read({}))
    monkeypatch.setattr(mpc, "upcoming_for", read([]))
    assert _serve("/my/sermons").status_code == 200


def test_a_sermons_own_page_still_reads_the_library(app, monkeypatch):
    import member_portal_sermons as mps
    _no_lead(monkeypatch)
    asked = []
    monkeypatch.setattr(mps, "load_library", lambda b: asked.append(b) or {"sermons": [], "series": []})
    resp = _serve("/my/sermons/44444444-4444-4444-4444-444444444444")
    assert asked == [BIZ] and resp.status_code in (200, 303)


def _no_lead(monkeypatch):
    import church_follow_up as cfu
    import group_lead
    import member_spaces as msp
    monkeypatch.setattr(msp, "leader_rows", lambda b, c: {})
    monkeypatch.setattr(msp, "has_children", lambda b, c: False)
    monkeypatch.setattr(cfu, "roles_for", lambda b, c: [])
    monkeypatch.setattr(group_lead, "led_groups", lambda b, c: [])
