"""Serving hours and background checks (church_serving.py). Kevin, 2026-10-27,
on the Church Office Prototypes ("Serving hours" tab): "lets go with your list"
and "make sure that the design is top tier".

Pins:
  * hours add up on their own: a yes at a service that has started this year
    counts from the arrive-by time (or the plan's Before items) to the plan's
    end, the team's own length when the office set one, 90 minutes when the
    plan has no times; two places the same day count their shared time once
  * a sub who said yes gets the hours; a no, an unanswered ask, an offered
    place, a pending cover and a day the person is away never move them
  * a logged group gathering counts for a leader who was marked there, never
    for a member; hours the office adds count, with their note
  * checks: due within 30 days, overdue, none on record, "can't serve with
    kids yet" (none, and on the schedule with kids soon), under 18; reminders
    go once a week at most, only to those who need one
  * another church is unreachable; a login whose areas leave Serving out is
    refused; the checks are Kids & youth's, People & care's and the owner's
  * the switch: off is a 404 and a quiet status; owner mode is the platform
    owner alone, and the member's side shows only in their own preview
  * a member sees only their own hours
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_areas  # noqa: E402
import church_serving as cs  # noqa: E402
import sb_clients  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from test_church_roles import FakeDB  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
NAMES = ("owner", "admin", "manager", "kidsdesk", "media", "office", "stranger", "other_owner")
PEOPLE = {n: AuthedUser(id=f"00000000-0000-4000-8000-{i:012d}", email=f"{n}@lovecity.org", role="authenticated")
          for i, n in enumerate(NAMES, start=1)}
ID = {n: u.id for n, u in PEOPLE.items()}
AREAS = {ID["kidsdesk"]: ["kids_youth"], ID["media"]: ["worship_media"], ID["office"]: ["office"]}
NY = ZoneInfo("America/New_York")
T0 = datetime(2026, 10, 27, 16, 0, tzinfo=timezone.utc)

DANA, ANDRE, MIA, LUIS, TEEN, OLD, NONE, KEPT, THEIRS = (f"cccccccc-0000-4000-8000-{i:012d}" for i in range(1, 10))
KIDS, WELCOME, STUDY, THEIR_TEAM = (f"9a000000-0000-4000-8000-{i:012d}" for i in range(1, 5))
NURSERY, GREETER, THEIR_PLACE = (f"9b000000-0000-4000-8000-{i:012d}" for i in range(1, 4))
S1, S2, S3, SOON, LAST_YEAR, THEIR_SVC = (f"9c000000-0000-4000-8000-{i:012d}" for i in range(1, 7))
M1, M2 = (f"9d000000-0000-4000-8000-{i:012d}" for i in range(1, 3))


def _utc(y, mo, d, h, mi=0) -> str:
    return datetime(y, mo, d, h, mi, tzinfo=NY).astimezone(timezone.utc).isoformat()


PLAN = [{"id": "s-before", "kind": "section", "title": "Before"},
        {"id": "loop", "kind": "slide", "minutes": 30},
        {"id": "s-service", "kind": "section", "title": "Service"},
        {"id": "songs", "kind": "song", "minutes": 25},
        {"id": "word", "kind": "sermon", "minutes": 35},
        {"id": "s-after", "kind": "section", "title": "After"},
        {"id": "bye", "kind": "slide", "minutes": 10}]


def _assign(sid, pid, cid, status="yes", slot=1, **kw):
    return {"id": f"{sid[-4:]}{pid[-4:]}{slot}", "business_id": kw.pop("biz", BIZ), "service_id": sid, "position_id": pid,
            "slot": slot, "contact_id": cid, "status": status, "swap_to": None, **kw}


def _contains(have, want) -> bool:
    if isinstance(want, dict):
        return isinstance(have, dict) and all(k in have and _contains(have[k], v) for k, v in want.items())
    return have == want


class ServingDB(FakeDB):
    """JSON containment (metadata=cs.{...}) and ilike *wildcards*, on the shared fake."""

    def _match(self, row, filters):
        rest = []
        for f in filters:
            if f[0] != "or" and f[1] == "cs":
                if not _contains(row.get(f[0]), json.loads(f[2])):
                    return False
            elif f[0] != "or" and f[1] == "ilike" and "*" in f[2]:
                if f[2].strip("*").lower() not in str(row.get(f[0]) or "").lower():
                    return False
            else:
                rest.append(f)
        return super()._match(row, rest)


@pytest.fixture
def db(monkeypatch):
    seats = (("admin", "admin"), ("manager", "manager"), ("kidsdesk", "member"), ("media", "manager"),
             ("office", "manager"))
    contact = lambda cid, name, born="1985-04-02", biz=BIZ, **kw: {  # noqa: E731
        "id": cid, "business_id": biz, "name": name, "birthdate": born, "email": f"{name.split()[0].lower()}@example.com",
        "metadata": {}, "updated_at": "2026-10-01T00:00:00+00:00", **kw}
    fake = ServingDB(
        businesses=[{"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": ID["owner"],
                     "settings": {"practitioner_name": "Pastor Reed"}},
                    {"id": OTHER, "name": "Grace Chapel", "type": "ministry", "owner_id": ID["other_owner"], "settings": {}}],
        business_users=[{"business_id": BIZ, "user_id": ID[n], "role": r, "status": "active",
                         "invited_email": f"{n}@lovecity.org"} for n, r in seats],
        contacts=[contact(DANA, "Dana Moore", metadata={"serving": {"hours": [
                      {"id": "e0000000-0000-4000-8000-000000000001", "on": "2026-09-12", "minutes": 240,
                       "note": "Fall work day", "by_name": "Pastor Reed"},
                      {"id": "e0000000-0000-4000-8000-000000000002", "on": "2025-06-01", "minutes": 120,
                       "note": "Last year's VBS", "by_name": "Pastor Reed"}]}}),
                  contact(ANDRE, "Andre Cole"), contact(MIA, "Mia Ellis"), contact(LUIS, "Luis Ortiz"),
                  contact(TEEN, "Jordan Price", born="2010-05-05"), contact(OLD, "Ruth Hayes"),
                  contact(NONE, "Sam Lee"), contact(KEPT, "Tasha Green", metadata={"serving": {"check_on": "2026-03-01"}}),
                  contact(THEIRS, "Grace Member", biz=OTHER)],
        groups=[{"id": KIDS, "business_id": BIZ, "name": "Kids", "kind": "team", "active": True},
                {"id": WELCOME, "business_id": BIZ, "name": "Welcome", "kind": "team", "active": True},
                {"id": STUDY, "business_id": BIZ, "name": "Tuesday Bible Study", "kind": "group", "active": True},
                {"id": THEIR_TEAM, "business_id": OTHER, "name": "Kids", "kind": "team", "active": True}],
        serve_teams=[{"group_id": KIDS, "business_id": BIZ, "call_time": "09:00:00", "sort": 0},
                     {"group_id": WELCOME, "business_id": BIZ, "call_time": None, "sort": 1},
                     {"group_id": THEIR_TEAM, "business_id": OTHER, "call_time": None, "sort": 0}],
        serve_positions=[{"id": NURSERY, "business_id": BIZ, "group_id": KIDS, "name": "Nursery", "active": True},
                         {"id": GREETER, "business_id": BIZ, "group_id": WELCOME, "name": "Greeter", "active": True},
                         {"id": THEIR_PLACE, "business_id": OTHER, "group_id": THEIR_TEAM, "name": "Nursery", "active": True}],
        group_members=[{"business_id": BIZ, "group_id": KIDS, "contact_id": c, "role": "member"}
                       for c in (DANA, MIA, TEEN, NONE, KEPT)]
        + [{"business_id": BIZ, "group_id": WELCOME, "contact_id": c, "role": "member"} for c in (ANDRE, LUIS, DANA)]
        + [{"business_id": BIZ, "group_id": STUDY, "contact_id": ANDRE, "role": "leader"},
           {"business_id": BIZ, "group_id": STUDY, "contact_id": DANA, "role": "member"}],
        worship_services=[
            {"id": S1, "business_id": BIZ, "starts_at": _utc(2026, 10, 4, 10), "items": PLAN, "archived_at": None, "is_template": False},
            {"id": S2, "business_id": BIZ, "starts_at": _utc(2026, 10, 11, 10), "items": [], "archived_at": None, "is_template": False},
            {"id": S3, "business_id": BIZ, "starts_at": _utc(2026, 10, 18, 10), "items": [], "archived_at": None, "is_template": False},
            {"id": SOON, "business_id": BIZ, "starts_at": _utc(2026, 11, 1, 10), "items": [], "archived_at": None, "is_template": False},
            {"id": LAST_YEAR, "business_id": BIZ, "starts_at": _utc(2025, 12, 28, 10), "items": [], "archived_at": None, "is_template": False},
            {"id": THEIR_SVC, "business_id": OTHER, "starts_at": _utc(2026, 10, 4, 10), "items": [], "archived_at": None, "is_template": False}],
        serve_assignments=[
            _assign(S1, NURSERY, DANA), _assign(S1, GREETER, DANA), _assign(S1, GREETER, ANDRE, slot=2),
            _assign(S1, NURSERY, None, status="offered", slot=2),
            _assign(S2, NURSERY, DANA, status="no"), _assign(S2, NURSERY, MIA, status="asked", slot=2),
            _assign(S2, GREETER, LUIS, note="Covering for Andre"),
            _assign(S3, NURSERY, DANA), _assign(S3, GREETER, ANDRE, swap_to=LUIS),
            _assign(SOON, NURSERY, MIA, status="asked"),
            _assign(LAST_YEAR, NURSERY, DANA),
            _assign(THEIR_SVC, THEIR_PLACE, THEIRS, biz=OTHER)],
        serve_away=[{"business_id": BIZ, "contact_id": DANA, "starts_on": "2026-10-17", "ends_on": "2026-10-19"}],
        group_meetings=[{"id": M1, "business_id": BIZ, "group_id": STUDY, "met_on": "2026-10-06"},
                        {"id": M2, "business_id": BIZ, "group_id": STUDY, "met_on": "2026-10-13"}],
        group_meeting_attendance=[{"business_id": BIZ, "meeting_id": M1, "contact_id": ANDRE},
                                  {"business_id": BIZ, "meeting_id": M1, "contact_id": DANA},
                                  {"business_id": BIZ, "meeting_id": M2, "contact_id": DANA}],
        space_leaders=[{"business_id": BIZ, "contact_id": DANA, "space": "kids", "background_check_on": "2024-11-15"},
                       {"business_id": BIZ, "contact_id": OLD, "space": "youth", "background_check_on": "2023-01-10"}],
        church_area_places=[], serve_prefs=[], business_sites=[],
    )
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    monkeypatch.setenv("CHURCH_SERVING", "on")
    monkeypatch.setenv("CHURCH_AREAS", "on")
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", "owner@lovecity.org")
    monkeypatch.setattr(cs, "_now", lambda: T0)
    monkeypatch.setattr(cs, "_zone", lambda biz: NY)
    monkeypatch.setattr(church_areas, "my_areas", lambda biz, uid, role: {"areas": AREAS.get(uid), "by": "picked"})
    return fake


def client(name) -> TestClient:
    app = FastAPI()
    app.include_router(cs.router)
    app.dependency_overrides[require_user] = lambda: PEOPLE[name]
    return TestClient(app)


def _read(name="owner", biz=BIZ, **q):
    extra = "".join(f"&{k}={v}" for k, v in q.items())
    return client(name).get(f"/church/serving?business_id={biz}{extra}")


def _person(page, cid):
    return next((p for p in page["people"] if p["contact_id"] == cid), None)


# ─── Hours: the arithmetic ───────────────────────────────────────────

def test_a_place_counts_from_arrive_by_to_the_plans_end():
    start = datetime(2026, 10, 4, 10, tzinfo=NY)
    assert cs.plan_minutes(PLAN) == (30, 70)
    begin, end = cs.place_span(start, PLAN, datetime.strptime("09:00", "%H:%M").time(), None)
    assert (begin.hour, begin.minute, end.hour, end.minute) == (9, 0, 11, 10), "arrive-by 9:00, the plan ends 11:10"
    begin, end = cs.place_span(start, PLAN, None, None)
    assert (begin.hour, begin.minute) == (9, 30), "no arrive-by: the Before items count back"
    begin, end = cs.place_span(start, [], None, None)
    assert (end - begin) == timedelta(minutes=90), "a plan with no times is 90 minutes"
    begin, end = cs.place_span(start, PLAN, None, 180)
    assert (begin, end - begin) == (start, timedelta(hours=3)), "the office's own length wins"
    begin, _ = cs.place_span(start, PLAN, datetime.strptime("05:00", "%H:%M").time(), None)
    assert begin.hour == 9, "an arrive-by time five hours back isn't this service's"


def test_two_places_the_same_day_count_their_shared_time_once():
    d = datetime(2026, 10, 4, tzinfo=NY)
    got = cs.credit_day([(d.replace(hour=9), d.replace(hour=11, minute=10), "kids"),
                         (d.replace(hour=9, minute=30), d.replace(hour=11, minute=10), "welcome"),
                         (d.replace(hour=11), d.replace(hour=13), "kids")])
    assert got == [("kids", 130), ("welcome", 0), ("kids", 110)]


def test_hours_add_up_from_who_said_yes(db):
    page = _read().json()
    dana, andre, luis = _person(page, DANA), _person(page, ANDRE), _person(page, LUIS)
    # Dana: Oct 4 nursery 9:00-11:10 and greeter 9:30-11:10 (counted once) = 130,
    # plus the office's 240 for the work day. Not Oct 11 (she said no), not
    # Oct 18 (she was away), not last December.
    assert dana["minutes"] == 130 + 240 and dana["sundays"] == 1 and dana["extra_minutes"] == 240
    assert dana["teams"][0] == "Kids"
    # Andre: Oct 4 greeter 100; Oct 18 greeter 90 (Luis was asked to cover and
    # hasn't said yes); one gathering he led and was marked at, 90.
    assert andre["minutes"] == 100 + 90 + 90 and andre["gatherings"] == 1
    # Luis covered Oct 11 and said yes: the place became his.
    assert luis["minutes"] == 90 and luis["sundays"] == 1
    assert _person(page, MIA) is None, "an ask nobody answered counts nothing"
    assert page["totals"]["minutes"] == 370 + 280 + 90
    assert [p["contact_id"] for p in page["people"]][:2] == [DANA, ANDRE], "the top people first"
    kids = next(t for t in page["teams"] if t["group_id"] == KIDS)
    welcome = next(t for t in page["teams"] if t["group_id"] == WELCOME)
    assert kids["minutes"] == 130 and welcome["minutes"] == 100 + 90 + 90
    assert page["groups"] == {"minutes": 90, "gatherings": 1, "leaders": 1, "names": ["Tuesday Bible Study"]}
    assert page["extra"][0]["note"] == "Fall work day" and len(page["extra"]) == 1, "this year's only"


def test_last_years_hours_are_their_own(db):
    page = _read(year=2025).json()
    assert _person(page, DANA)["minutes"] == 150 + 120, "Dec 28 (arrive by 9:00, no times: to 11:30) and last year's VBS"
    assert _read(year=2019).status_code == 400


def test_a_team_length_the_office_sets_is_how_its_sundays_count(db):
    c = client("manager")
    assert c.put("/church/serving/settings", json={"business_id": BIZ, "team_minutes": {KIDS: 180}}).status_code == 200
    dana = _person(_read().json(), DANA)
    # Kids now 10:00-13:00; the greeter 9:30-11:10 overlaps: 9:30-13:00 = 210.
    assert dana["minutes"] == 210 + 240
    assert c.put("/church/serving/settings", json={"business_id": BIZ, "team_minutes": {KIDS: None}}).status_code == 200
    assert _person(_read().json(), DANA)["minutes"] == 130 + 240
    assert c.put("/church/serving/settings", json={"business_id": BIZ, "team_minutes": {KIDS: 5}}).status_code == 400
    assert c.put("/church/serving/settings",
                 json={"business_id": BIZ, "team_minutes": {THEIR_TEAM: 120}}).status_code == 404, "their team"


def test_hours_outside_the_schedule_are_added_and_taken_off_with_a_note(db):
    c = client("admin")
    assert c.post("/church/serving/hours", json={"business_id": BIZ, "contact_id": LUIS, "on": "2026-10-24",
                                                  "hours": 3}).status_code == 400, "a note says what they did"
    assert c.post("/church/serving/hours", json={"business_id": BIZ, "contact_id": LUIS, "on": "2026-11-24",
                                                  "hours": 3, "note": "Work day"}).status_code == 400, "not the future"
    made = c.post("/church/serving/hours", json={"business_id": BIZ, "contact_id": LUIS, "on": "2026-10-24",
                                                 "hours": 2.5, "note": "Fall work day"})
    assert made.status_code == 200, made.text
    assert _person(_read().json(), LUIS)["minutes"] == 90 + 150
    gone = c.delete(f"/church/serving/hours/{made.json()['entry']['id']}?business_id={BIZ}&contact_id={LUIS}")
    assert gone.status_code == 200
    assert _person(_read().json(), LUIS)["minutes"] == 90


# ─── Checks ──────────────────────────────────────────────────────────

def test_checks_due_overdue_missing_and_cant_serve_yet(db):
    page = _read().json()
    by = {c["contact_id"]: c for c in page["checks"]}
    assert set(by) == {DANA, MIA, TEEN, NONE, KEPT, OLD}, "Kids team people and the Youth and Kids leaders; not Andre"
    assert (by[DANA]["status"], by[DANA]["due"]) == ("due", "2026-11-15"), "two years from Nov 15, 2024: 19 days"
    assert (by[OLD]["status"], by[OLD]["due"]) == ("overdue", "2025-01-10")
    assert by[NONE]["status"] == "none" and by[NONE]["on"] is None
    assert by[MIA]["status"] == "blocked" and by[MIA]["next"]["day"] == "2026-11-01", "no check, and on the schedule"
    assert by[TEEN]["status"] == "teen", "checks are for adults"
    assert (by[KEPT]["status"], by[KEPT]["due"]) == ("ok", "2028-03-01")
    assert [c["contact_id"] for c in page["checks"]][:4] == [MIA, OLD, NONE, DANA], "what needs someone first"
    assert [n["contact_id"] for n in page["needs"] if n["kind"] == "check"] == [MIA, OLD, NONE, DANA]
    assert page["check_counts"]["blocked"] == 1 and page["check_counts"]["ok"] == 1


def test_a_check_recorded_here_counts_and_reaches_the_leaders_page(db):
    c = client("kidsdesk")
    assert c.post("/church/serving/checks", json={"business_id": BIZ, "contact_id": DANA, "on": "2026-10-20"}).status_code == 403, \
        "a member-level login looks; it doesn't change"
    c = client("admin")
    assert c.post("/church/serving/checks", json={"business_id": BIZ, "contact_id": DANA, "on": "2027-01-01"}).status_code == 400
    assert c.post("/church/serving/checks", json={"business_id": BIZ, "contact_id": DANA, "on": "2026-10-20"}).status_code == 200
    by = {x["contact_id"]: x for x in _read().json()["checks"]}
    assert (by[DANA]["status"], by[DANA]["due"]) == ("ok", "2028-10-20")
    leader = next(x for x in db.t["space_leaders"] if x["contact_id"] == DANA)
    assert leader["background_check_on"] == "2026-10-20", "the Kids leaders page shows the same date"
    assert c.post("/church/serving/checks", json={"business_id": BIZ, "contact_id": MIA, "on": "2026-10-21"}).status_code == 200
    assert {x["contact_id"]: x for x in _read().json()["checks"]}[MIA]["status"] == "ok"


def test_check_years_and_link_are_the_offices(db):
    c = client("admin")
    assert c.put("/church/serving/settings", json={"business_id": BIZ, "check_link": "http://x.example"}).status_code == 400
    ok = c.put("/church/serving/settings", json={"business_id": BIZ, "check_years": 3,
                                                  "check_link": "https://checks.example.com/lovecity"})
    assert ok.status_code == 200 and ok.json()["settings"]["check_years"] == 3
    page = _read().json()
    assert page["settings"]["check_link"] == "https://checks.example.com/lovecity"
    assert {x["contact_id"]: x for x in page["checks"]}[DANA]["status"] == "ok", "three years from Nov 2024"
    assert client("media").put("/church/serving/settings",
                               json={"business_id": BIZ, "check_years": 1}).status_code == 403, "checks aren't media's"


def test_reminders_go_to_who_needs_one_and_once_a_week(db, monkeypatch):
    import member_push
    rang, mailed = [], []
    monkeypatch.setattr(member_push, "send", lambda biz, kind, **kw: rang.append((kind, kw["contact_ids"][0], kw["title"])) or 1)

    async def mail(biz, person, w, cta, app, week):
        mailed.append((person["id"], cta))
        return True
    monkeypatch.setattr(cs, "_email_one", mail)
    assert client("kidsdesk").post("/church/serving/checks/remind", json={"business_id": BIZ}).status_code == 403
    got = client("admin").post("/church/serving/checks/remind", json={"business_id": BIZ})
    assert got.status_code == 200, got.text
    assert got.json()["sent"] == 4 and got.json()["phones"] == 4 and got.json()["emails"] == 4
    assert {r[1] for r in rang} == {MIA, OLD, NONE, DANA}, "not the teen, not a current check"
    assert all(r[0] == "serving" for r in rang)
    assert next(r for r in rang if r[1] == DANA)[2] == "Your background check runs out Nov 15"
    assert next(r for r in rang if r[1] == MIA)[2] == "A background check before you serve with kids"
    assert all(m[1] is None for m in mailed), "no link and no app: the email says the office will send it"
    again = client("admin").post("/church/serving/checks/remind", json={"business_id": BIZ}).json()
    assert again["sent"] == 0 and again["recent"] == 4, "never twice in a week"
    assert len(rang) == 4


def test_reminder_words_name_where_the_check_stands():
    w = cs.reminder_words("Love City Church", {"status": "overdue", "due": "2025-01-10"}, link=True)
    assert w["title"] == "Your background check needs renewing"
    assert "Yours ran out Jan 10." in w["body"] and "link below" in w["body"]
    w = cs.reminder_words("Love City Church", {"status": "none", "due": None}, link=False)
    assert "The office will send you the link" in w["body"]


# ─── Who, and another church ─────────────────────────────────────────

def test_another_church_is_unreachable(db):
    page = _read().json()
    assert THEIRS not in {p["contact_id"] for p in page["people"]}
    assert THEIRS not in {c["contact_id"] for c in page["checks"]}
    assert _read("other_owner").status_code == 404
    assert _read("stranger").status_code == 404
    c = client("owner")
    assert c.post("/church/serving/hours", json={"business_id": BIZ, "contact_id": THEIRS, "on": "2026-10-24",
                                                  "hours": 2, "note": "Work day"}).status_code == 404
    assert c.post("/church/serving/checks", json={"business_id": BIZ, "contact_id": THEIRS, "on": "2026-10-24"}).status_code == 404
    assert db.t["contacts"][-1]["metadata"] == {}, "their person is untouched"
    assert client("other_owner").post("/church/serving/hours", json={"business_id": BIZ, "contact_id": DANA, "on": "2026-10-24",
                                                                      "hours": 2, "note": "x"}).status_code == 404


def test_areas_decide_who_sees_hours_and_who_sees_checks(db):
    def status(name):
        return client(name).get(f"/church/serving/status?business_id={BIZ}").json()
    assert status("owner") == {"enabled": True, "checks": True, "write": True}
    assert status("kidsdesk") == {"enabled": True, "checks": True, "write": False}
    assert status("media") == {"enabled": True, "checks": False, "write": True}
    assert status("office")["enabled"] is False, "their areas leave Serving out"
    assert _read("office").status_code == 403
    media = _read("media").json()
    assert media["checks"] is None and media["check_counts"] is None and media["settings"]["check_link"] is None
    assert not [n for n in media["needs"] if n["kind"] == "check"], "no check leaks through what needs someone"
    assert _person(media, DANA)["minutes"] == 370, "hours are theirs to see"
    assert client("media").post("/church/serving/checks/remind", json={"business_id": BIZ}).status_code == 403


# ─── The switch ──────────────────────────────────────────────────────

def test_the_switch(db, monkeypatch):
    monkeypatch.setenv("CHURCH_SERVING", "off")
    assert client("owner").get(f"/church/serving/status?business_id={BIZ}").json()["enabled"] is False
    assert _read().status_code == 404
    monkeypatch.setenv("CHURCH_SERVING", "owner")   # the platform owner alone until a Thursday
    assert client("owner").get(f"/church/serving/status?business_id={BIZ}").json()["enabled"] is True
    assert client("admin").get(f"/church/serving/status?business_id={BIZ}").json()["enabled"] is False
    assert _read("admin").status_code == 404
    assert cs.member_on(platform_owner_preview=True) is True
    assert cs.member_on(platform_owner_preview=False) is False
    monkeypatch.setenv("CHURCH_SERVING", "on")
    assert cs.member_on(platform_owner_preview=False) is True


def test_a_failed_read_is_a_503_never_zero_hours(db, monkeypatch):
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/serve_assignments") else real(path, **kw))
    assert _read().status_code == 503
    assert client("owner").get(f"/church/serving/status?business_id={BIZ}").json()["enabled"] is True


# ─── The member's own ────────────────────────────────────────────────

def test_a_member_sees_only_their_own_hours(db, monkeypatch):
    reads = []
    real = db.get

    def spy(path, **kw):
        reads.append(path)
        return real(path, **kw)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", spy)
    v = cs.member_view({"id": BIZ, "name": "Love City Church", "settings": {}}, DANA)
    assert v["minutes"] == 130 + 240 and v["sundays"] == 1 and v["extra"] == 1 and v["teams"] == ["Kids", "Welcome"]
    assert v["check"]["status"] == "due" and v["check"]["due"] == "2026-11-15"
    hours_reads = [p for p in reads if p.startswith(("/serve_assignments", "/group_members", "/group_meeting_attendance",
                                                      "/serve_away", "/space_leaders"))]
    assert hours_reads and all(DANA in p for p in hours_reads), "every read about people is filtered to her"
    contact_reads = [p for p in reads if p.startswith("/contacts")]
    assert all(f"id=eq.{DANA}" in p or f"id=in.({DANA})" in p for p in contact_reads)
    andre = cs.member_view({"id": BIZ, "name": "Love City Church", "settings": {}}, ANDRE)
    assert andre["minutes"] == 280 and andre["gatherings"] == 1 and andre["check"] is None, "Andre doesn't serve with kids"


def test_the_member_page_shows_hours_only_where_the_switch_lets_it(db, monkeypatch):
    import member_portal
    import member_portal_serving as mps
    me = {"id": DANA, "name": "Dana Moore"}
    biz = {"id": BIZ, "name": "Love City Church", "settings": {}}
    monkeypatch.setattr(member_portal, "_previewing", lambda request, b: None)
    got = asyncio.run(mps.hours_for(None, biz, me))
    assert got and got["minutes"] == 370
    monkeypatch.setenv("CHURCH_SERVING", "owner")
    assert asyncio.run(mps.hours_for(None, biz, me)) is None, "a member, before Thursday"
    monkeypatch.setattr(member_portal, "_previewing", lambda request, b: {"own": ID["owner"]})
    monkeypatch.setattr(cs, "is_platform_owner", lambda own: own == ID["owner"])
    assert asyncio.run(mps.hours_for(None, biz, me))["minutes"] == 370, "the platform owner's own preview"
    monkeypatch.setattr(member_portal, "_previewing", lambda request, b: {"own": ID["other_owner"]})
    assert asyncio.run(mps.hours_for(None, biz, me)) is None, "another owner's preview"
    monkeypatch.setenv("CHURCH_SERVING", "off")
    assert asyncio.run(mps.hours_for(None, biz, me)) is None


def test_the_member_page_says_thank_you_and_where_the_check_stands():
    import member_portal_serving as mps
    me = {"name": "Dana Moore"}
    html = mps._hours_html({"year": 2026, "minutes": 42 * 60, "sundays": 26, "teams": ["Kids", "Welcome"],
                            "gatherings": 4, "extra": 1}, me)
    assert "<b>42</b><span>hours</span>" in html and "Thank you, Dana." in html
    assert "Sundays on Kids and Welcome, 4 group nights and a day the office added." in html
    assert "first Sunday" in mps._hours_html({"year": 2026, "minutes": 0}, me)
    assert mps.hours_number(90) == "1.5" and mps.hours_number(60) == "1" and mps.hours_number(42 * 60 + 20) == "42"
    due = mps._check_html({"check": {"status": "due", "due": "2026-11-20", "on": "2024-11-20", "next": None},
                           "check_link": "https://checks.example.com/x"})
    assert "Runs out Nov 20" in due and 'href="https://checks.example.com/x"' in due and "Due soon" in due
    blocked = mps._check_html({"check": {"status": "blocked", "due": None, "on": None,
                                         "next": {"day": "2026-11-01", "place": "Nursery"}}, "check_link": None})
    assert "Needed before Nov 1" in blocked and "Nursery" in blocked and "The office will send you the link" in blocked
    assert mps._check_html({"check": {"status": "teen", "due": None, "on": None, "next": None}}) == ""
    assert "2024-11-20" not in due, "the member sees where it stands, not the office's date"
