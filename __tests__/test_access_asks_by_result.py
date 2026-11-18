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

  * A password confirmed for one business. An access or danger step-up
    names the business it was confirmed for (ledger_unlock); the invite,
    the accountant invite, a reviewer link and an erasure are pinned here,
    the token itself and every other gate in test_step_up_one_business.py.

  * The collaborators' routes took their ids raw too: a collaborator could
    be revoked at another business by its row id.

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


def test_a_logins_level_areas_and_job_are_one_row_write(monkeypatch):
    """church_areas.set_login is the one write of all three (2026-11-18): a
    level saved apart from the areas could leave a login moved down from
    Admin with no areas, which reads as the whole church."""
    import church_areas
    seen = []

    def patch(path, body, **kw):
        seen.append((path, dict(body)))
        return [{"user_id": SEAT, **body}]
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: [{"areas": None, "lane": "treasurer"}] if "select=areas,lane" in path else [])
    path = f"/business_users?business_id=eq.{BIZ}&user_id=eq.{SEAT}&status=eq.active"
    # A level with areas, and the job cleared with it: one PATCH, an active seat only.
    church_areas.set_login(BIZ, SEAT, "manager", areas=["office"], job=None, level="manager")
    assert seen == [(path, {"role": "manager", "areas": ["office"], "lane": None})]
    # A level alone leaves the areas and the job as they are stored.
    seen.clear()
    church_areas.set_login(BIZ, SEAT, "member", level="member")
    assert seen == [(path, {"role": "member"})]
    # Not a level, or nothing to save: a 400 and no write. A save that fails: a 503.
    seen.clear()
    for kw in ({"level": "owner"}, {"level": "boss"}, {}):
        with pytest.raises(HTTPException) as e:
            church_areas.set_login(BIZ, SEAT, "manager", **kw)
        assert e.value.status_code == 400
    assert seen == []
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda path, body, **kw: None)
    with pytest.raises(HTTPException) as e:
        church_areas.set_login(BIZ, SEAT, "member", level="member")
    assert e.value.status_code == 503
    assert not hasattr(bur, "set_level"), "the level has one writer"


def test_no_request_reads_as_locked_never_as_a_pass():
    import ledger_unlock
    with pytest.raises(HTTPException) as e:
        ledger_unlock.require_unlock(None, OWNER, ledger_unlock.SCOPE_ACCESS, BIZ)
    assert e.value.status_code == 403 and e.value.detail["code"] == "ledger_locked"
    assert e.value.detail["scope"] == "access"


# ─── A password confirmed for one business opens nothing at another ───
# (ledger_unlock, 2026-11-18. The token said only "this person, this scope",
# so anyone who owned any business could confirm there and carry it to a
# business where they were a Manager. The routes here; the token itself and
# every other gate in test_step_up_scopes.py.)

ELSEWHERE = "0e0e0e0e-0000-4000-8000-00000000000e"


def _proof(user_id, scope, business_id):
    import ledger_unlock
    os.environ.setdefault("AUDITOR_LINK_SECRET", "test-secret-for-the-access-gates")
    token = ledger_unlock.mint(str(user_id), scope, business_id)["token"]
    return SimpleNamespace(headers={ledger_unlock.UNLOCK_HEADER: token})


def _locked(e, scope):
    return e.value.status_code == 403 and isinstance(e.value.detail, dict) and (
        e.value.detail["code"], e.value.detail["scope"]) == ("ledger_locked", scope)


def test_an_invite_needs_the_password_confirmed_for_this_business(reads):
    for request in (_proof(SEAT, "access", ELSEWHERE), _proof(SEAT, "access", None), _proof(OWNER, "access", BIZ)):
        with pytest.raises(HTTPException) as e:
            asyncio.run(bur.invite(BIZ, bur.InviteBody(email="new@example.com", role="manager"), request,
                                   _user(SEAT)))
        assert _locked(e, "access")
    assert reads == [], "refused before anything was read"
    with pytest.raises(HTTPException) as e:
        asyncio.run(bcr.invite(BIZ, bcr.InviteBody(email="cpa@example.com"), _proof(OWNER, "access", ELSEWHERE),
                               _user(OWNER)))
    assert _locked(e, "access") and reads == []


def test_a_reviewer_link_and_an_erasure_need_it_for_this_business(reads, monkeypatch):
    import auditor_portal as ap
    with pytest.raises(HTTPException) as e:
        ap.mint_link(_proof(OWNER, "access", ELSEWHERE), ap.MintBody(business_id=BIZ), _user(OWNER))
    assert _locked(e, "access")
    posted = []
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda *a, **k: posted.append(a) or [])
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda *a, **k: posted.append(a) or [])
    body = ap.RedactBody(business_id=BIZ, subject_type="contacts", subject_id="c1")
    with pytest.raises(HTTPException) as e:
        ap.redact_subject(_proof(OWNER, "danger", ELSEWHERE), body, _user(OWNER))
    assert _locked(e, "danger") and posted == []


# ─── The collaborators' paths ─────────────────────────────────────────

def test_a_collaborator_is_revoked_only_at_its_own_business(reads, monkeypatch):
    """`POST /collaborators/<row id>%23/revoke?biz=<your own business>` put
    the row id first and raw: everything after it became a URL fragment, so
    the business filter never reached the database, and an owner or Admin
    of one business could revoke another tenant's collaborator."""
    patched = []
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda path, body, **kw: patched.append(path) or [])
    row = "c0c0c0c0-0000-4000-8000-00000000000c"
    assert bcr.revoke(row, BIZ, _user(OWNER)) == {"ok": True}
    assert patched == [f"/business_collaborators?business_id=eq.{BIZ}&id=eq.{row}"]
    patched.clear()
    for bad in (row + "#", row + "%23", row + "&business_id=neq.x", "*", "", f"{row},{row}"):
        with pytest.raises(HTTPException) as e:
            bcr.revoke(bad, BIZ, _user(OWNER))
        assert e.value.status_code == 404
    for bad in BAD:
        with pytest.raises(HTTPException) as e:
            bcr.revoke(row, bad, _user(OWNER))
        assert e.value.status_code == 404 and e.value.detail == "business not found"
    assert patched == [], "nothing was revoked"


@pytest.mark.parametrize("bad", BAD)
def test_the_collaborators_routes_take_no_id_that_isnt_one(reads, bad):
    for call in (lambda: bcr.list_collaborators(bad, _user(OWNER)),
                 lambda: bcr.accountant_overview(bad, _user(OWNER)),
                 lambda: asyncio.run(bcr.invite(bad, bcr.InviteBody(email="cpa@example.com"),
                                                _proof(OWNER, "access", bad), _user(OWNER)))):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 404 and e.value.detail == "business not found"
    assert reads == []


def test_a_collaborators_token_and_an_invites_email_are_quoted_into_their_paths(reads, monkeypatch):
    seen = []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **kw: seen.append(path) or [])
    with pytest.raises(HTTPException) as e:
        bcr.accept(bcr.AcceptBody(token="abc#&status=eq.pending"), _user(OWNER))
    assert e.value.status_code == 404
    assert seen == ["/business_collaborators?token=eq.abc%23%26status%3Deq.pending&select=*&limit=1"]
    # The team invite's "already invited?" read: an email carrying "&" or "#" stays one value.
    seen.clear()
    monkeypatch.setattr(bur, "require_role", lambda *a, **k: "owner")
    import billing_limits
    monkeypatch.setattr(billing_limits, "can_add_seat", lambda *a, **k: {"enforce": False, "allowed": True,
                                                                         "count": 1, "limit": 5})
    monkeypatch.setattr(bur, "match_contact", lambda *a, **k: None)
    monkeypatch.setattr(bur, "make_invite_row", lambda *a, **k: None)
    with pytest.raises(HTTPException):
        asyncio.run(bur.invite(BIZ, bur.InviteBody(email="a@b.example&status=eq.revoked#", role="member"),
                               _proof(OWNER, "access", BIZ), _user(OWNER)))
    asked = [p for p in seen if p.startswith("/business_users?")]
    assert asked == [f"/business_users?business_id=eq.{BIZ}&invited_email=eq.a@b.example%26status%3Deq.revoked%23"
                     "&status=in.(invited,active)&select=id&limit=1"]
