"""The Welcome Path after week one (guest_path_weeks.py, 2026-11-20).

Kevin, on the Welcome Path mock: "capture visitors, place them in a flow
where they receive automated texts from the church ... top tier", then
"build"; the Monday note signed by the senior pastor; each church picks its
own newcomers' next step. Pinned here:

  1. each road's timing: not yet (week two's Wednesday, week four's), came
     back (the day they're back, three hours after they arrive, never late),
     the next step (week three, the church's own event, skipped when none is
     picked or it's over)
  2. came back is church_guests' rule (their own check-in, or the kids desk
     for their family); connected ends the path
  3. the limits: up to four a week, one a week after week one
  4. hold: a road text waits and goes once the hold clears, or is skipped
     with why a day on; a week-one text found held is kept and sent later
     (run_scheduled), or skipped with why
  5. the Monday note's signature: the senior pastor, the church's own words,
     off, nobody
  6. the Saturday heads-up: who may come, who hears, once per Saturday
  7. claims: a send in flight is never sent twice; a stale one never again
  8. settings: the round trip, an old client's PUT keeps the new keys, the
     rules for the words, the event must be coming up
  9. switched off: nothing at all
"""
from __future__ import annotations

import asyncio
import copy
import json
import pathlib
import sys
import urllib.parse
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import guest_path  # noqa: E402
import guest_path_weeks as gpw  # noqa: E402
import new_here as nh  # noqa: E402
import sb_clients  # noqa: E402

BIZ = "6c1c2d3e-4f50-4a61-8b72-9c83d4e5f601"
MARIA = "6c000000-0000-4000-8000-000000000001"
LEE = "6c000000-0000-4000-8000-000000000002"
RENEE = "6c000000-0000-4000-8000-000000000003"
PAT = "6c000000-0000-4000-8000-000000000004"
DENISE = "6c000000-0000-4000-8000-0000000000d1"
KIM = "6c000000-0000-4000-8000-0000000000d2"
HOME = "6c000000-0000-4000-8000-0000000000f1"
MOD = "6c000000-0000-4000-8000-0000000000e1"
LUNCH = "6c000000-0000-4000-8000-0000000000e2"
GROUP = "6c000000-0000-4000-8000-0000000000a1"
PHONE = "+12315550142"
ET = ZoneInfo("America/New_York")


def at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ET)


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


FIRST = at(2026, 11, 1, 10, 30)          # a Sunday: Maria's first visit (the kids desk)


# ─── a PostgREST-shaped fake ─────────────────────────────────────────

def _value(row, key):
    if "->" not in key:
        return row.get(key)
    parts = key.replace("->>", "->").split("->")
    v = row.get(parts[0])
    for p in parts[1:]:
        v = v.get(p) if isinstance(v, dict) else None
    if key.split("->")[-1].startswith(">") and v is not None and not isinstance(v, str):
        return json.dumps(v)                       # ->> is text
    return v


def _cmp(row, key, op):
    v = _value(row, key)
    name, _, want = op.partition(".")
    if name == "not":
        return not _cmp(row, key, want)
    if isinstance(v, bool):
        v = "true" if v else "false"
    if name == "eq":
        return v is not None and str(v) == want
    if name == "neq":
        return v is not None and str(v) != want
    if name == "is":
        return v is None if want == "null" else str(v).lower() == want
    if name == "in":
        return v is not None and str(v) in [x.strip('"') for x in want.strip("()").split(",")]
    if name == "like":
        import fnmatch
        return v is not None and fnmatch.fnmatch(str(v), want.replace("%", "*"))
    if name in ("gte", "gt", "lte", "lt"):
        if v is None:
            return False
        a = str(v)
        return {"gte": a >= want, "gt": a > want, "lte": a <= want, "lt": a < want}[name]
    raise AssertionError(f"filter not faked: {key}={op}")


def _matches(row, params):
    for k, v in params:
        if k in ("select", "order", "limit", "offset", "on_conflict"):
            continue
        if k == "or":
            alts = [c.split(".", 2) for c in v.strip("()").split(",")]
            if not any(_cmp(row, c, f"{o}.{w}") for c, o, w in alts):
                return False
        elif not _cmp(row, k, v):
            return False
    return True


class Fake:
    def __init__(self):
        self.biz = {"id": BIZ, "name": "Grace Hill Church", "type": "church", "owner_id": "o1",
                    "settings": {"new_here": {"on": True}}}
        self.t = {k: [] for k in (
            "contacts", "church_follow_ups", "church_follow_up_notes", "attendance", "household_adults",
            "child_checkins", "children", "group_members", "groups", "academy_enrollments",
            "chief_scheduled_actions", "church_role_defs", "church_leader_roles", "church_shepherd_notices",
            "custom_modules", "module_entries", "sms_opt_outs", "audit_log", "sms_messages")}
        self.t["sms_numbers"] = [{"business_id": BIZ, "status": "active", "phone_number": "+12315550199"}]
        self.down = set()

    @staticmethod
    def _split(path):
        table, _, qs = path.lstrip("/").partition("?")
        return table, urllib.parse.parse_qsl(qs, keep_blank_values=True)

    def get(self, path, **kw):
        table, params = self._split(path)
        if table in self.down:
            return None
        if table == "businesses":
            return [copy.deepcopy(self.biz)]
        rows = [r for r in self.t.get(table, []) if _matches(r, params)]
        p = dict(params)
        order = p.get("order")
        if order:
            key, _, how = order.split(",")[0].partition(".")
            rows = sorted(rows, key=lambda r: str(r.get(key) or ""), reverse=how.startswith("desc"))
        off = int(p.get("offset") or 0)
        rows = rows[off:]
        if p.get("limit"):
            rows = rows[:int(p["limit"])]
        return copy.deepcopy(rows)

    def post(self, path, body, *a, prefer="return=representation", **kw):
        table, params = self._split(path)
        if table in self.down:
            return None
        conflict = dict(params).get("on_conflict")
        out = []
        for r in body if isinstance(body, list) else [body]:
            r = copy.deepcopy(r)
            if conflict:
                keys = conflict.split(",")
                if any(all(str(x.get(k)) == str(r.get(k)) for k in keys) for x in self.t.get(table, [])):
                    continue
            r.setdefault("id", str(uuid.uuid4()))
            out.append(r)
        self.t.setdefault(table, []).extend(out)
        return copy.deepcopy(out)

    def patch(self, path, body, **kw):
        table, params = self._split(path)
        if table in self.down:
            return None
        rows = [r for r in self.t.get(table, []) if _matches(r, params)]
        for r in rows:
            r.update(copy.deepcopy(body))
        return copy.deepcopy(rows)

    def delete(self, path):
        table, params = self._split(path)
        self.t[table] = [r for r in self.t.get(table, []) if not _matches(r, params)]
        return True

    # ── the church's people ──
    def guest(self, cid=MARIA, name="Maria Lopez", start=FIRST, door="kids", texts="on", phone=PHONE, **extra):
        mine = {"door": door, "texted_at": _iso(start), "texts_ok": texts == "on", "texts": texts,
                "code": "ABCDEFGH", "visits": 1, **extra}
        row = {"id": cid, "business_id": BIZ, "name": name, "phone": phone, "email": None,
               "created_at": _iso(start), "metadata": {"other": 1, "new_here": mine}}
        self.t["contacts"].append(row)
        self.t["chief_scheduled_actions"].append({
            "id": str(uuid.uuid4()), "business_id": BIZ, "status": "done", "run_at": _iso(start),
            "action": {"type": nh.KIND, "step": "welcome", "contact_id": cid, "phone": phone,
                       "texted_at": _iso(start), "door": door}})
        return row

    def contact(self, cid=MARIA):
        return next(c for c in self.t["contacts"] if c["id"] == cid)

    def mine(self, cid=MARIA):
        return self.contact(cid)["metadata"]["new_here"]

    def path(self, cid=MARIA):
        return self.mine(cid).get("path") or {}

    def checked_in(self, cid, when):
        self.t["attendance"].append({"id": str(uuid.uuid4()), "business_id": BIZ, "contact_id": cid,
                                     "checked_in_at": _iso(when)})

    def person(self, cid, name, email):
        self.t["contacts"].append({"id": cid, "business_id": BIZ, "name": name, "phone": None, "email": email,
                                   "metadata": {}})

    def role(self, key, job, cid):
        self.t["church_role_defs"].append({"id": str(uuid.uuid4()), "business_id": BIZ, "key": key, "title": key,
                                           "job": job, "status": "active", "sort": 0})
        self.t["church_leader_roles"].append({"business_id": BIZ, "contact_id": cid, "role": key,
                                              "status": "active"})

    def lunch(self, when="2026-11-22T12:30"):
        self.t["custom_modules"] = [{"id": MOD, "business_id": BIZ, "archetype": "event_roster", "is_active": True,
                                     "name": "Services & Events", "archetype_params": {}}]
        self.t["module_entries"] = [{"id": LUNCH, "business_id": BIZ, "module_id": MOD, "status": "active",
                                     "data": {"title": "Newcomers Lunch", "date": when}}]
        self.biz["settings"]["new_here"]["next_step"] = {"on": True, "event_id": LUNCH}


@pytest.fixture
def db(monkeypatch):
    f = Fake()
    f.now = FIRST
    f.on = True
    f.pastor = {"name": "James Carter", "title": "Lead Pastor"}
    import member_pastor
    import sample_church
    import sms_alerts
    import sms_routing
    import sms_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service", f.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", f.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", f.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", f.delete)
    monkeypatch.setattr(guest_path, "mode", lambda: "on" if f.on else "off")
    monkeypatch.setattr(guest_path, "switched_on", lambda bid: f.on)
    monkeypatch.setattr(nh, "switched_on", lambda bid: True)
    monkeypatch.setattr(nh, "tz_of", lambda business: ET)
    monkeypatch.setattr(nh, "_now", lambda: f.now.astimezone(timezone.utc))
    # The weeks' own clock too: the room's "coming events" read it (guest_path_weeks.events), and
    # on the real clock the Newcomers Lunch (2026-11-22 12:30) stopped being upcoming that afternoon.
    monkeypatch.setattr(gpw, "_now", lambda: f.now.astimezone(timezone.utc))
    monkeypatch.setattr(nh, "_origin", lambda bid: "https://gracehill.church")
    monkeypatch.setattr(sample_church, "exclude", lambda col="business_id": "")
    monkeypatch.setattr(sample_church, "drop_samples", lambda rows, key="business_id": list(rows or []))
    monkeypatch.setattr(sample_church, "skip", lambda biz: False)
    monkeypatch.setattr(member_pastor, "who", lambda biz: dict(f.pastor) if f.pastor else {})
    f.texts, f.stopped = [], set()

    async def send(phone, body, business_id=None, client=None):
        f.texts.append((phone, body))
        return "SM1"

    async def store(client, *a, **kw):
        return None

    async def stopped(client, phone, business_id=None):
        return phone in f.stopped

    monkeypatch.setattr(sms_routing, "_send_platform_sms", send)
    monkeypatch.setattr(sms_service, "_store_sms", store)
    monkeypatch.setattr(sms_service, "is_opted_out", stopped)
    monkeypatch.setattr(sms_alerts, "alerts_enabled", lambda: True)
    return f


def tick(db, when):
    db.now = when
    return gpw.sweep_tick(now=when.astimezone(timezone.utc))


def bodies(db):
    return [b for _, b in db.texts]


# ── 1. the roads' timing ──────────────────────────────────────────────

def test_week_two_is_the_first_wednesday_eight_days_on():
    assert gpw.week_two(date(2026, 11, 1)) == date(2026, 11, 11)        # a Sunday visit: the Wednesday after next
    assert gpw.week_two(date(2026, 11, 4)) == date(2026, 11, 18)        # a Wednesday: never beside week one's invite
    assert gpw.week_two(date(2026, 11, 7)) == date(2026, 11, 18)        # a Saturday
    assert gpw.week_two(date(2026, 11, 2)) == date(2026, 11, 11)        # a Monday


def test_not_yet_thinking_of_you_week_two_wednesday_at_11_once(db):
    db.guest()
    tick(db, at(2026, 11, 11, 10, 50))
    assert db.texts == []
    tick(db, at(2026, 11, 11, 11, 5))
    assert bodies(db) == ["Grace Hill Church: Thinking of you this week, Maria. No need to reply. We're glad you came."]
    assert db.path()["sent"]["thinking"] == _iso(at(2026, 11, 11, 11, 5))
    assert db.path()["log"] == [_iso(at(2026, 11, 11, 11, 5))] and "claim" not in db.path()
    tick(db, at(2026, 11, 11, 11, 20))
    assert len(db.texts) == 1                                           # once a path


def test_not_yet_week_four_the_door_is_open_then_the_texts_rest(db):
    db.guest(path={"for": _iso(FIRST), "sent": {"thinking": _iso(at(2026, 11, 11, 11))},
                   "log": [_iso(at(2026, 11, 11, 11))]})
    tick(db, at(2026, 11, 18, 11, 5))
    assert db.texts == []                                               # no event picked: no next step
    tick(db, at(2026, 11, 25, 11, 5))
    assert bodies(db) == ["Grace Hill Church: We're still so glad you visited, Maria. Our door is always open, "
                          "any Sunday."]
    for day in (26, 27, 28):
        tick(db, at(2026, 11, day, 11, 5))
    tick(db, at(2026, 12, 2, 11, 5))
    assert len(db.texts) == 1                                           # then they rest


def test_came_back_so_good_to_see_you_three_hours_after_they_arrive(db):
    db.guest()
    db.checked_in(MARIA, at(2026, 11, 8, 10, 15))
    tick(db, at(2026, 11, 8, 13, 5))
    assert db.texts == []
    tick(db, at(2026, 11, 8, 13, 20))
    assert bodies(db) == ["Grace Hill Church: So good to see you again, Maria! We'd love to help you find your place "
                          "here."]
    tick(db, at(2026, 11, 11, 11, 5))                                   # came back: no "thinking of you"
    tick(db, at(2026, 11, 25, 11, 5))                                   # nor "the door is open"
    assert len(db.texts) == 1


def test_came_back_late_in_the_day_the_last_slot_or_nothing(db):
    db.guest()
    db.checked_in(MARIA, at(2026, 11, 8, 19, 0))
    tick(db, at(2026, 11, 8, 19, 46))
    assert len(db.texts) == 1                                           # 7:45 PM, the day's last slot
    db.t["contacts"].clear()
    db.texts.clear()
    db.t["attendance"].clear()
    db.guest()
    db.checked_in(MARIA, at(2026, 11, 8, 19, 40))
    tick(db, at(2026, 11, 8, 19, 46))
    tick(db, at(2026, 11, 9, 13, 0))
    assert db.texts == []                                               # too late that day, and only that day


def test_the_kids_desk_for_their_family_is_coming_back(db):
    db.guest()
    db.t["household_adults"].append({"business_id": BIZ, "household_id": HOME, "contact_id": MARIA})
    db.t["child_checkins"].append({"id": "k1", "business_id": BIZ, "household_id": HOME,
                                   "checked_in_at": _iso(at(2026, 11, 8, 9, 50))})
    tick(db, at(2026, 11, 8, 12, 55))
    assert [b.split(": ", 1)[1][:16] for b in bodies(db)] == ["So good to see y"]


def test_the_next_step_names_the_churchs_own_event_in_week_three(db):
    db.lunch()
    db.guest()
    db.checked_in(MARIA, at(2026, 11, 8, 10, 15))
    tick(db, at(2026, 11, 8, 13, 20))
    tick(db, at(2026, 11, 18, 11, 5))
    assert bodies(db)[-1] == ("Grace Hill Church: Maria, our Newcomers Lunch is Sunday, November 22 at 12:30 PM. "
                              "We'd love for you to come. Just reply and we'll save your seats.")
    assert len(db.texts) == 2


def test_the_next_step_is_skipped_when_none_is_picked_or_it_has_passed(db):
    db.lunch(when="2026-11-17T12:30")                                   # over before week three
    db.guest(path={"for": _iso(FIRST), "sent": {"thinking": _iso(at(2026, 11, 11, 11))}})
    tick(db, at(2026, 11, 18, 11, 5))
    assert db.texts == []
    db.lunch(when="2026-11-18T13:00")                                   # too close: three hours or less
    tick(db, at(2026, 11, 18, 11, 10))
    assert db.texts == []


def test_a_plan_your_visit_guest_who_hasnt_come_gets_no_road_text(db):
    db.guest(door="form", start=FIRST)
    db.t["church_follow_ups"].append({"id": "f1", "business_id": BIZ, "contact_id": MARIA, "card_key": "form:F1",
                                      "path_kind": "visit", "status": "open", "step": 0,
                                      "created_at": _iso(FIRST), "answers": []})
    tick(db, at(2026, 11, 11, 11, 5))
    assert db.texts == []


# ── 2. connected ends the path ────────────────────────────────────────

def test_connected_ends_the_path(db):
    db.guest()
    db.t["groups"].append({"id": GROUP, "business_id": BIZ, "active": True, "kind": "small_group"})
    db.t["group_members"].append({"business_id": BIZ, "group_id": GROUP, "contact_id": MARIA,
                                  "joined_on": "2026-11-05"})
    tick(db, at(2026, 11, 11, 11, 5))
    assert db.texts == [] and db.path()["ended"]["why"] == "connected"
    tick(db, at(2026, 11, 25, 11, 5))
    assert db.texts == []


def test_a_connected_read_that_fails_decides_nothing(db):
    db.guest()
    db.down.add("group_members")
    tick(db, at(2026, 11, 11, 11, 5))
    assert db.texts == [] and "ended" not in db.path()
    db.down.clear()
    tick(db, at(2026, 11, 11, 11, 20))
    assert len(db.texts) == 1


# ── 3. the limits ─────────────────────────────────────────────────────

def test_the_limits():
    start = at(2026, 11, 1, 10, 30)
    four = {"texted_at": _iso(start), "door": "kids",
            "path": {"log": [_iso(start + timedelta(hours=h)) for h in (0, 3, 24, 96)]}}
    assert gpw.limit_says(four, start + timedelta(days=5)) == "week"
    assert gpw.limit_says(four, start + timedelta(days=7, hours=1)) == ""
    # The text door's welcome (the reply to their word) counts too.
    three = {"texted_at": _iso(start), "path": {"log": [_iso(start + timedelta(hours=h)) for h in (3, 24, 96)]}}
    assert gpw.limit_says(three, start + timedelta(days=5)) == "week"
    after = {"texted_at": _iso(start), "door": "kids",
             "path": {"log": [_iso(start + timedelta(days=8))]}}
    assert gpw.limit_says(after, start + timedelta(days=10)) == "one_a_week"
    assert gpw.limit_says(after, start + timedelta(days=15, hours=1)) == ""


def test_one_a_week_after_week_one_waits_then_skips_with_why(db):
    db.guest(path={"for": _iso(FIRST), "log": [_iso(at(2026, 11, 9, 12))]})
    tick(db, at(2026, 11, 11, 11, 5))
    assert db.texts == [] and db.path()["waits"] == {"thinking": "one_a_week"}
    tick(db, at(2026, 11, 12, 11, 5))
    assert db.texts == []
    assert db.path()["skipped"]["thinking"]["why"] == "one_a_week" and db.path()["waits"] == {}


def test_a_week_one_text_obeys_the_limits_too(db):
    db.guest(path={"for": _iso(FIRST), "log": [_iso(FIRST + timedelta(hours=h)) for h in (0, 3, 24, 50)]})
    db.now = at(2026, 11, 5, 18)
    act = {"type": nh.KIND, "step": "invite", "contact_id": MARIA, "phone": PHONE, "texted_at": _iso(FIRST),
           "door": "kids"}
    ok, what = asyncio.run(nh.run_scheduled(db.biz, act))
    assert ok and "Four texts" in what and db.texts == []


# ── 4. hold ───────────────────────────────────────────────────────────

def test_a_held_road_text_waits_and_goes_once_the_hold_clears(db):
    db.guest(hold=True, hold_since=_iso(at(2026, 11, 10, 20)))
    tick(db, at(2026, 11, 11, 11, 5))
    assert db.texts == [] and db.path()["waits"] == {"thinking": "held"}
    db.mine()["hold"] = False
    tick(db, at(2026, 11, 11, 15, 5))
    assert len(db.texts) == 1 and db.path()["sent"]["thinking"] and db.path()["waits"] == {}


def test_a_road_text_held_more_than_a_day_is_skipped_with_why(db):
    db.guest(hold=True)
    tick(db, at(2026, 11, 11, 11, 5))
    tick(db, at(2026, 11, 12, 11, 5))
    assert db.texts == [] and db.path()["skipped"]["thinking"]["why"] == "held"
    db.mine()["hold"] = False
    tick(db, at(2026, 11, 12, 12, 0))
    assert db.texts == []                                              # skipped is skipped


def monday_action():
    return {"type": nh.KIND, "step": "monday", "contact_id": MARIA, "phone": PHONE, "texted_at": _iso(FIRST),
            "door": "kids"}


def test_a_week_one_text_found_held_is_kept_and_sent_later(db):
    db.guest(hold=True)
    db.now = at(2026, 11, 2, 10)
    ok, what = asyncio.run(nh.run_scheduled(db.biz, monday_action()))
    assert ok and "waits" in what and db.texts == []
    waiting = db.path()["waiting"]["monday"]
    assert waiting["moment"] == _iso(at(2026, 11, 2, 10)) and waiting["action"]["step"] == "monday"
    tick(db, at(2026, 11, 2, 12, 5))
    assert db.texts == []                                              # still held
    db.mine()["hold"] = False
    tick(db, at(2026, 11, 2, 14, 5))
    assert bodies(db) == ["Grace Hill Church: Hi Maria, is there anything we can pray with you about this week? "
                          "Just reply. A real person reads every text. Pastor James"]
    assert db.path()["waiting"] == {} and "claim" not in db.path()
    assert db.path()["log"] == [_iso(at(2026, 11, 2, 14, 5))]
    tick(db, at(2026, 11, 2, 14, 20))
    assert len(db.texts) == 1


def test_a_week_one_text_held_more_than_a_day_is_skipped_with_why(db):
    db.guest(hold=True)
    db.now = at(2026, 11, 2, 10)
    asyncio.run(nh.run_scheduled(db.biz, monday_action()))
    db.mine()["hold"] = False
    tick(db, at(2026, 11, 3, 10, 5))
    assert db.texts == [] and db.path()["waiting"] == {}
    assert db.path()["skipped"]["week_one:monday"]["why"] == "held"


def test_a_held_thank_you_never_goes_the_next_day(db):
    db.guest(hold=True)
    db.now = at(2026, 11, 1, 13, 30)
    asyncio.run(nh.run_scheduled(db.biz, {**monday_action(), "step": "thanks"}))
    db.mine()["hold"] = False
    tick(db, at(2026, 11, 2, 9, 5))
    assert db.texts == [] and db.path()["skipped"]["week_one:thanks"]["why"] == "held"


def test_hold_is_honored_only_with_the_path_on(db):
    db.guest(hold=True)
    db.on = False
    db.now = at(2026, 11, 2, 10)
    db.mine()["door"] = "text"                                          # the text door's texts go on as before
    ok, what = asyncio.run(nh.run_scheduled(db.biz, {**monday_action(), "door": "text"}))
    assert ok and what.startswith("Sent") and "Pastor" not in bodies(db)[0]


# ── 5. the Monday note's signature ────────────────────────────────────

def test_the_monday_note_is_signed_by_the_senior_pastor(db):
    db.guest()
    db.now = at(2026, 11, 2, 10)
    asyncio.run(nh.run_scheduled(db.biz, monday_action()))
    assert bodies(db)[-1].endswith("A real person reads every text. Pastor James")


@pytest.mark.parametrize("pastor,setting,ends", [
    (None, {}, "every text."),                                          # nobody in the senior role: no signature
    ({"name": "James Carter", "title": "Lead Pastor"}, {"on": False}, "every text."),
    ({"name": "James Carter", "title": "Lead Pastor"}, {"on": True, "name": "Pastor J. Carter"}, "Pastor J. Carter"),
    ({"name": "Ruth Hale", "title": "Elders (Shepherds)"}, {}, "Ruth Hale"),
])
def test_the_signature_with_and_without_a_pastor(db, pastor, setting, ends):
    db.pastor = pastor
    if setting:
        db.biz["settings"]["new_here"]["signature"] = setting
    db.guest()
    db.now = at(2026, 11, 2, 10)
    asyncio.run(nh.run_scheduled(db.biz, monday_action()))
    assert bodies(db)[-1].endswith(ends)


def test_the_pastors_signature_words():
    assert gpw.pastor_signature("James Carter", "Lead Pastor") == "Pastor James"
    assert gpw.pastor_signature("Rev. James Carter", "Lead Pastor") == "Rev. James Carter"
    assert gpw.pastor_signature("James Carter", "Rector, Pastor or Priest") == "Pastor James"
    assert gpw.pastor_signature("", "Lead Pastor") == ""
    assert gpw.sign("Hi. Pastor James", "Pastor James") == "Hi. Pastor James"     # never twice
    assert gpw.sign("Hi.", "") == "Hi."


# ── 6. the Saturday heads-up ──────────────────────────────────────────

SATURDAY = at(2026, 11, 14, 9, 5)


@pytest.fixture
def team(db, monkeypatch):
    told = []
    monkeypatch.setattr(gpw, "_email_person", lambda biz, p, words, ref: told.append(("email", p["name"], words))
                        or True)
    monkeypatch.setattr(gpw, "_tell_login", lambda ch, uid, words, ref: told.append(("login", uid, words)) or True)
    import church_duties
    monkeypatch.setattr(church_duties, "manager_holders", lambda biz, duty: ["u-care"])
    monkeypatch.setattr(church_duties, "holders_of", lambda biz, duty: ["o1", "u-care"])
    # Maria came Sunday the 8th with her kids; Lee came back; Renee plans to
    # come tomorrow; Pat plans another Sunday.
    db.guest(start=at(2026, 11, 8, 10, 30), texts="no_yes")
    db.t["household_adults"].append({"business_id": BIZ, "household_id": HOME, "contact_id": MARIA})
    db.t["children"] += [{"id": "c2", "business_id": BIZ, "household_id": HOME, "first_name": "Mateo",
                          "birthdate": "2022-03-01", "active": True},
                         {"id": "c1", "business_id": BIZ, "household_id": HOME, "first_name": "Sofia",
                          "birthdate": "2019-05-01", "active": True}]
    db.guest(LEE, "Lee Park", start=at(2026, 11, 1, 10, 30))
    db.checked_in(LEE, at(2026, 11, 8, 10))
    for cid, name, said in ((RENEE, "Renee Ellis", "2026-11-15"), (PAT, "Pat Moore", "2026-11-22")):
        db.guest(cid, name, start=at(2026, 11, 11, 20), door="form")
        db.t["church_follow_ups"].append({"id": f"f-{cid}", "business_id": BIZ, "contact_id": cid,
                                          "card_key": "form:F1", "card_name": "Plan your visit",
                                          "path_kind": "visit", "status": "open", "step": 0,
                                          "created_at": _iso(at(2026, 11, 11, 20)),
                                          "answers": [{"q": "Which Sunday?", "a": said}]})
    db.person(DENISE, "Denise Ward", "denise@example.test")
    db.person(KIM, "Kim Lee", "kim@example.test")
    db.role("welcome_lead", "welcome", DENISE)
    db.role("kids_lead", "kids", KIM)
    return told


def test_the_heads_up_goes_to_the_greeters_and_the_kids_desk(db, team):
    tick(db, at(2026, 11, 14, 8, 55))
    assert team == []                                                   # 9 AM, not before
    tick(db, SATURDAY)
    assert [(k, who) for k, who, _ in team] == [("email", "Denise Ward"), ("email", "Kim Lee")]
    greeters, kids = team[0][2], team[1][2]
    assert greeters["subject"] == "Guests who may come tomorrow"
    assert "• Maria Lopez, with Sofia and Mateo · first came Sunday, November 8" in greeters["text"]
    assert "• Renee Ellis · planning a first visit" in greeters["text"]
    assert "Lee Park" not in greeters["text"] and "Pat Moore" not in greeters["text"]
    assert kids["text"].count("•") == 1 and "Maria Lopez’s kids, Sofia and Mateo" in kids["text"]
    assert PHONE not in greeters["text"] + kids["text"]
    assert [r["key"] for r in db.t["church_shepherd_notices"]] == ["guest-heads-up-2026-11-14-sat"]
    tick(db, at(2026, 11, 14, 9, 20))
    assert len(team) == 2                                               # once per Saturday


def test_no_welcome_team_the_first_time_guests_login_hears(db, team):
    db.t["church_leader_roles"] = [r for r in db.t["church_leader_roles"] if r["role"] != "welcome_lead"]
    tick(db, SATURDAY)
    assert [(k, who) for k, who, _ in team] == [("login", "u-care"), ("email", "Kim Lee")]


def test_the_heads_up_toggles_and_its_day(db, team):
    db.biz["settings"]["new_here"]["heads_up"] = {"greeters": False, "kids": True}
    tick(db, SATURDAY)
    assert [(k, who) for k, who, _ in team] == [("email", "Kim Lee")]
    team.clear()
    db.t["church_shepherd_notices"].clear()
    db.biz["settings"]["new_here"]["heads_up"] = {"greeters": False, "kids": False}
    tick(db, at(2026, 11, 14, 9, 35))
    tick(db, at(2026, 11, 13, 9, 5))                                    # a Friday
    assert team == [] and db.t["church_shepherd_notices"] == []


def test_a_heads_up_nobody_got_is_tried_again(db, team, monkeypatch):
    monkeypatch.setattr(gpw, "_email_person", lambda *a: False)
    tick(db, SATURDAY)
    assert db.t["church_shepherd_notices"] == []


# ── 7. claims ─────────────────────────────────────────────────────────

def test_a_send_in_flight_is_never_sent_twice(db):
    db.guest(path={"for": _iso(FIRST), "claim": {"step": "thinking", "at": _iso(at(2026, 11, 11, 11, 0)) + "#1"}})
    tick(db, at(2026, 11, 11, 11, 5))
    assert db.texts == []
    tick(db, at(2026, 11, 11, 11, 20))                                  # the claim went stale: maybe it went
    assert db.texts == [] and db.path()["skipped"]["thinking"]["why"] == "unsure" and "claim" not in db.path()


def test_a_claim_changes_nothing_else_someone_wrote(db):
    """A write finds the hold and the path's start as it read them, or tries again."""
    db.guest()
    real = db.patch
    calls = []

    def racing(path, body, **kw):
        calls.append(path)
        if len(calls) == 1:
            db.mine()["hold"] = True                                    # a reply came in between
        return real(path, body, **kw)

    db.now = at(2026, 11, 11, 11, 5)
    import sb_clients as sbc
    sbc.sb_patch_as_service = racing
    try:
        tick(db, at(2026, 11, 11, 11, 5))
    finally:
        sbc.sb_patch_as_service = real
    assert db.texts == [] and db.mine()["hold"] is True


def test_stop_ends_the_texts(db):
    db.guest()
    db.stopped.add(PHONE)
    tick(db, at(2026, 11, 11, 11, 5))
    assert db.texts == [] and db.path()["skipped"]["thinking"]["why"] == "stopped" and "claim" not in db.path()


def test_no_yes_no_road_texts(db):
    db.guest(texts="no_yes")
    tick(db, at(2026, 11, 11, 11, 5))
    assert db.texts == []


# ── 8. settings ───────────────────────────────────────────────────────

def test_the_defaults_and_a_saved_setting():
    s = nh.settings_of({"settings": {}})
    assert s["back"]["on"] and s["thinking"]["on"] and s["door_open"]["on"]
    assert s["next_step"] == {"on": True, "event_id": None, "text": nh.DEFAULTS["next_step"]["text"]}
    assert s["signature"] == {"on": True, "name": ""} and s["heads_up"] == {"greeters": True, "kids": True}
    saved = nh.settings_of({"settings": {"new_here": {
        "next_step": {"on": True, "event_id": "nope", "text": "Come to {event}"},
        "signature": {"on": False, "name": "  Pastor   J  "}, "heads_up": {"kids": False}}}})
    assert saved["next_step"]["event_id"] is None and "{when}" in saved["next_step"]["text"]
    assert saved["signature"] == {"on": False, "name": "Pastor J"} and saved["heads_up"] == {"greeters": True,
                                                                                               "kids": False}


def _body(**over):
    base = {"on": True, "word": "NEW", "welcome": nh.DEFAULTS["welcome"],
            "thanks": {"on": True, "text": "Thanks {first name}!", "hours": 3},
            "monday": {"on": True, "text": "Hi"}, "invite": {"on": True, "text": "Come back"}}
    return {**base, **over}


def test_what_the_path_texts_must_keep():
    for bad, why in (({"thinking": {"on": True, "text": "Here {card link}"}}, "Only the welcome"),
                     ({"back": {"on": True, "text": "Reply YES to come"}}, "just reply"),
                     ({"next_step": {"on": True, "text": "Come to lunch"}}, "{event} and {when}"),
                     ({"next_step": {"on": True, "text": "{event} {when}", "event_id": "x"}}, "upcoming")):
        with pytest.raises(HTTPException) as e:
            nh.clean(nh.NewHereIn(**_body(**bad)))
        assert e.value.status_code == 400 and why in e.value.detail, why
    old = nh.clean(nh.NewHereIn(**_body()))
    assert not set(old) & {"back", "thinking", "next_step", "door_open", "signature", "heads_up"}


@pytest.fixture
def room(db, monkeypatch):
    import business_access
    from auth_supabase import AuthedUser, require_user
    from settings_merge_fake import install
    monkeypatch.setattr(business_access, "assert_access", lambda biz, user, role: "admin")
    monkeypatch.setattr(nh, "_may_edit", lambda biz, user: True)
    import care_handoff
    import church_duties
    monkeypatch.setattr(care_handoff, "_called", lambda ch, uid: "Tiara")
    monkeypatch.setattr(church_duties, "manager_holders", lambda biz, duty: ["u-care"])
    calls = install(monkeypatch, lambda bid: db.biz)
    app = FastAPI()
    app.include_router(nh.router)
    app.dependency_overrides[require_user] = lambda: AuthedUser(id="u1", email="o@x.test", role="authenticated")
    return TestClient(app), calls


def test_the_room_round_trip_and_an_old_clients_put(db, room):
    c, calls = room
    db.lunch()
    db.now = at(2026, 11, 10, 9)
    got = c.get(f"/new-here/{BIZ}").json()
    path = got["path"]
    assert path["signer"] == "Pastor James" and path["signer_from"] == "role"
    assert [e["entry_id"] for e in path["events"]] == [LUNCH] and path["event"]["title"] == "Newcomers Lunch"
    assert path["limits"] == {"week": 4, "after_week_one": 1}
    assert path["heads_up_to"] == {"greeters": ["Tiara"], "greeters_from": "first_guests", "kids": []}
    full = _body(back={"on": False, "text": "So good, {first name}!"},
                 next_step={"on": True, "event_id": LUNCH, "text": "{first name}: {event}, {when}."},
                 signature={"on": True, "name": "Pastor J"}, heads_up={"greeters": True, "kids": False})
    r = c.put(f"/new-here/{BIZ}", json=full)
    assert r.status_code == 200, r.text
    saved = db.biz["settings"]["new_here"]
    assert saved["back"] == {"on": False, "text": "So good, {first name}!"}
    assert saved["signature"] == {"on": True, "name": "Pastor J"} and saved["heads_up"]["kids"] is False
    # Text › New here, or an app from before: none of the new keys sent, none wiped.
    r = c.put(f"/new-here/{BIZ}", json=_body(monday={"on": True, "text": "Hello"}))
    assert r.status_code == 200
    saved = db.biz["settings"]["new_here"]
    assert saved["monday"]["text"] == "Hello" and saved["back"]["on"] is False
    assert saved["signature"]["name"] == "Pastor J" and saved["next_step"]["event_id"] == LUNCH
    assert set(calls[-1]["set"]) == {"on", "word", "welcome", "thanks", "monday", "invite"}


def test_a_picked_event_must_be_coming_up(db, room):
    c, _ = room
    db.lunch(when="2026-11-01T12:30")
    db.biz["settings"]["new_here"].pop("next_step")
    db.now = at(2026, 11, 10, 9)
    r = c.put(f"/new-here/{BIZ}", json=_body(next_step={"on": True, "event_id": LUNCH, "text": "{event} {when}"}))
    assert r.status_code == 400 and "isn't coming up" in r.json()["detail"]


def test_the_room_shows_no_path_with_the_path_off(db, room):
    c, _ = room
    db.on = False
    assert "path" not in c.get(f"/new-here/{BIZ}").json()


# ── 9. switched off ───────────────────────────────────────────────────

def test_switched_off_nothing_at_all(db, monkeypatch):
    db.guest()
    db.on = False
    assert tick(db, at(2026, 11, 11, 11, 5))["sent"] == 0 and db.texts == []
    db.on = True
    monkeypatch.setattr(nh, "switched_on", lambda bid: False)          # NEW_HERE
    tick(db, at(2026, 11, 11, 11, 10))
    monkeypatch.setattr(nh, "switched_on", lambda bid: True)
    db.biz["settings"]["new_here"]["on"] = False                        # the church's own switch
    tick(db, at(2026, 11, 11, 11, 15))
    db.biz["settings"]["new_here"] = {"on": True, "thinking": {"on": False}}
    tick(db, at(2026, 11, 11, 11, 20))
    assert db.texts == [] and "path" not in db.mine()


def test_outside_the_churchs_hours_the_text_waits(db):
    db.biz["settings"]["texting_hours"] = {"auto_from": 12, "auto_until": 20}
    db.guest()
    tick(db, at(2026, 11, 11, 11, 5))
    assert db.texts == []
    tick(db, at(2026, 11, 11, 12, 5))                                   # moved inside its hours: noon
    assert len(db.texts) == 1


def test_the_wiring():
    src = (pathlib.Path(__file__).resolve().parent.parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert 'g("guest_path_weeks_sweep", _gpw.sweep_tick), "interval", minutes=15' in src
    run = (pathlib.Path(__file__).resolve().parent.parent / "new_here.py").read_text(encoding="utf-8")
    assert "gpw.wait_for_hold" in run and "gpw.limit_says" in run and "gpw.sign(" in run and "gpw.log_sent" in run


def test_a_hold_cleared_a_moment_ago_lets_the_text_go(db):
    db.guest(hold=True)
    held = copy.deepcopy(db.contact())
    db.mine()["hold"] = False                                           # answered between the two reads
    assert gpw.wait_for_hold(db.biz, held, monday_action(), at(2026, 11, 2, 10)) is None
    assert "waiting" not in db.path()
