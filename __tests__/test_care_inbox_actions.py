"""
test_care_inbox_actions.py — the Prayer & care inbox acts, not just reads.

Before this the inbox had one route, a GET, so a request's status never
moved off "new". These pin the actions to the same lock as the read: the
owner only, written as the service, every write pinned to the business.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import account_lifecycle
import private_care as P
import sb_clients

BIZ = "11111111-1111-1111-1111-111111111111"
REQ = "22222222-2222-2222-2222-222222222222"
NOTE = "33333333-3333-3333-3333-333333333333"


class Fake:
    def __init__(self, request=None, fail=()):
        self.request = request if request is not None else {
            "id": REQ, "status": "new", "prayed_at": None, "status_changed_at": None}
        self.fail = set(fail)
        self.calls = []

    def get(self, path):
        self.calls.append(("GET", path, None))
        table = path.split("?", 1)[0].strip("/")
        if table in self.fail or (table + ":new" in self.fail and "prayed_at" in path):
            return None
        if table == "ministry_care_requests":
            if "id=eq." in path:
                return [self.request] if self.request else []
            return [dict(self.request, created_at="2026-10-12T15:00:00Z",
                         submission={"prayer_request": "For my mother"})]
        if table == "ministry_care_notes":
            return [{"id": NOTE, "request_id": REQ, "body": "Called her Tuesday",
                     "created_at": "2026-10-13T10:00:00Z", "author_id": "owner"}]
        return []

    def patch(self, path, body):
        self.calls.append(("PATCH", path, body))
        return None if "patch" in self.fail else [dict(self.request, **body)]

    def post(self, path, body, **kw):
        self.calls.append(("POST", path, body))
        return None if "post" in self.fail else [dict(body, id=NOTE, created_at="now")]

    def delete(self, path):
        self.calls.append(("DELETE", path, None))
        return "delete" not in self.fail


@pytest.fixture
def fake(monkeypatch):
    def install(**kw):
        f = Fake(**kw)
        monkeypatch.setattr(sb_clients, "sb_get_as_service", f.get)
        monkeypatch.setattr(sb_clients, "sb_patch_as_service", f.patch)
        monkeypatch.setattr(sb_clients, "sb_post_as_service", f.post)
        monkeypatch.setattr(sb_clients, "sb_delete_as_service", f.delete)
        return f
    return install


def test_requests_come_back_with_their_notes(fake):
    fake()
    out = P.list_requests(BIZ)
    assert out["actions"] is True
    assert out["requests"][0]["notes"] == [
        {"id": NOTE, "body": "Called her Tuesday", "created_at": "2026-10-13T10:00:00Z"}]


def test_the_inbox_still_reads_before_the_migration(fake):
    """New columns missing (400 -> None): the old read still works, with
    the actions switched off rather than the inbox going blank."""
    f = fake(fail={"ministry_care_requests:new"})
    out = P.list_requests(BIZ)
    assert out["actions"] is False and out["requests"][0]["notes"] == []
    assert "prayed_at" not in f.calls[-1][1]


def test_a_status_moves_and_is_stamped(fake):
    f = fake()
    out = P.update_request(BIZ, REQ, status="reviewed")
    assert out["request"]["status"] == "reviewed"
    method, path, body = f.calls[-1]
    assert method == "PATCH" and f"business_id=eq.{BIZ}" in path and f"id=eq.{REQ}" in path
    assert body["status_changed_at"] and body["updated_at"]


def test_an_unknown_status_is_refused_before_any_write(fake):
    f = fake()
    with pytest.raises(HTTPException) as e:
        P.update_request(BIZ, REQ, status="deleted")
    assert e.value.status_code == 400
    assert not any(c[0] == "PATCH" for c in f.calls)


def test_prayed_marks_and_clears(fake):
    f = fake()
    P.update_request(BIZ, REQ, prayed=True)
    assert f.calls[-1][2]["prayed_at"]
    P.update_request(BIZ, REQ, prayed=False)
    assert f.calls[-1][2]["prayed_at"] is None


def test_nothing_to_change_writes_nothing(fake):
    f = fake()
    P.update_request(BIZ, REQ, status="new")
    assert not any(c[0] == "PATCH" for c in f.calls)


def test_another_churchs_request_is_not_found(fake):
    fake(request={})
    with pytest.raises(HTTPException) as e:
        P.update_request(BIZ, REQ, status="closed")
    assert e.value.status_code == 404


def test_a_note_is_saved_to_the_request_in_this_business(fake):
    f = fake()
    out = P.add_note(BIZ, REQ, "  Prayed with her after service  ", "owner-id")
    assert out["note"]["body"] == "Prayed with her after service"
    method, path, body = f.calls[-1]
    assert (method, path) == ("POST", "/ministry_care_notes")
    assert body == {"business_id": BIZ, "request_id": REQ, "author_id": "owner-id",
                    "body": "Prayed with her after service"}


@pytest.mark.parametrize("text", ["", "   ", "x" * (P.NOTE_MAX + 1)])
def test_empty_or_huge_notes_are_refused(fake, text):
    f = fake()
    with pytest.raises(HTTPException) as e:
        P.add_note(BIZ, REQ, text, "owner-id")
    assert e.value.status_code == 400
    assert not any(c[0] == "POST" for c in f.calls)


def test_a_failed_write_says_so(fake):
    fake(fail={"patch", "post"})
    with pytest.raises(HTTPException) as e:
        P.update_request(BIZ, REQ, status="closed")
    assert e.value.status_code == 503
    with pytest.raises(HTTPException) as e:
        P.add_note(BIZ, REQ, "hello", "owner-id")
    assert e.value.status_code == 503


def test_deleting_a_note_is_pinned_to_the_business(fake):
    f = fake()
    assert P.delete_note(BIZ, NOTE) == {"ok": True}
    assert f.calls[-1] == ("DELETE", f"/ministry_care_notes?id=eq.{NOTE}&business_id=eq.{BIZ}", None)


@pytest.mark.parametrize("bad", ["x", "1;drop", f"{REQ}&business_id=eq.other"])
def test_ids_are_uuids_or_refused(fake, bad):
    fake()
    with pytest.raises(HTTPException) as e:
        P.update_request(BIZ, bad, status="closed")
    assert e.value.status_code == 400


def test_notes_follow_the_owner_archive_and_erasure():
    t = account_lifecycle.BUSINESS_CHILD_TABLES
    assert t.index("ministry_care_notes") < t.index("ministry_care_requests")
    assert "ministry_care_notes" in account_lifecycle._IMPORT_SKIP


# ─── the routes ──────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
    os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import intake_endpoint
    from auth_supabase import require_user
    app = FastAPI()
    app.include_router(intake_endpoint.router)
    who = {"id": "owner"}
    app.dependency_overrides[require_user] = lambda: SimpleNamespace(id=who["id"])
    return TestClient(app), who


def test_a_seat_that_is_not_the_owner_cannot_act(client, fake, monkeypatch):
    c, who = client
    f = fake()
    monkeypatch.setattr(P, "require_owner", lambda b, u: (_ for _ in ()).throw(
        HTTPException(403, "owner only")) if u.id != "owner" else None)
    who["id"] = "associate"
    assert c.patch(f"/intake/private-care/{BIZ}/{REQ}", json={"status": "closed"}).status_code == 403
    assert c.post(f"/intake/private-care/{BIZ}/{REQ}/notes", json={"body": "hi"}).status_code == 403
    assert c.delete(f"/intake/private-care/{BIZ}/notes/{NOTE}").status_code == 403
    assert not any(m in ("PATCH", "POST", "DELETE") for m, _, _ in f.calls)


def test_the_owner_can_act(client, fake, monkeypatch):
    c, _ = client
    fake()
    monkeypatch.setattr(P, "require_owner", lambda b, u: None)
    r = c.patch(f"/intake/private-care/{BIZ}/{REQ}", json={"prayed": True})
    assert r.status_code == 200 and r.json()["request"]["prayed_at"]
    r = c.post(f"/intake/private-care/{BIZ}/{REQ}/notes", json={"body": "Called"})
    assert r.status_code == 200 and r.json()["note"]["body"] == "Called"
