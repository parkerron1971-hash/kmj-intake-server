# __tests__/test_kids_router.py
#
# Families and children (kids_router.py). Pins:
#   1. seats: member+ reads and edits families; a viewer or a stranger
#      gets nothing; medical and custody notes are manager+ to read AND
#      write (a member sees only THAT there is a note); deleting is manager+
#   2. another church's family, child or person is refused
#   3. all or nothing: a family whose parent can't be linked, and a child
#      whose allergy can't be saved, are rolled back, never half-saved
#   4. a stale child edit is refused (409), not written over
#   5. a failed read is "unavailable" (503), never "no access" or empty

import pathlib
import sys
import urllib.parse
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import kids_router as kr
from auth_supabase import AuthedUser, require_user

BIZ = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
OWNER = "aaaaaaaa-0000-0000-0000-000000000001"
MANAGER = "aaaaaaaa-0000-0000-0000-000000000002"
MEMBER = "aaaaaaaa-0000-0000-0000-000000000003"
VIEWER = "aaaaaaaa-0000-0000-0000-000000000004"
STRANGER = "aaaaaaaa-0000-0000-0000-000000000005"
PARENT = "cccccccc-0000-0000-0000-000000000001"
OTHER_PARENT = "cccccccc-0000-0000-0000-000000000002"

_CASCADE = {"households": [("household_adults", "household_id"), ("children", "household_id"),
                           ("household_pickups", "household_id")],
            "children": [("child_care_notes", "child_id")]}
_KEY = {"child_care_notes": "child_id"}


class Store:
    """A small in-memory PostgREST: eq/in filters, upserts, cascades."""

    def __init__(self):
        self.t = {"businesses": [{"id": BIZ, "owner_id": OWNER}, {"id": OTHER, "owner_id": STRANGER}],
                  "business_users": [
                      {"business_id": BIZ, "user_id": MANAGER, "status": "active", "role": "manager"},
                      {"business_id": BIZ, "user_id": MEMBER, "status": "active", "role": "member"},
                      {"business_id": BIZ, "user_id": VIEWER, "status": "active", "role": "viewer"}],
                  "contacts": [{"id": PARENT, "business_id": BIZ, "name": "Ana Rivers", "email": "ana@x.test", "phone": ""},
                               {"id": OTHER_PARENT, "business_id": OTHER, "name": "Zed", "email": "", "phone": ""}],
                  "households": [], "household_adults": [], "children": [], "household_pickups": [],
                  "child_care_notes": []}
        self.fail = set()
        self.clock = 0

    def _split(self, path):
        table, _, qs = path.lstrip("/").partition("?")
        return table, urllib.parse.parse_qsl(qs, keep_blank_values=True)

    def _match(self, row, params):
        for k, v in params:
            if k in ("select", "order", "limit", "on_conflict"):
                continue
            op, _, val = v.partition(".")
            if op == "eq" and str(row.get(k)) != val:
                return False
            if op == "in" and str(row.get(k)) not in val.strip("()").split(","):
                return False
        return True

    def _stamp(self):
        self.clock += 1
        return f"2026-09-29T20:00:{self.clock:02d}+00:00"

    def get(self, path):
        table, params = self._split(path)
        if table in self.fail:
            return None
        return [dict(r) for r in self.t[table] if self._match(r, params)]

    def post(self, path, body, prefer=None):
        table, params = self._split(path)
        if table in self.fail:
            return None
        conflict = dict(params).get("on_conflict")
        if conflict:
            keys = conflict.split(",")
            for r in self.t[table]:
                if all(str(r.get(k)) == str(body.get(k)) for k in keys):
                    r.update(body)
                    return [dict(r)]
        row = {"created_at": self._stamp(), "updated_at": self._stamp(), **body}
        if table not in ("household_adults",) and _KEY.get(table, "id") == "id":
            row.setdefault("id", str(uuid.uuid4()))
        self.t[table].append(row)
        return [dict(row)]

    def patch(self, path, body):
        table, params = self._split(path)
        if table in self.fail:
            return None
        out = []
        for r in self.t[table]:
            if self._match(r, params):
                r.update(body)
                if "updated_at" in body:
                    r["updated_at"] = self._stamp()
                out.append(dict(r))
        return out

    def delete(self, path):
        table, params = self._split(path)
        if table in self.fail:
            return False
        gone = [r for r in self.t[table] if self._match(r, params)]
        self.t[table] = [r for r in self.t[table] if r not in gone]
        for r in gone:
            for child_table, col in _CASCADE.get(table, []):
                self.delete(f"/{child_table}?{col}=eq.{r['id']}")
        return True


@pytest.fixture
def store(monkeypatch):
    s = Store()
    monkeypatch.setattr(kr.sb_clients, "sb_get_as_service", s.get)
    monkeypatch.setattr(kr.sb_clients, "sb_post_as_service", s.post)
    monkeypatch.setattr(kr.sb_clients, "sb_patch_as_service", s.patch)
    monkeypatch.setattr(kr.sb_clients, "sb_delete_as_service", s.delete)
    return s


def client(user_id):
    app = FastAPI()
    app.include_router(kr.router)
    app.dependency_overrides[require_user] = lambda: AuthedUser(id=user_id, email=None, role="authenticated")
    return TestClient(app)


def family(store, as_user=OWNER, **child):
    c = client(as_user)
    fam = c.post("/kids/families", json={"business_id": BIZ, "name": "The Rivers family",
                                          "adults": [{"contact_id": PARENT, "relationship": "parent"}]})
    assert fam.status_code == 200, fam.text
    fid = fam.json()["family"]["id"]
    kid = c.post("/kids/children", json={"business_id": BIZ, "household_id": fid, "first_name": "Mia",
                                         "last_name": "Rivers", "room": "Preschool", **child})
    assert kid.status_code == 200, kid.text
    return fid, kid.json()["child"]


# ── 1. seats ─────────────────────────────────────────────────────────

def test_member_reads_family_but_only_learns_that_private_notes_exist(store):
    family(store, allergies="Peanuts", medical="Inhaler in bag", custody="Never release to J. Doe")
    body = client(MEMBER).get(f"/kids/families?business_id={BIZ}").json()
    kid = body["families"][0]["children"][0]
    assert body["can_see_private"] is False
    assert kid["allergies"] == "Peanuts"
    assert kid["has_private_notes"] is True
    assert "medical" not in kid and "custody" not in kid
    assert body["families"][0]["adults"][0]["name"] == "Ana Rivers"
    assert "Preschool" in body["rooms"]


def test_manager_reads_medical_and_custody(store):
    family(store, medical="Inhaler in bag", custody="Never release to J. Doe")
    kid = client(MANAGER).get(f"/kids/families?business_id={BIZ}").json()["families"][0]["children"][0]
    assert kid["medical"] == "Inhaler in bag" and kid["custody"] == "Never release to J. Doe"


@pytest.mark.parametrize("who", [VIEWER, STRANGER])
def test_viewer_and_stranger_see_nothing(store, who):
    family(store)
    r = client(who).get(f"/kids/families?business_id={BIZ}")
    assert r.status_code == 403
    assert "Mia" not in r.text


def test_member_cannot_write_medical_or_custody(store):
    fid, kid = family(store)
    c = client(MEMBER)
    r = c.patch(f"/kids/children/{kid['id']}", json={"business_id": BIZ, "custody": "x"})
    assert r.status_code == 403
    r = c.post("/kids/children", json={"business_id": BIZ, "household_id": fid, "first_name": "Leo", "medical": "x"})
    assert r.status_code == 403
    assert [k["first_name"] for k in store.t["children"]] == ["Mia"]
    # …but can record an allergy at the welcome desk.
    r = c.patch(f"/kids/children/{kid['id']}", json={"business_id": BIZ, "allergies": "Dairy"})
    assert r.status_code == 200
    assert store.t["child_care_notes"][0]["allergies"] == "Dairy"


def test_deleting_is_for_managers(store):
    fid, kid = family(store)
    assert client(MEMBER).delete(f"/kids/children/{kid['id']}?business_id={BIZ}").status_code == 403
    assert client(MEMBER).delete(f"/kids/families/{fid}?business_id={BIZ}").status_code == 403
    assert client(MANAGER).delete(f"/kids/families/{fid}?business_id={BIZ}").status_code == 200
    assert store.t["children"] == [] and store.t["household_adults"] == []


def test_member_can_mark_a_child_inactive(store):
    _, kid = family(store)
    r = client(MEMBER).patch(f"/kids/children/{kid['id']}", json={"business_id": BIZ, "active": False})
    assert r.status_code == 200 and r.json()["child"]["active"] is False


# ── 2. another church ────────────────────────────────────────────────

def test_other_churchs_records_are_refused(store):
    fid, kid = family(store)
    stranger = client(STRANGER)  # owns OTHER
    assert stranger.patch(f"/kids/children/{kid['id']}",
                          json={"business_id": OTHER, "allergies": "x"}).status_code == 404
    assert stranger.post("/kids/children", json={"business_id": OTHER, "household_id": fid,
                                                  "first_name": "X"}).status_code == 404
    assert stranger.post(f"/kids/families/{fid}/pickups",
                         json={"business_id": OTHER, "name": "X"}).status_code == 404
    # A church can't link another church's person as a parent.
    r = client(OWNER).put(f"/kids/families/{fid}/adults/{OTHER_PARENT}", json={"business_id": BIZ})
    assert r.status_code == 404
    assert len(store.t["household_adults"]) == 1


def test_bad_ids_are_rejected_before_any_query(store):
    r = client(OWNER).get("/kids/families?business_id=not-a-uuid")
    assert r.status_code == 400


# ── 3. all or nothing ────────────────────────────────────────────────

def test_family_with_unlinkable_parent_is_rolled_back(store):
    r = client(OWNER).post("/kids/families", json={"business_id": BIZ, "name": "Half",
                                                    "adults": [{"contact_id": OTHER_PARENT}]})
    assert r.status_code == 404
    assert store.t["households"] == []


def test_child_whose_allergy_cannot_save_is_rolled_back(store):
    fid, _ = family(store)
    store.fail.add("child_care_notes")
    r = client(OWNER).post("/kids/children", json={"business_id": BIZ, "household_id": fid,
                                                    "first_name": "Leo", "allergies": "Peanuts"})
    assert r.status_code == 503
    assert [k["first_name"] for k in store.t["children"]] == ["Mia"]


# ── 4. stale edits ───────────────────────────────────────────────────

def test_stale_child_edit_is_refused(store):
    _, kid = family(store)
    c = client(OWNER)
    first = c.patch(f"/kids/children/{kid['id']}", json={"business_id": BIZ, "grade": "K",
                                                         "expected_updated_at": kid["updated_at"]})
    assert first.status_code == 200
    late = c.patch(f"/kids/children/{kid['id']}", json={"business_id": BIZ, "grade": "1",
                                                        "expected_updated_at": kid["updated_at"]})
    assert late.status_code == 409
    assert store.t["children"][0]["grade"] == "K"
    # Notes-only edits are guarded too, and move the stamp forward.
    fresh = first.json()["child"]["updated_at"]
    ok = c.patch(f"/kids/children/{kid['id']}", json={"business_id": BIZ, "allergies": "Eggs",
                                                      "expected_updated_at": fresh})
    assert ok.status_code == 200 and ok.json()["child"]["updated_at"] != fresh
    stale = c.patch(f"/kids/children/{kid['id']}", json={"business_id": BIZ, "allergies": "None",
                                                         "expected_updated_at": fresh})
    assert stale.status_code == 409
    assert store.t["child_care_notes"][0]["allergies"] == "Eggs"


# ── 5. failed reads ──────────────────────────────────────────────────

@pytest.mark.parametrize("table", ["business_users", "children", "child_care_notes", "contacts"])
def test_failed_read_is_unavailable_not_empty(store, table):
    family(store)
    store.fail.add(table)
    r = client(MEMBER).get(f"/kids/families?business_id={BIZ}")
    assert r.status_code == 503


def test_birthday_in_the_future_is_refused(store):
    fid, _ = family(store)
    r = client(OWNER).post("/kids/children", json={"business_id": BIZ, "household_id": fid,
                                                    "first_name": "Leo", "birthdate": "2099-01-01"})
    assert r.status_code == 400
