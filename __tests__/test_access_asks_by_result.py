"""Two older gaps the security review of the person sheet raised
(kmj-intake-server #1918), closed 2026-11-18. Kevin: "everything else, I agree."

  * An id in a PostgREST path. business_access, assert_access, role_of and
    the accountant check put the business id into a path as it arrived. A
    value ending in an encoded "#" made the rest of the query a URL fragment,
    so the filters after it (which user, which status) were dropped. An id
    is now letters, digits, hyphens and underscores, and quoted; anything
    else names no business: the same answer as one that doesn't exist, with
    nothing read.

  * The password, by what a write gives. The Logins & areas route and the
    Duties tab's move gave a login more with no password asked. Those are
    pinned beside their routes (test_church_login_areas.py,
    test_church_duties.py, test_chief_office.py); the sheet's own are in
    test_church_sheet.py.

People and the church here are made up."""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import business_access  # noqa: E402
import business_collaborators_router as bcr  # noqa: E402
import business_users_router as bur  # noqa: E402
import sb_clients  # noqa: E402
from fastapi import HTTPException  # noqa: E402

BIZ = "0a1b2c3d-4e5f-4a6b-8c7d-8e9f0a1b2c3d"
OWNER = "a0000000-0000-4000-8000-000000000001"
SEAT = "a0000000-0000-4000-8000-000000000002"

# What an id must never carry into a path: a fragment, another filter, a
# list, a wildcard, a dot, a space, or nothing at all.
BAD = [BIZ + "#", BIZ + "%23", BIZ + "&select=*", BIZ + "&user_id=neq.x", f"{BIZ},{BIZ}", "in.(a,b)",
       "*", "a.b", "a b", "", "x" * 65, BIZ + "\n", "é"]


@pytest.fixture
def reads(monkeypatch):
    """Every path the service role is asked for; a business and one Manager seat answer."""
    seen = []

    def get(path, **kw):
        seen.append(path)
        if path.startswith("/businesses?id=eq." + BIZ + "&"):
            return [{"id": BIZ, "owner_id": OWNER, "name": "Grace Fellowship"}]
        if path.startswith("/business_users?business_id=eq." + BIZ + "&user_id=eq." + SEAT + "&"):
            return [{"role": "manager"}]
        return []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    return seen


def _user(uid):
    return SimpleNamespace(id=uid, email="someone@example.com", user_metadata={})


def test_a_real_id_still_resolves(reads):
    assert bur.role_of(BIZ, OWNER) == "owner"
    assert bur.role_of(BIZ, SEAT) == "manager"
    assert bur.role_of(BIZ, "a0000000-0000-4000-8000-000000000009") is None
    assert business_access.assert_access(BIZ, _user(SEAT), "manager") == "manager"
    row = asyncio.run(business_access.business_access("viewer")(BIZ, SimpleNamespace(user=_user(SEAT))))
    assert row["id"] == BIZ and row["_caller_role"] == "manager"
    # Short ids the tests of other modules use are ids too: letters, digits, - and _.
    assert bur.safe_id("b1") and bur.safe_id("biz-0000-1111") and bur.safe_id("user_a")


@pytest.mark.parametrize("bad", BAD)
def test_an_id_that_isnt_one_names_no_business_and_nothing_is_read(reads, bad):
    assert not bur.safe_id(bad)
    assert bur.role_of(bad, OWNER) is None
    assert bur.role_of(BIZ, bad) is None or bad == ""      # an empty user id never reaches a path either
    with pytest.raises(HTTPException) as e:
        business_access.assert_access(bad, _user(OWNER), "viewer")
    assert e.value.status_code == 404 and e.value.detail == "business not found"
    with pytest.raises(HTTPException) as e:
        asyncio.run(business_access.business_access("viewer")(bad, SimpleNamespace(user=_user(OWNER))))
    assert e.value.status_code == 404 and e.value.detail == "business not found"
    with pytest.raises(HTTPException) as e:
        bur.require_business_admin(bad, _user(OWNER))
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        bur.require_role(bad, OWNER, "viewer")
    assert e.value.status_code == 403
    assert bcr.is_active_accountant(bad, OWNER) is False
    assert bur.my_role(bad, _user(OWNER)) == {"ok": True, "role": None, "accountant": False}
    # Not one path was asked for with it: the answer is the same as "no such business", with nothing read.
    assert [p for p in reads if "#" in p or bad and bad in p] == []
    assert all(BIZ in p for p in reads), reads


def test_the_owner_and_the_seat_are_quoted_into_the_path(reads):
    bur.role_of(BIZ, SEAT)
    assert reads == [f"/businesses?id=eq.{BIZ}&select=id,owner_id&limit=1",
                     f"/business_users?business_id=eq.{BIZ}&user_id=eq.{SEAT}&status=eq.active&select=role&limit=1"]


def test_a_bad_id_and_an_unknown_business_get_the_same_answer(reads):
    unknown = "0a1b2c3d-4e5f-4a6b-8c7d-000000000000"
    answers = []
    for biz in (unknown, BIZ + "#"):
        with pytest.raises(HTTPException) as e:
            business_access.assert_access(biz, _user(OWNER), "viewer")
        answers.append((e.value.status_code, e.value.detail))
    assert answers[0] == answers[1] == (404, "business not found")


def test_an_invites_token_is_quoted_into_its_path(monkeypatch):
    seen = []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **kw: seen.append(path) or [])
    with pytest.raises(HTTPException) as e:
        bur.accept(bur.AcceptBody(token="abc#&status=eq.active"), _user(OWNER))
    assert e.value.status_code == 404
    assert seen == ["/business_users?token=eq.abc%23%26status%3Deq.active&select=*&limit=1"]


def test_a_level_is_set_only_on_an_active_seat_and_a_failed_save_is_a_503(monkeypatch):
    seen = []

    def patch(path, body, **kw):
        seen.append((path, body))
        return [{"user_id": SEAT, "role": body["role"]}]
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)
    bur.set_level(BIZ, SEAT, "member")
    assert seen == [(f"/business_users?business_id=eq.{BIZ}&user_id=eq.{SEAT}&status=eq.active", {"role": "member"})]
    for level in ("owner", "boss", ""):
        with pytest.raises(HTTPException) as e:
            bur.set_level(BIZ, SEAT, level)
        assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        bur.set_level(BIZ + "#", SEAT, "member")
    assert e.value.status_code == 404
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda path, body, **kw: None)
    with pytest.raises(HTTPException) as e:
        bur.set_level(BIZ, SEAT, "member")
    assert e.value.status_code == 503
    assert len(seen) == 1


def test_no_request_reads_as_locked_never_as_a_pass():
    import ledger_unlock
    with pytest.raises(HTTPException) as e:
        ledger_unlock.require_unlock(None, OWNER, ledger_unlock.SCOPE_ACCESS)
    assert e.value.status_code == 403 and e.value.detail["code"] == "ledger_locked"
    assert e.value.detail["scope"] == "access"
