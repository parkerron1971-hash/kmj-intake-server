"""Leaders & follow-up (church_follow_up.py, church_router's /church/follow-ups
and /church/leaders, the intake and connect-card hooks, the sweep).

Kevin, 2026-10-17: every card becomes someone's job; Chief assigns on its
own; nobody is left behind. The tables are faked in memory below with the
PostgREST filters this module uses, so the reads and writes are the real
paths, not mocks of them."""
from __future__ import annotations

import asyncio
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import unquote

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import church_follow_up as cfu  # noqa: E402
import sb_clients  # noqa: E402

BIZ = "009e9a2c-3e81-4bfc-a92a-205a8806aa99"
OTHER_BIZ = "11111111-1111-1111-1111-111111111111"
OWNER = "22222222-2222-2222-2222-222222222222"


def cid(n: int) -> str:
    return f"00000000-0000-0000-0000-{n:012d}"


PASTOR, MINISTER, TASHA, ROBERT, DANA, MARCUS, KEISHA, ANDRE = (cid(i) for i in range(1, 9))
NAMES = {PASTOR: "Kevin McCloud", MINISTER: "Angela Price", TASHA: "Tasha Williams", ROBERT: "Robert Hayes",
         DANA: "Dana Rivers", MARCUS: "Marcus Taylor", KEISHA: "Keisha Morgan", ANDRE: "Andre Wallace"}

BAPTISM = {"id": "f-baptism", "name": "Baptism", "form_type": "general", "fields": [
    {"name": "name", "label": "Your name"}, {"name": "email", "label": "Email"}, {"name": "phone", "label": "Phone"},
    {"name": "faith", "label": "Have you given your life to Jesus?", "options": ["Yes", "I’m not sure yet", "I’d like to talk with a pastor"]},
    {"name": "before", "label": "Have you been baptized before?", "options": ["No", "Yes, as a child", "Yes, as an adult"]},
    {"name": "notes", "label": "Anything you’d like us to know?"}]}
SERVE = {"id": "f-serve", "name": "Serve with us", "form_type": "volunteer", "fields": [
    {"name": "name", "label": "Your name"}, {"name": "email", "label": "Email"},
    {"name": "team", "label": "Where would you like to serve?", "options": ["Youth Ministry (YWD)", "Hospitality Team", "Graphic and web design"]},
    {"name": "nmo", "label": "Have you been to New Members Orientation?", "options": ["Yes", "Not yet"]}]}
VISIT = {"id": "f-visit", "name": "Plan your visit", "form_type": "general", "fields": [
    {"name": "name", "label": "Your name"}, {"name": "sunday", "label": "Which Sunday are you planning to come?"},
    {"name": "kids", "label": "Are you bringing children?", "options": ["No", "Yes"]}]}
TRIP = {"id": "f-trip", "name": "Youth trip permission", "form_type": "event", "fields": []}


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


def _cmp(row, col, op, val):
    v = row.get(col)
    if op == "is":
        return v is None if val == "null" else str(v).lower() == val
    if op == "in":
        return str(v) in set(_split(val.strip("()")))
    if op == "eq":
        return str(v).lower() == val.lower() if isinstance(v, bool) else str(v) == val
    if op == "neq":
        return str(v) != val
    if v is None:
        return False
    if isinstance(v, (int, float)):
        val = type(v)(val)
    return {"gt": v > val, "lt": v < val, "gte": v >= val, "lte": v <= val}[op]


class FakeDB:
    def __init__(self, **tables):
        self.t = {k: [dict(r) for r in v] for k, v in tables.items()}
        self.writes = []

    def _parse(self, path):
        table, _, qs = path.lstrip("/").partition("?")
        filters, limit = [], None
        for part in qs.split("&") if qs else []:
            k, _, v = part.partition("=")
            v = unquote(v)
            if k in ("select", "order"):
                continue
            if k == "limit":
                limit = int(v)
            elif k == "or":
                ors = []
                for c in _split(v.strip("()")):
                    col, op, val = c.split(".", 2)
                    ors.append((col, op, val))
                filters.append(("or", ors))
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
        table, filters, limit = self._parse(path)
        rows = [dict(r) for r in self.t.get(table, []) if self._match(r, filters)]
        return rows[:limit] if limit else rows

    def post(self, path, body, prefer=None, **_):
        table = path.lstrip("/").split("?")[0]
        row = dict(body)
        row.setdefault("id", str(uuid.uuid4()))
        row.setdefault("created_at", cfu._iso(cfu._now()))
        if table == "church_follow_ups" and row.get("source_event") and any(
                r.get("source_event") == row["source_event"] and r["business_id"] == row["business_id"]
                for r in self.t.get(table, [])):
            return None  # the unique index
        self.t.setdefault(table, []).append(row)
        self.writes.append(("POST", table, row))
        return [dict(row)]

    def patch(self, path, body, **_):
        table, filters, _ = self._parse(path)
        out = []
        for r in self.t.get(table, []):
            if self._match(r, filters):
                r.update(body)
                out.append(dict(r))
        self.writes.append(("PATCH", table, body))
        return out

    def delete(self, path, **_):
        table, filters, _ = self._parse(path)
        self.t[table] = [r for r in self.t.get(table, []) if not self._match(r, filters)]
        return True


def _role(contact, role, scope="", status="active", biz=BIZ):
    return {"id": str(uuid.uuid4()), "business_id": biz, "contact_id": contact, "role": role, "scope": scope,
            "status": status, "invited_at": "2026-10-01T00:00:00+00:00", "answered_at": None}


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB(
        contacts=[{"id": k, "business_id": BIZ, "name": v, "email": f"{v.split()[0].lower()}@example.com", "phone": ""}
                  for k, v in NAMES.items()],
        church_leader_roles=[_role(PASTOR, "pastor"), _role(MINISTER, "baptism_minister"),
                             _role(TASHA, "team_leader", "Hospitality Team"), _role(ROBERT, "welcome_lead")],
        church_follow_ups=[], church_follow_up_notes=[], events=[],
        intake_forms=[dict(f, business_id=BIZ) for f in (BAPTISM, SERVE, VISIT, TRIP)],
        businesses=[{"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": OWNER}],
        business_sites=[{"business_id": BIZ, "slug": "love-city-church", "site_config": {"custom_domain": "lovecityc.com"}}],
    )
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", fake.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fake.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fake.delete)
    return fake


def _answers(form, **said):
    return cfu.answers_from_form(form, said)


# ─── Which path ───────────────────────────────────────────────────────

def test_love_citys_cards_start_their_own_paths_and_a_permission_slip_starts_none():
    assert [cfu.kind_for_form(f) for f in (BAPTISM, SERVE, VISIT, TRIP)] == ["baptism", "serve", "visit", None]
    assert cfu.kind_for_form({"name": "Contact us", "form_type": "general"}) == "general"
    assert cfu.kind_for_form({"name": "Retreat Registration", "form_type": "general"}) is None


def test_answers_keep_what_they_said_and_leave_name_email_and_phone_on_the_contact():
    got = _answers(BAPTISM, name="Marcus T", email="m@x.com", phone="555", faith="Yes", before="No",
                   notes="I want my daughter to see me do this.")
    assert got == [{"q": "Have you given your life to Jesus?", "a": "Yes"},
                   {"q": "Have you been baptized before?", "a": "No"},
                   {"q": "Anything you’d like us to know?", "a": "I want my daughter to see me do this."}]
    assert cfu.answers_from_connect({"first_name": "A", "email": "a@x", "visits": "This is my first time",
                                     "interests": ["Baptism", "Serving on a team"]}) == [
        {"q": "Have you been here before?", "a": "This is my first time"},
        {"q": "I’m interested in", "a": "Baptism, Serving on a team"}]


# ─── Chief picks the leader ───────────────────────────────────────────

ROLES = [dict(_role(PASTOR, "pastor"), name="Kevin McCloud"), dict(_role(MINISTER, "baptism_minister"), name="Angela Price"),
         dict(_role(TASHA, "team_leader", "Hospitality Team"), name="Tasha Williams"),
         dict(_role(ROBERT, "welcome_lead"), name="Robert Hayes")]


def _pick(kind, answers, roles=ROLES, load=None):
    p = cfu.choose(kind, answers, roles, load)
    return (p["leader"]["contact_id"] if p["leader"] else None), p["role"], p["reason"]


def test_a_baptism_card_goes_to_the_baptism_minister():
    assert _pick("baptism", _answers(BAPTISM, faith="Yes"))[:2] == (MINISTER, "baptism_minister")


def test_asking_for_a_pastor_goes_to_the_pastor_whatever_the_card():
    who, role, why = _pick("baptism", _answers(BAPTISM, faith="I’d like to talk with a pastor"))
    assert (who, role) == (PASTOR, "pastor") and "talk with a pastor" in why


def test_a_serve_card_goes_to_the_leader_of_the_team_they_picked_whatever_the_case():
    who, role, why = _pick("serve", _answers(SERVE, team="hospitality team"))
    assert (who, role) == (TASHA, "team_leader") and why == "They picked hospitality team, and Tasha leads it."


def test_a_team_with_no_leader_goes_to_the_pastor_and_says_so():
    who, role, why = _pick("serve", _answers(SERVE, team="Graphic and web design"))
    assert (who, role) == (PASTOR, "pastor")
    assert why.startswith("Graphic and web design has no leader yet.") and "Kevin McCloud" in why


def test_with_no_pastor_named_it_is_with_the_office_never_dropped():
    who, role, why = _pick("serve", _answers(SERVE, team="Graphic and web design"), roles=ROLES[2:])
    assert (who, role) == (None, "") and "with the office" in why


def test_visits_and_connect_cards_go_to_the_welcome_team_lead():
    assert _pick("visit", _answers(VISIT, sunday="Oct 18"))[:2] == (ROBERT, "welcome_lead")
    assert _pick("connect", [{"q": "Have you been here before?", "a": "This is my first time"}])[:2] == (ROBERT, "welcome_lead")
    assert _pick("connect", [{"q": "I’m interested in", "a": "Pastoral care"}])[:2] == (PASTOR, "pastor")


def test_two_holders_share_the_work_the_lighter_one_first():
    two = ROLES + [dict(_role(KEISHA, "baptism_minister"), name="Keisha Morgan")]
    assert _pick("baptism", [], roles=two, load={MINISTER: 3, KEISHA: 1})[0] == KEISHA
    invited = ROLES[:1] + [dict(_role(MINISTER, "baptism_minister", status="invited"), name="Angela Price")]
    assert _pick("baptism", [], roles=invited)[0] == PASTOR, "an invited role is not active yet"


# ─── The late ladder ──────────────────────────────────────────────────

def test_the_late_ladder_nudges_then_climbs_the_chain():
    due = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
    row = {"status": "open", "due_at": due.isoformat(), "late_level": 0}
    assert cfu.late_step(row, due - timedelta(hours=1)) is None
    assert cfu.late_step(row, due + timedelta(hours=1)) == (1, "nudged")
    assert cfu.late_step(dict(row, late_level=1), due + timedelta(days=1, hours=1)) == (2, "overseer_told")
    assert cfu.late_step(dict(row, late_level=2), due + timedelta(days=2)) is None
    assert cfu.late_step(dict(row, late_level=2), due + timedelta(days=3, hours=1)) == (3, "next_up")
    # A sweep that missed days takes the highest rung only: one message, not three.
    assert cfu.late_step(row, due + timedelta(days=5)) == (3, "next_up")
    assert cfu.late_step(dict(row, status="done"), due + timedelta(days=5)) is None


# ─── A card comes in ──────────────────────────────────────────────────

def test_a_card_opens_a_follow_up_handed_to_its_leader_with_the_reason_and_a_clock(db):
    row = cfu.on_intake_form({"id": BIZ, "type": "ministry"}, SERVE, {"team": "Hospitality Team", "nmo": "Not yet"}, DANA)
    assert row and row["leader_contact_id"] == TASHA and row["leader_role"] == "team_leader"
    assert row["path_kind"] == "serve" and row["step"] == 0 and row["status"] == "open"
    due = cfu._parse(row["due_at"])
    assert timedelta(days=1, hours=23) < due - cfu._now() <= timedelta(days=2)
    [note] = db.t["church_follow_up_notes"]
    assert note["author_kind"] == "chief" and note["kind"] == "assigned"
    assert note["body"] == "Handed to Tasha Williams. They picked Hospitality Team, and Tasha leads it."


def test_the_same_card_again_adds_to_the_open_follow_up_instead_of_a_second(db):
    biz = {"id": BIZ, "type": "ministry"}
    first = cfu.on_intake_form(biz, SERVE, {"team": "Hospitality Team"}, DANA)
    assert cfu.on_intake_form(biz, SERVE, {"team": "Hospitality Team", "nmo": "Yes"}, DANA) is None
    assert len(db.t["church_follow_ups"]) == 1
    again = [n for n in db.t["church_follow_up_notes"] if n["follow_up_id"] == first["id"] and n["kind"] == "note"]
    assert again and again[0]["body"].startswith("Filled in the card again.")


def test_only_a_church_and_only_a_card_that_starts_a_path(db):
    assert cfu.on_intake_form({"id": BIZ, "type": "salon"}, SERVE, {"team": "Hospitality Team"}, DANA) is None
    assert cfu.on_intake_form({"id": BIZ, "type": "ministry"}, TRIP, {}, DANA) is None
    assert db.t["church_follow_ups"] == []


def test_a_retried_connect_card_makes_one_follow_up(db):
    data = {"fields": {"visits": "This is my first time"}}
    assert cfu.on_connect_card(BIZ, MARCUS, data, "receipt-1")["leader_contact_id"] == ROBERT
    assert cfu.on_connect_card(BIZ, MARCUS, data, "receipt-1") is None
    assert len(db.t["church_follow_ups"]) == 1


def test_a_failed_save_never_breaks_the_card(db, monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda *a, **k: None)
    assert cfu.on_intake_form({"id": BIZ, "type": "ministry"}, BAPTISM, {"faith": "Yes"}, MARCUS) is None
    monkeypatch.setattr(cfu, "roles", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cfu.on_intake_form({"id": BIZ, "type": "ministry"}, BAPTISM, {"faith": "Yes"}, MARCUS) is None


def test_a_failed_read_never_misassigns_or_lets_a_duplicate_through(db, monkeypatch):
    real = sb_clients.sb_get_as_service

    def failing(table):
        return lambda path, **k: None if path.startswith(f"/{table}") else real(path, **k)
    for table in ("church_leader_roles", "church_follow_ups"):
        monkeypatch.setattr(sb_clients, "sb_get_as_service", failing(table))
        assert cfu.on_intake_form({"id": BIZ, "type": "ministry"}, BAPTISM, {"faith": "Yes"}, MARCUS) is None
        assert cfu.on_connect_card(BIZ, MARCUS, {"fields": {}}, "r-1") is None
    assert db.t["church_follow_ups"] == [] and db.t["church_follow_up_notes"] == []


# ─── The leader ───────────────────────────────────────────────────────

def _open(db, form=SERVE, person=DANA, **said):
    return cfu.on_intake_form({"id": BIZ, "type": "ministry"}, form, said or {"team": "Hospitality Team"}, person)


def test_a_conversation_that_reached_them_finishes_reach_out(db):
    f = _open(db)
    cfu.leader_note(BIZ, {"id": TASHA, "name": "Tasha Williams"}, f["id"], "talked", "Called Dana.", False)
    row = cfu._one(BIZ, f["id"])
    assert row["step"] == 1 and row["late_level"] == 0
    kinds = [n["kind"] for n in db.t["church_follow_up_notes"] if n["follow_up_id"] == f["id"]]
    assert "talked" in kinds and "step" in kinds


def test_no_answer_logs_but_does_not_move_them_on(db):
    f = _open(db)
    cfu.leader_note(BIZ, {"id": TASHA, "name": "Tasha Williams"}, f["id"], "noanswer", "", False)
    assert cfu._one(BIZ, f["id"])["step"] == 0


def test_a_leader_can_only_touch_whom_they_were_handed(db):
    f = _open(db)
    with pytest.raises(Exception) as e:
        cfu.leader_note(BIZ, {"id": ROBERT, "name": "Robert Hayes"}, f["id"], "talked", "hi", False)
    assert getattr(e.value, "status_code", None) == 404
    with pytest.raises(Exception):
        cfu.leader_advance(BIZ, {"id": ROBERT, "name": "Robert Hayes"}, f["id"])


def test_the_last_step_finishes_the_path(db):
    f = _open(db)
    for _ in range(3):
        cfu.leader_advance(BIZ, {"id": TASHA, "name": "Tasha Williams"}, f["id"])
    row = cfu._one(BIZ, f["id"])
    assert row["status"] == "done" and row["done_at"]
    assert cfu.leader_view(BIZ, TASHA)["follow_ups"] == [] and cfu.leader_view(BIZ, TASHA)["done_30"] == 1


def test_a_leader_never_reads_someone_elses_pastors_only_note(db):
    f = _open(db)
    cfu.office_note(BIZ, f["id"], "Family situation: be gentle.", pastors_only=True, by_user=OWNER, by_name="Kevin")
    cfu.office_note(BIZ, f["id"], "She loves coffee.", pastors_only=False, by_user=OWNER, by_name="Kevin")
    cfu.leader_note(BIZ, {"id": TASHA, "name": "Tasha Williams"}, f["id"], "notnow", "Mine, private.", True)
    [item] = cfu.leader_view(BIZ, TASHA)["follow_ups"]
    bodies = {n["body"] for n in item["notes"]}
    assert "She loves coffee." in bodies and "Mine, private." in bodies
    assert "Family situation: be gentle." not in bodies
    office = cfu.board(BIZ)["follow_ups"][0]
    assert "Family situation: be gentle." in {n["body"] for n in office["notes"]}


def test_handing_back_puts_them_with_the_office(db):
    f = _open(db)
    cfu.leader_hand_back(BIZ, {"id": TASHA, "name": "Tasha Williams"}, f["id"], "I’m away this month.")
    b = cfu.board(BIZ)
    assert b["follow_ups"][0]["status"] == "handed_back" and b["counts"]["with_no_one"] == 1


def test_an_invited_member_says_yes_and_their_role_is_active(db):
    row = cfu.add_role(BIZ, DANA, "team_leader", "Hospitality Team", by_user=OWNER)
    assert row["status"] == "invited"
    assert cfu.answer_invite(BIZ, DANA, row["id"], True)
    assert [r["status"] for r in cfu.roles_for(BIZ, DANA)] == ["active"]
    assert not cfu.answer_invite(BIZ, DANA, row["id"], True), "answered once"


# ─── The office ───────────────────────────────────────────────────────

def test_the_board_counts_who_has_no_one_and_who_is_late(db):
    _open(db)                                                              # Tasha
    _open(db, SERVE, ANDRE, team="Graphic and web design")                 # the pastor (no team leader)
    db.t["church_leader_roles"] = [r for r in db.t["church_leader_roles"] if r["role"] != "pastor"]
    _open(db, SERVE, KEISHA, team="Graphic and web design")                # nobody: the office
    db.t["church_follow_ups"][0]["due_at"] = cfu._iso(cfu._now() - timedelta(hours=2))
    b = cfu.board(BIZ)
    assert b["counts"] == {"open": 3, "with_no_one": 1, "late": 1, "done": 0}
    assert {i["person"]["name"] for i in b["follow_ups"] if not i["leader"]} == {"Keisha Morgan"}


def test_reassigning_needs_someone_who_holds_a_role(db):
    f = _open(db)
    with pytest.raises(Exception) as e:
        cfu.reassign(BIZ, f["id"], DANA, by_user=OWNER)
    assert getattr(e.value, "status_code", None) == 400
    cfu.reassign(BIZ, f["id"], ROBERT, by_user=OWNER, by_name="Kevin")
    row = cfu._one(BIZ, f["id"])
    assert row["leader_contact_id"] == ROBERT and row["leader_told_at"] is None, "the new leader is told"


def test_another_churchs_follow_up_is_never_reached(db):
    f = _open(db)
    with pytest.raises(Exception) as e:
        cfu.office_note(OTHER_BIZ, f["id"], "x", pastors_only=False, by_user=OWNER)
    assert getattr(e.value, "status_code", None) == 404


# ─── Nobody waits: the sweep ──────────────────────────────────────────

@pytest.fixture
def outbox(monkeypatch):
    sent = {"email": [], "alert": []}

    async def email(biz, to, name, subject, body, key):
        sent["email"].append((to, subject, key))
        return True

    async def alert(biz_id, title, body, key, person):
        sent["alert"].append((title, key))
        return True
    monkeypatch.setattr(cfu, "_email", email)
    monkeypatch.setattr(cfu, "_office_alert", alert)
    return sent


def test_the_sweep_tells_the_leader_once_and_the_office_when_there_is_no_one(db, outbox):
    _open(db)
    db.t["church_leader_roles"] = [r for r in db.t["church_leader_roles"] if r["role"] not in ("pastor",)]
    _open(db, SERVE, ANDRE, team="Graphic and web design")
    asyncio.run(cfu.sweep())
    assert [s for _, s, _ in outbox["email"]] == ["Dana Rivers is yours to follow up"]
    assert [t for t, _ in outbox["alert"]] == ["Andre Wallace has no one yet"]
    asyncio.run(cfu.sweep())
    assert len(outbox["email"]) == 1 and len(outbox["alert"]) == 1, "each told once"


def test_the_sweep_climbs_the_leaders_own_chain_one_message_per_rung(db, outbox):
    """Canvas board 5: a Hospitality sign-up late with Tasha goes to the
    Welcome Team lead (Hospitality is under that role) a day late, and three
    days late one more step up: the Associate Pastor holds no one, so it's
    passed over to the Lead Pastor, who is asked to hand them on."""
    import church_roles
    church_roles.ensure_library({"id": BIZ, "name": "Love City Church"})   # the office opened Leaders & roles
    f = _open(db)
    asyncio.run(cfu.sweep())                       # told
    row = db.t["church_follow_ups"][0]
    due = cfu._parse(row["due_at"])
    for days, want in ((0, "nudged"), (1, "overseer_told"), (3, "next_up")):
        asyncio.run(cfu.sweep(now=due + timedelta(days=days, hours=1)))
        assert row["late_level"] == {"nudged": 1, "overseer_told": 2, "next_up": 3}[want]
    sent = [(to, s) for to, s, _ in outbox["email"]]
    assert sent == [("tasha@example.com", "Dana Rivers is yours to follow up"),
                    ("tasha@example.com", "Dana Rivers is waiting to hear from you"),
                    ("robert@example.com", "Dana Rivers hasn’t been reached"),
                    ("kevin@example.com", "Hand Dana Rivers to someone else?")]
    assert [t for t, _ in outbox["alert"]] == ["Dana Rivers hasn’t been reached", "Hand Dana Rivers to someone else?"]
    kinds = [n["kind"] for n in db.t["church_follow_up_notes"] if n["follow_up_id"] == f["id"]]
    assert kinds.count("nudged") == kinds.count("overseer_told") == kinds.count("next_up") == 1
    told = next(n["body"] for n in db.t["church_follow_up_notes"] if n["kind"] == "overseer_told")
    assert "Robert Hayes" in told


def test_before_the_library_is_filled_a_late_step_goes_to_the_pastor(db, outbox):
    """A church that never opened Leaders & roles has only the first
    version's roles, none answering to another: a day late, the pastor."""
    _open(db)
    asyncio.run(cfu.sweep())
    row = db.t["church_follow_ups"][0]
    due = cfu._parse(row["due_at"])
    asyncio.run(cfu.sweep(now=due + timedelta(hours=1)))
    asyncio.run(cfu.sweep(now=due + timedelta(days=1, hours=1)))
    assert row["late_level"] == 2
    assert [(to, s) for to, s, _ in outbox["email"]][-1] == ("kevin@example.com", "Dana Rivers hasn’t been reached")
    assert db.t.get("church_role_defs", []) == [], "a card never fills the library"


def test_a_failed_email_is_not_recorded_as_said_and_is_tried_again(db, outbox, monkeypatch):
    f = _open(db)
    down = {"on": True}
    sent = outbox["email"]

    async def email(biz, to, name, subject, body, key):
        if down["on"]:
            return False
        sent.append((to, subject, key))
        return True
    monkeypatch.setattr(cfu, "_email", email)
    asyncio.run(cfu.sweep())
    row = db.t["church_follow_ups"][0]
    assert row.get("leader_told_at") is None and sent == []
    due = cfu._parse(row["due_at"])
    asyncio.run(cfu.sweep(now=due + timedelta(hours=1)))
    assert row.get("late_level", 0) == 0, "a nudge that didn’t go out is not a rung climbed"
    down["on"] = False
    asyncio.run(cfu.sweep(now=due + timedelta(hours=2)))
    assert row["leader_told_at"] and row["late_level"] == 1
    assert [s for _, s, _ in sent] == ["Dana Rivers is yours to follow up", "Dana Rivers is waiting to hear from you"]
    assert [n["kind"] for n in db.t["church_follow_up_notes"] if n["follow_up_id"] == f["id"]].count("nudged") == 1


def test_a_leader_with_no_email_is_the_offices_to_tell(db, outbox):
    for c in db.t["contacts"]:
        if c["id"] == TASHA:
            c["email"] = ""
    _open(db)
    asyncio.run(cfu.sweep())
    assert outbox["email"] == []
    assert [t for t, _ in outbox["alert"]] == ["Tell Tasha Williams about Dana Rivers"]
    assert db.t["church_follow_ups"][0].get("leader_told_at")


def test_a_sweep_that_cannot_read_the_roles_sends_nothing(db, outbox, monkeypatch):
    _open(db)
    monkeypatch.setattr(cfu, "roles", lambda *_: None)
    asyncio.run(cfu.sweep())
    assert outbox["email"] == [] and outbox["alert"] == [] and db.t["church_follow_ups"][0].get("leader_told_at") is None


def test_removing_a_leaders_last_role_returns_their_people_to_the_office(db, outbox):
    f = _open(db)
    tasha_role = next(r for r in db.t["church_leader_roles"] if r["contact_id"] == TASHA)
    assert cfu.remove_role(BIZ, tasha_role["id"]) == {"returned": 1, "prayer_returned": 0}
    row = cfu._one(BIZ, f["id"])
    assert row["leader_contact_id"] is None and row["leader_told_at"] is None
    assert "no longer leads" in row["reason"]
    asyncio.run(cfu.sweep())
    assert [t for t, _ in outbox["alert"]] == ["Dana Rivers has no one yet"]


def test_a_finished_follow_up_cannot_be_closed_over(db):
    f = _open(db)
    for _ in range(3):
        cfu.leader_advance(BIZ, {"id": TASHA, "name": "Tasha Williams"}, f["id"])
    with pytest.raises(Exception) as e:
        cfu.close(BIZ, f["id"], by_user=OWNER)
    assert getattr(e.value, "status_code", None) == 400 and cfu._one(BIZ, f["id"])["status"] == "done"


def test_an_email_from_the_church_after_the_hand_off_finishes_reach_out(db, outbox):
    f = _open(db)
    later = cfu._iso(cfu._now() + timedelta(minutes=5))
    db.t["events"].append({"business_id": BIZ, "contact_id": DANA, "event_type": "email_sent", "created_at": later})
    asyncio.run(cfu.sweep(now=cfu._now() + timedelta(minutes=10)))
    assert cfu._one(BIZ, f["id"])["step"] == 1


# ─── The routes ───────────────────────────────────────────────────────

@pytest.fixture
def office(db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import business_access
    import church_router
    who = {"role": "owner"}
    monkeypatch.setattr(business_access, "_resolve_role", lambda b, u: who["role"])
    sent = []

    async def invite(biz, row):
        sent.append(row["person"]["name"])
        return True
    monkeypatch.setattr(cfu, "send_invite", invite)
    app = FastAPI()
    app.include_router(church_router.router)
    app.dependency_overrides[sb_clients.authed_request] = (
        lambda: SimpleNamespace(user=SimpleNamespace(id=OWNER, email="kevin@example.com", user_metadata={})))
    client = TestClient(app)
    client.who, client.sent = who, sent
    return client


def test_the_office_reads_the_board_and_a_member_seat_is_refused(office, db):
    _open(db)
    r = office.get(f"/church/follow-ups?business_id={BIZ}")
    assert r.status_code == 200 and r.json()["counts"]["open"] == 1
    office.who["role"] = "member"
    assert office.get(f"/church/follow-ups?business_id={BIZ}").status_code == 404
    assert office.get(f"/church/leaders?business_id={BIZ}").status_code == 404


def test_asking_a_member_to_lead_emails_them_once(office, db):
    r = office.post(f"/church/leaders?business_id={BIZ}",
                    json={"contact_id": DANA, "role": "team_leader", "scope": "Hospitality Team"})
    assert r.status_code == 200 and r.json()["status"] == "invited" and office.sent == ["Dana Rivers"]
    again = office.post(f"/church/leaders?business_id={BIZ}",
                        json={"contact_id": DANA, "role": "team_leader", "scope": "Hospitality Team"})
    assert again.json()["already"] is True and office.sent == ["Dana Rivers"]
    leaders = office.get(f"/church/leaders?business_id={BIZ}").json()
    assert leaders["teams"] == ["Youth Ministry (YWD)", "Hospitality Team", "Graphic and web design"]
    team = next(r for r in leaders["roles"] if r["key"] == "team_leader")
    assert [(h["name"], h["status"], h["scope"]) for h in team["holders"] if h["name"] == "Dana Rivers"] == \
        [("Dana Rivers", "invited", "Hospitality Team")]


def test_a_role_must_be_one_we_know_and_a_team_leader_names_the_team(office):
    assert office.post(f"/church/leaders?business_id={BIZ}", json={"contact_id": DANA, "role": "bishop"}).status_code == 400
    assert office.post(f"/church/leaders?business_id={BIZ}", json={"contact_id": DANA, "role": "team_leader"}).status_code == 400


def test_the_office_reassigns_notes_and_closes(office, db):
    f = _open(db)
    assert office.post(f"/church/follow-ups/{f['id']}/reassign?business_id={BIZ}",
                       json={"leader_contact_id": ROBERT}).status_code == 200
    assert office.post(f"/church/follow-ups/{f['id']}/note?business_id={BIZ}",
                       json={"text": "Call after 5pm.", "pastors_only": False}).status_code == 200
    assert office.post(f"/church/follow-ups/{f['id']}/close?business_id={BIZ}").status_code == 200
    assert cfu._one(BIZ, f["id"])["status"] == "closed"


def test_the_new_routes_are_guarded_by_business_access():
    import ownership_sweep
    swept = ownership_sweep.sweep()
    mine = {h["fn"] for h in swept["handlers"] if h["file"] == "church_router.py"}
    assert {"follow_ups", "follow_up_reassign", "follow_up_note", "follow_up_step", "follow_up_close",
            "leaders", "leader_add", "leader_remove"} <= mine
    assert [h["fn"] for h in swept["unguarded"] if h["file"] == "church_router.py"] == []
