"""Board & minutes (church_board.py). Kevin 2026-10-27, on the Church Office
Prototypes ("Board & minutes" tab): "lets go with your list". Elders and
deacons meet, decide and need a record.

Pins:
  * who: the owner and admins see every board; anyone else only the boards
    they sit on (a member row with their login), a viewer reads; a login on
    no board, an office manager included, is refused
  * another church's boards, meetings, items, people and files are
    unreachable
  * the quorum: a majority is more than half (4 of 7, 4 of 6), a count is
    that number; it's worked out live as people are marked, and excused
    isn't present
  * an open item (tabled, or a follow-up) carries into the next meeting
    once: not twice for two presses, and not again into a later meeting
  * a decision keeps its motion, who moved and seconded, the vote and the
    result, and the log finds it across years by any of its words
  * approving minutes: only a draft, at a later meeting of the same board,
    and approved minutes no longer change
  * "Send minutes for approval" emails the board's own members and no one
    else
  * the switch, and the tables before their migration: status false,
    routes 503, nothing 500
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_board as cb  # noqa: E402
import sb_clients  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from test_church_roles import FakeDB, _cmp  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
NAMES = ("owner", "admin", "deacon", "elder", "clerk", "watcher", "stranger", "other_owner")
PEOPLE = {n: AuthedUser(id=f"00000000-0000-4000-8000-{i:012d}", email=f"{n}@lovecity.org", role="authenticated")
          for i, n in enumerate(NAMES, start=1)}
ID = {n: u.id for n, u in PEOPLE.items()}
T0 = datetime(2026, 10, 27, 16, 0, 0, tzinfo=timezone.utc)
HAYES = "cccccccc-0000-4000-8000-000000000001"     # a deacon with a login (deacon@lovecity.org)
MOORE = "cccccccc-0000-4000-8000-000000000002"     # a deacon, no login
PRICE = "cccccccc-0000-4000-8000-000000000003"     # a deacon with no email
REED = "cccccccc-0000-4000-8000-000000000004"      # an elder with a login (elder@lovecity.org)
ELLIS = "cccccccc-0000-4000-8000-000000000005"     # a member, on no board
THEIRS = "cccccccc-0000-4000-8000-000000000006"    # another church's person


def _ilike(row, col, val):
    """PostgREST's ilike with * wildcards (the shared fake matches exactly)."""
    v = row.get(col)
    if v is None:
        return False
    import fnmatch
    want = val.replace("\\_", "_").replace("\\%", "%").replace("\\\\", "\\").lower()
    return fnmatch.fnmatchcase(str(v).lower(), want) if "*" in want else str(v).lower() == want


class BoardDB(FakeDB):
    """The six tables' defaults and their unique rules, ilike wildcards, and
    the tables missing before the migration."""

    DEFAULTS = {
        "church_boards": {"quorum_count": None, "sort": 0, "archived": False},
        "church_board_members": {"contact_id": None, "user_id": None, "title": "", "active": True},
        "church_board_meetings": {"title": "", "place": "", "video_url": "", "status": "planned", "sent_at": None,
                                  "sent_count": 0, "approved_at": None, "approved_by": None, "approved_in": None},
        "church_board_items": {"notes": "", "minutes": "", "status": "open", "documents": [], "carried_from": None,
                               "follow_up_member": None, "follow_up_due": None, "task_id": None, "position": 0},
        "church_board_decisions": {"moved_by": None, "seconded_by": None, "votes_for": 0, "votes_against": 0,
                                   "votes_abstain": 0},
    }

    def _match(self, row, filters):
        plain = []
        for f in filters:
            if f[0] == "or":
                if not any(_ilike(row, c, v) if o == "ilike" else _cmp(row, c, o, v) for c, o, v in f[1]):
                    return False
            elif f[1] == "ilike":
                if not _ilike(row, f[0], f[2]):
                    return False
            else:
                plain.append(f)
        return super()._match(row, plain)

    def _gone(self, path):
        return self.missing and path.lstrip("/").split("?")[0].startswith("church_board")

    def get(self, path, **kw):
        return None if self._gone(path) else super().get(path, **kw)

    def post(self, path, body, prefer=None, **kw):
        if self._gone(path):
            return None
        table = path.lstrip("/").split("?")[0]
        rows = [{**self.DEFAULTS.get(table, {}), **r} for r in (body if isinstance(body, list) else [body])]
        have = self.t.setdefault(table, [])
        if table == "church_board_items":
            taken = {h.get("carried_from") for h in have if h.get("carried_from")}
            fresh = [r for r in rows if not r.get("carried_from") or r["carried_from"] not in taken]
            if len(fresh) < len(rows) and "on_conflict=carried_from" not in path:
                return None    # 409: carried once
            rows = fresh
        if table == "church_board_attendance":
            out = []
            for r in rows:
                old = next((h for h in have if h["meeting_id"] == r["meeting_id"] and h["member_id"] == r["member_id"]), None)
                if old is None:
                    have.append(dict(r))
                    out.append(dict(r))
                elif "merge-duplicates" in (prefer or ""):
                    old.update(r)
                    out.append(dict(old))
            return out
        if table == "tasks" and self.tasks_fail:
            return None
        return super().post(path, rows, prefer=prefer, **kw) if rows else []

    def patch(self, path, body, **kw):
        return None if self._gone(path) else super().patch(path, body, **kw)


@pytest.fixture
def db(monkeypatch):
    seats = (("admin", "admin"), ("deacon", "member"), ("elder", "member"), ("clerk", "manager"),
             ("watcher", "viewer"))
    fake = BoardDB(
        businesses=[{"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": ID["owner"],
                     "settings": {"practitioner_name": "Pastor Kevin"}},
                    {"id": OTHER, "name": "Grace Chapel", "type": "ministry", "owner_id": ID["other_owner"], "settings": {}}],
        business_users=[{"business_id": BIZ, "user_id": ID[n], "role": r, "status": "active",
                         "invited_email": f"{n}@lovecity.org"} for n, r in seats],
        contacts=[{"id": HAYES, "business_id": BIZ, "name": "Darnell Hayes", "email": "deacon@lovecity.org"},
                  {"id": MOORE, "business_id": BIZ, "name": "Dana Moore", "email": "dana.moore@example.com"},
                  {"id": PRICE, "business_id": BIZ, "name": "Noah Price", "email": None},
                  {"id": REED, "business_id": BIZ, "name": "Pastor Reed", "email": "elder@lovecity.org"},
                  {"id": ELLIS, "business_id": BIZ, "name": "Mia Ellis", "email": "mia@example.com"},
                  {"id": THEIRS, "business_id": OTHER, "name": "Grace Member", "email": "grace@example.com"}],
        church_boards=[], church_board_members=[], church_board_meetings=[], church_board_items=[],
        church_board_attendance=[], church_board_decisions=[], tasks=[],
    )
    fake.missing = False
    fake.tasks_fail = False
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    monkeypatch.setenv("CHURCH_BOARD", "on")
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", "owner@lovecity.org")
    monkeypatch.setattr(cb, "_now", lambda: T0)
    monkeypatch.setattr(cb, "_tz", lambda biz: ZoneInfo("America/New_York"))
    monkeypatch.setattr(cb, "owner_email", lambda uid: "owner@lovecity.org")
    fake.sent = []
    monkeypatch.setattr(cb, "deliver", lambda biz, to, name, subject, text, key: fake.sent.append(
        {"to": to, "name": name, "subject": subject, "text": text, "key": key}))
    return fake


def client(name) -> TestClient:
    app = FastAPI()
    app.include_router(cb.router)
    app.dependency_overrides[require_user] = lambda: PEOPLE[name]
    return TestClient(app)


def ok(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()


def _board(name="Deacons", **kw):
    return ok(client("owner").post("/church/board/boards", json={"business_id": BIZ, "name": name, **kw}))["board"]


def _member(board_id, who="owner", **kw):
    return client(who).post(f"/church/board/boards/{board_id}/members", json={"business_id": BIZ, **kw})


def _deacons():
    """The Deacons: Hayes (a login), Moore, Price; a majority quorum."""
    b = _board("Deacons")
    ids = {k: ok(_member(b["id"], contact_id=c))["member"]["id"] for k, c in (("hayes", HAYES), ("moore", MOORE),
                                                                              ("price", PRICE))}
    return b, ids


def _meeting(board_id, when="2026-10-29T23:00:00+00:00", who="owner", **kw):
    return ok(client(who).post("/church/board/meetings", json={"business_id": BIZ, "board_id": board_id,
                                                               "starts_at": when, **kw}))


def _item(meeting_id, title, who="owner", **kw):
    got = ok(client(who).post(f"/church/board/meetings/{meeting_id}/items", json={"business_id": BIZ, "title": title, **kw}))
    return next(i for i in got["items"] if i["id"] == got["item"])


def _patch_item(item_id, who="owner", **kw):
    return client(who).patch(f"/church/board/items/{item_id}", json={"business_id": BIZ, **kw})


def _status(meeting_id, status, who="owner"):
    return client(who).patch(f"/church/board/meetings/{meeting_id}", json={"business_id": BIZ, "status": status})


def _mark(meeting_id, member_id, status, who="owner"):
    return client(who).put(f"/church/board/meetings/{meeting_id}/attendance",
                           json={"business_id": BIZ, "member_id": member_id, "status": status})


def _decide(item_id, who="owner", **kw):
    body = {"business_id": BIZ, "motion": "Accept Northside Roofing's bid of $18,400.", "votes_for": 5,
            "votes_against": 1, "votes_abstain": 0, "result": "carried", **kw}
    return client(who).post(f"/church/board/items/{item_id}/decisions", json=body)


# ─── Who ──────────────────────────────────────────────────────────────

def test_a_login_on_no_board_is_refused_even_an_office_manager(db):
    b, _ = _deacons()
    for who in ("clerk", "watcher"):
        assert client(who).get(f"/church/board?business_id={BIZ}").status_code == 403
        assert ok(client(who).get(f"/church/board/status?business_id={BIZ}"))["enabled"] is False
    # A deacon with a login, linked by their email when the owner added them as a person.
    st = ok(client("deacon").get(f"/church/board/status?business_id={BIZ}"))
    assert st == {"enabled": True, "manage": False, "member": True, "boards": 1}
    assert [x["name"] for x in ok(client("deacon").get(f"/church/board?business_id={BIZ}"))["boards"]] == ["Deacons"]
    # No seat at all: not even told the church has boards.
    assert client("stranger").get(f"/church/board?business_id={BIZ}").status_code == 404
    assert ok(client("owner").get(f"/church/board/status?business_id={BIZ}"))["manage"] is True


def test_members_see_only_their_board_and_a_viewer_on_it_only_reads(db):
    deacons, ids = _deacons()
    elders = _board("Elders", quorum_kind="count", quorum_count=2)
    ok(_member(elders["id"], contact_id=REED))
    em = _meeting(elders["id"])["meeting"]
    # The elder doesn't see the Deacons, or their meetings.
    page = ok(client("elder").get(f"/church/board?business_id={BIZ}"))
    assert [x["name"] for x in page["boards"]] == ["Elders"]
    dm = _meeting(deacons["id"])["meeting"]
    assert client("elder").get(f"/church/board/meetings/{dm['id']}?business_id={BIZ}").status_code == 404
    assert client("deacon").get(f"/church/board/meetings/{em['id']}?business_id={BIZ}").status_code == 404
    # The deacon writes on their own board, not another's; never sets boards up.
    assert _item(dm["id"], "Van insurance", who="deacon")["title"] == "Van insurance"
    assert client("deacon").post(f"/church/board/meetings/{em['id']}/items",
                                 json={"business_id": BIZ, "title": "Sneaky"}).status_code == 404
    assert client("deacon").post("/church/board/boards", json={"business_id": BIZ, "name": "Mine"}).status_code == 403
    assert _member(deacons["id"], who="deacon", contact_id=ELLIS).status_code == 403
    # A viewer seat on the Deacons reads, and can't change a thing.
    ok(_member(deacons["id"], user_id=ID["watcher"]))
    assert ok(client("watcher").get(f"/church/board/meetings/{dm['id']}?business_id={BIZ}"))["can"]["write"] is False
    assert client("watcher").post(f"/church/board/meetings/{dm['id']}/items",
                                  json={"business_id": BIZ, "title": "Mine"}).status_code == 403
    assert _mark(dm["id"], ids["moore"], "present", who="watcher").status_code == 403


def test_another_church_is_unreachable(db):
    b, ids = _deacons()
    m = _meeting(b["id"])["meeting"]
    it = _item(m["id"], "Roof bids")
    # Their owner, with our ids, under their church or ours.
    for path in (f"/church/board/meetings/{m['id']}?business_id={OTHER}", f"/church/board/meetings/{m['id']}?business_id={BIZ}"):
        assert client("other_owner").get(path).status_code in (403, 404)
    assert client("other_owner").patch(f"/church/board/items/{it['id']}",
                                       json={"business_id": OTHER, "minutes": "x"}).status_code == 404
    assert client("other_owner").post(f"/church/board/boards/{b['id']}/members",
                                      json={"business_id": OTHER, "contact_id": THEIRS}).status_code == 404
    # Our owner can't add their person, or link their files.
    assert _member(b["id"], contact_id=THEIRS).status_code == 400
    assert _patch_item(it["id"], documents=[{"path": f"{OTHER}/general/123-budget.pdf", "name": "Budget"}]).status_code == 400
    assert _patch_item(it["id"], documents=[{"path": f"{BIZ}/../{OTHER}/general/x.pdf"}]).status_code == 400
    got = ok(_patch_item(it["id"], documents=[{"path": f"{BIZ}/general/1730000000000-roof-bids.pdf"}]))
    assert got["items"][0]["documents"] == [{"path": f"{BIZ}/general/1730000000000-roof-bids.pdf", "name": "roof-bids.pdf"}]
    # Nothing of theirs was written.
    assert all(r["business_id"] == BIZ for t in ("church_boards", "church_board_members", "church_board_items")
               for r in db.t[t])


# ─── The quorum ───────────────────────────────────────────────────────

def test_quorum_math():
    assert cb.quorum("majority", None, 7, 4)["needed"] == 4 and cb.quorum("majority", None, 7, 4)["met"]
    assert cb.quorum("majority", None, 7, 3)["met"] is False
    assert cb.quorum("majority", None, 6, 3)["needed"] == 4      # half isn't a majority
    assert cb.quorum("majority", None, 1, 1)["met"]
    assert cb.quorum("majority", None, 0, 0)["met"] is False      # no members, no quorum
    assert cb.quorum("count", 5, 7, 5)["met"] and not cb.quorum("count", 5, 7, 4)["met"]
    assert cb.quorum("count", 9, 7, 7)["met"] is False            # a count the board can't reach
    assert cb.quorum_words("count", 5) == "5 present"


def test_the_quorum_is_live_and_excused_is_not_present(db):
    b, ids = _deacons()
    m = _meeting(b["id"])["meeting"]
    ok(_status(m["id"], "in_progress"))
    q = ok(_mark(m["id"], ids["hayes"], "present"))["quorum"]
    assert (q["present"], q["needed"], q["total"], q["met"]) == (1, 2, 3, False)
    assert ok(_mark(m["id"], ids["price"], "excused"))["quorum"]["met"] is False
    assert ok(_mark(m["id"], ids["moore"], "present", who="deacon"))["quorum"]["met"] is True
    assert ok(_mark(m["id"], ids["moore"], None))["quorum"]["present"] == 1     # a tap undone
    # Ending the meeting marks whoever wasn't marked absent; the roster is settled.
    page = ok(_status(m["id"], "drafted"))
    assert {p["name"]: p["status"] for p in page["roster"]} == {
        "Darnell Hayes": "present", "Dana Moore": "absent", "Noah Price": "excused"}
    # Someone leaving the board later stays in these minutes, not in the next meeting's roster.
    ok(client("owner").patch(f"/church/board/members/{ids['price']}", json={"business_id": BIZ, "active": False}))
    again = ok(client("owner").get(f"/church/board/meetings/{m['id']}?business_id={BIZ}"))
    assert len(again["roster"]) == 3
    nxt = _meeting(b["id"], "2026-11-26T00:00:00+00:00")
    assert {p["name"] for p in nxt["roster"]} == {"Darnell Hayes", "Dana Moore"} and nxt["quorum"]["needed"] == 2


# ─── Carrying forward ─────────────────────────────────────────────────

def test_an_open_item_carries_forward_once(db):
    b, ids = _deacons()
    sep = _meeting(b["id"], "2026-09-24T23:00:00+00:00")["meeting"]
    roof = _item(sep["id"], "Roof bids", notes="Three bids attached.")
    fund = _item(sep["id"], "Benevolence fund limit")
    _item(sep["id"], "Christmas Eve services")
    ok(_patch_item(roof["id"], status="tabled"))
    ok(_patch_item(fund["id"], status="follow_up", follow_up_member=ids["moore"], follow_up_due="2026-10-20"))
    # October's agenda starts with September's two open items.
    oct_ = _meeting(b["id"], "2026-10-29T23:00:00+00:00")
    assert oct_["carried"] == 2
    titles = [i["title"] for i in oct_["items"]]
    assert titles == ["Roof bids", "Benevolence fund limit"]
    carried = oct_["items"][0]["carried_from"]
    assert carried["meeting_id"] == sep["id"] and carried["starts_at"].startswith("2026-09-24")
    assert oct_["items"][1]["follow_up"]["name"] == "Dana Moore"
    # Pressing "Bring in open items" again brings nothing twice.
    again = ok(client("owner").post(f"/church/board/meetings/{oct_['meeting']['id']}/carry", json={"business_id": BIZ}))
    assert again["carried"] == 0 and len(again["items"]) == 2
    # November doesn't take them from September again: October has them.
    nov = _meeting(b["id"], "2026-11-26T00:00:00+00:00")
    assert nov["carried"] == 0 and nov["items"] == []
    # Tabled again in October, the roof goes on to November, once.
    ok(_patch_item(oct_["items"][0]["id"], status="tabled"))
    nov2 = ok(client("owner").post(f"/church/board/meetings/{nov['meeting']['id']}/carry", json={"business_id": BIZ}))
    assert [i["title"] for i in nov2["items"]] == ["Roof bids"]
    assert sum(1 for i in db.t["church_board_items"] if i["title"] == "Roof bids") == 3


# ─── Decisions and the log ────────────────────────────────────────────

def test_a_decision_records_its_vote_and_is_searchable(db):
    b, ids = _deacons()
    old = _meeting(b["id"], "2024-03-14T23:00:00+00:00")["meeting"]
    ok(_decide(_item(old["id"], "Parking lot")["id"], motion="Repave the north lot.", votes_for=3, votes_against=0))
    m = _meeting(b["id"])["meeting"]
    roof = _item(m["id"], "Roof bids")
    page = ok(_decide(roof["id"], moved_by=ids["hayes"], seconded_by=ids["moore"]))
    d = page["items"][0]["decisions"][0]
    assert (d["moved_by_name"], d["seconded_by_name"]) == ("Darnell Hayes", "Dana Moore")
    assert (d["votes_for"], d["votes_against"], d["votes_abstain"], d["result"]) == (5, 1, 0, "carried")
    assert d["decided_on"] == "2026-10-29"          # the meeting's own day, in the church's clock
    assert page["items"][0]["status"] == "done"     # a motion that carried settles an open item
    # The same person can't move and second; a stranger can't do either.
    assert _decide(roof["id"], moved_by=ids["hayes"], seconded_by=ids["hayes"]).status_code == 400
    assert _decide(roof["id"], moved_by="99999999-0000-4000-8000-000000000000").status_code == 400
    assert _decide(roof["id"], result="maybe").status_code == 400
    # "When did we approve the roof?" Any of its words, across years; a word from the motion or the title.
    log = lambda q="", **kw: ok(client("deacon").get(  # noqa: E731
        "/church/board/decisions", params={"business_id": BIZ, "q": q, **kw}))
    assert [x["item_title"] for x in log("roof")["decisions"]] == ["Roof bids"]
    assert [x["item_title"] for x in log("northside roofing")["decisions"]] == ["Roof bids"]
    assert log("roof parking")["decisions"] == []
    assert [x["item_title"] for x in log("REPAVE")["decisions"]] == ["Parking lot"]
    got = log()
    assert [x["item_title"] for x in got["decisions"]] == ["Roof bids", "Parking lot"]
    assert got["years"] == ["2026", "2024"] and got["decisions"][0]["board"] == "Deacons"
    assert [x["item_title"] for x in log(year="2024")["decisions"]] == ["Parking lot"]
    # A tabled motion tables its item, so it carries.
    fund = _item(m["id"], "Benevolence limit")
    assert ok(_decide(fund["id"], motion="Raise the single gift limit to $300.", result="tabled"))["items"][1]["status"] == "tabled"
    # Renaming an item renames it in the log's search.
    ok(_patch_item(roof["id"], title="Sanctuary roof"))
    assert [x["item_title"] for x in log("sanctuary")["decisions"]] == ["Sanctuary roof"]
    # The elders' login sees none of the deacons' decisions.
    elders = _board("Elders")
    ok(_member(elders["id"], contact_id=REED))
    assert ok(client("elder").get("/church/board/decisions", params={"business_id": BIZ, "q": "roof"}))["decisions"] == []


# ─── Approval ─────────────────────────────────────────────────────────

def test_approving_minutes(db):
    b, ids = _deacons()
    sep = _meeting(b["id"], "2026-09-24T23:00:00+00:00")["meeting"]
    it = _item(sep["id"], "Roof bids")
    approve = lambda mid, **kw: client("owner").post(f"/church/board/meetings/{mid}/approve",  # noqa: E731
                                                     json={"business_id": BIZ, **kw})
    assert approve(sep["id"]).status_code == 409             # not drafted yet
    ok(_status(sep["id"], "in_progress"))
    ok(_patch_item(it["id"], minutes="Three bids. Northside is lowest."))
    ok(_status(sep["id"], "drafted"))
    oct_ = _meeting(b["id"], "2026-10-29T23:00:00+00:00")
    # October's page shows September's draft waiting for approval.
    assert [w["id"] for w in oct_["waiting"]] == [sep["id"]]
    # Approved at a later meeting of the same board only.
    elders = _board("Elders")
    em = _meeting(elders["id"], "2026-10-30T23:00:00+00:00")["meeting"]
    assert approve(sep["id"], in_meeting_id=em["id"]).status_code in (400, 404)
    earlier = _meeting(b["id"], "2026-08-27T23:00:00+00:00")["meeting"]
    assert approve(sep["id"], in_meeting_id=earlier["id"]).status_code == 400
    got = ok(approve(sep["id"], in_meeting_id=oct_["meeting"]["id"]))
    assert got["meeting"]["status"] == "approved" and got["meeting"]["approved_in"]["id"] == oct_["meeting"]["id"]
    assert got["can"]["write"] is False
    again = ok(client("owner").get(f"/church/board/meetings/{oct_['meeting']['id']}?business_id={BIZ}"))
    assert again["waiting"] == [] and [a["id"] for a in again["approves"]] == [sep["id"]]
    # Approved minutes no longer change.
    assert _patch_item(it["id"], minutes="Rewritten").status_code == 409
    assert _decide(it["id"]).status_code == 409
    assert _mark(sep["id"], ids["moore"], "present").status_code == 409
    assert _status(sep["id"], "in_progress").status_code == 409
    assert approve(sep["id"]).status_code == 409
    assert client("owner").delete(f"/church/board/meetings/{sep['id']}?business_id={BIZ}").status_code == 409


# ─── Send for approval ────────────────────────────────────────────────

def test_send_for_approval_goes_only_to_the_boards_members(db):
    b, ids = _deacons()
    elders = _board("Elders")
    ok(_member(elders["id"], contact_id=REED))
    ok(_member(b["id"], user_id=ID["admin"], title="Secretary"))     # a login with no person: their sign-in email
    ok(_member(b["id"], contact_id=ELLIS))
    ellis = next(m["id"] for m in db.t["church_board_members"] if m["contact_id"] == ELLIS)
    ok(client("owner").patch(f"/church/board/members/{ellis}", json={"business_id": BIZ, "active": False}))
    m = _meeting(b["id"])["meeting"]
    it = _item(m["id"], "Roof bids")
    send = lambda: client("deacon").post(f"/church/board/meetings/{m['id']}/send", json={"business_id": BIZ})  # noqa: E731
    assert send().status_code == 409                          # planned: there are no minutes yet
    ok(_status(m["id"], "in_progress"))
    ok(_mark(m["id"], ids["hayes"], "present"))
    ok(_patch_item(it["id"], minutes="Three bids came in."))
    ok(_decide(it["id"], moved_by=ids["hayes"], seconded_by=ids["moore"]))
    got = ok(send())
    assert sorted(x["to"] for x in db.sent) == ["admin@lovecity.org", "dana.moore@example.com", "deacon@lovecity.org"]
    assert got["sent"] == 3 and got["no_email"] == ["Noah Price"]
    # Sending ended the meeting: minutes drafted, the rest marked absent.
    assert got["meeting"]["status"] == "drafted" and got["meeting"]["sent_count"] == 1
    mail = db.sent[0]
    assert mail["subject"].startswith("Draft minutes: Deacons, Thursday, October 29, 2026")
    assert "Present: Darnell Hayes." in mail["text"] and "1. Roof bids" in mail["text"]
    assert "Moved by Darnell Hayes, seconded by Dana Moore. For 5, against 1, abstaining 0. Carried." in mail["text"]
    # Never the elders, never someone who left, never a login on no board.
    assert not any(x["to"] in ("elder@lovecity.org", "mia@example.com", "clerk@lovecity.org") for x in db.sent)
    # Sent again: each gets it again, under a new key.
    ok(send())
    assert len(db.sent) == 6 and len({x["key"] for x in db.sent}) == 6


# ─── Follow-ups become tasks ──────────────────────────────────────────

def test_follow_ups_become_tasks_once_handed_to_a_login(db):
    b, ids = _deacons()
    m = _meeting(b["id"])["meeting"]
    van = _item(m["id"], "Van insurance")
    bids = _item(m["id"], "Get a third roof bid")
    ok(_patch_item(van["id"], status="follow_up", follow_up_member=ids["hayes"], follow_up_due="2026-11-05"))
    ok(_patch_item(bids["id"], status="follow_up", follow_up_member=ids["moore"]))
    tasks = lambda: client("owner").post(f"/church/board/meetings/{m['id']}/tasks", json={"business_id": BIZ})  # noqa: E731
    assert ok(tasks())["made"] == 2
    by = {t["title"]: t for t in db.t["tasks"]}
    assert by["Van insurance"]["assigned_to"] == ID["deacon"] and by["Van insurance"]["due_date"] == "2026-11-05"
    assert by["Get a third roof bid (Dana Moore)"]["assigned_to"] is None
    assert all(t["business_id"] == BIZ and t["status"] == "todo" for t in db.t["tasks"])
    assert ok(tasks())["made"] == 0 and len(db.t["tasks"]) == 2


# ─── The switch, and before the migration ─────────────────────────────

def test_the_switch(db, monkeypatch):
    b, _ = _deacons()
    monkeypatch.setenv("CHURCH_BOARD", "owner")
    assert ok(client("owner").get(f"/church/board/status?business_id={BIZ}"))["enabled"] is True
    assert ok(client("deacon").get(f"/church/board/status?business_id={BIZ}"))["enabled"] is False
    assert client("deacon").get(f"/church/board?business_id={BIZ}").status_code == 404
    monkeypatch.setenv("CHURCH_BOARD", "off")
    assert ok(client("owner").get(f"/church/board/status?business_id={BIZ}"))["enabled"] is False
    assert client("owner").get(f"/church/board?business_id={BIZ}").status_code == 404
    monkeypatch.setenv("CHURCH_BOARD", "sideways")      # anything unknown is off
    assert cb.mode() == "off"
    monkeypatch.delenv("CHURCH_BOARD")
    assert cb.mode() == "owner"


def test_before_the_migration_nothing_answers_500(db):
    db.missing = True
    assert ok(client("owner").get(f"/church/board/status?business_id={BIZ}"))["enabled"] is False
    for r in (client("owner").get(f"/church/board?business_id={BIZ}"),
              client("owner").post("/church/board/boards", json={"business_id": BIZ, "name": "Deacons"}),
              client("owner").get("/church/board/decisions", params={"business_id": BIZ, "q": "roof"})):
        assert r.status_code == 503, r.text


def test_a_business_that_isnt_a_church_has_no_board(db):
    db.t["businesses"][0]["type"] = "salon"
    assert ok(client("owner").get(f"/church/board/status?business_id={BIZ}"))["enabled"] is False
    assert client("owner").get(f"/church/board?business_id={BIZ}").status_code == 404
