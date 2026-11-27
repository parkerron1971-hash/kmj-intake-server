"""The Welcome Path, every door (2026-11-20).

Kevin, on the mock: "capture visitors, place them in a flow where they
receive automated texts from the church", then "build". Until now only a
guest who texted the word (NEW) got New here's texts; every other door handed
the guest to a leader and texted nothing. Pinned here:

  1. enroll: a guest from any door is on the path (door, texted_at, texts_ok,
     a card code, New here's own keys kept); with a yes the welcome is
     queued now and the week after it; the thank-you only for a guest who
     was at church that day
  2. when the texts can't go (no yes, no mobile, no church number, New here
     off, STOP, an unread STOP) the guest is still on the path, with why
  3. one guest, one path: a second door this week starts nothing, except
     the first set of texts when the first door had no yes
  4. switched off, not a church, not a door: nothing is written
  5. outside the church's texting hours the welcome waits for the morning
  6. the text door records its door; the word starts another door's texts
  7. the welcome goes through the scheduler, read again at send time
  8. New here's list shows every door; the card is never texted to a guest
     who said no
  9. a second door's card is a note on the first door's follow-up
 10. the yes: kept once, with where and how; the box shows only where a yes
     brings texts, in the carriers' words
 11. each door's hook: the website card, a church guest card (and its
     intake hand-off), the member app, the kids desk's Add a family
"""
from __future__ import annotations

import asyncio
import copy
import json
import pathlib
import sys
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import church_follow_up as cfu  # noqa: E402
import new_here as nh  # noqa: E402
import sb_clients  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402

BIZ = "5b1c2d3e-4f50-4a61-8b72-9c83d4e5f601"
GUEST = "5b000000-0000-4000-8000-000000000001"
OTHER = "5b000000-0000-4000-8000-000000000002"
PHONE = "+12315550142"
CHURCH_NUMBER = "+12315550199"
ET = ZoneInfo("America/New_York")


def at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ET)


SUNDAY = at(2026, 11, 15, 10, 42)


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── a PostgREST-shaped fake ─────────────────────────────────────────

def _cmp(row, key, op):
    v = row.get(key)
    if "->" in key:
        parts = key.replace("->>", "->").split("->")
        v = row.get(parts[0])
        for p in parts[1:]:
            v = v.get(p) if isinstance(v, dict) else None
    name, _, want = op.partition(".")
    if name == "eq":
        return v is not None and str(v) == want
    if name == "is":
        return v is None if want == "null" else str(v).lower() == want
    if name == "in":
        return str(v) in [x.strip('"') for x in want.strip("()").split(",")]
    if name in ("gte", "gt", "lte", "lt"):
        if v is None:
            return False
        a = str(v)
        return {"gte": a >= want, "gt": a > want, "lte": a <= want, "lt": a < want}[name]
    raise AssertionError(f"filter not faked: {key}={op}")


class Fake:
    def __init__(self):
        self.biz = {"id": BIZ, "name": "Grace Hill Church", "type": "church", "owner_id": "o1",
                    "settings": {"new_here": {"on": True}}}
        self.t = {"contacts": [], "sms_numbers": [{"business_id": BIZ, "status": "active",
                                                    "phone_number": CHURCH_NUMBER}],
                  "sms_opt_outs": [], "sms_consents": [], "church_follow_ups": [], "church_follow_up_notes": [],
                  "chief_scheduled_actions": [], "attendance": []}
        self.down = set()
        self.writes = []

    def person(self, cid=GUEST, name="Maria Lopez", phone=PHONE, metadata=None):
        row = {"id": cid, "business_id": BIZ, "name": name, "phone": phone, "tags": [],
               "metadata": copy.deepcopy(metadata if metadata is not None else {"other": 1})}
        self.t["contacts"].append(row)
        return row

    def contact(self, cid=GUEST):
        return next(c for c in self.t["contacts"] if c["id"] == cid)

    def mine(self, cid=GUEST):
        return (self.contact(cid).get("metadata") or {}).get("new_here") or {}

    def scheduled(self):
        return self.t["chief_scheduled_actions"]

    def steps(self):
        return sorted(r["action"]["step"] for r in self.scheduled())

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
        rows = []
        for r in self.t.get(table, []):
            ok = True
            for k, v in params:
                if k in ("select", "order", "limit"):
                    continue
                if k == "or":
                    alts = [c.split(".", 2) for c in v.strip("()").split(",")]
                    ok = ok and any(_cmp(r, c, f"{o}.{w}") for c, o, w in alts)
                else:
                    ok = ok and _cmp(r, k, v)
            if ok:
                rows.append(r)
        order = dict(params).get("order")
        if order:
            key, _, how = order.partition(".")
            rows = sorted(rows, key=lambda r: str(r.get(key) or ""), reverse=how.startswith("desc"))
        return copy.deepcopy(rows)

    def post(self, path, body, *a, **kw):
        table, _ = self._split(path)
        if table in self.down:
            return None
        out = []
        for r in body if isinstance(body, list) else [body]:
            r = copy.deepcopy(r)
            r.setdefault("id", str(uuid.uuid4()))
            r.setdefault("created_at", _iso(datetime.now(timezone.utc)))
            out.append(r)
        self.t.setdefault(table, []).extend(out)
        self.writes.append(("post", table, out))
        return copy.deepcopy(out)

    def patch(self, path, body, **kw):
        table, params = self._split(path)
        if table in self.down:
            return None
        rows = [r for r in self.t.get(table, []) if all(_cmp(r, k, v) for k, v in params)]
        for r in rows:
            r.update(copy.deepcopy(body))
        self.writes.append(("patch", table, rows))
        return copy.deepcopy(rows)


@pytest.fixture
def db(monkeypatch):
    f = Fake()
    f.now = SUNDAY
    f.path = True
    f.new_here = True
    monkeypatch.setattr(sb_clients, "sb_get_as_service", f.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", f.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", f.patch)
    monkeypatch.setattr(nh, "_now", lambda: f.now.astimezone(timezone.utc))
    monkeypatch.setattr(nh, "tz_of", lambda business: ET)
    monkeypatch.setattr(nh, "path_on", lambda bid: f.path)
    monkeypatch.setattr(nh, "switched_on", lambda bid: f.new_here)
    monkeypatch.setattr(nh, "_origin", lambda bid: "https://gracehill.church")
    return f


def said_yes(db, phone=PHONE, source="kids_checkin"):
    """This number already said yes to the church's texts (the kids desk, a
    YES reply): a website card from it starts the texts at once (M-5)."""
    db.t["sms_consents"].append({"business_id": BIZ, "phone": phone, "source": source})


def _when(db, step):
    row = next(r for r in db.scheduled() if r["action"]["step"] == step)
    return datetime.fromisoformat(row["run_at"]).astimezone(ET)


# ── 1. enroll: a door's guest with a yes ──────────────────────────────

def test_a_kids_desk_guest_with_a_yes_gets_the_welcome_now_and_the_week(db):
    db.person()
    mine = nh.enroll(db.biz, db.contact(), door="kids", texts_ok=True, visit_at=SUNDAY)
    saved = db.mine()
    assert mine == saved
    assert saved["door"] == "kids" and saved["texted_at"] == _iso(SUNDAY) and saved["texts_ok"] is True
    assert saved["texts"] == "on" and saved["welcome_at"] == _iso(SUNDAY) and saved["visits"] == 1
    assert len(saved["code"]) == nh.CODE_LEN
    assert db.contact()["metadata"]["other"] == 1                       # the rest of metadata kept
    assert db.steps() == ["invite", "monday", "thanks", "welcome"]
    assert _when(db, "welcome") == SUNDAY                               # now: inside the church's hours
    assert _when(db, "thanks") == at(2026, 11, 15, 13, 42)              # 3 hours after the visit
    assert _when(db, "monday") == at(2026, 11, 16, 10)
    assert _when(db, "invite") == at(2026, 11, 19, 18)
    assert all(r["action"]["type"] == nh.KIND and r["action"]["door"] == "kids" and r["action"]["phone"] == PHONE
               and r["action"]["contact_id"] == GUEST and r["business_id"] == BIZ for r in db.scheduled())


def test_new_heres_own_keys_are_kept(db):
    db.person(metadata={"new_here": {"code": "ABCDEFGH", "card_at": "2026-10-01T00:00:00Z",
                                     "app": {"at": "2026-10-01T00:00:00Z"}}})
    nh.enroll(db.biz, db.contact(), door="web", texts_ok=True)
    saved = db.mine()
    assert saved["code"] == "ABCDEFGH" and saved["card_at"] and saved["app"]["at"]


def test_a_guest_who_wasnt_seen_at_church_gets_no_thank_you(db):
    db.person()
    said_yes(db)
    nh.enroll(db.biz, db.contact(), door="web", texts_ok=True)
    assert db.steps() == ["invite", "monday", "welcome"]


def test_the_number_they_said_yes_for_is_the_one_texted(db):
    db.person(phone="+12315550000")
    nh.enroll(db.biz, db.contact(), door="web", texts_ok=True, phone="(231) 555-0142")
    assert {r["action"]["phone"] for r in db.scheduled()} == {PHONE}


# ── 2. when the texts can't go ────────────────────────────────────────

def test_without_a_yes_the_guest_is_on_the_path_and_nothing_is_texted(db):
    db.person()
    mine = nh.enroll(db.biz, db.contact(), door="desk", texts_ok=False, visit_at=SUNDAY)
    assert mine["door"] == "desk" and mine["texted_at"] == _iso(SUNDAY) and mine["texts_ok"] is False
    assert mine["texts"] == "no_yes" and "welcome_at" not in mine and mine["code"]
    assert db.scheduled() == []


@pytest.mark.parametrize("why", ["no_phone", "no_number", "new_here_off", "switch_off", "stopped", "unread"])
def test_why_the_texts_didnt_start(db, why):
    db.person(phone="" if why == "no_phone" else PHONE)
    if why == "no_number":
        db.t["sms_numbers"] = []
    elif why == "new_here_off":
        db.biz["settings"] = {"new_here": {"on": False}}
    elif why == "switch_off":
        db.new_here = False
    elif why == "stopped":
        db.t["sms_opt_outs"] = [{"phone": PHONE, "business_id": None}]
    elif why == "unread":
        db.down.add("sms_opt_outs")
    mine = nh.enroll(db.biz, db.contact(), door="kids", texts_ok=True, visit_at=SUNDAY)
    assert mine["door"] == "kids" and mine["texts_ok"] is True
    assert mine["texts"] == ("new_here_off" if why == "switch_off" else why)
    assert mine["texts"] in nh.WHY_NOT and db.scheduled() == []


def test_a_yes_that_cant_be_read_is_never_a_no_and_is_read_again(db):
    db.person()
    db.down.add("sms_consents")
    mine = nh.enroll_by_id(BIZ, GUEST, door="kids", texts_ok=None, visit_at=SUNDAY)
    assert mine["door"] == "kids" and mine["texts"] == "unread" and mine["texts_ok"] is False
    assert db.scheduled() == []
    # A door that says no this week never settles it; the next read does.
    assert nh.enroll(db.biz, db.contact(), door="web", texts_ok=False)["texts"] == "unread"
    db.down.discard("sms_consents")
    db.t["sms_consents"].append({"business_id": BIZ, "phone": PHONE, "source": "kids_checkin"})
    db.now = SUNDAY + timedelta(minutes=30)
    again = nh.enroll_by_id(BIZ, GUEST, door="kids", texts_ok=None, visit_at=SUNDAY)
    assert again["texts"] == "on" and again["texts_ok"] is True and again["texted_at"] == _iso(SUNDAY)
    assert "welcome" in db.steps()


def test_a_read_that_fails_once_is_tried_again(db, monkeypatch):
    db.person()
    db.t["sms_consents"].append({"business_id": BIZ, "phone": PHONE, "source": "kids_checkin"})
    answers = iter([None, True])
    monkeypatch.setattr(nh, "has_yes", lambda biz, phone: next(answers))
    assert nh.enroll_by_id(BIZ, GUEST, door="desk", texts_ok=None)["texts"] == "on"


def test_a_welcome_that_cant_be_queued_is_never_texts_on(db):
    db.person()
    db.down.add("chief_scheduled_actions")
    mine = nh.enroll(db.biz, db.contact(), door="kids", texts_ok=True, visit_at=SUNDAY)
    assert mine["texts"] == "unread" and "welcome_at" not in mine
    assert db.mine()["texts"] == "unread"
    # Nothing after the welcome was queued either; the next door with a yes tries again.
    db.down.discard("chief_scheduled_actions")
    assert db.scheduled() == []
    said_yes(db)
    again = nh.enroll(db.biz, db.contact(), door="web", texts_ok=True)
    assert again["texts"] == "on" and again["door"] == "kids" and "welcome" in db.steps()


def test_a_stop_at_another_church_is_not_this_churchs(db):
    db.person()
    db.t["sms_opt_outs"] = [{"phone": PHONE, "business_id": OTHER}]
    assert nh.enroll(db.biz, db.contact(), door="kids", texts_ok=True)["texts"] == "on"


# ── 3. one guest, one path ────────────────────────────────────────────

def test_one_guest_is_one_path(db):
    db.person()
    said_yes(db)
    nh.enroll(db.biz, db.contact(), door="kids", texts_ok=True, visit_at=SUNDAY)
    db.now = SUNDAY + timedelta(days=2)
    again = nh.enroll(db.biz, db.contact(), door="web", texts_ok=True)
    assert again["door"] == "kids" and again["texted_at"] == _iso(SUNDAY) and again["visits"] == 1
    assert len(db.scheduled()) == 4                                     # nothing queued twice
    # A week on, a door is a new visit: a new path, as a second NEW is.
    db.now = SUNDAY + timedelta(days=8)
    later = nh.enroll(db.biz, db.contact(), door="web", texts_ok=True)
    assert later["door"] == "web" and later["visits"] == 2 and len(db.scheduled()) == 7


def test_a_second_door_with_a_yes_starts_the_texts_the_first_had_none(db):
    db.person()
    nh.enroll(db.biz, db.contact(), door="kids", texts_ok=False, visit_at=SUNDAY)
    db.now = SUNDAY + timedelta(days=1, hours=1)                        # Monday 11:42
    mine = nh.enroll(db.biz, db.contact(), door="app", texts_ok=True)
    assert mine["door"] == "kids" and mine["texted_at"] == _iso(SUNDAY)  # still the kids desk's path
    assert mine["texts_ok"] is True and mine["texts"] == "on"
    assert db.steps() == ["invite", "monday", "welcome"]               # no "today" thank-you a day later
    # ...and a third door this week starts nothing more.
    nh.enroll(db.biz, db.contact(), door="form", texts_ok=True)
    assert len(db.scheduled()) == 3


def test_a_second_door_without_a_yes_never_undoes_one(db):
    db.person()
    said_yes(db)
    nh.enroll(db.biz, db.contact(), door="web", texts_ok=True)
    mine = nh.enroll(db.biz, db.contact(), door="desk", texts_ok=False)
    assert mine["texts_ok"] is True and mine["texts"] == "on" and mine["door"] == "web"


# ── 4. off, not a church, not a door ──────────────────────────────────

def test_switched_off_nothing_changes(db):
    db.person()
    db.path = False
    assert nh.enroll(db.biz, db.contact(), door="kids", texts_ok=True) is None
    assert nh.enroll_by_id(BIZ, GUEST, door="kids", texts_ok=True) is None
    db.path = True
    assert nh.enroll(dict(db.biz, type="salon"), db.contact(), door="kids", texts_ok=True) is None
    assert nh.enroll(db.biz, db.contact(), door="lobby", texts_ok=True) is None
    assert db.writes == []


def test_a_guest_that_doesnt_save_is_not_texted(db):
    db.person()
    db.down.add("contacts")
    assert nh.enroll(db.biz, db.contact(), door="kids", texts_ok=True) is None
    assert db.scheduled() == []


# ── 5. outside the church's hours ─────────────────────────────────────

def test_late_at_night_the_welcome_waits_for_the_morning(db):
    db.person()
    db.now = at(2026, 11, 15, 20, 30)
    nh.enroll(db.biz, db.contact(), door="kids", texts_ok=True, visit_at=db.now)
    assert db.mine()["welcome_at"] == _iso(at(2026, 11, 16, 9))
    assert _when(db, "welcome") == at(2026, 11, 16, 9)
    assert "thanks" not in db.steps()                                   # "today" would be wrong tomorrow
    assert _when(db, "monday") == at(2026, 11, 16, 10)


def test_early_in_the_morning_the_welcome_waits_and_the_thank_you_follows_it(db):
    db.person()
    db.now = at(2026, 11, 15, 7, 0)
    nh.enroll(db.biz, db.contact(), door="kids", texts_ok=True, visit_at=db.now)
    assert _when(db, "welcome") == at(2026, 11, 15, 9)
    assert _when(db, "thanks") == at(2026, 11, 15, 10)


def test_minutes_before_the_hours_close_it_waits_too(db):
    db.person()
    db.now = at(2026, 11, 15, 19, 55)
    said_yes(db)
    nh.enroll(db.biz, db.contact(), door="web", texts_ok=True)
    assert _when(db, "welcome") == at(2026, 11, 16, 9)


def test_the_churchs_own_hours(db):
    db.person()
    db.biz["settings"]["texting_hours"] = {"auto_from": 11, "auto_until": 18}
    db.now = at(2026, 11, 15, 10, 0)
    said_yes(db)
    nh.enroll(db.biz, db.contact(), door="web", texts_ok=True)
    assert _when(db, "welcome") == at(2026, 11, 15, 11)


# ── 6. the text door ──────────────────────────────────────────────────

def test_the_text_door_records_its_door(db):
    hit = nh.on_text(BIZ, PHONE, "NEW")
    assert hit and nh.CARD_LINK not in hit["text"]
    mine = db.t["contacts"][0]["metadata"]["new_here"]
    assert mine["door"] == "text" and mine["texts_ok"] is True and mine["texts"] == "on" and mine["visits"] == 1
    assert db.steps() == ["invite", "monday", "thanks"]                 # the welcome is the reply itself


def test_the_word_starts_the_texts_of_a_guest_another_door_left_without_them(db):
    db.person()
    nh.enroll(db.biz, db.contact(), door="kids", texts_ok=False, visit_at=SUNDAY)
    db.now = SUNDAY + timedelta(minutes=20)
    assert nh.on_text(BIZ, PHONE, "new")
    mine = db.mine()
    assert mine["door"] == "kids" and mine["texts_ok"] is True and mine["texts"] == "on" and mine["visits"] == 1
    assert db.steps() == ["invite", "monday", "thanks"]
    assert nh.on_text(BIZ, PHONE, "NEW") and len(db.scheduled()) == 3   # the same visit after that


def test_with_the_path_off_the_text_door_is_exactly_as_it_was(db):
    db.path = False
    nh.on_text(BIZ, PHONE, "NEW")
    mine = db.t["contacts"][0]["metadata"]["new_here"]
    assert set(mine) == {"code", "texted_at", "visits"}


# ── 7. the welcome, sent by the scheduler ─────────────────────────────

@pytest.fixture
def sender(db, monkeypatch):
    import sms_alerts
    import sms_routing
    import sms_service
    sent = {"texts": [], "stopped": False}

    async def send(phone, body, business_id=None, client=None):
        sent["texts"].append((phone, body))
        return "SM1"

    async def store(client, *a, **kw):
        return None

    async def stopped(client, phone, business_id=None):
        return sent["stopped"]
    monkeypatch.setattr(sms_routing, "_send_platform_sms", send)
    monkeypatch.setattr(sms_service, "_store_sms", store)
    monkeypatch.setattr(sms_service, "is_opted_out", stopped)
    monkeypatch.setattr(sms_alerts, "alerts_enabled", lambda: True)
    db.person(metadata={"new_here": {"code": "K7M2QX4P", "door": "kids", "texts": "on"}})
    return sent


def _action(step="welcome", door="kids"):
    return {"type": nh.KIND, "step": step, "contact_id": GUEST, "phone": PHONE,
            "texted_at": _iso(SUNDAY), "door": door}


def test_the_welcome_goes_in_the_churchs_words_with_the_card(sender, db):
    ok, what = asyncio.run(nh.run_scheduled(db.biz, _action()))
    assert ok and "welcome" in what
    [(phone, body)] = sender["texts"]
    assert phone == PHONE
    assert body.startswith("Grace Hill Church: Welcome! So glad you're here. Tell us about you: "
                           "https://gracehill.church/new/K7M2QX4P")
    assert "STOP" in body and "HELP" in body and "{" not in body


def test_a_welcome_outside_the_hours_moves_to_the_morning(sender, db):
    db.now = at(2026, 11, 15, 21, 5)
    ok, what = asyncio.run(nh.run_scheduled(db.biz, _action()))
    assert ok and "morning" in what and sender["texts"] == []
    [row] = db.scheduled()
    assert row["action"] == _action()
    assert datetime.fromisoformat(row["run_at"]).astimezone(ET) == at(2026, 11, 16, 9)


def test_turned_off_a_doors_texts_stop_and_the_text_doors_go_on(sender, db):
    db.path = False
    assert "Welcome Path is off" in asyncio.run(nh.run_scheduled(db.biz, _action()))[1]
    db.now = at(2026, 11, 16, 10)
    assert "Welcome Path is off" in asyncio.run(nh.run_scheduled(db.biz, _action("monday")))[1]
    assert sender["texts"] == []
    ok, what = asyncio.run(nh.run_scheduled(db.biz, _action("monday", door="text")))
    assert ok and "monday" in what and len(sender["texts"]) == 1


def test_the_welcome_reads_stop_again(sender, db):
    sender["stopped"] = True
    assert "STOP" in asyncio.run(nh.run_scheduled(db.biz, _action()))[1] and sender["texts"] == []


# ── 8. New here's list, and the card again ────────────────────────────

def test_new_heres_list_shows_every_door(db):
    since = _iso(SUNDAY - timedelta(hours=1))
    db.person(GUEST, "Maria Lopez", metadata={"new_here": {"door": "kids", "texted_at": since, "texts_ok": False,
                                                          "texts": "no_yes", "code": "AAAAAAAA"}})
    db.person(OTHER, PHONE, phone="+12315550143",
              metadata={"new_here": {"texted_at": since, "code": "BBBBBBBB", "visits": 1}})
    db.t["church_follow_ups"].append({"id": "f1", "business_id": BIZ, "contact_id": GUEST, "card_key": "checkin:first",
                                      "path_kind": "connect", "status": "open", "step": 0, "leader_contact_id": None,
                                      "created_at": since})
    guests = {g["contact_id"]: g for g in nh.guests_of(db.biz)}
    assert guests[GUEST]["door"] == "kids" and guests[GUEST]["from"] == "text"
    assert guests[GUEST]["texts_ok"] is False and guests[GUEST]["texts"] == "no_yes"
    assert guests[GUEST]["follow_up"]["status"] == "open"            # the kids desk's follow-up, not only New here's
    assert guests[OTHER]["door"] == "text" and guests[OTHER]["texts_ok"] is True   # texted the word, before the path


def test_the_member_apps_guest_reads_as_the_app(db):
    told = _iso(SUNDAY - timedelta(hours=2))
    db.person(metadata={"new_here": {"door": "app", "texted_at": told, "texts_ok": True, "texts": "on",
                                     "app": {"at": told, "first_time": True}}})
    [g] = nh.guests_of(db.biz)
    assert g["door"] == "app" and g["from"] == "app" and g["card_at"] == told


def test_the_card_is_never_texted_to_a_guest_who_said_no(db, monkeypatch):
    import business_access
    monkeypatch.setattr(business_access, "assert_access", lambda *a, **kw: None)
    db.person(metadata={"new_here": {"door": "kids", "texts_ok": False, "code": "AAAAAAAA"}})
    app = FastAPI()
    app.include_router(nh.router)
    app.dependency_overrides[require_user] = lambda: AuthedUser(id="u1", email="a@example.com", role="authenticated")
    r = TestClient(app).post(f"/new-here/{BIZ}/resend", json={"contact_id": GUEST})
    assert r.status_code == 409 and "yes" in r.json()["detail"]


# ── 9. a second door's card ───────────────────────────────────────────

def _open_follow_up(db, card_key="checkin:first", kind="connect"):
    db.t["church_follow_ups"].append({"id": "f1", "business_id": BIZ, "contact_id": GUEST, "card_key": card_key,
                                      "path_kind": kind, "status": "open", "created_at": _iso(SUNDAY)})


def test_a_second_doors_card_is_a_note_on_the_first(db):
    _open_follow_up(db)
    answers = [{"q": "How they heard", "a": "A friend or family"}]
    assert nh.second_door(BIZ, GUEST, "web:connect_card", answers, "Also sent the website connect card.") is True
    [note] = db.t["church_follow_up_notes"]
    assert note["follow_up_id"] == "f1" and note["author_kind"] == "chief"
    assert note["body"] == "Also sent the website connect card. How they heard A friend or family"
    # The same card again is start()'s own (it notes "filled in again"); off, it's start()'s too.
    assert nh.second_door(BIZ, GUEST, "checkin:first", answers, "x") is False
    db.path = False
    assert nh.second_door(BIZ, GUEST, "web:connect_card", answers, "x") is False


def test_a_follow_up_that_isnt_a_guests_never_takes_the_note(db):
    _open_follow_up(db, card_key="form:serve-1", kind="serve")
    assert nh.second_door(BIZ, GUEST, "web:connect_card", [], "x") is False
    db.down.add("church_follow_ups")
    assert nh.second_door(BIZ, GUEST, "web:connect_card", [], "x") is False


def test_the_new_here_card_of_a_guest_from_another_door_is_a_note(db, monkeypatch):
    started = []
    monkeypatch.setattr(cfu, "start", lambda *a, **kw: started.append(kw) or {"id": "x"})
    db.person(metadata={"new_here": {"code": "AAAAAAAA", "door": "kids", "texted_at": _iso(SUNDAY)}})
    _open_follow_up(db)
    assert nh.save_card(db.biz, db.contact(), {"name": "Maria Lopez", "first": "yes", "heard": "Online"})
    assert started == []
    assert db.t["church_follow_up_notes"][0]["body"].startswith("Filled in the New here card. First time? Yes")


# ── 10. the yes, and the box ──────────────────────────────────────────

def test_a_yes_is_kept_once_with_where_and_how(db):
    assert nh.keep_yes(BIZ, "(231) 555-0142", source="kids_checkin", name=" Maria  Lopez ", ip="203.0.113.9",
                       user_agent="Mozilla/5.0") is True
    [row] = db.t["sms_consents"]
    assert row["phone"] == PHONE and row["source"] == "kids_checkin" and row["business_id"] == BIZ
    assert row["name"] == "Maria Lopez" and row["ip"] == "203.0.113.9" and row["user_agent"] == "Mozilla/5.0"
    assert row["consented_at"]
    assert nh.keep_yes(BIZ, PHONE, source="kids_checkin") is True and len(db.t["sms_consents"]) == 1
    assert nh.keep_yes(BIZ, PHONE, source="member_app_new") is True and len(db.t["sms_consents"]) == 2
    assert nh.keep_yes(BIZ, "555-01", source="kids_checkin") is False
    # A box ticked on a web page keeps nothing until the phone says YES (M-5).
    assert nh.keep_yes(BIZ, PHONE, source="connect_card") is True and len(db.t["sms_consents"]) == 2
    assert nh.keep_yes(BIZ, PHONE, source="connect_card", confirmed=True) is True
    assert db.t["sms_consents"][-1]["source"] == "connect_card" and len(db.t["sms_consents"]) == 3
    db.down.add("sms_consents")
    assert nh.keep_yes(BIZ, "+12315550111", source="kids_checkin") is False
    assert set(nh.YES_SOURCES) == {"kids", "web", "form", "app"}


def test_the_box_says_what_the_carriers_ask(db):
    words = nh.text_me_words(db.biz)
    for part in ("Grace Hill Church may text me", "up to 4 msgs a week", "Msg & data rates may apply",
                 "Reply STOP to end", "HELP for help"):
        assert part in words, part
    assert nh.text_me_words(db.biz, ask=True).startswith("Ask first, and tick only if they say yes")


@pytest.mark.parametrize("why", ["path", "new_here", "settings", "number", "church"])
def test_the_box_shows_only_where_a_yes_brings_texts(db, why):
    biz = db.biz
    if why == "path":
        db.path = False
    elif why == "new_here":
        db.new_here = False
    elif why == "settings":
        biz = dict(biz, settings={})
    elif why == "number":
        db.t["sms_numbers"] = []
    elif why == "church":
        biz = dict(biz, type="salon")
    assert nh.text_me_words(biz) == "" and nh.can_text(biz) is False


PHONE_FIELD = {"name": "phone", "label": "Mobile", "type": "phone"}


@pytest.mark.parametrize("form, shown", [
    ({"id": "c1", "name": "Connect Card", "form_type": "connect_card", "fields": [PHONE_FIELD]}, True),
    ({"id": "v1", "name": "Plan your visit", "fields": [PHONE_FIELD]}, True),
    ({"id": "c2", "name": "Connect Card", "fields": [{"name": "mobile", "type": "phone"}]}, False),
    ({"id": "s1", "name": "Serve on a team", "form_type": "volunteer", "fields": [PHONE_FIELD]}, False),
    ({"id": "r1", "name": "Retreat Registration", "fields": [PHONE_FIELD]}, False),
    ({"id": "g1", "name": "Welcome", "fields": [PHONE_FIELD]}, True),       # the bulletin's guest card
])
def test_a_church_cards_box(db, form, shown):
    db.biz["settings"]["new_here"]["guest_form"] = "g1"
    assert bool(nh.text_me_for_form(db.biz, form)) is shown


def test_the_form_page_box_is_unticked_and_the_answers_never_carry_it():
    import form_page_renderer as fpr
    biz = {"id": BIZ, "name": "Grace Hill Church"}
    form = {"id": "c1", "business_id": BIZ, "name": "Connect Card", "fields": [PHONE_FIELD]}
    page = fpr.render_form_page(biz, form, submit_url="https://x/intake/submit", canonical_url="https://g.church/f",
                                text_me="Yes, Grace Hill Church may text me.")
    assert f'name="{fpr.TEXTS_NAME}" value="yes">' in page and "checked" not in page.split(fpr.TEXTS_NAME)[1][:40]
    assert "<b>Text me.</b> Yes, Grace Hill Church may text me." in page
    assert fpr.TEXTS_NAME not in fpr.render_form_page(biz, form, submit_url="https://x/intake/submit",
                                                      canonical_url="https://g.church/f")
    # A card whose own field is named like the box never draws it twice.
    assert fpr._field_html({"name": fpr.TEXTS_NAME, "type": "checkbox"}) == ""
    assert cfu.answers_from_form(form, {"phone": PHONE, fpr.TEXTS_NAME: "yes"}) == []


# ── 11. each door's hook ──────────────────────────────────────────────

@pytest.fixture
def doors(db, monkeypatch):
    got = {"enroll": [], "start": []}
    monkeypatch.setattr(nh, "enroll_by_id", lambda biz, cid, **kw: got["enroll"].append((biz, cid, kw)) or {})
    monkeypatch.setattr(cfu, "start", lambda biz, cid, **kw: got["start"].append(kw) or {"id": "f-new"})
    return got


def test_the_website_card_joins_the_path(doors, db):
    data = {"phone": "(231) 555-0142", "fields": {"visits": "This is my first time"}}
    assert cfu.on_connect_card(BIZ, GUEST, data, "r-1", texts_ok=True) == {"id": "f-new"}
    [(biz, cid, kw)] = doors["enroll"]
    assert (biz, cid, kw["door"], kw["texts_ok"], kw["phone"]) == (BIZ, GUEST, "web", True, PHONE)


def test_a_regulars_website_card_doesnt(doors, db):
    cfu.on_connect_card(BIZ, GUEST, {"fields": {"visits": "I'm a regular"}}, "r-1", texts_ok=True)
    assert doors["enroll"] == [] and len(doors["start"]) == 1


def test_with_the_path_off_the_website_card_is_as_it_was(doors, db):
    db.path = False
    _open_follow_up(db)
    cfu.on_connect_card(BIZ, GUEST, {"fields": {}}, "r-1", texts_ok=True)
    assert doors["enroll"] == [] and len(doors["start"]) == 1 and db.t["church_follow_up_notes"] == []


def test_a_guest_from_another_door_gets_a_note_not_a_second_follow_up(doors, db):
    _open_follow_up(db)
    assert cfu.on_connect_card(BIZ, GUEST, {"fields": {"visits": "This is my first time"}}, "r-1") is None
    assert doors["start"] == [] and len(db.t["church_follow_up_notes"]) == 1
    assert doors["enroll"][0][2]["door"] == "web" and doors["enroll"][0][2]["texts_ok"] is False


CONNECT = {"id": "c1", "name": "Connect Card", "form_type": "connect_card",
           "fields": [PHONE_FIELD, {"name": "visits", "label": "How many times have you visited?"}]}


def test_a_church_guest_card_joins_the_path(doors, db):
    row = cfu.on_intake_form(db.biz, CONNECT, {"visits": "First time"}, GUEST, texts_ok=True, phone=PHONE)
    assert row == {"id": "f-new"} and doors["start"][0]["card_key"] == "form:c1"
    [(biz, cid, kw)] = doors["enroll"]
    assert (kw["door"], kw["texts_ok"], kw["phone"]) == ("form", True, PHONE)
    doors["enroll"].clear()
    cfu.on_intake_form(db.biz, CONNECT, {"visits": "I'm a regular"}, GUEST)
    assert doors["enroll"] == []
    cfu.on_intake_form(db.biz, {"id": "s1", "name": "Serve on a team", "form_type": "volunteer"}, {}, GUEST)
    assert doors["enroll"] == []
    db.path = False
    cfu.on_intake_form(db.biz, CONNECT, {"visits": "First time"}, GUEST, texts_ok=True, phone=PHONE)
    assert doors["enroll"] == []


def test_the_intake_hand_off_keeps_a_guest_cards_yes_first(db, monkeypatch):
    import intake_endpoint
    got = []
    monkeypatch.setattr(cfu, "on_intake_form", lambda *a, **kw: got.append(kw) or {"id": "f"})
    kw = dict(phone=PHONE, name="Maria Lopez", ip="203.0.113.9", user_agent="Mozilla/5.0")
    asyncio.run(intake_endpoint.church_card(db.biz, CONNECT, {}, GUEST, texts_ok=True, **kw))
    # A box ticked on a web page is a request: nothing is kept until the phone
    # replies YES (M-5), and the guest goes on to be asked.
    assert db.t["sms_consents"] == [] and got[-1]["texts_ok"] is True
    # A yes on a card that isn't a guest door isn't one, and keeps nothing.
    asyncio.run(intake_endpoint.church_card(db.biz, {"id": "s1", "name": "Serve", "form_type": "volunteer"}, {},
                                            GUEST, texts_ok=True, **kw))
    assert got[-1]["texts_ok"] is False and db.t["sms_consents"] == []
    # The endpoint takes the box out of the answers before anything stores them.
    src = (pathlib.Path(intake_endpoint.__file__)).read_text(encoding="utf-8")
    assert "submission_data.pop(TEXTS_NAME" in src


def test_the_member_app_joins_the_path(db):
    import member_im_new as imn
    db.person()
    out = imn.join_path(db.biz, {"id": GUEST}, {"first_time": True}, texts_ok=True, ip="203.0.113.9",
                        user_agent="Mozilla/5.0")
    assert out["door"] == "app" and out["texts"] == "on"
    [row] = db.t["sms_consents"]
    assert row["source"] == "member_app_new" and row["phone"] == PHONE and row["ip"] == "203.0.113.9"
    assert "welcome" in db.steps()


def test_the_member_app_without_a_yes_or_for_someone_coming_a_while(db):
    import member_im_new as imn
    db.person()
    assert imn.join_path(db.biz, {"id": GUEST}, {"first_time": True}, texts_ok=False)["texts"] == "no_yes"
    assert db.t["sms_consents"] == [] and db.scheduled() == []
    db.t["contacts"].clear()
    db.person()
    assert imn.join_path(db.biz, {"id": GUEST}, {"first_time": False}, texts_ok=True) is None
    assert len(db.t["sms_consents"]) == 1 and db.mine() == {}         # their yes kept; no guest path
    db.path = False
    db.t["sms_consents"].clear()
    assert imn.join_path(db.biz, {"id": GUEST}, {"first_time": True}, texts_ok=True) is None
    assert db.t["sms_consents"] == []


def test_the_member_apps_yes_counts_only_where_the_box_shows(db):
    import member_im_new as imn
    db.person()
    db.t["sms_numbers"] = []
    assert imn.join_path(db.biz, {"id": GUEST}, {"first_time": True}, texts_ok=True)["texts_ok"] is False
    assert db.t["sms_consents"] == []
    assert imn.text_me(db.biz, {"id": GUEST, "phone": PHONE}) == ("", "")
    db.t["sms_numbers"] = [{"business_id": BIZ, "status": "active", "phone_number": CHURCH_NUMBER}]
    words, phone = imn.text_me(db.biz, {"id": GUEST, "phone": PHONE})
    assert "Grace Hill Church may text me" in words and phone == PHONE
    # Signed in by email: the mobile is read from their record; none there, no box.
    assert imn.text_me(db.biz, {"id": GUEST})[1] == PHONE
    db.contact()["phone"] = ""
    assert imn.text_me(db.biz, {"id": GUEST}) == ("", "")


@pytest.fixture
def desk(db, monkeypatch):
    import kids_router
    monkeypatch.setattr(kids_router, "require", lambda biz, user, minimum: "member")
    db.t.update(households=[], household_adults=[], children=[], household_pickups=[], child_care_notes=[])
    import church_keys
    monkeypatch.setattr(church_keys, "is_open", lambda *a, **kw: True)
    app = FastAPI()
    app.include_router(kids_router.router)
    app.dependency_overrides[require_user] = lambda: AuthedUser(id="u1", email="desk@example.com",
                                                               role="authenticated")
    return TestClient(app)


def test_the_kids_desk_box_on_add_a_family(desk, db):
    got = desk.get(f"/kids/families?business_id={BIZ}").json()["guest_texts"]
    assert got["on"] is True and got["words"].startswith("Ask first") and "Grace Hill Church" in got["words"]
    db.path = False
    assert desk.get(f"/kids/families?business_id={BIZ}").json()["guest_texts"] == {"on": False, "words": ""}


def test_the_kids_desks_yes_is_kept_for_the_parent(desk, db):
    db.person()
    r = desk.post("/kids/families", json={"business_id": BIZ, "name": "The Lopez family", "texts_ok": True,
                                          "adults": [{"contact_id": GUEST, "relationship": "parent"}]},
                  headers={"user-agent": "KidsDesk/1"})
    assert r.status_code == 200 and r.json()["texts"] == "kept"
    [row] = db.t["sms_consents"]
    assert row["source"] == "kids_checkin" and row["phone"] == PHONE and row["user_agent"] == "KidsDesk/1"
    # Unticked (or an older app that never sends it): nothing is kept.
    r = desk.post("/kids/families", json={"business_id": BIZ, "name": "The Lopez family",
                                          "adults": [{"contact_id": GUEST, "relationship": "parent"}]})
    assert r.status_code == 200 and "texts" not in r.json() and len(db.t["sms_consents"]) == 1


def test_a_kids_desk_yes_without_a_mobile_or_the_box(desk, db):
    db.person(phone="")
    body = {"business_id": BIZ, "name": "The Lopez family", "texts_ok": True,
            "adults": [{"contact_id": GUEST, "relationship": "parent"}]}
    assert desk.post("/kids/families", json=body).json()["texts"] == "no_mobile"
    db.path = False
    assert desk.post("/kids/families", json=body).json()["texts"] == "off"
    assert db.t["sms_consents"] == []


def test_the_kids_desks_first_check_in_reads_the_yes(db):
    db.person()
    db.t["sms_consents"].append({"business_id": BIZ, "phone": PHONE, "source": "kids_checkin"})
    assert nh.enroll_by_id(BIZ, GUEST, door="kids", texts_ok=None, visit_at=SUNDAY)["texts"] == "on"
    db.t["contacts"].clear()
    db.t["chief_scheduled_actions"].clear()
    db.person()
    db.t["sms_consents"].clear()
    assert nh.enroll_by_id(BIZ, GUEST, door="desk", texts_ok=None, visit_at=SUNDAY)["texts"] == "no_yes"
    assert db.scheduled() == []


# ── the website: the slot and the submit ─────────────────────────────

def test_the_connect_cards_slot(monkeypatch):
    import public_site
    page = '<form data-church-form="connect-card"><!--solutionist:guest-texts--><button>Send</button></form>'
    biz = {"id": BIZ, "name": "Grace Hill Church", "type": "church", "settings": {}}

    async def rows(client, path):
        return [biz]
    monkeypatch.setattr(public_site, "_sb_service", rows)
    monkeypatch.setattr(nh, "text_me_words", lambda b, **kw: "Yes, Grace Hill Church may text me & you.")
    out = asyncio.run(public_site._fill_guest_texts_slot(None, BIZ, page))
    assert '<input type="checkbox" name="sms_consent" value="yes">' in out
    assert "<b>Text me.</b> Yes, Grace Hill Church may text me &amp; you." in out and "solutionist:" not in out
    monkeypatch.setattr(nh, "text_me_words", lambda b, **kw: "")
    assert asyncio.run(public_site._fill_guest_texts_slot(None, BIZ, page)) == page.replace(
        public_site.GUEST_TEXTS_SLOT, "")


def test_love_citys_connect_card_marks_the_slot_and_sends_the_yes_apart():
    site = pathlib.Path(__file__).resolve().parent.parent / "sites" / "love-city-church"
    html = (site / "connect.html").read_text(encoding="utf-8")
    card = html.split('data-church-form="connect-card"')[1].split("</form>")[0]
    assert "<!--solutionist:guest-texts-->" in card
    js = (site / "forms.js").read_text(encoding="utf-8")
    assert "sms_consent: 1" in js and "k !== 'sms_consent'" in js and "payload.sms_consent = true" in js


@pytest.fixture
def site_post(monkeypatch):
    import public_site
    import website_forms
    got = {"capture": [], "yes": []}

    def capture(*a, **kw):
        got["capture"].append(kw)
        return "c1"

    async def alert(*a, **kw):
        return None

    async def not_sample(biz):
        return False
    import sample_church
    monkeypatch.setattr(sample_church, "is_sample_async", not_sample)
    monkeypatch.setattr(public_site, "_capture_contact_from_form", capture)
    monkeypatch.setattr(public_site, "_check_contact_rate", lambda ip: True)
    monkeypatch.setattr(website_forms, "alert_church", alert)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **kw: [{"type": "ministry", "settings": {}}])
    monkeypatch.setattr(nh, "keep_yes", lambda *a, **kw: got["yes"].append((a, kw)) or True)
    monkeypatch.setattr(nh, "path_on", lambda biz: got.get("path", True))
    import brand_engine
    monkeypatch.setattr(brand_engine, "get_bundle", lambda b: {})
    monkeypatch.setattr(brand_engine, "_sb_get", lambda p: [])
    app = FastAPI()
    app.include_router(public_site.router)
    got["client"] = TestClient(app)
    return got


def _card(site_post, **extra):
    body = {"name": "Maria Lopez", "email": "maria@example.org", "phone": "(231) 555-0142", "message": "",
            "form": "connect_card", "fields": {"visits": "This is my first time"}, **extra}
    return site_post["client"].post(f"/sites/{BIZ}/contact-submit", json=body, headers={"user-agent": "Safari/17"})


def test_the_website_cards_yes_is_kept_and_carried_to_the_hook(site_post):
    _card(site_post, sms_consent=True)
    [(args, kw)] = site_post["yes"]
    assert args == (BIZ, "(231) 555-0142") and kw["source"] == "connect_card" and kw["user_agent"] == "Safari/17"
    assert site_post["capture"][-1]["texts_ok"] is True


def test_no_box_ticked_or_the_path_off_keeps_nothing(site_post):
    _card(site_post)
    assert site_post["yes"] == [] and site_post["capture"][-1]["texts_ok"] is False
    site_post["path"] = False
    _card(site_post, sms_consent=True)
    assert site_post["yes"] == [] and site_post["capture"][-1]["texts_ok"] is False


# ── 11. a box ticked on a web page asks the phone first (M-5) ─────────
#
# Kevin, 2026-11-27, after two website connect cards at Love City were one
# sales campaign: welcome texts only after the phone replies YES. A website
# card's "Text me" (or a church guest card's) took any number typed and
# texted it four times, so anyone could put a stranger on a church's texts.

@pytest.mark.parametrize("door", ["web", "form"])
def test_a_web_cards_text_me_queues_one_question_and_keeps_no_yes(db, door):
    db.person()
    mine = nh.enroll(db.biz, db.contact(), door=door, texts_ok=True)
    assert mine["texts"] == "confirm" and mine["confirm_at"] == _iso(SUNDAY) and mine["texts_ok"] is True
    assert db.steps() == ["confirm"], "no welcome, no Monday note, no invite: one question"
    assert db.t["sms_consents"] == [], "a typed number isn't a yes"
    assert "welcome_at" not in mine and mine["texts"] in nh.WHY_NOT


def test_the_question_says_reply_yes_in_the_churchs_name(sender, db):
    db.contact()["metadata"]["new_here"] = {"code": "K7M2QX4P", "door": "web", "texts": "confirm"}
    ok, what = asyncio.run(nh.run_scheduled(db.biz, _action("confirm", "web")))
    assert ok and "confirm" in what
    [(phone, body)] = sender["texts"]
    assert phone == PHONE and body.startswith("Grace Hill Church: Reply YES to get texts from Grace Hill Church")
    assert "Reply STOP to end, HELP for help." in body, "the carriers' opt-in words: STOP and HELP"
    assert "gracehill.church/new/" not in body, "no link until they say yes"


def test_the_question_isnt_sent_once_answered_and_waits_out_the_night(sender, db):
    db.contact()["metadata"]["new_here"] = {"code": "K7M2QX4P", "door": "web", "texts": "on"}
    ok, what = asyncio.run(nh.run_scheduled(db.biz, _action("confirm", "web")))
    assert ok and "Already answered" in what and sender["texts"] == []
    db.contact()["metadata"]["new_here"]["texts"] = "confirm"
    db.now = at(2026, 11, 15, 22, 0)
    ok, what = asyncio.run(nh.run_scheduled(db.biz, _action("confirm", "web")))
    assert ok and "waits for the morning" in what and sender["texts"] == []
    assert _when(db, "confirm") == at(2026, 11, 16, 9)


def test_yes_from_the_phone_keeps_the_yes_and_starts_the_path(db):
    db.person()
    nh.enroll(db.biz, db.contact(), door="web", texts_ok=True)
    db.now = SUNDAY + timedelta(hours=2)
    hit = nh.on_yes(BIZ, "(231) 555-0142")
    assert hit == {"contact_ids": [GUEST], "welcome_at": _iso(SUNDAY + timedelta(hours=2))}
    [row] = db.t["sms_consents"]
    assert row["source"] == "connect_card_yes" and row["phone"] == PHONE and "YES" in row["user_agent"]
    mine = db.mine()
    assert mine["texts"] == "on" and mine["texts_ok"] is True and "confirm_at" not in mine and mine["yes_at"]
    assert db.steps() == ["confirm", "invite", "monday", "welcome"]
    assert _when(db, "welcome") == SUNDAY + timedelta(hours=2)
    assert all(r["action"]["door"] == "web" for r in db.scheduled())
    assert nh.on_yes(BIZ, PHONE) is None, "a second YES starts nothing more"
    assert len(db.scheduled()) == 4


def test_no_reply_means_nothing_more_and_a_late_yes_starts_nothing(db):
    db.person()
    nh.enroll(db.biz, db.contact(), door="web", texts_ok=True)
    db.now = SUNDAY + timedelta(days=nh.CONFIRM_DAYS, hours=1)
    assert nh.on_yes(BIZ, PHONE) is None
    assert db.steps() == ["confirm"] and db.t["sms_consents"] == []


def test_a_yes_from_someone_nobody_asked_about_is_an_ordinary_yes(db):
    db.person()
    nh.enroll(db.biz, db.contact(), door="kids", texts_ok=False, visit_at=SUNDAY)
    assert nh.on_yes(BIZ, PHONE) is None and db.t["sms_consents"] == []
    db.person(cid=OTHER, phone="+12315550999", metadata={"new_here": {"texts": "confirm",
                                                                      "confirm_at": _iso(SUNDAY), "door": "web"}})
    db.t["contacts"][-1]["business_id"] = "another-church"
    assert nh.on_yes(BIZ, "+12315550999") is None, "another church's question is theirs"


def test_a_guest_marked_inactive_before_their_yes_starts_nothing(db):
    db.person()
    nh.enroll(db.biz, db.contact(), door="web", texts_ok=True)
    db.contact()["status"] = "inactive"
    assert nh.on_yes(BIZ, PHONE) is None and db.steps() == ["confirm"]


def test_a_second_web_card_this_week_never_asks_twice(db):
    db.person()
    nh.enroll(db.biz, db.contact(), door="web", texts_ok=True)
    db.now = SUNDAY + timedelta(days=2)
    again = nh.enroll(db.biz, db.contact(), door="form", texts_ok=True)
    assert again["texts"] == "confirm" and db.steps() == ["confirm"]


def test_a_number_that_already_said_yes_isnt_asked_again(db):
    db.person()
    said_yes(db, source="connect_card_yes")
    mine = nh.enroll(db.biz, db.contact(), door="web", texts_ok=True)
    assert mine["texts"] == "on" and "confirm" not in db.steps() and "welcome" in db.steps()


def test_a_yes_that_cant_be_read_is_never_a_question_or_a_no(db):
    db.person()
    db.down.add("sms_consents")
    mine = nh.enroll(db.biz, db.contact(), door="web", texts_ok=True)
    assert mine["texts"] == "unread" and db.scheduled() == []


def test_a_question_that_cant_be_queued_is_never_confirm(db):
    db.person()
    db.down.add("chief_scheduled_actions")
    mine = nh.enroll(db.biz, db.contact(), door="web", texts_ok=True)
    assert mine["texts"] == "unread" and db.mine()["texts"] == "unread" and "confirm_at" not in db.mine()


def test_the_kids_desk_and_the_member_app_still_start_at_once(db):
    db.person()
    assert nh.enroll(db.biz, db.contact(), door="kids", texts_ok=True, visit_at=SUNDAY)["texts"] == "on"
    assert "confirm" not in db.steps()


def test_the_website_door_keeps_no_yes_when_the_box_is_ticked(db, monkeypatch):
    """public_site's connect card calls keep_yes(source connect_card): it
    says there's a number to ask, and keeps nothing."""
    assert nh.keep_yes(BIZ, PHONE, source=nh.YES_SOURCES["web"], ip="203.0.113.9") is True
    assert nh.keep_yes(BIZ, PHONE, source=nh.YES_SOURCES["form"]) is True
    assert nh.keep_yes(BIZ, "555", source=nh.YES_SOURCES["web"]) is False
    assert db.t["sms_consents"] == []


# ── 12. the review of #2100 (account 2, 2026-11-27) ───────────────────

@pytest.mark.parametrize("source", ["texts_page", "event_waitlist", "booking_widget", "website_contact",
                                    "connect_card", "guest_form", "web_form"])
def test_a_yes_typed_on_any_public_page_never_skips_the_question(db, source):
    """Must-fix 1: someone puts a victim's number on the church's /texts page
    or an event wait-list, then sends a connect card with it. Only a yes the
    phone or a person gave counts."""
    db.person()
    said_yes(db, source=source)
    mine = nh.enroll(db.biz, db.contact(), door="web", texts_ok=True)
    assert mine["texts"] == "confirm" and db.steps() == ["confirm"]


@pytest.mark.parametrize("source", ["kids_checkin", "member_app_new", "member_app", "connect_card_yes",
                                    "guest_form_yes"])
def test_a_yes_given_in_person_in_the_app_or_by_reply_skips_it(db, source):
    db.person()
    said_yes(db, source=source)
    assert nh.enroll(db.biz, db.contact(), door="form", texts_ok=True)["texts"] == "on"


def test_the_yes_is_found_by_the_number_that_was_asked(db):
    """Must-fix 2: a returning visitor matched by email keeps an old number
    on their record; the question went to the card's new number."""
    db.person(phone="+12315550000")
    nh.enroll(db.biz, db.contact(), door="web", texts_ok=True, phone="(231) 555-0142")
    assert db.mine()["confirm_phone"] == PHONE
    assert nh.on_yes(BIZ, "+12315550000") is None, "the old number on file was never asked"
    assert nh.on_yes(BIZ, PHONE)["contact_ids"] == [GUEST]
    assert {r["action"]["phone"] for r in db.scheduled()} == {PHONE}
    assert db.t["sms_consents"][-1]["phone"] == PHONE


def test_a_reply_is_kept_even_beside_an_old_unverified_row(db):
    """Should-fix 4: a connect_card row from before the question used to make
    the YES write nothing, so the record never showed the reply."""
    db.person()
    nh.enroll(db.biz, db.contact(), door="web", texts_ok=True)
    said_yes(db, source="connect_card")
    nh.on_yes(BIZ, PHONE)
    assert [r["source"] for r in db.t["sms_consents"]] == ["connect_card", "connect_card_yes"]


def test_a_stop_that_still_stands_starts_nothing_and_leaves_them_asked(db):
    """Should-fix 5: on_yes never saves "Said STOP" for someone it counts as
    started; sms_routing clears a STOP before asking it (a YES is a START)."""
    db.person()
    nh.enroll(db.biz, db.contact(), door="web", texts_ok=True)
    db.t["sms_opt_outs"] = [{"phone": PHONE, "business_id": BIZ}]
    assert nh.on_yes(BIZ, PHONE) is None
    assert db.mine()["texts"] == "confirm" and db.t["sms_consents"] == [] and db.steps() == ["confirm"]
    db.t["sms_opt_outs"] = []
    assert nh.on_yes(BIZ, PHONE)["contact_ids"] == [GUEST]


def test_a_yes_at_night_says_when_the_first_text_comes(db):
    db.person()
    db.now = at(2026, 11, 15, 21, 0)
    nh.enroll(db.biz, db.contact(), door="web", texts_ok=True)
    hit = nh.on_yes(BIZ, PHONE)
    assert hit["welcome_at"] == _iso(at(2026, 11, 16, 9))
