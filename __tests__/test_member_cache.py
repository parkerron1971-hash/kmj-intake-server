# __tests__/test_member_cache.py
#
# The member app stops repeating itself (member_cache.py, 2026-11-18). Kevin:
# "the members app move slow when send messages in chat, switching from one
# tab to another". Every page read the church on its address (about 140 ms on
# lovecityc.com, measured by the stopwatch), the signed-in member's record,
# and whether they get the Lead and Board tabs, before its own reads. Pins:
#   1. the church is kept a minute per address; a failed read and "no such
#      site" never are; the per-request checks (offline, a sample church's
#      preview) still run; a hit is a copy; the owner's switch forgets it
#   2. the member's record is kept 30 s; a failed read never is; the owner's
#      preview never uses it
#   3. the Lead and Board tabs are kept a minute, a failed read never
#   4. a second page reads less than the first; MEMBER_CACHE=off reads all

import asyncio
import pathlib
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import member_cache
import member_portal as mp
import member_portal_preview as pv
import sb_clients
from starlette.requests import Request

BIZ = "11111111-1111-1111-1111-111111111111"
ME = {"id": "22222222-2222-2222-2222-222222222222", "name": "Ana Reyes", "email": "ana@example.com",
      "birthdate": "1980-05-01"}
BUSINESS = {"id": BIZ, "name": "First Light Church", "type": "church", "is_sample": False,
            "settings": {"member_portal": {"enabled": True}}, "stripe_account_id": None}
HOST = "first-light.mysolutionist.app"


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setenv("CUSTOMER_TOKEN_SECRET", "test-root-secret")
    monkeypatch.delenv("MEMBER_CACHE", raising=False)
    member_cache.forget_all()
    clock = {"t": 1000.0}
    monkeypatch.setattr(member_cache, "_now", lambda: clock["t"])
    yield clock
    member_cache.forget_all()


@pytest.fixture
def db(monkeypatch):
    """Every read, counted. `site` and `people` are what the database holds;
    None makes that read fail."""
    state = SimpleNamespace(site=[{"slug": "first-light", "business_id": BIZ, "site_config": {},
                                   "business": dict(BUSINESS)}],
                            people=[dict(ME)], asked=[])

    def get(path, **k):
        state.asked.append(path.split("?")[0])
        if path.startswith("/business_sites"):
            return state.site
        if path.startswith("/contacts"):
            return state.people
        return []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    state.n = lambda table: sum(1 for p in state.asked if p == table)
    return state


def _request(path="/my", host=HOST, cookies=None):
    headers = [(b"host", host.encode())]
    if cookies:
        headers.append((b"cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()).encode()))
    return Request({"type": "http", "method": "GET", "path": path, "raw_path": path.encode(), "query_string": b"",
                    "scheme": "https", "server": (host, 443), "client": ("127.0.0.1", 1), "root_path": "",
                    "headers": headers})


def _member():
    return {mp.SESSION_COOKIE: mp.mint_session(BIZ, ME["email"], ME["id"])}


# ── 1. the church on an address ───────────────────────────────────────

def test_the_church_is_read_once_a_minute_per_address(db, clean):
    first = mp._church_for_request(_request())
    assert mp._church_for_request(_request("/my/groups")) == first
    assert db.n("/business_sites") == 1
    mp._church_for_request(_request(host="other.mysolutionist.app"))      # another address
    assert db.n("/business_sites") == 2
    clean["t"] += 61                       # a minute
    assert mp._church_for_request(_request()) == first
    assert db.n("/business_sites") == 3


@pytest.mark.parametrize("answer", [
    None,                                                                         # the read failed
    [],                                                                           # no such site
    [{"slug": "x", "business_id": BIZ, "site_config": {}, "business": None}],     # its church is gone
])
def test_a_failed_or_empty_read_is_never_kept(db, answer):
    db.site = answer
    assert mp._church_for_request(_request()) is None
    assert mp._church_for_request(_request()) is None
    assert db.n("/business_sites") == 2


def test_an_offline_site_stays_offline_from_the_kept_row(db, clean):
    db.site[0]["site_config"] = {"offline": True}
    assert mp._church_for_request(_request()) is None
    assert mp._church_for_request(_request()) is None
    assert db.n("/business_sites") == 1
    db.site[0]["site_config"] = {}                      # the owner puts it back online
    assert mp._church_for_request(_request()) is None   # within the minute
    clean["t"] += 61                       # a minute
    assert mp._church_for_request(_request()) is not None


def test_a_sample_churchs_preview_is_checked_on_every_request(db, monkeypatch):
    db.site[0]["business"]["is_sample"] = True
    monkeypatch.setattr(pv, "read_session", lambda value, biz_id, epoch=0: {"cid": "x"} if value == "ok" else None)
    assert mp._church_for_request(_request(cookies={pv.PREVIEW_COOKIE: "ok"})) is not None
    assert mp._church_for_request(_request()) is None                     # no preview cookie
    assert db.n("/business_sites") == 1


def test_a_kept_church_is_a_copy(db):
    a = mp._church_for_request(_request())
    a["business"]["settings"]["member_portal"]["enabled"] = False
    a["site"]["slug"] = "changed"
    b = mp._church_for_request(_request())
    assert b["business"]["settings"]["member_portal"]["enabled"] is True and b["site"]["slug"] == "first-light"


def test_the_owners_switch_forgets_the_church_here(db, monkeypatch):
    mp._church_for_request(_request())
    import business_sites_helpers
    monkeypatch.setattr(mp, "_require_owner", lambda bid, user: dict(BUSINESS))
    monkeypatch.setattr(business_sites_helpers, "ensure_business_site", lambda biz: ({"slug": "first-light"}, False))
    monkeypatch.setattr(mp, "_config_payload", lambda biz, site, user=None: {"ok": True})
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda path, body: [{"id": BIZ}])
    real_get = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **k: (
        [{"settings": dict(BUSINESS["settings"])}] if path.startswith("/businesses") else real_get(path, **k)))
    mp.patch_member_portal_config(BIZ, {"enabled": False}, SimpleNamespace(id="owner-1", email="o@example.com"))
    mp._church_for_request(_request())
    assert db.n("/business_sites") == 2


# ── 2. the signed-in member's record ──────────────────────────────────

def test_the_members_record_is_read_once_in_thirty_seconds(db, clean):
    church = mp._church_for_request(_request())
    for _ in range(3):
        assert mp._session_for(_request(cookies=_member()), church)["me"]["id"] == ME["id"]
    assert db.n("/contacts") == 1
    clean["t"] += 31                       # the promise: out within 30 s
    mp._session_for(_request(cookies=_member()), church)
    assert db.n("/contacts") == 2


def test_a_removed_member_is_out_within_thirty_seconds(db, clean):
    church = mp._church_for_request(_request())
    assert mp._session_for(_request(cookies=_member()), church)["me"]
    db.people = []                                                     # the office removes them
    clean["t"] += 31                       # the promise: out within 30 s
    assert mp._session_for(_request(cookies=_member()), church) is None


def test_a_failed_read_says_try_again_and_is_never_kept(db):
    church = mp._church_for_request(_request())
    db.people = None
    assert mp._session_for(_request(cookies=_member()), church) == {"unavailable": True}
    db.people = [dict(ME)]
    assert mp._session_for(_request(cookies=_member()), church)["me"]["id"] == ME["id"]
    assert db.n("/contacts") == 2


def test_the_owners_preview_never_uses_it(db, monkeypatch):
    church = mp._church_for_request(_request())
    monkeypatch.setattr(mp, "portal_eligible", lambda biz: True)
    loaded = []
    monkeypatch.setattr(pv, "load_contact", lambda biz_id, cid: loaded.append(cid) or dict(ME))
    cookie = {pv.PREVIEW_COOKIE: pv.mint_session(BIZ, ME["id"], "owner-1")}
    for _ in range(2):
        assert mp._session_for(_request(cookies=cookie), church)["preview"] is True
    assert loaded == [ME["id"], ME["id"]] and db.n("/contacts") == 0 and len(member_cache.people) == 0


# ── 3. the Lead and Board tabs ────────────────────────────────────────

def _lead_reads(monkeypatch, roles, led):
    import church_follow_up as cfu
    import church_leader_tasks
    import group_lead
    calls = []
    monkeypatch.setattr(cfu, "roles_for", lambda b, m: calls.append("roles") or roles)
    monkeypatch.setattr(group_lead, "led_groups", lambda b, m: calls.append("led") or led)
    monkeypatch.setattr(church_leader_tasks, "section", lambda biz, m: calls.append("tasks") or None)
    return calls


@pytest.mark.parametrize("roles, led, tab, kept", [
    ([{"id": "r1"}], [], True, True),
    ([], [], False, True),
    (None, [], False, False),         # the roles read failed: asked again next page
    (None, [{"id": "g1"}], True, True),
])
def test_the_lead_tab_is_kept_a_minute_when_known(monkeypatch, clean, roles, led, tab, kept):
    calls = _lead_reads(monkeypatch, roles, led)
    for _ in range(2):
        assert asyncio.run(mp._leads(BIZ, ME["id"], dict(BUSINESS), dict(ME), kept=True)) is tab
    assert calls.count("roles") == (1 if kept else 2)
    clean["t"] += 61
    asyncio.run(mp._leads(BIZ, ME["id"], dict(BUSINESS), dict(ME), kept=True))
    assert calls.count("roles") == (2 if kept else 3)
    asyncio.run(mp._leads(BIZ, ME["id"], dict(BUSINESS), dict(ME)))      # asked plainly: always read
    assert calls.count("roles") == (3 if kept else 4)


def test_the_board_tab_is_kept_a_minute_and_a_failed_read_never(monkeypatch):
    import member_portal_board as mpb
    monkeypatch.setattr(mpb, "tab_on", lambda: True)
    asked = {"n": 0, "fail": True}

    def boards_of(biz_id, person_id):
        asked["n"] += 1
        if asked["fail"]:
            raise RuntimeError("503")
        return {"board-1"}
    monkeypatch.setattr(mpb, "boards_of", boards_of)
    assert asyncio.run(mpb.on_board(dict(BUSINESS), dict(ME), kept=True)) is False
    asked["fail"] = False
    assert asyncio.run(mpb.on_board(dict(BUSINESS), dict(ME), kept=True)) is True
    assert asyncio.run(mpb.on_board(dict(BUSINESS), dict(ME), kept=True)) is True
    assert asked["n"] == 2
    assert asyncio.run(mpb.on_board(dict(BUSINESS), dict(ME))) is True    # asked plainly: always read
    assert asked["n"] == 3


# ── 4. a page, twice ──────────────────────────────────────────────────

@pytest.fixture
def page(monkeypatch, db):
    """member_portal.serve for Ana, with the real church and session
    lookups and every other read answered empty."""
    import church_follow_up as cfu
    import giving_router
    monkeypatch.setattr(cfu, "is_church", lambda b: True)
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: False)
    monkeypatch.setattr(mp, "portal_active", lambda b: True)

    def serve(path="/my/prayer"):
        return asyncio.run(mp.serve(_request(path, cookies=_member()), path))
    return serve


def test_a_second_page_reads_less_than_the_first(page, db):
    assert page().status_code == 200
    first = list(db.asked)
    db.asked.clear()
    assert page("/my/events").status_code == 200
    second = list(db.asked)
    for table in ("/business_sites", "/contacts", "/church_leader_roles", "/group_members"):
        assert first.count(table) >= 1 and second.count(table) == 0, (table, first, second)
    assert len(second) < len(first), (first, second)


def test_switched_off_every_page_reads_everything(page, db, monkeypatch):
    monkeypatch.setenv("MEMBER_CACHE", "off")
    page()
    first = len(db.asked)
    db.asked.clear()
    page()
    assert len(db.asked) == first and db.n("/business_sites") == 1 and db.n("/contacts") == 1
