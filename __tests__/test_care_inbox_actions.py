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


OWNER = "44444444-4444-4444-4444-444444444444"
ASSOC = "55555555-5555-5555-5555-555555555555"
STRANGER = "66666666-6666-6666-6666-666666666666"


class Fake:
    def __init__(self, request=None, fail=(), seats=None, note_author=OWNER):
        self.request = request if request is not None else {
            "id": REQ, "status": "new", "prayed_at": None, "status_changed_at": None,
            "assigned_to": None}
        self.fail = set(fail)
        self.seats = seats if seats is not None else {ASSOC: "member"}
        self.note_author = note_author
        self.calls = []

    def get(self, path):
        self.calls.append(("GET", path, None))
        table, _, query = path.partition("?")
        table = table.strip("/")
        if table in self.fail or (table + ":new" in self.fail and "prayed_at" in path):
            return None
        if table == "businesses":
            return [{"id": BIZ, "owner_id": OWNER}]
        if table == "business_users":
            rows = [{"user_id": u, "role": r, "invited_email": f"{r}@church.test"}
                    for u, r in self.seats.items()]
            if "user_id=eq." in query:
                uid = query.split("user_id=eq.", 1)[1].split("&", 1)[0]
                rows = [x for x in rows if x["user_id"] == uid]
            return rows
        if table == "ministry_care_requests":
            if query.startswith("id=eq."):
                return [self.request] if self.request else []
            if "assigned_to=eq." in query:
                uid = query.split("assigned_to=eq.", 1)[1].split("&", 1)[0]
                if str(self.request.get("assigned_to")) != uid:
                    return []
            return [dict(self.request, created_at="2026-10-12T15:00:00Z",
                         submission={"prayer_request": "For my mother"})]
        if table == "ministry_care_notes":
            if query.startswith("id=eq."):
                return [{"request_id": REQ, "author_id": self.note_author}]
            return [{"id": NOTE, "request_id": REQ, "body": "Called her Tuesday",
                     "created_at": "2026-10-13T10:00:00Z", "author_id": OWNER}]
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
        {"id": NOTE, "body": "Called her Tuesday", "created_at": "2026-10-13T10:00:00Z",
         "author_id": OWNER}]


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
    who = {"id": OWNER}
    app.dependency_overrides[require_user] = lambda: SimpleNamespace(id=who["id"])
    return TestClient(app), who


def _as(c, who, uid):
    who["id"] = uid
    return c


def test_someone_with_no_seat_cannot_see_or_act(client, fake):
    c, who = client
    f = fake()
    _as(c, who, STRANGER)
    assert c.get(f"/intake/private-care/{BIZ}").status_code == 403
    assert c.patch(f"/intake/private-care/{BIZ}/{REQ}", json={"status": "closed"}).status_code == 403
    assert c.post(f"/intake/private-care/{BIZ}/{REQ}/notes", json={"body": "hi"}).status_code == 403
    assert c.delete(f"/intake/private-care/{BIZ}/notes/{NOTE}").status_code == 403
    assert not any(m in ("PATCH", "POST", "DELETE") for m, _, _ in f.calls)


def test_the_owner_can_act(client, fake):
    c, _ = client
    fake()
    r = c.patch(f"/intake/private-care/{BIZ}/{REQ}", json={"prayed": True})
    assert r.status_code == 200 and r.json()["request"]["prayed_at"]
    r = c.post(f"/intake/private-care/{BIZ}/{REQ}/notes", json={"body": "Called"})
    assert r.status_code == 200 and r.json()["note"]["body"] == "Called"


def test_the_owner_sees_everything_and_the_team(client, fake):
    c, _ = client
    fake()
    j = c.get(f"/intake/private-care/{BIZ}").json()
    assert j["scope"] == "all" and len(j["requests"]) == 1
    assert j["team"] == [{"user_id": ASSOC, "email": "member@church.test", "role": "member"}]


# ─── handing a request to a teammate ─────────────────────────────────

def test_the_owner_hands_a_request_to_a_teammate(client, fake):
    c, _ = client
    f = fake()
    r = c.patch(f"/intake/private-care/{BIZ}/{REQ}", json={"assigned_to": ASSOC})
    assert r.status_code == 200 and r.json()["request"]["assigned_to"] == ASSOC
    body = f.calls[-1][2]
    assert body["assigned_to"] == ASSOC and body["assigned_by"] == OWNER and body["assigned_at"]


def test_only_a_teammate_on_this_church_can_be_handed_one(client, fake):
    c, _ = client
    f = fake()
    r = c.patch(f"/intake/private-care/{BIZ}/{REQ}", json={"assigned_to": STRANGER})
    assert r.status_code == 400
    assert not any(m == "PATCH" for m, _, _ in f.calls)


def test_the_owner_takes_a_request_back(client, fake):
    c, _ = client
    f = fake(request={"id": REQ, "status": "new", "prayed_at": None,
                      "status_changed_at": None, "assigned_to": ASSOC})
    r = c.patch(f"/intake/private-care/{BIZ}/{REQ}", json={"assigned_to": None})
    assert r.status_code == 200
    assert f.calls[-1][2]["assigned_to"] is None


def test_leaving_assigned_to_out_leaves_it_alone(client, fake):
    c, _ = client
    f = fake(request={"id": REQ, "status": "new", "prayed_at": None,
                      "status_changed_at": None, "assigned_to": ASSOC})
    c.patch(f"/intake/private-care/{BIZ}/{REQ}", json={"status": "reviewed"})
    assert "assigned_to" not in f.calls[-1][2]


def test_a_teammate_sees_only_what_was_handed_to_them(client, fake):
    c, who = client
    f = fake(request={"id": REQ, "status": "new", "prayed_at": None,
                      "status_changed_at": None, "assigned_to": ASSOC})
    _as(c, who, ASSOC)
    j = c.get(f"/intake/private-care/{BIZ}").json()
    assert j["scope"] == "assigned" and len(j["requests"]) == 1 and j["team"] == []
    listing = next(p for m, p, _ in f.calls if p.startswith("/ministry_care_requests?business_id"))
    assert f"assigned_to=eq.{ASSOC}" in listing


def test_a_teammate_with_nothing_handed_to_them_sees_nothing(client, fake):
    c, who = client
    fake()  # unassigned
    _as(c, who, ASSOC)
    assert c.get(f"/intake/private-care/{BIZ}").json()["requests"] == []


def test_a_teammate_acts_on_their_request(client, fake):
    c, who = client
    fake(request={"id": REQ, "status": "new", "prayed_at": None,
                  "status_changed_at": None, "assigned_to": ASSOC})
    _as(c, who, ASSOC)
    assert c.patch(f"/intake/private-care/{BIZ}/{REQ}", json={"prayed": True}).status_code == 200
    r = c.post(f"/intake/private-care/{BIZ}/{REQ}/notes", json={"body": "Visited"})
    assert r.status_code == 200 and r.json()["note"]["author_id"] == ASSOC


def test_a_teammate_cannot_touch_a_request_not_handed_to_them(client, fake):
    c, who = client
    f = fake()  # unassigned
    _as(c, who, ASSOC)
    assert c.patch(f"/intake/private-care/{BIZ}/{REQ}", json={"prayed": True}).status_code == 404
    assert c.post(f"/intake/private-care/{BIZ}/{REQ}/notes", json={"body": "x"}).status_code == 404
    assert not any(m in ("PATCH", "POST") for m, _, _ in f.calls)


def test_a_teammate_cannot_reassign(client, fake):
    c, who = client
    f = fake(request={"id": REQ, "status": "new", "prayed_at": None,
                      "status_changed_at": None, "assigned_to": ASSOC})
    _as(c, who, ASSOC)
    assert c.patch(f"/intake/private-care/{BIZ}/{REQ}", json={"assigned_to": None}).status_code == 403
    assert not any(m == "PATCH" for m, _, _ in f.calls)


def test_a_teammate_removes_only_their_own_note(client, fake):
    c, who = client
    assigned = {"id": REQ, "status": "new", "prayed_at": None,
                "status_changed_at": None, "assigned_to": ASSOC}
    f = fake(request=assigned, note_author=OWNER)
    _as(c, who, ASSOC)
    assert c.delete(f"/intake/private-care/{BIZ}/notes/{NOTE}").status_code == 404
    assert not any(m == "DELETE" for m, _, _ in f.calls)
    f = fake(request=assigned, note_author=ASSOC)
    assert c.delete(f"/intake/private-care/{BIZ}/notes/{NOTE}").status_code == 200
    assert f.calls[-1][1].endswith(f"&author_id=eq.{ASSOC}")
