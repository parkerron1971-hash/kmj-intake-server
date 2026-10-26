"""A first-time check-in starts a welcome follow-up (church_first_visit.py).

Kevin, 2026-10-26 ("who sees what" for churches): "yes, a first-time
check-in starts a welcome follow-up." Two writers hand it on: the kids desk
(kids_checkin.do_checkin, every way in), and the office's First time
check-in in Attendance (written from the app, picked up by the follow-up
sweep). One follow-up per family per first visit, for the adult, routed
like a connect card, only while CHURCH_AREAS is on, and never in the way
of the check-in.

The tables are faked in memory below with the PostgREST filters these
modules use, so the reads and writes are the real paths, not mocks."""
from __future__ import annotations

import asyncio
import os
import re
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import church_first_visit as cfv  # noqa: E402
import church_follow_up as cfu  # noqa: E402
import kids_checkin as kc  # noqa: E402
import sb_clients  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402

BIZ = "009e9a2c-3e81-4bfc-a92a-205a8806aa99"
OWNER = "22222222-2222-2222-2222-222222222222"


def _id(prefix: str, n: int) -> str:
    return f"{prefix}-0000-0000-0000-{n:012d}"


PASTOR, ROBERT, ANA, LUIS, GRANDMA, OLD_MEMBER, GUEST, GUEST_SPOUSE = (_id("00000000", i) for i in range(1, 9))
ENTRY, LAST_WEEK, NEXT_WEEK = (_id("eeeeeeee", i) for i in range(1, 4))
HOME, OLD_HOME, GUEST_HOME = (_id("aaaaaaaa", i) for i in range(1, 4))
MIA, LEO, SAM = (_id("cccccccc", i) for i in range(1, 4))

NOW = datetime.now(timezone.utc)
REAL_SPAWN = cfv._spawn


def ago(**kw) -> str:
    return (NOW - timedelta(**kw)).isoformat()


# ─── A small PostgREST, in memory ─────────────────────────────────────

def _split(s: str):
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def _when(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _cmp(row, col, op, val):
    v = row.get(col)
    if op == "not":
        inner_op, _, inner_val = val.partition(".")
        return not _cmp(row, col, inner_op, inner_val)
    if op == "is":
        return v is None if val == "null" else str(v).lower() == val
    if op == "in":
        return str(v) in {x.strip('"') for x in _split(val.strip("()"))}
    if op == "eq":
        return str(v).lower() == val.lower() if isinstance(v, bool) else str(v) == val
    if op == "neq":
        return str(v) != val
    if op == "like":
        return v is not None and re.fullmatch(re.escape(val).replace(r"\*", ".*"), str(v)) is not None
    if v is None:
        return False
    a, b = _when(v), _when(val)
    if a is None or b is None:
        a, b = (v, type(v)(val)) if isinstance(v, (int, float)) else (str(v), val)
    return {"gt": a > b, "lt": a < b, "gte": a >= b, "lte": a <= b}[op]


class FakeDB:
    def __init__(self, **tables):
        self.t = {k: [dict(r) for r in v] for k, v in tables.items()}
        self.gets = []
        self.fail_post = set()

    def _parse(self, path):
        table, _, qs = path.lstrip("/").partition("?")
        filters, limit = [], None
        for part in qs.split("&") if qs else []:
            k, _, v = part.partition("=")
            v = unquote(v)
            if k in ("select", "order", "on_conflict"):
                continue
            if k == "limit":
                limit = int(v)
            elif k == "or":
                filters.append(("or", [tuple(c.split(".", 2)) for c in _split(v.strip("()"))]))
            else:
                op, _, val = v.partition(".")
                filters.append((k, op, val))
        return table, filters, limit

    def _match(self, row, filters):
        for f in filters:
            if f[0] == "or":
                if not any(_cmp(row, c, o, v) for c, o, v in f[1]):
                    return False
            elif not _cmp(row, *f):
                return False
        return True

    def get(self, path, **_):
        self.gets.append(path)
        table, filters, limit = self._parse(path)
        rows = [dict(r) for r in self.t.get(table, []) if self._match(r, filters)]
        return rows[:limit] if limit else rows

    def post(self, path, body, prefer=None, **_):
        table = path.lstrip("/").split("?")[0]
        if table in self.fail_post:
            return None
        out = []
        for b in body if isinstance(body, list) else [body]:
            row = dict(b)
            row.setdefault("id", str(uuid.uuid4()))
            row.setdefault("created_at", cfu._iso(cfu._now()))
            if table == "child_checkins":
                row = {"checked_in_at": cfu._iso(cfu._now()), "checked_out_at": None, "released_to": None, **row}
            if table == "church_follow_ups" and row.get("source_event") and any(
                    r.get("source_event") == row["source_event"] and r["business_id"] == row["business_id"]
                    for r in self.t.get(table, [])):
                return None  # the unique index
            self.t.setdefault(table, []).append(row)
            out.append(dict(row))
        return out

    def patch(self, path, body, **_):
        table, filters, _ = self._parse(path)
        out = []
        for r in self.t.get(table, []):
            if self._match(r, filters):
                r.update(body)
                out.append(dict(r))
        return out

    def delete(self, path, **_):
        table, filters, _ = self._parse(path)
        self.t[table] = [r for r in self.t.get(table, []) if not self._match(r, filters)]
        return True


def _role(contact, role):
    return {"id": str(uuid.uuid4()), "business_id": BIZ, "contact_id": contact, "role": role, "scope": "",
            "status": "active", "invited_at": "2026-10-01T00:00:00+00:00", "answered_at": None}


def _contact(cid, name, created):
    return {"id": cid, "business_id": BIZ, "name": name, "email": f"{name.split()[0].lower()}@example.com",
            "phone": "", "created_at": created}


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB(
        businesses=[{"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": OWNER}],
        business_users=[], events=[], church_role_defs=[], child_care_notes=[],
        contacts=[_contact(PASTOR, "Kevin McCloud", ago(days=400)), _contact(ROBERT, "Robert Hayes", ago(days=300)),
                  _contact(ANA, "Ana Rivers", ago(hours=1)), _contact(LUIS, "Luis Rivers", ago(hours=1)),
                  _contact(GRANDMA, "June Rivers", ago(hours=1)), _contact(OLD_MEMBER, "Pat Long", ago(days=200)),
                  _contact(GUEST, "Dana Guest", ago(minutes=30)), _contact(GUEST_SPOUSE, "Sam Guest", ago(minutes=30))],
        church_leader_roles=[_role(PASTOR, "pastor"), _role(ROBERT, "welcome_lead")],
        church_follow_ups=[], church_follow_up_notes=[], attendance=[], child_checkins=[],
        module_entries=[{"id": ENTRY, "business_id": BIZ, "data": {"title": "Sunday Worship"}},
                        {"id": LAST_WEEK, "business_id": BIZ, "data": {"title": "Sunday Worship"}},
                        {"id": NEXT_WEEK, "business_id": BIZ, "data": {"title": "Sunday Worship"}}],
        # The Rivers registered at the desk today; the Longs have been in
        # Families for months.
        households=[{"id": HOME, "business_id": BIZ, "name": "The Rivers family", "created_at": ago(hours=1)},
                    {"id": OLD_HOME, "business_id": BIZ, "name": "The Long family", "created_at": ago(days=200)}],
        household_adults=[
            {"household_id": HOME, "contact_id": GRANDMA, "business_id": BIZ, "relationship": "grandparent", "created_at": ago(minutes=59)},
            {"household_id": HOME, "contact_id": ANA, "business_id": BIZ, "relationship": "parent", "created_at": ago(minutes=58)},
            {"household_id": HOME, "contact_id": LUIS, "business_id": BIZ, "relationship": "parent", "created_at": ago(minutes=57)},
            {"household_id": OLD_HOME, "contact_id": OLD_MEMBER, "business_id": BIZ, "relationship": "parent", "created_at": ago(days=200)}],
        children=[{"id": MIA, "business_id": BIZ, "household_id": HOME, "first_name": "Mia", "last_name": "Rivers", "room": "Preschool", "active": True},
                  {"id": LEO, "business_id": BIZ, "household_id": HOME, "first_name": "Leo", "last_name": "Rivers", "room": "Nursery", "active": True},
                  {"id": SAM, "business_id": BIZ, "household_id": OLD_HOME, "first_name": "Sam", "last_name": "Long", "room": "K-2", "active": True}],
    )
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    import member_push
    monkeypatch.setattr(member_push, "tell_kids_in", lambda *a, **k: None)
    # The welcome runs in the background in production; inline here so a
    # test reads what it wrote. The non-blocking test puts a thread back.
    monkeypatch.setattr(cfv, "_spawn", lambda fn, *a: fn(*a))
    monkeypatch.setenv("CHURCH_AREAS", "on")
    return fake


def desk(user=OWNER):
    app = FastAPI()
    app.include_router(kc.router)
    app.dependency_overrides[require_user] = lambda: AuthedUser(id=user, email=None, role="authenticated")
    return TestClient(app)


def kids_in(kids, home=HOME, entry=ENTRY, adult=ANA):
    r = desk().post("/kids/checkin", json={"business_id": BIZ, "entry_id": entry, "household_id": home,
                                           "children": [{"child_id": k} for k in kids], "dropped_off_by": adult})
    assert r.status_code == 200, r.text
    return r.json()


def follow_ups(db):
    return db.t["church_follow_ups"]


# ─── The kids desk ────────────────────────────────────────────────────

def test_a_first_time_family_at_the_kids_desk_gets_one_welcome_follow_up_for_the_parent(db):
    kids_in([MIA, LEO])
    [f] = follow_ups(db)
    assert f["contact_id"] == ANA, "the adult who brought them, never a child"
    assert f["leader_contact_id"] == ROBERT and f["leader_role"] == "welcome_lead"
    assert (f["card_key"], f["card_name"], f["path_kind"]) == ("checkin:first", "First check-in", "connect")
    assert f["answers"] == [{"q": "First visit", "a": "First time at Sunday Worship · 2 kids checked in"}]
    assert f["source_event"] == f"first-visit:h:{HOME}"
    assert f["reason"] == "First check-ins go to the Welcome Team lead."
    assert f["status"] == "open" and f["step"] == 0 and f["due_at"]
    [note] = db.t["church_follow_up_notes"]
    assert note["kind"] == "assigned" and note["body"] == "Handed to Robert Hayes. First check-ins go to the Welcome Team lead."


def test_the_next_check_in_starts_none_even_once_the_first_is_finished(db):
    kids_in([MIA, LEO])
    follow_ups(db)[0]["status"] = "done"
    kids_in([MIA, LEO], entry=NEXT_WEEK)
    assert len(follow_ups(db)) == 1


def test_a_family_that_has_been_before_starts_none(db):
    db.t["child_checkins"].append({"id": str(uuid.uuid4()), "business_id": BIZ, "entry_id": LAST_WEEK,
                                   "child_id": MIA, "household_id": HOME, "code": "ACDE",
                                   "checked_in_at": ago(days=7), "checked_out_at": ago(days=7)})
    kids_in([MIA])
    assert follow_ups(db) == []
    # An adult of theirs at another service is the same: they've been.
    db.t["child_checkins"].clear()
    db.t["attendance"].append({"id": str(uuid.uuid4()), "business_id": BIZ, "entry_id": LAST_WEEK,
                               "contact_id": LUIS, "name": "Luis Rivers", "first_time": True, "method": "staff"})
    kids_in([LEO])
    assert follow_ups(db) == []


def test_a_double_tapped_or_resent_check_in_makes_one(db):
    kids_in([MIA])
    kids_in([MIA])            # the same tap, sent again
    kids_in([LEO])            # a sibling checked in a minute later
    assert len(follow_ups(db)) == 1
    # Sent again after the first was finished: the family's receipt still holds.
    follow_ups(db)[0]["status"] = "done"
    assert cfv.welcome_kids(BIZ, ENTRY, "Sunday Worship", HOME, ANA) is None
    assert len(follow_ups(db)) == 1


def test_a_child_only_check_in_goes_to_the_familys_parent_once(db):
    r = desk().post("/kids/checkin", json={"business_id": BIZ, "entry_id": ENTRY, "household_id": HOME,
                                           "children": [{"child_id": MIA}, {"child_id": LEO}]})
    assert r.status_code == 200, r.text
    [f] = follow_ups(db)
    assert f["contact_id"] == ANA, "a parent before the grandparent, the first one added"
    assert f["answers"][0]["a"].endswith("· 2 kids checked in")


def test_the_self_kiosk_and_a_station_hand_it_on_too(db):
    entry = {"id": ENTRY, "data": {"title": "Sunday Worship"}}
    asyncio.run(kc.do_checkin(BIZ, entry, HOME, [(MIA, "")], LUIS, False, "self", None, False))
    [f] = follow_ups(db)
    assert f["contact_id"] == LUIS and f["answers"][0]["a"] == "First time at Sunday Worship · 1 kid checked in"


def test_anyone_in_the_family_already_in_follow_up_keeps_that_one(db):
    assert cfu.on_connect_card(BIZ, LUIS, {"fields": {"visits": "This is my first time"}}, "receipt-9")
    kids_in([MIA], adult=ANA)
    assert [f["card_key"] for f in follow_ups(db)] == ["web:connect_card"]


def test_a_family_the_office_typed_in_from_old_records_is_not_new(db):
    # In Families for months, even with a record added this week.
    db.t["household_adults"].append({"household_id": OLD_HOME, "contact_id": GUEST_SPOUSE, "business_id": BIZ,
                                     "relationship": "parent", "created_at": ago(minutes=5)})
    kids_in([SAM], home=OLD_HOME, adult=GUEST_SPOUSE)
    assert follow_ups(db) == []
    # A family added this week for a long-time member (their record is old).
    db.t["household_adults"].append({"household_id": HOME, "contact_id": OLD_MEMBER, "business_id": BIZ,
                                     "relationship": "parent", "created_at": ago(minutes=5)})
    kids_in([MIA], adult=OLD_MEMBER)
    assert follow_ups(db) == []


@pytest.mark.parametrize("title", ["Community Meal", "GriefShare: grieving together", "Talk with a pastor night"])
def test_the_occasions_name_never_decides_who_gets_them(db, title):
    db.t["module_entries"][0]["data"]["title"] = title
    kids_in([MIA])
    [f] = follow_ups(db)
    assert f["leader_contact_id"] == ROBERT and f["reason"] == "First check-ins go to the Welcome Team lead."
    assert f["answers"][0]["a"] == f"First time at {title} · 1 kid checked in"


def test_with_no_welcome_lead_it_goes_where_any_unheld_card_goes(db):
    db.t["church_leader_roles"] = [r for r in db.t["church_leader_roles"] if r["role"] != "welcome_lead"]
    kids_in([MIA])
    [f] = follow_ups(db)
    assert f["leader_contact_id"] == PASTOR
    assert f["reason"] == "No one holds a role that takes first check-ins yet. It’s with Kevin McCloud until someone is named."
    db.t["church_follow_ups"].clear()
    db.t["church_leader_roles"].clear()
    cfv.welcome_kids(BIZ, ENTRY, "Sunday Worship", HOME, LUIS)
    [f] = follow_ups(db)
    assert f["leader_contact_id"] is None and "with the office" in f["reason"]


def test_not_a_church_starts_nothing(db):
    db.t["businesses"][0]["type"] = "salon"
    kids_in([MIA])
    assert follow_ups(db) == []


@pytest.mark.parametrize("mode", [None, "owner", "off", "ON?"])
def test_switched_off_it_starts_nothing_and_reads_nothing(db, monkeypatch, mode):
    if mode is None:
        monkeypatch.delenv("CHURCH_AREAS", raising=False)
    else:
        monkeypatch.setenv("CHURCH_AREAS", mode)
    started = []
    monkeypatch.setattr(cfv, "_spawn", lambda fn, *a: started.append(fn))
    kids_in([MIA, LEO])
    db.t["attendance"].append({"id": "a1", "business_id": BIZ, "entry_id": ENTRY, "contact_id": GUEST,
                               "name": "Dana Guest", "first_time": True, "method": "staff", "checked_in_at": ago(minutes=5)})
    before = len(db.gets)
    assert asyncio.run(cfv.sweep()) == 0
    assert started == [] and follow_ups(db) == [] and len(db.gets) == before


def test_a_failed_follow_up_never_breaks_the_check_in(db, monkeypatch):
    db.fail_post.add("church_follow_ups")
    out = kids_in([MIA])
    assert out["checkins"] and len(db.t["child_checkins"]) == 1 and follow_ups(db) == []
    # Even a crash inside the welcome stays out of the check-in.
    monkeypatch.setattr(cfv, "welcome_kids", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    kids_in([LEO])
    assert len(db.t["child_checkins"]) == 2
    monkeypatch.setattr(cfv, "after_kids_checkin", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    db.t["child_checkins"].clear()
    kids_in([MIA, LEO])
    assert len(db.t["child_checkins"]) == 2


def test_the_check_in_never_waits_for_the_welcome(db, monkeypatch):
    """The real background thread: the check-in answers while the welcome
    is still reading."""
    gate, ran = threading.Event(), threading.Event()

    def slow(*a):
        gate.wait(5)
        ran.set()
    monkeypatch.setattr(cfv, "_spawn", REAL_SPAWN)
    monkeypatch.setattr(cfv, "welcome_kids", slow)
    kids_in([MIA])
    assert not ran.is_set(), "the check-in answered before the welcome finished"
    gate.set()
    assert ran.wait(5)


# ─── The office's First time ──────────────────────────────────────────

@pytest.fixture
def outbox(monkeypatch):
    sent = {"email": [], "alert": []}

    async def email(biz, to, name, subject, body, key):
        sent["email"].append((to, subject))
        return True

    async def alert(biz_id, title, body, key, person):
        sent["alert"].append(title)
        return True
    monkeypatch.setattr(cfu, "_email", email)
    monkeypatch.setattr(cfu, "_office_alert", alert)
    return sent


def first_time(db, contact, entry=ENTRY, at=None, name="Dana Guest"):
    row = {"id": str(uuid.uuid4()), "business_id": BIZ, "entry_id": entry, "contact_id": contact, "name": name,
           "first_time": True, "method": "staff", "checked_in_at": at or ago(minutes=20)}
    db.t["attendance"].append(row)
    return row


def test_the_offices_first_time_becomes_a_welcome_follow_up_and_the_lead_is_told_that_pass(db, outbox):
    first_time(db, GUEST)
    stats = asyncio.run(cfu.sweep())
    assert stats["first_visits"] == 1
    [f] = follow_ups(db)
    assert f["contact_id"] == GUEST and f["leader_contact_id"] == ROBERT
    assert f["answers"] == [{"q": "First visit", "a": "First time at Sunday Worship"}]
    assert f["source_event"] == f"first-visit:c:{GUEST}"
    assert outbox["email"] == [("robert@example.com", "Dana Guest is yours to follow up")]
    asyncio.run(cfu.sweep())
    assert len(follow_ups(db)) == 1 and len(outbox["email"]) == 1, "once, and told once"


def test_two_adults_of_one_family_marked_first_time_make_one(db):
    db.t["households"].append({"id": GUEST_HOME, "business_id": BIZ, "name": "The Guests", "created_at": ago(minutes=10)})
    for c in (GUEST, GUEST_SPOUSE):
        db.t["household_adults"].append({"household_id": GUEST_HOME, "contact_id": c, "business_id": BIZ,
                                         "relationship": "parent", "created_at": ago(minutes=10)})
    first_time(db, GUEST, at=ago(minutes=21))
    first_time(db, GUEST_SPOUSE, at=ago(minutes=20), name="Sam Guest")
    assert asyncio.run(cfv.sweep()) == 1
    [f] = follow_ups(db)
    assert f["contact_id"] == GUEST and f["source_event"] == f"first-visit:h:{GUEST_HOME}"
    assert asyncio.run(cfv.sweep()) == 0


def test_the_kids_desk_then_the_office_mark_make_one(db):
    kids_in([MIA, LEO], adult=ANA)
    first_time(db, LUIS, name="Luis Rivers")
    assert asyncio.run(cfv.sweep()) == 0
    assert len(follow_ups(db)) == 1


def test_the_sweep_skips_returners_name_only_guests_old_rows_and_other_businesses(db):
    first_time(db, OLD_MEMBER, name="Pat Long")
    db.t["attendance"].append({"id": "prior", "business_id": BIZ, "entry_id": LAST_WEEK, "contact_id": OLD_MEMBER,
                               "name": "Pat Long", "first_time": False, "method": "self", "checked_in_at": ago(days=7)})
    first_time(db, None, name="Walk-in with no record")
    first_time(db, GUEST, at=ago(hours=30))
    db.t["businesses"].append({"id": "33333333-3333-3333-3333-333333333333", "name": "A salon", "type": "salon"})
    db.t["attendance"].append({"id": "salon", "business_id": "33333333-3333-3333-3333-333333333333", "entry_id": ENTRY,
                               "contact_id": GUEST_SPOUSE, "name": "x", "first_time": True, "method": "staff",
                               "checked_in_at": ago(minutes=3)})
    assert asyncio.run(cfv.sweep()) == 0
    assert follow_ups(db) == []


def _failing(db, prefix):
    return lambda path, **k: None if path.lstrip("/").startswith(prefix) else db.get(path)


def test_a_failed_read_never_reads_as_new(db, monkeypatch):
    """A Supabase blip must never hand a family on as new: every read that
    decides it stops the welcome instead."""
    first_time(db, GUEST)
    for prefix in ("household_adults", "church_follow_ups", "attendance?business_id", "businesses"):
        monkeypatch.setattr(sb_clients, "sb_get_as_service", _failing(db, prefix))
        assert asyncio.run(cfv.sweep()) == 0, prefix
    for prefix in ("households", "household_adults", "contacts", "child_checkins", "attendance", "businesses",
                   "church_follow_ups"):
        monkeypatch.setattr(sb_clients, "sb_get_as_service", _failing(db, prefix))
        assert cfv.welcome_kids(BIZ, ENTRY, "Sunday Worship", HOME, ANA) is None, prefix
    assert follow_ups(db) == []


# ─── The pieces ───────────────────────────────────────────────────────

def test_the_line_the_leader_reads():
    assert cfv.line_for("Sunday Worship", 2) == "First time at Sunday Worship · 2 kids checked in"
    assert cfv.line_for("Sunday Worship", 1) == "First time at Sunday Worship · 1 kid checked in"
    assert cfv.line_for("", 0) == "First time"


def test_the_switch_is_read_through_the_module_never_an_alias():
    src = open(os.path.join(ROOT, "church_first_visit.py"), encoding="utf-8").read()
    assert "import church_areas\n" in src and "church_areas.mode() == \"on\"" in src
    assert not re.search(r"from\s+church_areas\s+import", src)
