# __tests__/test_member_portal_groups.py
#
# "My groups" on the member page (member_portal_church.py). Pins:
#   1. a member sees their groups and the current OPEN groups with room;
#      never a closed, full, archived or another church's group, and never
#      who else belongs — only leaders' first names
#   2. joining adds them as a member (not a leader); a closed, full or gone
#      group is refused with its own message; joining twice is harmless
#   3. leaving removes only their own membership; a leader can't leave here
#   4. a failed read is "try again", never "no groups"
#   5. the route: no session → sign in; a malformed id is refused; the
#      redirect carries a code, never a name

import pathlib
import sys
import urllib.parse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import member_portal_church as mpc

BIZ = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
ME = {"id": "c-me", "name": "Ana Rivers", "email": "ana@example.com"}
G_MINE = "aaaaaaaa-0000-0000-0000-000000000001"
G_OPEN = "aaaaaaaa-0000-0000-0000-000000000002"
G_CLOSED = "aaaaaaaa-0000-0000-0000-000000000003"
G_FULL = "aaaaaaaa-0000-0000-0000-000000000004"
G_ARCHIVED = "aaaaaaaa-0000-0000-0000-000000000005"
G_LEAD = "aaaaaaaa-0000-0000-0000-000000000006"
G_THEIRS = "aaaaaaaa-0000-0000-0000-000000000007"


def _params(path):
    table, _, qs = path.lstrip("/").partition("?")
    return table, urllib.parse.parse_qsl(qs, keep_blank_values=True)


class Fake:
    def __init__(self):
        g = lambda gid, biz=BIZ, **k: {"id": gid, "business_id": biz, "name": k.pop("name", gid[-1]), "kind": "small_group",
                                       "description": "", "meets": "Tuesdays, 7 pm", "location": "", "capacity": None,
                                       "open_to_join": True, "active": True, **k}
        self.groups = [g(G_MINE, name="Tuesday Night"), g(G_OPEN, name="Young Adults", capacity=10),
                       g(G_CLOSED, name="Elders", open_to_join=False), g(G_FULL, name="Full One", capacity=1),
                       g(G_ARCHIVED, name="Old", active=False), g(G_LEAD, name="Greeters"),
                       g(G_THEIRS, OTHER, name="Theirs")]
        self.members = [
            {"group_id": G_MINE, "contact_id": "c-me", "business_id": BIZ, "role": "member"},
            {"group_id": G_MINE, "contact_id": "c-lead", "business_id": BIZ, "role": "leader"},
            {"group_id": G_MINE, "contact_id": "c-secret", "business_id": BIZ, "role": "member"},
            {"group_id": G_FULL, "contact_id": "c-x", "business_id": BIZ, "role": "member"},
            {"group_id": G_LEAD, "contact_id": "c-me", "business_id": BIZ, "role": "leader"},
        ]
        self.contacts = {"c-lead": "Marcus Rivers", "c-secret": "Secret Person", "c-x": "X", "c-me": "Ana Rivers"}
        self.fail = set()

    def _match(self, row, params):
        for k, v in params:
            if k in ("select", "order", "limit", "on_conflict"):
                continue
            op, _, val = v.partition(".")
            if op == "eq" and str(row.get(k)).lower() != val.lower():
                return False
            if op == "in" and str(row.get(k)) not in val.strip("()").split(","):
                return False
        return True

    def get(self, path):
        table, params = _params(path)
        if table in self.fail:
            return None
        if table == "groups":
            return [dict(r) for r in self.groups if self._match(r, params)]
        if table == "group_members":
            return [dict(r) for r in self.members if self._match(r, params)]
        if table == "contacts":
            ids = dict(params).get("id", "in.()")[3:].strip("()").split(",")
            return [{"id": i, "name": self.contacts[i]} for i in ids if i in self.contacts]
        return []

    def post(self, path, body, prefer=None):
        if "group_members" in self.fail:
            return None
        if not any(m["group_id"] == body["group_id"] and m["contact_id"] == body["contact_id"] for m in self.members):
            self.members.append(dict(body))
        return [body]

    def delete(self, path):
        table, params = _params(path)
        before = len(self.members)
        self.members = [m for m in self.members if not self._match(m, params)]
        return True


@pytest.fixture
def fake(monkeypatch):
    f = Fake()
    monkeypatch.setattr(mpc.sb_clients, "sb_get_as_service", f.get)
    monkeypatch.setattr(mpc.sb_clients, "sb_post_as_service", f.post)
    monkeypatch.setattr(mpc.sb_clients, "sb_delete_as_service", f.delete)
    return f


# ── 1. what a member sees ────────────────────────────────────────────

def test_member_sees_their_groups_and_open_ones_only(fake):
    data = mpc.groups_for(BIZ, ME)
    assert [g["name"] for g in data["mine"]] == ["Tuesday Night", "Greeters"]
    assert [g["name"] for g in data["open"]] == ["Young Adults"]  # not closed, full, archived or another church's
    mine = data["mine"][0]
    assert mine["leaders"] == ["Marcus"]  # first name only
    assert "Secret" not in str(data)       # nobody else in the group is named


def test_the_page_names_no_other_members(fake):
    html = mpc.render_groups({"name": "First Light"}, None, _req(), mpc.groups_for(BIZ, ME))
    assert "Led by Marcus" in html and "Rivers" not in html and "Secret" not in html
    assert "You lead this group." in html
    # A leader is not offered "Leave" for the group they lead.
    assert html.count('value="leave"') == 1


# ── 2. joining ───────────────────────────────────────────────────────

def test_join_open_group_as_member(fake):
    assert mpc.member_join(BIZ, ME, G_OPEN) == (True, "joined")
    row = next(m for m in fake.members if m["group_id"] == G_OPEN)
    assert row["role"] == "member" and row["contact_id"] == "c-me"
    assert mpc.member_join(BIZ, ME, G_OPEN) == (True, "joined")
    assert sum(1 for m in fake.members if m["group_id"] == G_OPEN) == 1


@pytest.mark.parametrize("gid,code", [(G_CLOSED, "group_closed"), (G_FULL, "group_full"),
                                      (G_ARCHIVED, "group_gone"), (G_THEIRS, "group_gone")])
def test_join_refusals(fake, gid, code):
    assert mpc.member_join(BIZ, ME, gid) == (False, code)
    assert not any(m["group_id"] == gid and m["contact_id"] == "c-me" for m in fake.members)


# ── 3. leaving ───────────────────────────────────────────────────────

def test_leave_removes_only_me(fake):
    assert mpc.member_leave(BIZ, ME, G_MINE) == (True, "left")
    assert [m["contact_id"] for m in fake.members if m["group_id"] == G_MINE] == ["c-lead", "c-secret"]


def test_a_leader_cannot_leave_here(fake):
    assert mpc.member_leave(BIZ, ME, G_LEAD) == (False, "leader")
    assert any(m["group_id"] == G_LEAD and m["contact_id"] == "c-me" for m in fake.members)


# ── 4. failed reads ──────────────────────────────────────────────────

@pytest.mark.parametrize("table", ["groups", "group_members"])
def test_failed_read_is_try_again(fake, table):
    fake.fail.add(table)
    assert mpc.groups_for(BIZ, ME) is None
    html = mpc.render_groups({"name": "First Light"}, None, _req(), None)
    assert "couldn't load" in html


# ── 5. the route ─────────────────────────────────────────────────────

def _req():
    from starlette.requests import Request
    return Request({"type": "http", "query_string": b"", "headers": []})


def _client(monkeypatch, me):
    async def signed_in(request):
        return {"business": {"id": BIZ, "name": "First Light"}}, me, False
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    monkeypatch.setattr(mpc, "_allowed", lambda church, who: True)
    app = FastAPI()
    app.include_router(mpc.router)
    return TestClient(app, follow_redirects=False)


def test_route_joins_and_redirects_with_a_code(fake, monkeypatch):
    r = _client(monkeypatch, ME).post("/my/groups", data={"group_id": G_OPEN, "action": "join"})
    assert r.status_code == 303 and r.headers["location"] == "/my/groups?done=joined"


def test_route_without_a_session_goes_to_sign_in(fake, monkeypatch):
    r = _client(monkeypatch, None).post("/my/groups", data={"group_id": G_OPEN, "action": "join"})
    assert r.headers["location"] == "/my"


def test_route_refuses_a_malformed_id(fake, monkeypatch):
    r = _client(monkeypatch, ME).post("/my/groups", data={"group_id": "x;drop", "action": "join"})
    assert r.headers["location"] == "/my/groups?err=group_gone"
