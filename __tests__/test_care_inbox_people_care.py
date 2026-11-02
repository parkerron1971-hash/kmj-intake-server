"""
test_care_inbox_people_care.py — the People & Care login sees what was shared.

Kevin, 2026-11-01 (Love City's office checkup): the People & Care admin works
the care board, but the inbox showed her only what the owner handed her.
Now a church login whose own areas name People & care also sees the
requests people agreed to share with the prayer team. A request kept
private, or one that needs a pastor, stays with the owner (or the People &
care keeper), who can still hand it over. Admins don't count: "the whole
church" in the menu is not People & care's inbox.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import church_areas
import church_keys
import private_care as P
import sb_clients

BIZ = "11111111-1111-1111-1111-111111111111"
SHARED_REQ = "22222222-2222-2222-2222-222222222222"
PRIVATE_REQ = "22222222-2222-2222-2222-333333333333"
CRISIS_REQ = "22222222-2222-2222-2222-444444444444"
NOTE = "33333333-3333-3333-3333-333333333333"

OWNER = "44444444-4444-4444-4444-444444444444"
CARE = "55555555-5555-5555-5555-555555555555"     # People & Care manager
OFFICE = "66666666-6666-6666-6666-666666666666"   # Office & Leadership manager
ADMIN = "77777777-7777-7777-7777-777777777777"    # the treasurer's Admin seat

AREAS = {CARE: ["people_care", "kids_youth", "groups_classes"],
         OFFICE: ["messages_safety", "office"], ADMIN: None}
ROLES = {CARE: "manager", OFFICE: "manager", ADMIN: "admin"}


def _req(rid, *, shared, crisis=False, to=None):
    return {"id": rid, "status": "new", "prayed_at": None, "status_changed_at": None,
            "assigned_to": to, "contact_id": None, "prayer_team": shared, "needs_pastor": crisis,
            "created_at": "2026-10-30T15:00:00Z", "submission": {"prayer_request": "For my mother"}}


class Fake:
    def __init__(self, requests=None, fail=()):
        self.requests = requests if requests is not None else [
            _req(SHARED_REQ, shared=True), _req(PRIVATE_REQ, shared=False),
            _req(CRISIS_REQ, shared=True, crisis=True)]
        self.fail = set(fail)
        self.calls = []

    def get(self, path):
        self.calls.append(("GET", path, None))
        table, _, query = path.partition("?")
        table = table.strip("/")
        if table == "businesses":
            return [{"id": BIZ, "owner_id": OWNER}]
        if table == "business_users":
            uid = query.split("user_id=eq.", 1)[1].split("&", 1)[0] if "user_id=eq." in query else None
            if uid:
                return [{"role": ROLES[uid]}] if uid in ROLES else []
            return [{"user_id": u, "role": r, "invited_email": f"{u[:4]}@church.test"} for u, r in ROLES.items()]
        if table == "ministry_care_requests":
            if "shared" in self.fail and "or=(" in query:
                return None
            if query.startswith("id=eq."):
                rid = query.split("id=eq.", 1)[1].split("&", 1)[0]
                return [dict(r) for r in self.requests if r["id"] == rid]
            rows = list(self.requests)
            if "or=(" in query:
                uid = query.split("assigned_to.eq.", 1)[1].split(",", 1)[0]
                rows = [r for r in rows if r["assigned_to"] == uid
                        or (r["prayer_team"] is True and r["needs_pastor"] is False)]
            elif "assigned_to=eq." in query:
                uid = query.split("assigned_to=eq.", 1)[1].split("&", 1)[0]
                rows = [r for r in rows if r["assigned_to"] == uid]
            return [dict(r) for r in rows]
        if table == "ministry_care_notes":
            if query.startswith("id=eq."):
                return [{"request_id": SHARED_REQ, "author_id": CARE}]
            return []
        return []

    def patch(self, path, body):
        self.calls.append(("PATCH", path, body))
        rid = path.split("id=eq.", 1)[1].split("&", 1)[0]
        row = next(r for r in self.requests if r["id"] == rid)
        return [dict(row, **body)]

    def post(self, path, body, **kw):
        self.calls.append(("POST", path, body))
        return [dict(body, id=NOTE, created_at="now")]

    def delete(self, path):
        self.calls.append(("DELETE", path, None))
        return True


@pytest.fixture
def fake(monkeypatch):
    def install(**kw):
        f = Fake(**kw)
        monkeypatch.setattr(sb_clients, "sb_get_as_service", f.get)
        monkeypatch.setattr(sb_clients, "sb_patch_as_service", f.patch)
        monkeypatch.setattr(sb_clients, "sb_post_as_service", f.post)
        monkeypatch.setattr(sb_clients, "sb_delete_as_service", f.delete)
        return f
    monkeypatch.setattr(church_keys, "opened", lambda biz, user, area: None)
    monkeypatch.setattr(church_areas, "my_areas",
                        lambda biz, uid, role: {"areas": AREAS.get(str(uid)), "by": "picked"})
    import member_push
    monkeypatch.setattr(member_push, "tell_prayed", lambda *a, **k: None)
    return install


@pytest.fixture
def client():
    os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
    os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import intake_endpoint
    from auth_supabase import require_user
    app = FastAPI()
    app.include_router(intake_endpoint.router)
    who = {"id": CARE}
    app.dependency_overrides[require_user] = lambda: SimpleNamespace(id=who["id"], email=None)
    return TestClient(app), who


def _ids(j):
    return sorted(r["id"] for r in j["requests"])


def test_people_and_care_sees_what_was_shared_and_what_was_handed(client, fake):
    c, _ = client
    f = fake(requests=[_req(SHARED_REQ, shared=True), _req(PRIVATE_REQ, shared=False, to=CARE),
                       _req(CRISIS_REQ, shared=True, crisis=True)])
    j = c.get(f"/intake/private-care/{BIZ}").json()
    assert j["scope"] == "shared" and j["team"] == []
    assert _ids(j) == sorted([SHARED_REQ, PRIVATE_REQ])
    listing = next(p for m, p, _ in f.calls if p.startswith("/ministry_care_requests?business_id"))
    assert f"or=(assigned_to.eq.{CARE},{P.SHARED})" in listing


def test_a_private_request_stays_with_the_pastor(client, fake):
    c, _ = client
    f = fake()
    assert PRIVATE_REQ not in _ids(c.get(f"/intake/private-care/{BIZ}").json())
    assert c.patch(f"/intake/private-care/{BIZ}/{PRIVATE_REQ}", json={"prayed": True}).status_code == 404
    assert c.post(f"/intake/private-care/{BIZ}/{PRIVATE_REQ}/notes", json={"body": "x"}).status_code == 404
    assert not any(m in ("PATCH", "POST") for m, _, _ in f.calls)


def test_a_request_that_needs_a_pastor_is_never_hers_even_if_marked_shared(client, fake):
    c, _ = client
    fake()
    assert CRISIS_REQ not in _ids(c.get(f"/intake/private-care/{BIZ}").json())
    assert c.patch(f"/intake/private-care/{BIZ}/{CRISIS_REQ}", json={"status": "reviewed"}).status_code == 404


def test_she_acts_on_a_shared_request(client, fake):
    c, _ = client
    fake()
    assert c.patch(f"/intake/private-care/{BIZ}/{SHARED_REQ}", json={"prayed": True}).status_code == 200
    r = c.post(f"/intake/private-care/{BIZ}/{SHARED_REQ}/notes", json={"body": "Called her"})
    assert r.status_code == 200 and r.json()["note"]["author_id"] == CARE
    assert c.delete(f"/intake/private-care/{BIZ}/notes/{NOTE}").status_code == 200


def test_she_still_cannot_hand_a_request_to_someone(client, fake):
    c, _ = client
    f = fake()
    r = c.patch(f"/intake/private-care/{BIZ}/{SHARED_REQ}", json={"assigned_to": OFFICE})
    assert r.status_code == 403
    assert not any(m == "PATCH" for m, _, _ in f.calls)


@pytest.mark.parametrize("uid", [OFFICE, ADMIN])
def test_a_login_without_people_and_care_sees_only_what_was_handed(client, fake, uid):
    c, who = client
    f = fake(requests=[_req(SHARED_REQ, shared=True), _req(PRIVATE_REQ, shared=False, to=uid)])
    who["id"] = uid
    j = c.get(f"/intake/private-care/{BIZ}").json()
    assert j["scope"] == "assigned" and _ids(j) == [PRIVATE_REQ]
    assert c.patch(f"/intake/private-care/{BIZ}/{SHARED_REQ}", json={"prayed": True}).status_code == 404
    assert not any("or=(" in p for _, p, _ in f.calls)


def test_a_failed_shared_read_falls_back_to_what_was_handed_never_more(client, fake):
    c, _ = client
    fake(requests=[_req(SHARED_REQ, shared=True), _req(PRIVATE_REQ, shared=False, to=CARE)], fail={"shared"})
    j = c.get(f"/intake/private-care/{BIZ}").json()
    assert j["scope"] == "assigned" and _ids(j) == [PRIVATE_REQ]


def test_off_the_church_switch_nothing_counts_as_shared(client, fake, monkeypatch):
    c, _ = client
    fake()
    monkeypatch.setattr(church_areas, "my_areas", lambda biz, uid, role: None)
    assert c.get(f"/intake/private-care/{BIZ}").json()["scope"] == "assigned"


def test_with_a_care_keeper_named_she_still_sees_the_shared_ones(client, fake, monkeypatch):
    c, _ = client
    fake()
    monkeypatch.setattr(church_keys, "opened", lambda biz, user, area: str(user.id) == OWNER)
    j = c.get(f"/intake/private-care/{BIZ}").json()
    assert j["scope"] == "shared" and _ids(j) == [SHARED_REQ]


def test_the_keeper_and_the_owner_still_see_everything(client, fake, monkeypatch):
    c, who = client
    fake()
    who["id"] = OWNER
    j = c.get(f"/intake/private-care/{BIZ}").json()
    assert j["scope"] == "all" and len(j["requests"]) == 3
    monkeypatch.setattr(church_keys, "opened", lambda biz, user, area: str(user.id) == CARE)
    who["id"] = CARE
    assert c.get(f"/intake/private-care/{BIZ}").json()["scope"] == "all"
