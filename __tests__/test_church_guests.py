"""The Guests room (church_guests.py, 2026-11-20): People › Guests.

Kevin, on the Welcome Path mock: "build". Pinned here, on one made-up church
week in an in-memory PostgREST (every reader runs its real path):
  1. Who a guest is: every door (New here's texts, the member app, the kids
     desk, the website card, a church's own card), counted once from the
     earliest; another church's never; an old guest never "new".
  2. This week: the groups (New this week, Came back, Planning a visit), the
     door, the family line, the texts' steps (sent, skipped, waiting), the
     call (who, when, late, the last try), the facts row.
  3. The next move, in order: a reply waiting, the longest-late call, anyone
     with no one, else calm (and calm says why).
  4. The side cards: texts going out this week (an invite to a guest who
     came back is said to be skipped, by New here's own rule) and what Chief
     did (guests' follow-ups only, newest five, in History's words).
  5. The scorecard: the funnel, connected, by door, by caller (on time, the
     backup), the church's own call window, the periods.
  6. Reads: a page at a time, never more than 1,000 rows; a core read that
     fails is a 503, a side read that fails is null, never "nobody".
  7. Who: the switch, a church, a Manager, People & care's areas.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import business_access as ba  # noqa: E402
import church_guests as cg  # noqa: E402
import guest_path  # noqa: E402
import sb_clients  # noqa: E402

ET = ZoneInfo("America/New_York")
BIZ = "5c000000-0000-4000-8000-000000000001"
OTHER = "5c000000-0000-4000-8000-000000000002"
OWNER = "5a000000-0000-4000-8000-000000000001"


def cid(n: int) -> str:
    return f"5d000000-0000-4000-8000-{n:012d}"


def fid(n: int) -> str:
    return f"5f000000-0000-4000-8000-{n:012d}"


RENEE, MARCUS = cid(1), cid(2)
MARIA, ADA, JORDAN, KIM, TYRELL, HAYES, SAM, LEE, PAT, OLD, OUTSIDER, LONGAGO, BAPTIZED = (
    cid(i) for i in range(10, 23))
NOW = datetime(2026, 11, 23, 10, 30, tzinfo=ET)          # a Monday morning


def at(m, d, hh, mm=0, y=2026):
    return datetime(y, m, d, hh, mm, tzinfo=ET).astimezone(timezone.utc).isoformat()


def z(m, d, hh, mm=0, y=2026):
    """New here's own format (no +00:00)."""
    return datetime(y, m, d, hh, mm, tzinfo=ET).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── A small PostgREST, in memory ─────────────────────────────────────

def _split(s):
    out, depth, cur = [], 0, ""
    for ch in s:
        depth += (ch == "(") - (ch == ")")
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    return out + ([cur] if cur else [])


def _value(row, col):
    """a, a->b->>c: PostgREST's JSON paths (->> reads text)."""
    parts = col.replace("->>", "->").split("->")
    v = row.get(parts[0])
    for p in parts[1:]:
        v = v.get(p) if isinstance(v, dict) else None
    return v


def _cmp(row, col, op, val):
    v = _value(row, col)
    if op == "is":
        return v is None if val == "null" else str(v).lower() == val
    if op == "in":
        return str(v) in set(_split(val.strip("()")))
    if op == "eq":
        return str(v).lower() == val.lower() if isinstance(v, bool) else str(v) == val
    if op == "neq":
        return str(v) != val
    if op == "like":
        import fnmatch
        return v is not None and fnmatch.fnmatchcase(str(v), val)
    if v is None:
        return False
    a, b = str(v), val
    if "T" in a and "T" in b:              # timestamps compare as times, whatever their form
        a, b = cg._parse(a), cg._parse(b)
    return {"gt": a > b, "lt": a < b, "gte": a >= b, "lte": a <= b}[op]


class FakeDB:
    def __init__(self, **tables):
        self.t = {k: [dict(r) for r in v] for k, v in tables.items()}
        self.paths = []
        self.broken = set()

    def get(self, path, **_):
        self.paths.append(path)
        table, _, qs = path.lstrip("/").partition("?")
        if table in self.broken:
            return None
        filters, order, limit, offset = [], [], None, 0
        for part in qs.split("&") if qs else []:
            k, _, v = part.partition("=")
            v = unquote(v)
            if k == "select":
                continue
            if k == "order":
                order = [o.rsplit(".", 1) if "." in o else (o, "asc") for o in v.split(",")]
            elif k == "limit":
                limit = int(v)
            elif k == "offset":
                offset = int(v)
            else:
                op, _, val = v.partition(".")
                filters.append((unquote(k), op, val))
        rows = [dict(r) for r in self.t.get(table, []) if all(_cmp(r, *f) for f in filters)]
        for col, way in reversed(order):
            rows.sort(key=lambda r: str(_value(r, col) or ""), reverse=(way == "desc"))
        rows = rows[offset:]
        return rows[:limit] if limit else rows


# ─── One made-up church week (names are made up) ─────────────────────

def _fu(n, contact, card_key, created, *, step=0, status="open", leader=RENEE, due=None, kind="connect",
        card_name="Card", answers=None, biz=BIZ):
    steps = [{"title": "Reach out", "rule": "within 2 days", "days": 2},
             {"title": "Invite to a next step", "rule": "a class, a group, or a team", "days": 14}]
    if kind == "visit":
        steps = [{"title": "Reach out", "rule": "before their Sunday", "days": 2},
                 {"title": "Greet on Sunday", "rule": "meet them at the door", "days": 7}]
    return {"id": fid(n), "business_id": biz, "contact_id": contact, "card_key": card_key, "card_name": card_name,
            "path_kind": kind, "answers": answers or [], "steps": steps, "step": step, "status": status,
            "leader_contact_id": leader, "due_at": due or created, "assigned_at": created, "created_at": created,
            "done_at": None}


def _note(follow_up, kind, when, author=RENEE, name="Renee Ellis"):
    return {"id": str(uuid.uuid4()), "business_id": BIZ, "follow_up_id": follow_up, "kind": kind,
            "author_kind": "leader", "author_contact_id": author, "author_name": name, "created_at": when}


def _person(contact, name, *, meta=None, created="2026-11-01T12:00:00+00:00", biz=BIZ, phone=""):
    return {"id": contact, "business_id": biz, "name": name, "phone": phone, "metadata": meta or {},
            "created_at": created}


def _sched(contact, step, run_at, status, texted_at, last_run=None, biz=BIZ):
    return {"id": str(uuid.uuid4()), "business_id": biz, "run_at": run_at, "status": status,
            "last_run_at": last_run, "action": {"type": "new_here_text", "step": step, "contact_id": contact,
                                                "phone": "+15555550100", "texted_at": texted_at}}


def _audit(target, summary, when, biz=BIZ, actor="church"):
    return {"id": str(uuid.uuid4()), "business_id": biz, "actor_id": actor, "verb": "church:card_handed",
            "target_type": "church_follow_up", "target_id": target, "summary": summary, "created_at": when}


def church_week():
    nh = lambda texted, **more: {"new_here": {"code": "ABCD2345", "texted_at": texted, "visits": 1, **more}}  # noqa: E731
    contacts = [
        _person(RENEE, "Renee Ellis"), _person(MARCUS, "Marcus Taylor"),
        _person(MARIA, "Maria Lopez", created=at(11, 22, 11)),
        _person(ADA, "Ada Okafor", meta=nh(z(11, 22, 10, 42), card={"first_time": True, "kids": "2"})),
        _person(JORDAN, "Jordan Price", created=at(11, 21, 9)),
        _person(KIM, "Kim Nguyen", meta=nh(z(11, 22, 9, 50), card={"first_time": True, "kids": "None"})),
        _person(TYRELL, "Tyrell Hayes", meta=nh(z(11, 19, 19))),
        _person(HAYES, "Brianna Cole", meta=nh(z(11, 15, 10, 30))),
        _person(SAM, "Sam Whitfield", created=at(11, 20, 8)),
        _person(LEE, "Lee Grant", meta={"new_here": {"app": {"at": z(11, 22, 13), "kids": "yes", "ages": "3, 6"}}}),
        _person(PAT, "+15555550123", meta=nh(z(11, 23, 9))),               # texted the word, no card yet
        _person(OLD, "Olive Dean", meta=nh(z(9, 6, 10))),
        _person(OUTSIDER, "Other Church Guest", biz=OTHER, meta=nh(z(11, 22, 10))),
        _person(LONGAGO, "Long Time Member", created="2025-01-01T12:00:00+00:00",
                meta={"new_here": {"texted_at": z(11, 22, 10, 5), "visits": 3}}),
        _person(BAPTIZED, "Ben Baptism"),
    ]
    follow_ups = [
        _fu(1, MARIA, "checkin:first", at(11, 22, 11, 30), due=at(11, 24, 11, 30), card_name="First check-in",
            answers=[{"q": "First visit", "a": "First time at Sunday Worship · 2 kids checked in"}]),
        _fu(2, ADA, "text:new_here", at(11, 22, 11), step=1, due=at(12, 6, 14), card_name="New here card"),
        _fu(3, JORDAN, "web:connect_card", at(11, 21, 9), due=at(11, 23, 9), card_name="Connect card"),
        _fu(4, KIM, "text:new_here", at(11, 22, 10), due=at(11, 24, 10), card_name="New here card"),
        _fu(5, TYRELL, "text:new_here", at(11, 19, 20), status="done", step=2, card_name="New here card"),
        _fu(6, SAM, "form:f-visit", at(11, 20, 8), due=at(11, 22, 8), kind="visit", card_name="Plan your visit"),
        _fu(7, LEE, "app:new_here", at(11, 22, 13), leader=None, due=at(11, 24, 13),
            card_name="New here (member app) card"),
        _fu(8, OLD, "text:new_here", at(9, 6, 11), step=2, status="done", leader=MARCUS, card_name="New here card"),
        _fu(9, OUTSIDER, "text:new_here", at(11, 22, 11), biz=OTHER),
        _fu(10, BAPTIZED, "form:f-baptism", at(11, 22, 12), kind="baptism", card_name="Baptism"),   # not a guest's
        _fu(11, HAYES, "text:new_here", at(11, 15, 11), step=1, card_name="New here card", due=at(11, 29, 11)),
    ]
    notes = [
        _note(fid(2), "talked", at(11, 22, 14)),
        _note(fid(3), "noanswer", at(11, 22, 15)),
        _note(fid(8), "talked", at(9, 11, 12), author=MARCUS, name="Marcus Taylor"),   # five days after the hand-off
        _note(fid(11), "message", at(11, 16, 9)),
        _note(fid(9), "talked", at(11, 22, 12)),
    ]
    attendance = [
        {"id": "a1", "business_id": BIZ, "contact_id": TYRELL, "checked_in_at": at(11, 22, 10, 50)},
        {"id": "a2", "business_id": BIZ, "contact_id": HAYES, "checked_in_at": at(11, 22, 10, 55)},
        {"id": "a3", "business_id": BIZ, "contact_id": OLD, "checked_in_at": at(9, 13, 10)},
        {"id": "a4", "business_id": BIZ, "contact_id": OLD, "checked_in_at": at(9, 20, 10)},
        {"id": "a5", "business_id": OTHER, "contact_id": OUTSIDER, "checked_in_at": at(11, 22, 10)},
    ]
    sched = [
        _sched(ADA, "thanks", at(11, 22, 13, 42), "done", z(11, 22, 10, 42), last_run=at(11, 22, 13, 42, )),
        _sched(ADA, "monday", at(11, 23, 10), "done", z(11, 22, 10, 42), last_run=at(11, 23, 10)),
        _sched(ADA, "invite", at(11, 26, 18), "queued", z(11, 22, 10, 42)),
        _sched(KIM, "thanks", at(11, 22, 12, 50), "done", z(11, 22, 9, 50), last_run=at(11, 22, 12, 50)),
        _sched(KIM, "invite", at(11, 26, 18), "queued", z(11, 22, 9, 50)),
        _sched(TYRELL, "invite", at(11, 26, 18), "queued", z(11, 19, 19)),
        _sched(PAT, "thanks", at(11, 23, 12), "queued", z(11, 23, 9)),
        _sched(OUTSIDER, "invite", at(11, 26, 18), "queued", z(11, 22, 10), biz=OTHER),
    ]
    sms = [
        {"id": "m1", "business_id": BIZ, "contact_id": ADA, "direction": "outbound", "read": True,
         "created_at": at(11, 22, 13, 42)},
        {"id": "m2", "business_id": BIZ, "contact_id": ADA, "direction": "outbound", "read": True,
         "created_at": at(11, 23, 10)},
        # Kim's thank-you was skipped (no message beside its run); her reply waits.
        {"id": "m3", "business_id": BIZ, "contact_id": KIM, "direction": "inbound", "read": False,
         "created_at": at(11, 22, 9, 50)},                                  # the word itself
        {"id": "m4", "business_id": BIZ, "contact_id": KIM, "direction": "inbound", "read": False,
         "created_at": at(11, 23, 9)},
        {"id": "m5", "business_id": BIZ, "contact_id": ADA, "direction": "inbound", "read": True,
         "created_at": at(11, 22, 15)},                                     # read: not waiting
    ]
    audit = [_audit(fid(1), f"Line {i}", at(11, 22, 12, i)) for i in range(1, 5)] + [
        _audit(fid(2), "Handed a New here card to Renee Ellis", at(11, 22, 11, 1)),
        _audit(fid(3), "Emailed Renee Ellis: a Connect card is theirs to follow up", at(11, 22, 12, 30)),
        _audit(fid(10), "Handed a Baptism card to Pastor", at(11, 23, 9)),      # not a guest's
        _audit(fid(9), "Other church", at(11, 23, 9), biz=OTHER),
    ]
    groups = [{"id": "g1", "business_id": BIZ, "active": True, "kind": "small_group"},
              {"id": "g2", "business_id": BIZ, "active": False, "kind": "team"}]
    members = [{"group_id": "g1", "contact_id": OLD, "business_id": BIZ, "joined_on": "2026-09-27",
                "created_at": at(9, 27, 12)},
               {"group_id": "g2", "contact_id": ADA, "business_id": BIZ, "joined_on": "2026-11-22",
                "created_at": at(11, 22, 12)},                              # an inactive group
               {"group_id": "g1", "contact_id": KIM, "business_id": BIZ, "joined_on": "2026-01-10",
                "created_at": at(1, 10, 12)}]                               # before her first visit
    enrollments = [{"id": "e1", "business_id": BIZ, "contact_id": ADA, "status": "active",
                    "enrolled_at": at(11, 22, 16)}]
    return FakeDB(
        businesses=[{"id": BIZ, "name": "Grace Hill Church", "type": "ministry", "owner_id": OWNER,
                     "settings": {"guest_calls": {"backup": {"contact_id": MARCUS}}}},
                    {"id": OTHER, "name": "Other Church", "type": "ministry", "owner_id": "x", "settings": {}}],
        contacts=contacts, church_follow_ups=follow_ups, church_follow_up_notes=notes, attendance=attendance,
        household_adults=[{"household_id": "h1", "contact_id": MARIA, "business_id": BIZ}],
        child_checkins=[], chief_scheduled_actions=sched, sms_messages=sms, audit_log=audit, groups=groups,
        group_members=members, academy_enrollments=enrollments,
    )


@pytest.fixture
def db(monkeypatch):
    fake = church_week()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setattr(cg, "_tz", lambda business: ET)
    monkeypatch.setattr(cg, "_now", lambda: NOW.astimezone(timezone.utc))
    monkeypatch.setenv("GUEST_PATH", "on")
    return fake


def _biz(db):
    return dict(db.t["businesses"][0])


def _week(db, **kw):
    return cg.this_week(_biz(db), now=NOW.astimezone(timezone.utc), **kw)


def _by_name(week):
    return {g["name"] or "(nameless)": (grp["key"], g) for grp in week["groups"] for g in grp["guests"]}


# ── 1. who a guest is ─────────────────────────────────────────────────

def test_every_door_is_a_guest_once_and_nobody_elses(db):
    got = _by_name(_week(db))
    assert {k: v[0] for k, v in got.items()} == {
        "Maria Lopez": "new", "Ada Okafor": "new", "Jordan Price": "new", "Kim Nguyen": "new",
        "Lee Grant": "new", "(nameless)": "new", "Tyrell Hayes": "came_back", "Brianna Cole": "came_back",
        "Sam Whitfield": "planned"}
    # another church's guest, a baptism card, an old guest and a member who
    # texted the word for the third time are not this week's guests
    assert "Other Church Guest" not in got and "Ben Baptism" not in got
    assert "Olive Dean" not in got and "Long Time Member" not in got


def test_the_door_and_the_family_line(db):
    got = {k: v[1] for k, v in _by_name(_week(db)).items()}
    assert {k: g["door"] for k, g in got.items()} == {
        "Maria Lopez": "kids", "Ada Okafor": "text", "Jordan Price": "web", "Kim Nguyen": "text",
        "Lee Grant": "app", "(nameless)": "text", "Tyrell Hayes": "text", "Brianna Cole": "text",
        "Sam Whitfield": "form"}
    assert got["Sam Whitfield"]["door_words"] == "Plan your visit"        # the church's own card's name
    assert got["Jordan Price"]["door_words"] == "Website card"
    assert got["Maria Lopez"]["family"] == "2 kids checked in"
    assert got["Ada Okafor"]["family"] == "with 2 kids"
    assert got["Kim Nguyen"]["family"] == ""                               # "None" on the card
    assert got["Lee Grant"]["family"] == "with kids (3, 6)"
    assert got["(nameless)"]["name"] == "" and got["(nameless)"]["initials"] == ""


def test_a_door_the_path_wrote_wins_over_the_card(db):
    db.t["contacts"][2]["metadata"] = {"new_here": {"door": "desk", "texted_at": z(11, 22, 11, 20)}}
    got = {k: v[1] for k, v in _by_name(_week(db)).items()}
    assert got["Maria Lopez"]["door"] == "desk" and got["Maria Lopez"]["door_words"] == "Welcome desk"


# ── 2. this week ──────────────────────────────────────────────────────

def test_the_texts_steps(db):
    got = {k: v[1] for k, v in _by_name(_week(db)).items()}

    def states(name):
        return [s["state"] for s in got[name]["texts"]["steps"]]
    assert [s["label"] for s in got["Ada Okafor"]["texts"]["steps"]] == [
        "Welcome", "Thank you", "Call", "Monday note", "Invite back"]
    assert states("Ada Okafor") == ["done", "done", "done", "done", "waiting"]
    assert states("Kim Nguyen") == ["done", "skipped", "waiting", "off", "waiting"]   # no message beside the run
    assert states("Maria Lopez") == ["off", "off", "waiting", "off", "off"]          # the kids desk: no texts
    assert got["Maria Lopez"]["texts"]["ok"] is False and got["Ada Okafor"]["texts"]["ok"] is True
    assert states("(nameless)") == ["done", "waiting", "off", "off", "off"]           # no card, no call yet


def test_a_guest_who_said_yes_from_another_door_gets_the_texts_and_one_who_didnt_doesnt():
    assert cg.texts_ok({"door": "kids", "texted_at": "x", "texts_ok": True})
    assert not cg.texts_ok({"door": "kids", "texted_at": "x"})
    assert cg.texts_ok({"texted_at": "x"}) and not cg.texts_ok({})


def test_the_call_and_the_status_line(db):
    got = {k: v[1] for k, v in _by_name(_week(db)).items()}
    maria = got["Maria Lopez"]
    assert maria["follow_up"]["caller"]["name"] == "Renee Ellis" and maria["follow_up"]["caller"]["initials"] == "RE"
    assert maria["status"] == {"tone": "need", "line": "Call by 11:30 AM tomorrow", "sub": "Renee Ellis has them"}
    jordan = got["Jordan Price"]
    assert jordan["follow_up"]["late"] is True and jordan["follow_up"]["last_outcome"]["words"] == "No answer"
    assert jordan["status"] == {"tone": "need", "line": "Call is past due", "sub": "No answer"}
    assert got["Ada Okafor"]["status"] == {"tone": "ok", "line": "Talked", "sub": "Next: Invite to a next step"}
    assert got["Kim Nguyen"]["status"]["line"] == "Texted back: waiting on you"
    assert got["Kim Nguyen"]["reply_waiting"] is True and got["Ada Okafor"]["reply_waiting"] is False
    assert got["Lee Grant"]["status"]["line"] == "No one has them yet"
    assert got["(nameless)"]["status"]["line"] == "Waiting on their card"
    assert got["Sam Whitfield"]["status"] == {"tone": "calm", "line": "Planning a visit", "sub": "Renee Ellis has them"}
    assert got["Tyrell Hayes"]["came_back"] is True and got["Tyrell Hayes"]["visits"] == 2


def test_the_facts_row(db):
    c = _week(db)["counts"]
    # new: Maria, Ada, Jordan, Kim, Lee, the nameless texter and Tyrell (met Thursday, came back Sunday)
    assert c["new"] == 7 and c["called"] == 1 and c["came_back"] == 2 and c["planned"] == 1
    # to call: open at Reach out with no call yet — Maria, Jordan, Kim, Lee and Sam (planned)
    assert c["to_call"] == 5 and c["late"] == 2                             # Jordan, and Sam's before-Sunday
    assert c["to_call_by_words"] == "Tue"


def test_a_kids_desk_family_that_comes_back_came_back(db):
    db.t["child_checkins"] = [{"id": "k1", "business_id": BIZ, "household_id": "h1", "checked_in_at": at(11, 23, 9)}]
    got = _by_name(_week(db))
    # Monday is a later day than Sunday's first check-in: she came back
    assert got["Maria Lopez"][0] == "came_back"


def test_a_planned_visit_that_came_is_new_not_planned(db):
    db.t["attendance"].append({"id": "a9", "business_id": BIZ, "contact_id": SAM, "checked_in_at": at(11, 22, 10)})
    sam = _by_name(_week(db))["Sam Whitfield"]
    assert sam[0] == "new" and sam[1]["came_back"] is False and sam[1]["first_day"] == "2026-11-22"


# ── 3. the next move ──────────────────────────────────────────────────

def test_the_next_move_in_order(db):
    m = _week(db)["next_move"]
    assert m["kind"] == "answer" and m["guest_id"] == KIM and m["action"] == "Answer Kim"
    assert m["line"] == "Kim Nguyen texted back, and the reply is waiting."
    db.t["sms_messages"] = [s for s in db.t["sms_messages"] if s["id"] != "m4"]
    m = _week(db)["next_move"]
    # the longest-late call: Sam's (due Sunday) before Jordan's (due Monday)
    assert m["kind"] == "call" and m["guest_id"] == SAM and m["action"] == "Open Sam"
    assert m["line"] == "Sam Whitfield's welcome call is a day late." and m["detail"] == "Renee Ellis has them."
    for f in db.t["church_follow_ups"]:
        if f["id"] in (fid(3), fid(6)):
            f["due_at"] = at(11, 30, 9)
    m = _week(db)["next_move"]
    assert m["kind"] == "hand_on" and m["guest_id"] == LEE and m["action"] == "Hand Lee on"
    for f in db.t["church_follow_ups"]:
        if f["id"] == fid(7):
            f["leader_contact_id"] = RENEE
    m = _week(db)["next_move"]
    assert m["kind"] == "calm" and m["line"] == "Nothing is late."
    assert "1 guest hasn’t sent their card yet" in m["detail"]


def test_calm_with_no_guests(db):
    for t in ("contacts", "church_follow_ups"):
        db.t[t] = [r for r in db.t[t] if r.get("id") in (RENEE, MARCUS)]
    w = _week(db)
    assert w["next_move"]["line"] == "No new guests this week yet."
    assert all(not g["guests"] for g in w["groups"]) and w["counts"]["new"] == 0 and w["chief_did"] == []


# ── 4. the side cards ─────────────────────────────────────────────────

def test_the_texts_going_out_this_week(db):
    got = _week(db)["texts_this_week"]
    assert [(e["words"], e["when"], e["count"]) for e in got] == [
        ("Thank you", "Mon 12 PM", 1), ("Invite back", "Thu 6 PM", 3)]
    invite = got[1]
    # Tyrell checked in Sunday, 20+ hours after Thursday's text: New here skips his invite
    assert invite["skip"] == 1 and invite["skip_names"] == ["Tyrell Hayes"]


def test_what_chief_did_is_guests_only_newest_five_in_its_own_words(db):
    got = _week(db)["chief_did"]
    assert len(got) == 5
    assert [g["line"] for g in got] == ["Emailed Renee Ellis: a Connect card is theirs to follow up",
                                        "Line 4", "Line 3", "Line 2", "Line 1"]


# ── 5. the scorecard ──────────────────────────────────────────────────

def _card(db, period="season"):
    return cg.scorecard(_biz(db), period, now=NOW.astimezone(timezone.utc))


def test_the_funnel_this_fall(db):
    s = _card(db)
    assert (s["label"], s["span"], s["from"], s["to"]) == ("This fall", "September to November", "2026-09-01",
                                                          "2026-12-01")
    # nine guests met this fall (Sam planned a visit and hasn't come)
    assert [(f["label"], f["n"]) for f in s["funnel"]] == [
        ("First-time guests", 9), ("Called within 2 days", 2), ("Came back", 3), ("Came a third time", 1),
        ("Connected", 2)]
    # one door with three or more guests: nothing to compare, so no "fewest" clause
    assert s["read"] == "Of 9 first-time guests this fall, 2 are now in a group, a class or a team."


def test_connected_means_a_group_class_or_team_after_their_first_visit(db):
    got = cg._connected(BIZ, {OLD: date(2026, 9, 6), ADA: date(2026, 11, 22), KIM: date(2026, 11, 22)}, ET)
    # Olive joined an active group; Ada's group is inactive but she enrolled in a class; Kim's group
    # was before her first visit
    assert got == {OLD, ADA}


def test_by_door_and_by_caller(db):
    s = _card(db)
    doors = {d["door"]: (d["guests"], d["called"], d["came_back"]) for d in s["doors"]}
    assert doors["text"][0] == 6 and doors["kids"] == (1, 0, 0) and doors["web"] == (1, 0, 0)
    assert "form" not in doors                                               # Sam hasn't come
    callers = {c["name"]: (c["calls"], c["on_time"], c["backup"]) for c in s["callers"]}
    assert callers == {"Renee Ellis": (2, 2, False), "Marcus Taylor": (1, 0, True)}


def test_the_churchs_own_call_window(db):
    db.t["businesses"][0]["settings"]["guest_calls"]["due_days"] = 3
    s = _card(db)
    assert s["due_days"] == 3 and s["funnel"][1]["label"] == "Called within 3 days"
    db.t["businesses"][0]["settings"]["guest_calls"]["due_days"] = 9                      # not a choice
    assert _card(db)["due_days"] == 2


def test_not_reached(db):
    s = _card(db)
    # Jordan (no answer, past due) and Tyrell (finished with no call logged)
    assert s["not_reached"] == 2
    assert s["no_follow_up"] == 1                                            # the nameless texter


def test_the_periods():
    sun = datetime(2026, 11, 22, 12, tzinfo=ET)
    assert cg.period_of("month", sun, ET)["from"] == date(2026, 11, 1)
    assert cg.period_of("month", sun, ET)["to"] == date(2026, 12, 1)
    assert cg.period_of("year", sun, ET)["to"] == date(2027, 1, 1)
    jan = cg.period_of("season", datetime(2027, 1, 10, tzinfo=ET), ET)
    assert (jan["label"], jan["from"], jan["to"]) == ("This winter", date(2026, 12, 1), date(2027, 3, 1))
    dec = cg.period_of("season", datetime(2026, 12, 10, tzinfo=ET), ET)
    assert (dec["from"], dec["to"]) == (date(2026, 12, 1), date(2027, 3, 1))
    assert cg.period_of("season", datetime(2026, 7, 4, tzinfo=ET), ET)["label"] == "This summer"


def test_the_read_line():
    doors = [{"words": "Text NEW", "guests": 9, "came_back": 5}, {"words": "Website card", "guests": 4,
                                                                    "came_back": 1}]
    assert cg.read_line(24, 5, 11, doors, "This fall") == (
        "Of 24 first-time guests this fall, 5 are now in a group, a class or a team. "
        "Website card: 1 of 4 came back, the fewest of any door.")
    assert cg.read_line(1, 1, 0, doors[:1], "This month") == (
        "Of 1 first-time guest this month, 1 is now in a group, a class or a team.")
    assert cg.read_line(0, 0, 0, [], "This year") == "No first-time guests this year yet."
    assert cg.read_line(3, None, 2, [], "This year") == "Of 3 first-time guests this year, 2 came back."


# ── 6. reads ──────────────────────────────────────────────────────────

def test_every_read_is_a_page_and_a_small_page_still_reads_everyone(db, monkeypatch):
    whole = _week(db)
    s = _card(db, "year")
    for p in db.paths:
        assert "limit=" in p, p
        assert int(p.split("limit=")[1].split("&")[0]) <= 1000, p
    db.paths.clear()
    monkeypatch.setattr(cg, "PAGE", 2)
    assert _by_name(_week(db)).keys() == _by_name(whole).keys()
    assert _card(db, "year")["funnel"] == s["funnel"]
    assert any("offset=2" in p for p in db.paths)


@pytest.mark.parametrize("table", ["contacts", "church_follow_ups", "church_follow_up_notes", "attendance",
                                   "household_adults"])
def test_a_core_read_that_fails_is_a_503_never_nobody(db, table):
    db.broken = {table}
    with pytest.raises(cg.Unread):
        _week(db)
    with pytest.raises(cg.Unread):
        _card(db)


def test_a_side_read_that_fails_is_null_and_the_room_still_reads(db):
    db.broken = {"chief_scheduled_actions", "audit_log"}
    w = _week(db)
    assert w["texts_this_week"] is None and w["chief_did"] is None and w["texts_read"] is False
    ada = _by_name(w)["Ada Okafor"][1]
    assert [s["state"] for s in ada["texts"]["steps"]] == ["done", "unknown", "done", "unknown", "unknown"]
    db.broken = {"group_members"}
    assert _card(db)["funnel"][-1]["n"] is None


# ── 7. who ────────────────────────────────────────────────────────────

def _client(monkeypatch, role="manager"):
    app = FastAPI()
    app.include_router(cg.router)
    monkeypatch.setattr(ba, "_resolve_role", lambda b, u: role)
    monkeypatch.setattr(ba.billing_context, "set_current", lambda b: None)
    user = SimpleNamespace(user=SimpleNamespace(id=OWNER, user_metadata={}, email="pastor@example.org"))
    app.dependency_overrides[sb_clients.authed_request] = lambda: user
    return TestClient(app)


@pytest.fixture
def areas(monkeypatch):
    import church_areas
    import church_duties
    state = {"mode": "on", "view": {"areas": ["people_care", "kids_youth"]}}
    monkeypatch.setattr(church_areas, "mode", lambda: state["mode"])
    monkeypatch.setattr(church_areas, "my_areas", lambda b, u, r: state["view"])
    monkeypatch.setattr(church_duties, "holds", lambda b, u, d: d == guest_path.FIRST_GUESTS)
    monkeypatch.setattr(cg, "_person_of", lambda b, u: state.get("person", ""))
    return state


def test_the_routes(db, monkeypatch, areas):
    t = _client(monkeypatch)
    r = t.get(f"/church/guests/{BIZ}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["on"] is True and body["you_do_first_guests"] is True and body["counts"]["came_back"] == 2
    s = t.get(f"/church/guests/{BIZ}/scorecard", params={"period": "month"})
    assert s.status_code == 200 and s.json()["label"] == "This month"
    assert t.get(f"/church/guests/{BIZ}/scorecard").json()["period"] == "season"
    assert t.get(f"/church/guests/{BIZ}/scorecard", params={"period": "week"}).status_code == 400
    db.paths.clear()
    st = t.get(f"/church/guests/{BIZ}/status")
    assert st.status_code == 200 and st.json() == {"open": True}
    assert not any(p.startswith(("/contacts", "/church_follow_ups")) for p in db.paths)   # no guest read


def test_the_switch(db, monkeypatch, areas):
    t = _client(monkeypatch)
    monkeypatch.setenv("GUEST_PATH", "off")
    assert t.get(f"/church/guests/{BIZ}").status_code == 404
    assert t.get(f"/church/guests/{BIZ}/status").status_code == 404
    assert t.get(f"/church/guests/{BIZ}/scorecard").status_code == 404
    monkeypatch.setenv("GUEST_PATH", "owner")
    monkeypatch.setattr(guest_path, "switched_on", lambda b: str(b) == BIZ)
    assert t.get(f"/church/guests/{BIZ}").status_code == 200


def test_only_a_church(db, monkeypatch, areas):
    db.t["businesses"][0]["type"] = "coaching"
    assert _client(monkeypatch).get(f"/church/guests/{BIZ}").status_code == 404


def test_a_seat_below_manager_and_the_areas(db, monkeypatch, areas):
    import church_duties
    monkeypatch.setattr(church_duties, "holds", lambda b, u, d: False)       # not the one who calls guests
    assert _client(monkeypatch, role="member").get(f"/church/guests/{BIZ}").status_code == 404
    t = _client(monkeypatch, role="manager")
    areas["view"] = {"areas": ["worship_media"]}
    r = t.get(f"/church/guests/{BIZ}")
    assert r.status_code == 403 and "People & care" in r.json()["detail"]
    assert t.get(f"/church/guests/{BIZ}/status").status_code == 403
    areas["view"] = {"areas": None}                                           # the whole church
    assert t.get(f"/church/guests/{BIZ}").status_code == 200
    areas["view"] = None                                                      # unread
    assert t.get(f"/church/guests/{BIZ}").status_code == 503
    areas["mode"] = "off"                                                     # Who sees what off: every login
    assert t.get(f"/church/guests/{BIZ}").status_code == 200
    areas["mode"], areas["view"] = "on", {"areas": ["worship_media"]}
    assert _client(monkeypatch, role="admin").get(f"/church/guests/{BIZ}").status_code == 200
    assert _client(monkeypatch, role="owner").get(f"/church/guests/{BIZ}").status_code == 200


def test_a_failed_read_is_a_503_through_the_route(db, monkeypatch, areas):
    db.broken = {"church_follow_ups"}
    r = _client(monkeypatch).get(f"/church/guests/{BIZ}")
    assert r.status_code == 503 and "couldn't be read" in r.json()["detail"]


def test_a_duty_that_cant_be_read_decides_nothing(db, monkeypatch, areas):
    import church_duties

    def boom(*a):
        raise HTTPException(503, "no")
    monkeypatch.setattr(church_duties, "holds", boom)
    assert _client(monkeypatch).get(f"/church/guests/{BIZ}").json()["you_do_first_guests"] is None


def test_the_router_is_mounted_before_the_catch_all():
    src = open(os.path.join(ROOT, "kmj_intake_automation.py"), encoding="utf-8").read()
    assert src.index("app.include_router(church_guests_router)") < src.index("app.include_router(public_site_router)")
