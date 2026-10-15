"""
test_church_care_counts.py — the Operate overview's Prayer & care card.

GET /church/care-counts serves the numbers church_reads already worked out
for Chief: how many requests are new, reviewed, closed and marked prayed in
the last 90 days, and how long the oldest new one has waited. These pin
the three things that matter about it:

  * who: the owner and staff (manager, admin) only, the same people Chief
    gives these numbers to; member and viewer seats, accountants and
    strangers are refused before anything is read;
  * what: numbers and nothing else, in exactly the documented shape, even
    when a row carries words, names or ids, or a status nobody expected;
  * honesty: a failed read is a 503, never a row of zeros.

And that Chief's own care_counts is unchanged by the care half moving into
care_request_counts.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import business_users_router
import chief_church_actions
import church_reads as C
import church_router
import sb_clients

BIZ = "11111111-1111-1111-1111-111111111111"
OWNER = "00000000-0000-0000-0000-0000000000a1"
STAFF = {role: f"00000000-0000-0000-0000-0000000000b{i}"
         for i, role in enumerate(("admin", "manager", "member", "viewer", "accountant"))}
ACCOUNTANT = "00000000-0000-0000-0000-0000000000c1"   # a bookkeeping collaborator, no seat
STRANGER = "00000000-0000-0000-0000-0000000000d1"

SECRETS = ("Please pray for my sister", "Dana Whitfield", "dana@example.org",
           "contact-42", "req-1", "child-7")


class FakeDB:
    """sb_get_as_service by table name. None for a table = that read failed.
    business_users is filtered by user_id so the real role_of runs."""

    def __init__(self, tables):
        self.tables = tables
        self.calls = []

    def __call__(self, path):
        self.calls.append(path)
        table = path.split("?", 1)[0].strip("/")
        rows = self.tables.get(table, [])
        if rows is None:
            return None
        if table == "business_users" and "user_id=eq." in path:
            uid = path.split("user_id=eq.", 1)[1].split("&", 1)[0]
            rows = [r for r in rows if r.get("user_id") == uid and r.get("status") == "active"]
        return [dict(r) for r in rows]

    def read(self, table):
        return [c for c in self.calls if c.startswith(f"/{table}")]


def _ago(days, hours=1):
    return (datetime.now(timezone.utc) - timedelta(days=days, hours=hours)).isoformat()


def _request(status, days, prayed=False, hours=1, **extra):
    # Rows carry what a real row has (words, ids, a contact) so the tests
    # prove the route never passes them on, whatever the select says.
    return {"id": "req-1", "contact_id": "contact-42", "status": status,
            "created_at": _ago(days, hours), "prayed_at": _ago(0) if prayed else None,
            "submission": {"name": "Dana Whitfield", "email": "dana@example.org",
                           "prayer_request": "Please pray for my sister"}, **extra}


INBOX = [_request("new", 12), _request("new", 5), _request("reviewed", 30, prayed=True),
         _request("closed", 60, prayed=True)]


@pytest.fixture
def api(monkeypatch):
    who = {"user": OWNER}

    def install(care=INBOX, **tables):
        tables.setdefault("businesses", [{"id": BIZ, "owner_id": OWNER, "name": "Grace Church"}])
        tables.setdefault("business_users", [
            {"business_id": BIZ, "user_id": uid, "role": role, "status": "active"}
            for role, uid in STAFF.items()])
        tables.setdefault("business_collaborators", [
            {"business_id": BIZ, "user_id": ACCOUNTANT, "role": "accountant", "status": "active"}])
        tables.setdefault("child_checkins", [{"entry_id": "e1", "child_id": "child-7",
                                              "checked_in_at": _ago(3)}])
        tables["ministry_care_requests"] = care
        fake = FakeDB(tables)
        monkeypatch.setattr(sb_clients, "sb_get_as_service", fake)
        app = FastAPI()
        app.include_router(church_router.router)
        app.dependency_overrides[sb_clients.authed_request] = (
            lambda: SimpleNamespace(user=SimpleNamespace(id=who["user"])))
        client = TestClient(app)

        def get(user=OWNER, business_id=BIZ):
            who["user"] = user
            return client.get(f"/church/care-counts?business_id={business_id}")
        get.db = fake
        return get
    return install


# ─── who may read it ─────────────────────────────────────────────────

def test_the_owner_gets_the_counts(api):
    get = api()
    r = get(OWNER)
    assert r.status_code == 200, r.text
    assert r.json() == {"care": {"new": 2, "reviewed": 1, "closed": 1, "prayed": 2,
                                 "oldest_new_days": 12},
                        "window_days": 90}


@pytest.mark.parametrize("role", ["manager", "admin"])
def test_staff_seats_get_the_counts(api, role):
    get = api()
    r = get(STAFF[role])
    assert r.status_code == 200, r.text
    assert r.json()["care"]["new"] == 2


@pytest.mark.parametrize("user", [STAFF["member"], STAFF["viewer"], STAFF["accountant"],
                                  ACCOUNTANT, STRANGER],
                         ids=["member", "viewer", "accountant-seat", "accountant-collaborator",
                              "stranger"])
def test_everyone_else_is_refused_before_anything_is_read(api, user):
    get = api()
    r = get(user)
    # business_access refuses with the same 404 a stranger gets, so a
    # refusal never confirms which business ids are real.
    assert r.status_code == 404
    assert "care" not in r.text and not any(s in r.text for s in SECRETS)
    assert get.db.read("ministry_care_requests") == []
    assert get.db.read("child_checkins") == []


def test_the_route_admits_exactly_the_roles_chief_gives_care_numbers_to():
    """One rule in two places: if either side moves, this fails."""
    rank = business_users_router._ROLE_RANK
    admitted = {r for r, n in rank.items() if n >= rank[church_router.CARE_MIN_ROLE]}
    assert admitted == chief_church_actions._CARE_ROLES == {"owner", "admin", "manager"}
    assert "accountant" not in rank


# ─── what it says ────────────────────────────────────────────────────

def test_the_answer_is_numbers_in_exactly_the_documented_shape(api):
    # An unexpected status, extra fields and a request with no status at
    # all: none of it may change the shape or reach the app.
    get = api(care=INBOX + [_request("archived", 2, flagged="yes"), _request(None, 1)])
    r = get(OWNER)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"care", "window_days"}
    assert set(body["care"]) == {"new", "reviewed", "closed", "prayed", "oldest_new_days"}
    assert body["window_days"] == 90
    for key, value in body["care"].items():
        assert value is None or type(value) is int, (key, value)
    assert body["care"]["new"] == 3          # a request with no status is new
    assert not any(s in r.text for s in SECRETS + ("archived", "flagged", "submission"))


def test_oldest_new_counts_whole_days_and_only_new_requests(api):
    # The 40-day reviewed request is older but not waiting; it never counts.
    get = api(care=[_request("new", 3), _request("new", 17, hours=6),
                    _request("reviewed", 40)])
    assert get(OWNER).json()["care"]["oldest_new_days"] == 17


def test_oldest_new_is_null_when_nothing_is_new(api):
    get = api(care=[_request("reviewed", 4), _request("closed", 9, prayed=True)])
    care = get(OWNER).json()["care"]
    assert care["new"] == 0 and care["oldest_new_days"] is None
    get = api(care=[])
    assert get(OWNER).json() == {"care": {"new": 0, "reviewed": 0, "closed": 0, "prayed": 0,
                                          "oldest_new_days": None}, "window_days": 90}


def test_it_reads_the_care_inbox_only_never_children(api):
    get = api()
    get(OWNER)
    reads = get.db.read("ministry_care_requests")
    assert len(reads) == 1
    q = reads[0]
    assert f"business_id=eq.{BIZ}" in q
    assert q.split("select=", 1)[1].split("&", 1)[0] == "status,created_at,prayed_at"
    assert "created_at=gte." in q and "+" not in q
    assert get.db.read("child_checkins") == []


# ─── failures are failures ───────────────────────────────────────────

def test_a_failed_read_is_503_not_zeros(api):
    get = api(care=None)
    r = get(OWNER)
    assert r.status_code == 503
    assert r.json()["detail"] == ("Prayer and care numbers couldn't be loaded. "
                                  "Try again in a moment.")
    assert '"new"' not in r.text


@pytest.mark.parametrize("bad", ["not-a-uuid", "1234", "11111111-1111-1111-1111-11111111111Z"])
def test_a_bad_business_id_is_400(api, bad):
    get = api()
    r = get(OWNER, business_id=bad)
    assert r.status_code == 400
    assert r.json()["detail"] == "That business id isn't valid"
    assert get.db.read("ministry_care_requests") == []


# ─── church_reads ────────────────────────────────────────────────────

NOW = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)


def test_care_request_counts_is_the_care_half_of_care_counts(monkeypatch):
    rows = [{"status": "new", "created_at": (NOW - timedelta(days=5)).isoformat(), "prayed_at": None},
            {"status": "reviewed", "created_at": (NOW - timedelta(days=9)).isoformat(),
             "prayed_at": NOW.isoformat()}]
    fake = FakeDB({"ministry_care_requests": rows,
                   "child_checkins": [{"entry_id": "e1",
                                       "checked_in_at": (NOW - timedelta(days=3)).isoformat()}]})
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake)
    alone = C.care_request_counts(BIZ, now=NOW)
    assert alone == {"new": 1, "reviewed": 1, "closed": 0, "prayed": 1, "oldest_new_days": 5}
    assert fake.read("child_checkins") == []
    # Chief's reader: the same care numbers, plus children, in the same
    # order of reads it always made.
    fake.calls.clear()
    assert C.care_counts(BIZ, now=NOW) == {
        "care": alone, "children_checked_in": [{"date": "2026-10-11", "children": 1}]}
    assert [c.split("?", 1)[0] for c in fake.calls] == ["/ministry_care_requests", "/child_checkins"]
    assert fake.calls[0] == (f"/ministry_care_requests?business_id=eq.{BIZ}"
                             "&created_at=gte.2026-07-16T15:00:00Z"
                             "&select=status,created_at,prayed_at&limit=5000")


def test_a_failed_care_read_is_none_in_both_readers(monkeypatch):
    fake = FakeDB({"ministry_care_requests": None, "child_checkins": []})
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake)
    assert C.care_request_counts(BIZ, now=NOW) is None
    assert C.care_counts(BIZ, now=NOW) is None
    fake = FakeDB({"ministry_care_requests": [], "child_checkins": None})
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake)
    assert C.care_request_counts(BIZ, now=NOW) == {"new": 0, "reviewed": 0, "closed": 0,
                                                   "prayed": 0, "oldest_new_days": None}
    assert C.care_counts(BIZ, now=NOW) is None


# ─── the app ─────────────────────────────────────────────────────────

def test_the_endpoint_is_mounted_before_the_catch_all_and_needs_a_sign_in():
    os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
    os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test")
    import kmj_intake_automation

    routes = [(getattr(r, "path", ""), getattr(r, "methods", set()) or set())
              for r in kmj_intake_automation.app.routes]
    paths = [p for p, _ in routes]
    assert ("/church/care-counts", {"GET"}) in routes
    assert paths.index("/church/care-counts") < paths.index("/{path:path}")
    r = TestClient(kmj_intake_automation.app).get(f"/church/care-counts?business_id={BIZ}")
    assert r.status_code in (401, 403)


def test_the_route_is_guarded_by_business_access():
    """The ratchet in test_business_access_ratchet counts this handler as
    guarded because business_access is on its signature."""
    import ownership_sweep
    swept = ownership_sweep.sweep()
    mine = {h["fn"] for h in swept["handlers"] if h["file"] == "church_router.py"}
    assert {"care_counts", "first_time_guests"} <= mine
    assert [h["fn"] for h in swept["unguarded"] if h["file"] == "church_router.py"] == []
