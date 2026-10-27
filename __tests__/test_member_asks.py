"""Ask the church (member_asks.py; Kevin, 2026-10-27: "we need to create a
path for members to be able to request these things from the church app as
well"). Pins:

  1. off by default: nothing served, nothing offered, nothing saved
  2. an ask the church didn't turn on is refused
  3. a member can't book for someone else, set a status, or pick a church
  4. a room clash is refused, and never names what's there
  5. help is confidential and lands in Prayer & care, marked Help
  6. a pledge keeps one per giver and goes only to a campaign that hasn't ended
  7. no other church is reachable
  8. minors get only prayer and help, the youth way
  9. the rate limit holds
  plus: the office's switch is the owner's, the CHURCH_MEMBER_ASKS switch,
  who hears each ask, and the way in from Home and Me.
"""
import json
import pathlib
import sys
import urllib.parse
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import church_spaces
import member_asks as ma
import member_portal as mp
import rate_limit as _rl
import sb_clients

REAL_STRICT = _rl.allow_strict

BIZ = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
HOST = "love-city.mysolutionist.app"
ORIGIN = {"origin": f"https://{HOST}"}
NY = ZoneInfo("America/New_York")
ADULT = "1980-05-01"
TEEN = f"{date.today().year - 15}-01-01"


def cid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


ANA, BEN, TEO, KID = cid(1), cid(2), cid(3), cid(4)
HALL, VAN, GONE, THEIRS = cid(11), cid(12), cid(13), cid(14)
FUND, OLD, FAR = cid(21), cid(22), cid(23)


# ─── a PostgREST-shaped fake ─────────────────────────────────────────


def _parse(s):
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _cmp(have, want):
    a, b = _parse(have), _parse(want)
    if a is not None and b is not None and len(str(have)) >= 10 and len(str(want)) >= 10:
        return (a > b) - (a < b)
    return (str(have) > str(want)) - (str(have) < str(want))


def _get(row, key):
    if "->>" in key:
        col, sub = key.split("->>", 1)
        v = (row.get(col) or {}).get(sub)
        return None if v is None else str(v)
    return row.get(key)


def _match(row, key, op):
    v = _get(row, key)
    if op.startswith("eq."):
        want = op[3:]
        if isinstance(v, bool):
            return str(v).lower() == want
        return v is not None and str(v) == want
    if op.startswith("in.("):
        return str(v) in op[4:-1].split(",")
    if op == "is.null":
        return v is None
    if op.startswith(("gt.", "gte.", "lt.", "lte.")):
        name, want = op.split(".", 1)
        if v is None:
            return False
        c = _cmp(v, want)
        return {"gt": c > 0, "gte": c >= 0, "lt": c < 0, "lte": c <= 0}[name]
    raise AssertionError(f"filter not faked: {key}={op}")


class Fake:
    def __init__(self):
        self.t = {k: [] for k in ("contacts", "children", "msg_guardians", "church_spaces", "church_space_bookings",
                                  "ministry_care_requests", "church_campaigns", "church_pledges", "invoices",
                                  "business_users", "business_collaborators")}
        self.biz = {
            BIZ: {"id": BIZ, "name": "Love City Church", "type": "church", "owner_id": "owner",
                  "settings": {"member_portal": {"enabled": True}}},
            OTHER: {"id": OTHER, "name": "Other Church", "type": "church", "owner_id": "other-owner",
                    "settings": {"member_portal": {"enabled": True, "asks": {"on": list(ma.ASKS)}}}},
        }
        self.writes = []
        self.down = set()

    def add(self, table, **row):
        row.setdefault("id", str(uuid.uuid4()))
        self.t[table].append(row)
        return row

    def person(self, i, name, *, biz=BIZ, birthdate=ADULT, tags=None, email=""):
        return self.add("contacts", id=i, business_id=biz, name=name, email=email or f"{name.split()[0].lower()}@example.com",
                        phone="555 010 2030", birthdate=birthdate, status="active", tags=tags or [], metadata={},
                        updated_at="r1")

    def _rows(self, path):
        table, _, qs = path.lstrip("/").partition("?")
        params = urllib.parse.parse_qsl(qs, keep_blank_values=True)
        return table, params

    def get(self, path, **kw):
        table, params = self._rows(path)
        if table in self.down:
            return None
        if table == "businesses":
            want = dict(params).get("id", "").removeprefix("eq.")
            b = self.biz.get(want)
            return [json.loads(json.dumps(b))] if b else []
        if table not in self.t:
            return []
        rows = [r for r in self.t[table]
                if all(_match(r, k, v) for k, v in params if k not in ("select", "order", "limit", "on_conflict"))]
        order = dict(params).get("order")
        if order:
            key, _, how = order.split(",")[0].partition(".")
            rows.sort(key=lambda r: str(r.get(key) or ""), reverse=how.startswith("desc"))
        return json.loads(json.dumps(rows))

    def post(self, path, body, **kw):
        table, _ = self._rows(path)
        if table.startswith("rpc/"):
            return None
        if table in self.down:
            return None
        rows = body if isinstance(body, list) else [body]
        out = []
        for r in rows:
            r = json.loads(json.dumps(r))
            r.setdefault("id", str(uuid.uuid4()))
            r.setdefault("created_at", datetime.now(timezone.utc).isoformat())
            if table == "church_space_bookings" and r.get("status") == "booked":
                for b in self.t[table]:
                    if (b["space_id"] == r["space_id"] and b["status"] == "booked"
                            and _cmp(b["start_at"], r["end_at"]) < 0 and _cmp(r["start_at"], b["end_at"]) < 0):
                        return None
            if table == "church_pledges" and any(p["campaign_id"] == r["campaign_id"] and p["contact_id"] == r["contact_id"]
                                                 for p in self.t[table]):
                return None
            out.append(r)
        self.t[table].extend(out)
        self.writes.append(("post", table, out))
        return out

    def patch(self, path, body, **kw):
        table, params = self._rows(path)
        if table == "businesses":
            b = self.biz[dict(params)["id"].removeprefix("eq.")]
            b.update(json.loads(json.dumps(body)))
            self.writes.append(("patch", table, [b]))
            return [b]
        rows = [r for r in self.t.get(table, []) if all(_match(r, k, v) for k, v in params)]
        for r in rows:
            r.update(json.loads(json.dumps(body)))
        self.writes.append(("patch", table, rows))
        return json.loads(json.dumps(rows))

    def written(self, table):
        return [w for w in self.writes if w[1] == table]

    def turn_on(self, *asks, biz=BIZ):
        self.biz[biz]["settings"]["member_portal"]["asks"] = {"on": list(asks or ma.ASKS)}

    def business(self, b=BIZ):
        return json.loads(json.dumps({k: v for k, v in self.biz[b].items() if k != "owner_id"}))


@pytest.fixture
def fake(monkeypatch):
    f = Fake()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", f.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", f.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", f.patch)
    for k in ("CHURCH_MEMBER_ASKS", "CHURCH_SPACES", "CHURCH_PLEDGES"):
        monkeypatch.setenv(k, "on")
    monkeypatch.setattr(ma, "_spaces_tz", lambda biz: NY)
    monkeypatch.setattr(church_spaces, "_tz", lambda me, given=None: NY)
    ma._READY.clear()
    ma._OWNER_CACHE.clear()
    f.told = []
    monkeypatch.setattr(ma, "notify", lambda *a, **kw: f.told.append(a))
    f.person(ANA, "Ana Rivers")
    f.person(BEN, "Ben Stone")
    f.add("church_spaces", id=HALL, business_id=BIZ, name="Fellowship Hall", kind="room", capacity=120, notes="",
          active=True, sort_order=0)
    f.add("church_spaces", id=VAN, business_id=BIZ, name="Church van", kind="vehicle", active=True, sort_order=1)
    f.add("church_spaces", id=GONE, business_id=BIZ, name="Old annex", kind="room", active=False, sort_order=2)
    f.add("church_spaces", id=THEIRS, business_id=OTHER, name="Their hall", kind="room", active=True, sort_order=0)
    today = datetime.now(NY).date()
    f.add("church_campaigns", id=FUND, business_id=BIZ, name="Building Fund", goal_cents=50_000_000, fund="Building",
          starts_on=(today - timedelta(days=30)).isoformat(), ends_on=(today + timedelta(days=60)).isoformat(), note="")
    f.add("church_campaigns", id=OLD, business_id=BIZ, name="Last year's roof", goal_cents=100_000, fund="Building",
          starts_on=(today - timedelta(days=400)).isoformat(), ends_on=(today - timedelta(days=2)).isoformat(), note="")
    f.add("church_campaigns", id=FAR, business_id=OTHER, name="Their campaign", goal_cents=100_000, fund="General",
          starts_on=(today - timedelta(days=3)).isoformat(), ends_on=(today + timedelta(days=30)).isoformat(), note="")
    return f


def _app(fake, monkeypatch, me_id, space=""):
    """The church's address with `me_id` signed in, in the space they
    switched to."""
    monkeypatch.setenv("CUSTOMER_TOKEN_SECRET", "test-root-secret")
    monkeypatch.setattr(mp, "_church_for_request", lambda req: {"business": fake.business(), "site": {}})
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda b, k, **kw: True)

    def session(request, church):
        if not me_id:
            return None
        row = next(dict(c) for c in fake.t["contacts"] if c["id"] == me_id)
        return {"claims": {}, "people": [row], "me": row}
    monkeypatch.setattr(mp, "_session_for", session)
    import member_spaces as msp

    async def resolve(b, me, wanted=""):
        return msp._placed(me, space, {"youth": {}} if space == "youth" else {}, space == "kids")
    monkeypatch.setattr(msp, "resolve_async", resolve)

    async def leads(*a, **kw):
        return False
    monkeypatch.setattr(mp, "_leads", leads)
    app = FastAPI()
    app.include_router(ma.router)

    @app.get("/my/{rest:path}")
    async def page(request: Request, rest: str):
        return await mp.serve(request, "/my/" + rest)
    return TestClient(app, base_url=f"https://{HOST}")


def _post(c, path, data):
    return c.post(path, data=data, headers=ORIGIN, follow_redirects=False)


def _slot(days=3, start="17:00", end="20:00"):
    d = datetime.now(NY).date() + timedelta(days=days)
    return {"space": HALL, "day": d.isoformat(), "start": start, "end": end}


def _utc(day, hm):
    h, m = map(int, hm.split(":"))
    return church_spaces._iso(datetime(day.year, day.month, day.day, h, m, tzinfo=NY))


# ─── 1. off by default ───────────────────────────────────────────────


def test_off_by_default(fake, monkeypatch):
    biz = fake.business()
    for b in ({}, None, {"settings": {}}, {"settings": {"member_portal": {"asks": True}}},
              {"settings": {"member_portal": {"asks": {"on": "room"}}}}, biz):
        assert ma.turned_on(b) == []
    assert ma.offered(biz, minor=False) == [] and ma.entry(biz, {"id": ANA}) == []
    c = _app(fake, monkeypatch, ANA)
    for path in ("/my/ask", "/my/ask/room", "/my/ask/help", "/my/ask/pledge"):
        r = c.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/my", path
    for path, data in (("/my/ask/care", {"kind": "help", "pick": "food", "text": "Groceries this week"}),
                       ("/my/ask/room", {**_slot(), "reason": "Baby shower"}),
                       ("/my/ask/pledge", {"campaign": FUND, "amount": "100"})):
        r = _post(c, path, data)
        assert r.headers["location"] == "/my/ask?err=ask_off", path
    assert not fake.writes and not fake.told
    # Me has no way in either.
    assert "Ask the church" not in c.get("/my/me").text


def test_the_switch_keeps_it_dark(fake, monkeypatch):
    fake.turn_on("help")
    biz = fake.business()
    monkeypatch.setenv("CHURCH_MEMBER_ASKS", "off")
    assert ma.offered(biz, minor=False) == []
    monkeypatch.setenv("CHURCH_MEMBER_ASKS", "nonsense")
    assert ma.mode() == "off" and ma.offered(biz, minor=False) == []
    # Owner (the default): only a church whose owner is the platform owner.
    monkeypatch.delenv("CHURCH_MEMBER_ASKS")
    assert ma.mode() == "owner"
    monkeypatch.setattr(ma, "platform_church", lambda b: False)
    assert ma.offered(biz, minor=False) == []
    monkeypatch.setattr(ma, "platform_church", lambda b: True)
    assert ma.offered(biz, minor=False) == ["help"]


def test_platform_church_reads_the_owner_once_and_fails_closed(fake, monkeypatch):
    import messaging_router
    seen = []
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", "kevin@example.com")
    monkeypatch.setattr(messaging_router, "_owner_email", lambda uid: seen.append(uid) or
                        ("kevin@example.com" if uid == "owner" else "someone@example.com"))
    assert ma.platform_church(BIZ) is True and ma.platform_church(BIZ) is True
    assert seen == ["owner"]
    assert ma.platform_church(OTHER) is False
    monkeypatch.setattr(messaging_router, "_owner_email", lambda uid: "")
    ma._OWNER_CACHE.clear()
    assert ma.platform_church(BIZ) is False
    assert ma.platform_church("not-a-uuid") is False


# ─── 2. an ask the church didn't turn on ─────────────────────────────


def test_an_ask_the_church_didnt_turn_on_is_refused(fake, monkeypatch):
    fake.turn_on("help")
    c = _app(fake, monkeypatch, ANA)
    page = c.get("/my/ask").text
    assert "Ask for help" in page and "Book a room" not in page and "Make a pledge" not in page
    assert 'href="/my/prayer"' in page          # prayer has its own page; Ask links to it
    for path in ("/my/ask/room", "/my/ask/visit", "/my/ask/pledge", "/my/ask/life"):
        r = c.get(path, follow_redirects=False)
        assert r.headers["location"] == "/my/ask", path
    for path, data in (("/my/ask/room", {**_slot(), "reason": "Baby shower"}),
                       ("/my/ask/care", {"kind": "visit", "pick": "home"}),
                       ("/my/ask/care", {"kind": "life_event", "pick": "wedding"}),
                       ("/my/ask/care", {"kind": "anything", "pick": "x"}),
                       ("/my/ask/pledge", {"campaign": FUND, "amount": "100"})):
        assert _post(c, path, data).headers["location"] == "/my/ask?err=ask_off", data
    assert not fake.writes


def test_an_ask_its_features_dont_support_isnt_offered(fake, monkeypatch):
    fake.turn_on("room", "pledge")
    biz = fake.business()
    assert ma.offered(biz, minor=False) == ["room", "pledge"]
    monkeypatch.setenv("CHURCH_SPACES", "off")
    monkeypatch.setenv("CHURCH_PLEDGES", "off")
    assert ma.offered(biz, minor=False, fresh=True) == []
    monkeypatch.setenv("CHURCH_SPACES", "on")
    monkeypatch.setenv("CHURCH_PLEDGES", "on")
    # Only the church's active rooms count (not the van, not a retired room).
    fake.t["church_spaces"] = [s for s in fake.t["church_spaces"] if s["id"] != HALL]
    fake.t["church_campaigns"] = [c for c in fake.t["church_campaigns"] if c["id"] != FUND]
    assert ma.offered(biz, minor=False, fresh=True) == []
    # The tables before their migration: not offered, never an error.
    fake.down |= {"church_spaces", "church_campaigns"}
    assert ma.offered(biz, minor=False, fresh=True) == []


# ─── 3. a member can't book for someone else ─────────────────────────


def test_a_room_request_is_the_members_own_and_only_requested(fake, monkeypatch):
    fake.turn_on("room")
    c = _app(fake, monkeypatch, ANA)
    page = c.get("/my/ask/room").text
    assert "Fellowship Hall" in page and "Church van" not in page and "Old annex" not in page
    assert "Their hall" not in page and "is free all day" in page
    slot = _slot()
    r = _post(c, "/my/ask/room", {**slot, "reason": "Baby shower for the Rivers family",
                                  "contact_id": BEN, "status": "booked", "kind": "rental", "business_id": OTHER,
                                  "booked_by": "owner", "fee": "0"})
    assert r.headers["location"] == "/my/ask?done=ask_room"
    [b] = fake.t["church_space_bookings"]
    day = date.fromisoformat(slot["day"])
    assert b["business_id"] == BIZ and b["contact_id"] == ANA and b["status"] == "requested" and b["kind"] == "use"
    assert b["booked_by"] is None and b["decided_by"] is None and b["space_id"] == HALL
    assert b["start_at"] == _utc(day, "17:00") and b["end_at"] == _utc(day, "20:00")
    assert b["title"] == "Baby shower for the Rivers family" and not b.get("fee_cents")
    # The office is told, by the first name only.
    [(biz, area, title, body, nav, key)] = fake.told
    assert biz == BIZ and area == "office" and nav == "operate:spaces" and "Ana asked for Fellowship Hall" in body
    assert "Rivers" not in body
    # A second tap lands once; the member sees their own ask.
    _post(c, "/my/ask/room", {**slot, "reason": "Baby shower for the Rivers family"})
    assert len(fake.t["church_space_bookings"]) == 1
    page = c.get(f"/my/ask/room?day={slot['day']}").text
    assert "Your asks" in page and "Waiting for the office" in page
    # Another church's room, a vehicle, a retired room: refused.
    for space in (THEIRS, VAN, GONE, "not-a-room"):
        r = _post(c, "/my/ask/room", {**_slot(4), "space": space, "reason": "Choir practice"})
        assert "err=ask_off" in r.headers["location"], space
    assert len(fake.t["church_space_bookings"]) == 1


def test_a_room_ask_checks_its_times(fake, monkeypatch):
    fake.turn_on("room")
    c = _app(fake, monkeypatch, ANA)
    yesterday = (datetime.now(NY).date() - timedelta(days=1)).isoformat()
    for data, code in (({**_slot(), "start": "20:00", "end": "17:00"}, "ask_room_time"),
                       ({**_slot(), "day": yesterday}, "ask_room_time"),
                       ({**_slot(), "start": "25:00"}, "ask_room_time"),
                       ({**_slot(400)}, "ask_room_far"),
                       ({**_slot(), "reason": " "}, "ask_room_reason")):
        data.setdefault("reason", "Bible study")
        r = _post(c, "/my/ask/room", data)
        assert f"err={code}" in r.headers["location"] and r.headers["location"].startswith("/my/ask/room?"), data
    assert not fake.t["church_space_bookings"]


# ─── 4. the room clash ───────────────────────────────────────────────


def test_a_clash_is_refused_and_never_named(fake, monkeypatch):
    fake.turn_on("room")
    slot = _slot()
    day = date.fromisoformat(slot["day"])
    fake.add("church_space_bookings", business_id=BIZ, space_id=HALL, title="Johnson family funeral meal",
             contact_id=BEN, status="booked", start_at=_utc(day, "18:00"), end_at=_utc(day, "21:00"), kind="use")
    c = _app(fake, monkeypatch, ANA)
    page = c.get(f"/my/ask/room?space={HALL}&day={slot['day']}").text
    assert "6:00 PM" in page and "9:00 PM" in page and "Busy" in page
    assert "Johnson" not in page and "Ben" not in page and "funeral" not in page
    r = _post(c, "/my/ask/room", {**slot, "reason": "Baby shower"})
    assert r.headers["location"] == f"/my/ask/room?err=ask_room_taken&space={HALL}&day={slot['day']}"
    assert "Johnson" not in c.get(r.headers["location"]).text
    assert len(fake.t["church_space_bookings"]) == 1 and not fake.told
    # Back to back is fine (half-open, as the office's own check).
    r = _post(c, "/my/ask/room", {**slot, "start": "21:00", "end": "22:00", "reason": "Baby shower"})
    assert r.headers["location"] == "/my/ask?done=ask_room"


# ─── 5. help is confidential and lands in Care ───────────────────────


def test_help_is_confidential_and_lands_in_care(fake, monkeypatch):
    fake.turn_on("help", "visit", "life_event")
    c = _app(fake, monkeypatch, ANA)
    page = c.get("/my/ask/help").text
    assert 'name="pick" value="food"' in page and 'name="pick" value="ride"' in page
    r = _post(c, "/my/ask/care", {"kind": "help", "pick": "bill", "text": "Our light bill is past due.",
                                  "wants_call": "yes", "contact_id": BEN, "business_id": OTHER, "status": "closed"})
    assert r.headers["location"] == "/my/ask?done=ask_help"
    [row] = fake.t["ministry_care_requests"]
    sub = row["submission"]
    assert row["business_id"] == BIZ and row["contact_id"] == ANA and row["status"] == "new" and row["form_id"] is None
    assert sub["kind"] == ma.KIND_HELP == "help" and sub["need"] == "A bill" and sub["confidential"] == "yes"
    assert sub["source"] == ma.SOURCE and sub["request"] == "Our light bill is past due."
    assert sub["name"] == "Ana Rivers" and row["prayer_team"] is False and row["wants_call"] is True
    # The alert says nothing about who or what.
    [(biz, area, title, body, nav, key)] = fake.told
    assert area == "people_care" and nav == "operate:care"
    assert "Ana" not in body + title and "bill" not in body + title
    # What happens next is said plainly, in the church's name.
    done = c.get("/my/ask?done=ask_help").text
    assert "Sent privately." in done and "Someone from Love City Church will reach out to you." in done
    # A double tap lands once.
    _post(c, "/my/ask/care", {"kind": "help", "pick": "bill", "text": "Our light bill is past due."})
    assert len(fake.t["ministry_care_requests"]) == 1
    # Help needs a pick and a few words.
    assert "err=ask_pick" in _post(c, "/my/ask/care", {"kind": "help", "pick": "cash", "text": "x y"}).headers["location"]
    assert "err=ask_empty" in _post(c, "/my/ask/care", {"kind": "help", "pick": "food"}).headers["location"]


def test_a_visit_and_a_life_event_land_in_care_by_kind(fake, monkeypatch):
    fake.turn_on("visit", "life_event")
    c = _app(fake, monkeypatch, ANA)
    assert _post(c, "/my/ask/care", {"kind": "visit", "pick": "hospital"}).headers["location"] == "/my/ask?done=ask_visit"
    when = (datetime.now(NY).date() + timedelta(days=90)).isoformat()
    r = _post(c, "/my/ask/care", {"kind": "life_event", "pick": "wedding", "date": when, "text": "June, outdoors"})
    assert r.headers["location"] == "/my/ask?done=ask_life"
    visit, life = fake.t["ministry_care_requests"]
    assert visit["submission"]["kind"] == "visit" and visit["submission"]["visit"] == "A hospital visit"
    assert visit["submission"]["request"] == "A hospital visit"       # no words: the pick says it
    assert life["submission"]["kind"] == "life_event" and life["submission"]["life_event"] == "A wedding"
    assert life["submission"]["date"] == when and life["submission"]["confidential"] == "yes"
    assert all(x["prayer_team"] is False for x in (visit, life))
    assert "err=ask_date" in _post(c, "/my/ask/care", {"kind": "life_event", "pick": "baptism",
                                                       "date": "2001-01-01"}).headers["location"]


def test_crisis_words_show_the_crisis_line(fake, monkeypatch):
    fake.turn_on("help")
    c = _app(fake, monkeypatch, ANA)
    r = _post(c, "/my/ask/care", {"kind": "help", "pick": "other", "text": "I want to kill myself"})
    assert r.headers["location"] == "/my/ask?done=care"
    assert fake.t["ministry_care_requests"][0]["needs_pastor"] is True
    assert "988" in c.get(r.headers["location"]).text


# ─── 6. pledges ──────────────────────────────────────────────────────


def test_a_pledge_is_one_per_giver_to_a_running_campaign(fake, monkeypatch):
    fake.turn_on("pledge")
    c = _app(fake, monkeypatch, ANA)
    page = c.get("/my/ask/pledge").text
    assert "Building Fund" in page and "Last year's roof" not in page and "Their campaign" not in page
    r = _post(c, "/my/ask/pledge", {"campaign": FUND, "how": "total", "amount": "$1,200", "contact_id": BEN,
                                    "request_id": str(uuid.uuid4())})
    assert r.headers["location"] == "/my/ask/pledge?done=ask_pledge"
    [p] = fake.t["church_pledges"]
    assert p["business_id"] == BIZ and p["contact_id"] == ANA and p["recorded_by"] == ANA
    assert p["total_cents"] == 120_000 and p["period"] is None
    [(biz, area, title, body, nav, key)] = fake.told
    assert area == "giving" and nav == "operate:pledges" and "Ana" not in body and "1,200" not in body
    # Pledging again changes the one pledge, never a second.
    r = _post(c, "/my/ask/pledge", {"campaign": FUND, "how": "weekly", "amount": "25", "times": "52",
                                    "request_id": str(uuid.uuid4())})
    assert r.headers["location"] == "/my/ask/pledge?done=ask_pledge_changed"
    [p] = fake.t["church_pledges"]
    assert (p["per_period_cents"], p["period"], p["periods"], p["total_cents"]) == (2500, "weekly", 52, 130_000)
    # An ended campaign, another church's, nonsense: refused.
    for camp in (OLD, FAR, "nope"):
        r = _post(c, "/my/ask/pledge", {"campaign": camp, "amount": "50"})
        assert r.headers["location"] == "/my/ask/pledge?err=ask_campaign", camp
    for data, code in (({"amount": "0"}, "ask_amount"), ({"amount": "ten"}, "ask_amount"),
                       ({"amount": "10", "how": "weekly", "times": "0"}, "ask_times"),
                       ({"amount": "10", "how": "yearly"}, "ask_amount")):
        r = _post(c, "/my/ask/pledge", {"campaign": FUND, **data})
        assert r.headers["location"] == f"/my/ask/pledge?err={code}", data
    assert len(fake.t["church_pledges"]) == 1


def test_a_second_pledge_racing_the_first_finds_it(fake, monkeypatch):
    fake.turn_on("pledge")
    fake.add("church_pledges", business_id=BIZ, campaign_id=FUND, contact_id=ANA, total_cents=5000)
    real = fake.get
    # The pledge isn't seen by the first read (another tap just made it).
    calls = {"n": 0}

    def get(path, **kw):
        if path.startswith("/church_pledges") and "campaign_id" in path and calls["n"] == 0:
            calls["n"] += 1
            return []
        return real(path, **kw)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    ok, code = ma.ask_pledge(fake.business(), {"id": ANA, "name": "Ana Rivers"}, {"campaign": FUND, "amount": "20"})
    assert ok and code == "ask_pledge" and len(fake.t["church_pledges"]) == 1


def test_a_member_sees_their_own_progress(fake, monkeypatch):
    fake.turn_on("pledge")
    fake.add("church_pledges", business_id=BIZ, campaign_id=FUND, contact_id=ANA, total_cents=100_000,
             per_period_cents=None, period=None, periods=None, note="")
    paid = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    for who, total, fund in ((ANA, 250.0, "Building Fund"), (ANA, 50.0, "General"), (BEN, 9000.0, "Building")):
        fake.add("invoices", business_id=BIZ, contact_id=who, is_gift=True, status="paid", gift_fund=fund,
                 total=total, paid_at=paid, refund_amount_cents=0)
    page = _app(fake, monkeypatch, ANA).get("/my/ask/pledge").text
    assert "Given <b>$250</b> of $1,000" in page and "25%" in page and 'aria-valuenow="25"' in page
    assert "Change the amount" in page and "9,000" not in page
    # A failed gifts read says so; the pledge still shows.
    fake.down.add("invoices")
    page = _app(fake, monkeypatch, ANA).get("/my/ask/pledge").text
    assert "couldn't load just now" in page and "$1,000" in page


# ─── 7. no other church ──────────────────────────────────────────────


def test_no_other_church_is_reachable(fake, monkeypatch):
    fake.turn_on()
    # The church comes from the address the member is on, never the form:
    # a member of Other Church on Love City's address isn't signed in here.
    fake.person(TEO, "Teo Far", biz=OTHER)
    c = _app(fake, monkeypatch, ANA)
    _post(c, "/my/ask/care", {"kind": "help", "pick": "food", "text": "Groceries", "business_id": OTHER})
    _post(c, "/my/ask/room", {**_slot(), "space": THEIRS, "reason": "x y z"})
    _post(c, "/my/ask/pledge", {"campaign": FAR, "amount": "10"})
    assert all(r["business_id"] == BIZ for t in ("ministry_care_requests", "church_space_bookings", "church_pledges")
               for r in fake.t[t])
    assert not fake.t["church_space_bookings"] and not fake.t["church_pledges"]
    # Another church's office is refused.
    import business_access

    def no_role(b, user, min_role="viewer"):
        raise HTTPException(404, "business not found")
    monkeypatch.setattr(business_access, "assert_access", no_role)
    outsider = SimpleNamespace(id="other-owner", email="o@example.com")
    with pytest.raises(HTTPException) as e:
        ma.get_asks(BIZ, outsider)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        ma.save_asks(BIZ, {"on": ["help"]}, outsider)
    assert e.value.status_code == 403
    assert not fake.written("businesses")


def test_signed_out_and_cross_site_never_reach_it(fake, monkeypatch):
    fake.turn_on()
    c = _app(fake, monkeypatch, None)
    assert c.get("/my/ask", follow_redirects=False).headers["location"] == "/my"
    assert _post(c, "/my/ask/care", {"kind": "help", "pick": "food", "text": "x y"}).headers["location"] == "/my"
    c = _app(fake, monkeypatch, ANA)
    r = c.post("/my/ask/care", data={"kind": "help", "pick": "food", "text": "x y"},
               headers={"origin": "https://evil.example"}, follow_redirects=False)
    assert r.status_code == 403 and not fake.writes


# ─── 8. minors ───────────────────────────────────────────────────────


def test_a_teen_gets_only_prayer_and_help_the_youth_way(fake, monkeypatch):
    fake.turn_on()
    fake.person(TEO, "Teo Rivers", birthdate=TEEN)
    c = _app(fake, monkeypatch, TEO, "youth")
    page = c.get("/my/ask").text
    assert "Ask for help" in page and 'href="/my/prayer?for=youth"' in page
    for word in ("Book a room", "Make a pledge", "Talk to a pastor", "Plan a life event", "Sign up for an event"):
        assert word not in page, word
    for path, data in (("/my/ask/room", {**_slot(), "reason": "Party"}),
                       ("/my/ask/pledge", {"campaign": FUND, "amount": "10"}),
                       ("/my/ask/care", {"kind": "visit", "pick": "home"})):
        assert _post(c, path, data).headers["location"] == "/my/ask?err=ask_youth", path
    assert _post(c, "/my/ask/care", {"kind": "help", "pick": "ride", "text": "A ride to youth night",
                                     "wants_call": "yes"}).headers["location"] == "/my/ask?done=ask_help"
    [row] = fake.t["ministry_care_requests"]
    sub = row["submission"]
    assert sub["source"] == ma.SOURCE_YOUTH and sub["youth"] == "yes" and sub["confidential"] == "yes"
    assert row["prayer_team"] is False and not fake.t["church_space_bookings"] and not fake.t["church_pledges"]


def test_anyone_the_office_marks_a_child_is_a_minor_here_too(fake, monkeypatch):
    fake.turn_on()
    fake.person(TEO, "Teo Rivers", tags=["Youth"])          # an adult birthdate on record, tagged youth
    fake.person(KID, "Kai Rivers", birthdate=None)
    fake.add("children", business_id=BIZ, contact_id=KID)
    for who in (TEO, KID):
        assert ma.minor(BIZ, {"id": who}) is True
        page = _app(fake, monkeypatch, who).get("/my/ask").text
        assert "Ask for help" in page and "Book a room" not in page, who
    assert ma.minor(BIZ, {"id": ANA}) is False
    # A failed read is never "an adult".
    fake.down.add("children")
    assert ma.minor(BIZ, {"id": ANA}) is None
    assert _app(fake, monkeypatch, ANA).get("/my/ask").status_code == 503


def test_kids_and_an_adult_in_youth_go_back_to_church(fake, monkeypatch):
    fake.turn_on()
    for space in ("kids", "youth"):
        r = _app(fake, monkeypatch, ANA, space).get("/my/ask", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/my", space
    assert _app(fake, monkeypatch, ANA, "church").get("/my/ask").status_code == 200


# ─── 9. the rate limit ───────────────────────────────────────────────


def test_the_rate_limit_holds(fake, monkeypatch):
    import rate_limit
    fake.turn_on("help")
    c = _app(fake, monkeypatch, ANA)
    monkeypatch.setattr(rate_limit, "allow_strict", REAL_STRICT)
    monkeypatch.setenv("RATE_LIMIT_SHARED", "off")
    rate_limit._buckets.clear()
    limit = rate_limit._LIMITS["member_ask"][0]
    codes = [_post(c, "/my/ask/care", {"kind": "help", "pick": "food", "text": f"Groceries, week {i}"}).headers["location"]
             for i in range(limit + 2)]
    assert codes[:limit] == ["/my/ask?done=ask_help"] * limit
    assert codes[limit:] == ["/my/ask/help?err=slow"] * 2
    assert len(fake.t["ministry_care_requests"]) == limit
    # Another member has their own budget.
    c2 = _app(fake, monkeypatch, BEN)
    monkeypatch.setattr(rate_limit, "allow_strict", REAL_STRICT)
    assert _post(c2, "/my/ask/care", {"kind": "help", "pick": "food", "text": "Groceries"}).headers["location"]         == "/my/ask?done=ask_help"
    assert rate_limit._LIMITS["member_ask_day"][1] == 86400
    rate_limit._buckets.clear()


# ─── the office ──────────────────────────────────────────────────────


def test_only_the_owner_turns_asks_on(fake, monkeypatch):
    import business_access
    monkeypatch.setattr(business_access, "assert_access", lambda b, u, r="viewer": "admin")
    admin = SimpleNamespace(id="an-admin", email="admin@example.com")
    view = ma.get_asks(BIZ, admin)
    assert view["can_switch"] is False and view["on"] == []
    assert [c["key"] for c in view["choices"]] == list(ma.ASKS) and not any(c["on"] for c in view["choices"])
    with pytest.raises(HTTPException) as e:
        ma.save_asks(BIZ, {"on": ["help"]}, admin)
    assert e.value.status_code == 403 and not fake.written("businesses")
    owner = SimpleNamespace(id="owner", email="pastor@example.com")
    with pytest.raises(HTTPException) as e:
        ma.save_asks(BIZ, {"on": "help"}, owner)
    assert e.value.status_code == 400
    out = ma.save_asks(BIZ, {"on": ["pledge", "help", "help", "rocket"]}, owner)
    assert out["on"] == ["help", "pledge"] and out["can_switch"] is True
    cfg = fake.biz[BIZ]["settings"]["member_portal"]
    assert cfg["asks"]["on"] == ["help", "pledge"] and cfg["asks"]["by"] == "owner" and cfg["enabled"] is True
    # Each choice says what it needs and where it lands.
    by = {c["key"]: c for c in out["choices"]}
    assert by["help"]["lands"].startswith("Prayer & care") and by["room"]["lands"].startswith("Rooms & spaces")
    assert by["room"]["ready"] and by["pledge"]["ready"]
    monkeypatch.setenv("CHURCH_SPACES", "off")
    fake.t["church_campaigns"] = []
    by = {c["key"]: c for c in ma.get_asks(BIZ, owner)["choices"]}
    assert not by["room"]["ready"] and "isn't open" in by["room"]["why"]
    assert not by["pledge"]["ready"] and "campaign" in by["pledge"]["why"]


def test_the_office_section_follows_the_switch(fake, monkeypatch):
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", "kevin@example.com")
    monkeypatch.setenv("CHURCH_MEMBER_ASKS", "owner")
    owner = SimpleNamespace(id="owner", email="pastor@example.com")
    for call in (lambda: ma.get_asks(BIZ, owner), lambda: ma.save_asks(BIZ, {"on": ["help"]}, owner)):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 404
    kevin = SimpleNamespace(id="owner", email="Kevin@Example.com")
    assert ma.save_asks(BIZ, {"on": ["help"]}, kevin)["on"] == ["help"]
    monkeypatch.setenv("CHURCH_MEMBER_ASKS", "off")
    with pytest.raises(HTTPException):
        ma.get_asks(BIZ, kevin)


def test_the_office_routes_need_a_signed_in_user():
    app = FastAPI()
    app.include_router(ma.router)
    c = TestClient(app)
    assert c.get(f"/member-portal/{BIZ}/asks").status_code in (401, 403)
    assert c.put(f"/member-portal/{BIZ}/asks", json={"on": ["help"]}).status_code in (401, 403)


def test_who_hears_each_ask(fake, monkeypatch):
    import church_areas
    fake.biz[BIZ]["owner_id"] = "owner"
    for uid, role in (("adm", "admin"), ("care", "member"), ("desk", "manager"), ("look", "viewer")):
        fake.add("business_users", business_id=BIZ, user_id=uid, role=role, status="active")
    fake.add("business_users", business_id=BIZ, user_id="left", role="admin", status="removed")
    fake.add("business_collaborators", business_id=BIZ, user_id="cpa", role="accountant", status="active")
    monkeypatch.setenv("CHURCH_AREAS", "off")
    # Before Who sees what: the owner and admins.
    assert ma.recipients(BIZ, "people_care") == {"owner", "adm"}
    assert ma.recipients(BIZ, "giving") == {"owner", "adm", "cpa"}
    monkeypatch.setenv("CHURCH_AREAS", "on")
    views = {"care": {"areas": ["people_care"]}, "desk": {"areas": ["office", "giving_money"]}, "look": {"areas": None}}
    monkeypatch.setattr(church_areas, "my_areas", lambda b, uid, role: views.get(uid))
    assert ma.recipients(BIZ, "people_care") == {"owner", "adm", "care", "look"}
    assert ma.recipients(BIZ, "office") == {"owner", "adm", "desk", "look"}
    # Money is the owner's, the admins' and the accountant's, whatever the areas say.
    assert ma.recipients(BIZ, "giving") == {"owner", "adm", "cpa"}


def test_notify_rings_the_bell_and_the_phones_without_words(monkeypatch):
    import importlib
    import notification_engine
    import push_notifications
    real = importlib.reload(ma)
    try:
        bells, phones = [], []

        async def bell(client, biz, title, body, **kw):
            bells.append((biz, title, body, kw))
        monkeypatch.setattr(notification_engine, "create_urgent_alert", bell)
        monkeypatch.setattr(push_notifications, "send_to_user", lambda uid, **kw: phones.append((uid, kw)) or 1)
        monkeypatch.setattr(real, "recipients", lambda b, area: {"owner", "adm"})
        monkeypatch.setattr(real, "_later", lambda fn: fn())
        real.notify(BIZ, "people_care", "A new request in Prayer & care", "Someone asked for help.",
                    "operate:care", "ask-care-1", priority="high")
        [(biz, title, body, kw)] = bells
        assert biz == BIZ and kw["dedup_key"] == "ask-care-1" and kw["priority"] == "high"
        assert kw["suggested_action"] == "Open Prayer & care"
        assert sorted(u for u, _ in phones) == ["adm", "owner"]
        assert all(kw["nav"] == "operate:care" and kw["business_id"] == BIZ for _, kw in phones)
    finally:
        importlib.reload(ma)


# ─── the way in ──────────────────────────────────────────────────────


def test_me_and_home_point_at_ask_when_theres_something_to_ask(fake, monkeypatch):
    fake.turn_on("help", "room")
    c = _app(fake, monkeypatch, ANA)
    me = c.get("/my/me").text
    assert 'href="/my/ask"' in me and "Ask the church" in me
    row = ma.home_row(ma.entry(fake.business(), {"id": ANA, "birthdate": ADULT}))
    assert 'href="/my/ask"' in row and "A room, help" in row
    assert ma.home_row([]) == ""
    # In Kids there's no way in.
    assert "Ask the church" not in _app(fake, monkeypatch, ANA, "kids").get("/my/me").text


def test_the_pages_on_a_phone(fake, monkeypatch):
    fake.turn_on()
    c = _app(fake, monkeypatch, ANA)
    menu = c.get("/my/ask").text
    assert 'name="viewport"' in menu and "Ask the <em>church</em>" in menu
    for href in ("/my/ask/room", "/my/ask/help", "/my/ask/visit", "/my/ask/life", "/my/ask/pledge", "/my/events",
                 "/my/prayer"):
        assert f'href="{href}"' in menu, href
    # Each ask wears one family colour; tap targets are 44px or more.
    for hue in ("h-teal", "h-coral", "h-violet", "h-gold", "h-brand"):
        assert hue in menu, hue
    assert "min-height:76px" in ma.CSS and ".ask-dot{width:44px;height:44px" in ma.CSS
    for path in ("/my/ask/room", "/my/ask/help", "/my/ask/visit", "/my/ask/life", "/my/ask/pledge"):
        page = c.get(path)
        assert page.status_code == 200 and 'class="mp-go ask-cta"' in page.text, path
