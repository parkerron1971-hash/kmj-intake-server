# __tests__/test_sunday_planning.py
#
# ChurchSavvy Planning: Sunday teams and who serves when (sunday_planning.py).
# Pins:
#   * the switch: off hides it from everyone, owner shows it only to the
#     platform owner, on shows it to every church
#   * a stranger gets 404; a viewer seat and a booth volunteer read but never
#     schedule (403); the owner and a ChurchSavvy planner schedule
#   * a team becomes a Sunday team once, with its starting places; a place
#     name is never on a team twice; a retired place leaves the schedule
#   * who's trained on a place joins the team (the group), and someone from
#     another church is refused
#   * an ask is refused when they're away, already on another place that
#     hour, or not on the team; a yes is never overwritten by a new ask
#   * filling the month asks only trained people who are free, never past the
#     team's Sundays a month, never one person twice the same hour, and the
#     most rested first; whatever's left stays open
#   * only asks that haven't gone out yet can be taken back
#   * a volunteer is never a seat (business_users is never written)

import fnmatch
import pathlib
import sys
import uuid as uuidlib
from datetime import datetime, timezone
from urllib.parse import parse_qsl
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import business_marketing
import sb_clients
import sunday_planning as sp
import worship_team as wt
from auth_supabase import AuthedUser, require_user

BIZ = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
OWNER_EMAIL = "kmjcreativesolution@gmail.com"
PEOPLE = {name: AuthedUser(id=f"u-{name}", email=f"{name}@lovecity.org", role="authenticated")
          for name in ("viewer", "planner", "booth", "stranger")}
PEOPLE["owner"] = AuthedUser(id="u-owner", email=OWNER_EMAIL, role="authenticated")
SEATS = {("u-owner", BIZ): "owner", ("u-viewer", BIZ): "viewer"}
# Wednesday 21 October 2026, 10am in Chicago: the coming Sundays are
# 10/25, 11/1, 11/8, 11/15 and 11/22.
NOW = datetime(2026, 10, 21, 15, 0, tzinfo=timezone.utc)
ZONE = ZoneInfo("America/Chicago")
PRODUCTION = "33333333-3333-4333-8333-333333333333"
WELCOME = "44444444-4444-4444-8444-444444444444"


def _cid(n):
    return f"c0000000-0000-4000-8000-{n:012d}"


# Made-up members of the church; Ty is sixteen.
MARCUS, KENDRA, JO, ANA, LEE, TY = (_cid(i) for i in range(1, 7))
NAMES = {MARCUS: "Marcus Hill", KENDRA: "Kendra Lane", JO: "Jo Park", ANA: "Ana Cruz", LEE: "Lee Ford",
         TY: "Ty Brooks"}
ELSEWHERE = _cid(99)


class FakeDb:
    """sb_*_as_service over the tables Planning reads, with the PostgREST
    filters it uses: eq. neq. in.() is.null gte. gt. lt. lte. ilike."""

    # on_conflict targets, and the unique keys a second insert breaks.
    KEYS = {"serve_teams": ("group_id",), "serve_trained": ("position_id", "contact_id"),
            "group_members": ("group_id", "contact_id"), "serve_prefs": ("business_id", "contact_id"),
            "serve_assignments": ("service_id", "position_id", "slot")}

    def __init__(self):
        contacts = [{"id": c, "business_id": BIZ, "name": n, "birthdate": None} for c, n in NAMES.items()]
        contacts[-1]["birthdate"] = "2010-03-02"
        contacts.append({"id": ELSEWHERE, "business_id": OTHER, "name": "Not Here", "birthdate": None})
        self.t = {
            "businesses": [{"id": BIZ, "name": "Love City Church", "owner_id": "u-owner",
                            "settings": {"practitioner_name": "Pastor Kevin"}}],
            "business_users": [],
            "worship_team": [{"id": str(uuidlib.uuid4()), "business_id": BIZ, "user_id": "u-planner",
                              "name": "Dana", "roles": ["planner"], "status": "active"},
                             {"id": str(uuidlib.uuid4()), "business_id": BIZ, "user_id": "u-booth",
                              "name": "Sam", "roles": ["booth"], "status": "active"}],
            "contacts": contacts,
            "groups": [{"id": PRODUCTION, "business_id": BIZ, "name": "Production", "kind": "team", "active": True},
                       {"id": WELCOME, "business_id": BIZ, "name": "Welcome", "kind": "team", "active": True},
                       {"id": str(uuidlib.uuid4()), "business_id": BIZ, "name": "Tuesday Moms", "kind": "group",
                        "active": True}],
            "group_members": [],
            "worship_services": [],
            "serve_teams": [], "serve_positions": [], "serve_trained": [], "serve_assignments": [],
            "serve_away": [], "serve_prefs": [],
        }

    @staticmethod
    def _split(path):
        table, _, q = path.lstrip("/").partition("?")
        return table, [(k, v) for k, v in parse_qsl(q, keep_blank_values=True)
                       if k not in ("select", "order", "limit", "on_conflict")]

    @staticmethod
    def _match(row, filters):
        for k, v in filters:
            if k == "or":
                # or=(contact_id.eq.X,swap_to.eq.X,status.eq.offered): any one.
                if not any(FakeDb._match(row, [tuple(part.split(".", 1))]) for part in v[1:-1].split(",")):
                    return False
                continue
            val = row.get(k)
            have = str(val).lower() if isinstance(val, bool) else str(val)
            op, _, want = v.partition(".")
            if op == "is" and want == "null":
                if val is not None:
                    return False
            elif op == "eq" and have != want:
                return False
            elif op == "neq" and have == want:
                return False
            elif op == "in" and have not in want[1:-1].split(","):
                return False
            elif op in ("gte", "gt", "lt", "lte"):
                if val is None:
                    return False
                if not {"gte": have >= want, "gt": have > want, "lt": have < want, "lte": have <= want}[op]:
                    return False
            elif op == "ilike" and not fnmatch.fnmatch((val or "").lower(), want.lower()):
                return False
        return True

    def get(self, path, **_):
        table, f = self._split(path)
        return [dict(r) for r in self.t.get(table, []) if self._match(r, f)]

    def post(self, path, body, prefer=None, **_):
        table, _f = self._split(path)
        key = self.KEYS.get(table)
        out = []
        for b in (body if isinstance(body, list) else [body]):
            hit = next((r for r in self.t[table] if key and all(str(r.get(k)) == str(b.get(k, 1 if k == "slot" else None))
                                                                for k in key)), None)
            if hit is not None:
                if "merge-duplicates" in (prefer or ""):
                    hit.update(b)
                    out.append(dict(hit))
                    continue
                if "ignore-duplicates" in (prefer or ""):
                    continue
                return None  # a unique key broke: PostgREST answers 409
            row = {"id": str(uuidlib.uuid4()), "created_at": NOW.isoformat(), **b}
            if table in ("groups", "serve_positions"):
                row.setdefault("active", True)
            if table == "serve_positions":
                row.setdefault("needed", 1)
                row.setdefault("note", "")
            if table == "worship_services":
                row.setdefault("archived_at", None)
                row.setdefault("is_template", False)
            if table == "serve_assignments":
                row.setdefault("slot", 1)
                row.setdefault("notified_at", None)
                row.setdefault("note", "")
                row.setdefault("swap_to", None)
            self.t[table].append(row)
            out.append(dict(row))
        return None if prefer == "return=minimal" else out

    def patch(self, path, body):
        table, f = self._split(path)
        hit = [r for r in self.t[table] if self._match(r, f)]
        for r in hit:
            r.update(body)
        return [dict(r) for r in hit]

    def delete(self, path):
        table, f = self._split(path)
        self.t[table] = [r for r in self.t[table] if not self._match(r, f)]
        return True


@pytest.fixture
def api(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", db.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", db.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", db.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", db.delete)
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", OWNER_EMAIL)
    monkeypatch.setenv("SUNDAY_PLANNING", "on")
    monkeypatch.setattr(wt, "role_of", lambda biz, uid: SEATS.get((uid, biz)))
    monkeypatch.setattr(business_marketing, "business_tz", lambda row: ZONE)
    monkeypatch.setattr(sp, "_now", lambda: NOW)
    who = {"user": PEOPLE["owner"]}
    app = FastAPI()
    app.include_router(sp.router)
    app.dependency_overrides[require_user] = lambda: who["user"]
    client = TestClient(app)

    def as_(name):
        who["user"] = PEOPLE[name]
        return client

    return db, as_


# ─── helpers ─────────────────────────────────────────────────────────


def sundays(as_, count=5, who="owner"):
    r = as_(who).post("/planning/sundays", json={"business_id": BIZ, "count": count})
    assert r.status_code == 200, r.text
    return r


def services(db):
    return sorted(db.t["worship_services"], key=lambda s: s["starts_at"])


def make_team(as_, gid=PRODUCTION, places=("Sound", "Slides"), who="owner"):
    r = as_(who).post("/planning/teams", json={"business_id": BIZ, "group_id": gid, "places": list(places)})
    assert r.status_code == 200, r.text
    return r.json()["team"]


def train(as_, place_id, people, who="owner"):
    r = as_(who).put(f"/planning/positions/{place_id}/people",
                     json={"business_id": BIZ, "people": [{"contact_id": c, "level": lv} for c, lv in people]})
    assert r.status_code == 200, r.text
    return r.json()["place"]


def place(team, name):
    return next(p["id"] for p in team["places"] if p["name"] == name)


def ask(as_, svc, pid, cid, who="owner", **extra):
    return as_(who).post("/planning/ask", json={"business_id": BIZ, "service_id": svc, "position_id": pid,
                                                "contact_id": cid, **extra})


def away(db, cid, start, end):
    db.t["serve_away"].append({"id": str(uuidlib.uuid4()), "business_id": BIZ, "contact_id": cid,
                               "starts_on": start, "ends_on": end, "note": ""})


# ─── the switch and who may do what ──────────────────────────────────


def test_the_switch(api, monkeypatch):
    _db, as_ = api
    monkeypatch.setenv("SUNDAY_PLANNING", "off")
    assert as_("owner").get(f"/planning/teams?business_id={BIZ}").status_code == 404
    assert as_("owner").get("/planning/status").status_code == 404
    monkeypatch.setenv("SUNDAY_PLANNING", "owner")
    assert as_("owner").get("/planning/status").json() == {"enabled": True}
    assert as_("planner").get("/planning/status").status_code == 404
    assert as_("planner").get(f"/planning/teams?business_id={BIZ}").status_code == 404
    monkeypatch.setenv("SUNDAY_PLANNING", "on")
    assert as_("planner").get(f"/planning/status?business_id={BIZ}").json() == {
        "enabled": True, "can_write": True, "roles": ["planner"], "can_setup": False, "email_asks": False,
        "member_app": False}
    # A word the switch doesn't know is off, never on.
    monkeypatch.setenv("SUNDAY_PLANNING", "yes please")
    assert as_("owner").get("/planning/status").status_code == 404


def test_who_reads_and_who_schedules(api):
    db, as_ = api
    team = make_team(as_)
    assert as_("stranger").get(f"/planning/teams?business_id={BIZ}").status_code == 404
    assert as_("stranger").get(f"/planning/schedule?business_id={BIZ}").status_code == 404
    for reader in ("viewer", "booth"):
        r = as_(reader).get(f"/planning/teams?business_id={BIZ}")
        assert r.status_code == 200 and r.json()["can_write"] is False
        assert as_(reader).get(f"/planning/schedule?business_id={BIZ}").json()["can_write"] is False
        assert as_(reader).post("/planning/sundays", json={"business_id": BIZ}).status_code == 403
        assert as_(reader).post("/planning/positions", json={"business_id": BIZ, "group_id": PRODUCTION,
                                                             "name": "Lights"}).status_code == 403
        assert as_(reader).get(f"/planning/people?business_id={BIZ}&q=ma").status_code == 403
        assert as_(reader).post("/planning/fill", json={"business_id": BIZ}).status_code == 403
    r = as_("booth").post("/planning/teams", json={"business_id": BIZ, "group_id": WELCOME})
    assert r.status_code == 403 and "planner or an admin" in r.json()["detail"]
    # A ChurchSavvy planner schedules.
    assert make_team(as_, WELCOME, ("Greeter",), who="planner")["name"] == "Welcome"
    assert as_("planner").post("/planning/positions", json={"business_id": BIZ, "group_id": PRODUCTION,
                                                            "name": "Lights"}).status_code == 200
    assert as_("owner").get(f"/planning/teams?business_id={BIZ}").json()["can_write"] is True
    assert [p["name"] for p in as_("owner").get(f"/planning/teams?business_id={BIZ}").json()["teams"][0]["places"]] \
        == ["Sound", "Slides", "Lights"]
    assert team["group_id"] == PRODUCTION
    assert db.t["business_users"] == []


# ─── teams and places ────────────────────────────────────────────────


def test_a_team_becomes_a_sunday_team_once(api):
    db, as_ = api
    team = make_team(as_, places=("Sound", "Slides", "sound"))
    assert [p["name"] for p in team["places"]] == ["Sound", "Slides"]
    assert team["max_month"] == 2 and team["families"] is True
    j = as_("owner").get(f"/planning/teams?business_id={BIZ}").json()
    assert [t["name"] for t in j["teams"]] == ["Production"]
    # Only serving teams can be added; a Bible study group isn't one.
    assert [o["name"] for o in j["other_teams"]] == ["Welcome"]
    assert set(j["starters"]) == {"worship", "production", "welcome", "kids", "prayer"}
    r = as_("owner").post("/planning/teams", json={"business_id": BIZ, "group_id": PRODUCTION})
    assert r.status_code == 409
    moms = next(g["id"] for g in db.t["groups"] if g["name"] == "Tuesday Moms")
    assert as_("owner").post("/planning/teams", json={"business_id": BIZ, "group_id": moms}).status_code == 404
    # A new team by name is a new serving group that people ask to join.
    kids = as_("owner").post("/planning/teams", json={"business_id": BIZ, "name": "  Kids   Ministry ",
                                                      "places": ["Nursery", "Check-in"]})
    assert kids.status_code == 200, kids.text
    made = next(g for g in db.t["groups"] if g["name"] == "Kids Ministry")
    assert made["kind"] == "team" and made["join_mode"] == "ask"
    assert [p["name"] for p in kids.json()["team"]["places"]] == ["Nursery", "Check-in"]
    assert as_("owner").post("/planning/teams", json={"business_id": BIZ, "name": " "}).status_code == 400
    assert as_("owner").post("/planning/teams", json={"business_id": BIZ, "name": "X",
                                                      "places": ["p"] * 13}).status_code == 400


def test_a_teams_turns(api):
    _db, as_ = api
    make_team(as_)
    url = f"/planning/teams/{PRODUCTION}"
    r = as_("owner").patch(url, json={"business_id": BIZ, "call_time": "09:15", "max_month": 3,
                                      "swap_needs_ok": True, "families": False})
    assert r.status_code == 200, r.text
    t = r.json()["team"]
    assert (t["call_time"], t["max_month"], t["swap_needs_ok"], t["families"]) == ("09:15", 3, True, False)
    for bad in ({"call_time": "9:15am"}, {"max_month": 6}, {"max_month": True}, {"families": "yes"}, {}):
        assert as_("owner").patch(url, json={"business_id": BIZ, **bad}).status_code == 400, bad
    assert as_("owner").patch(f"/planning/teams/{WELCOME}", json={"business_id": BIZ, "max_month": 1}).status_code == 404
    assert as_("viewer").patch(url, json={"business_id": BIZ, "max_month": 1}).status_code == 403


def test_places_never_repeat_and_retire(api):
    _db, as_ = api
    team = make_team(as_)
    add = lambda **b: as_("owner").post("/planning/positions", json={"business_id": BIZ, "group_id": PRODUCTION, **b})
    r = add(name="Livestream", needed=2, note="Camera 2 on the balcony")
    assert r.status_code == 200 and r.json()["place"]["needed"] == 2 and r.json()["place"]["sort"] == 2
    assert add(name=" SOUND ").status_code == 409
    assert add(name="Lights", needed=0).status_code == 400
    assert add(name="Lights", needed=11).status_code == 400
    assert add(name="x" * 41).status_code == 400
    sound, slides = place(team, "Sound"), place(team, "Slides")
    assert as_("owner").patch(f"/planning/positions/{slides}", json={"business_id": BIZ, "name": "sound"}).status_code == 409
    r = as_("owner").patch(f"/planning/positions/{slides}", json={"business_id": BIZ, "name": "ProPresenter", "needed": 2})
    assert r.status_code == 200 and r.json()["place"]["name"] == "ProPresenter"
    assert as_("owner").delete(f"/planning/positions/{sound}?business_id={BIZ}").status_code == 200
    names = [p["name"] for p in as_("owner").get(f"/planning/teams?business_id={BIZ}").json()["teams"][0]["places"]]
    assert names == ["ProPresenter", "Livestream"]
    # A retired place's name is free again.
    assert add(name="Sound").status_code == 200
    assert as_("owner").patch(f"/planning/positions/{sound}", json={"business_id": BIZ, "note": "x"}).status_code == 404


def test_who_is_trained_joins_the_team(api):
    db, as_ = api
    team = make_team(as_)
    db.t["group_members"].append({"group_id": PRODUCTION, "contact_id": MARCUS, "business_id": BIZ, "role": "leader"})
    sound = place(team, "Sound")
    got = train(as_, sound, [(KENDRA, "trained"), (TY, "learning"), (MARCUS, "trained")])
    assert [(p["name"], p["level"], p["teen"]) for p in got["people"]] == [
        ("Kendra Lane", "trained", False), ("Marcus Hill", "trained", False), ("Ty Brooks", "learning", True)]
    on_team = {(m["contact_id"], m["role"]) for m in db.t["group_members"]}
    assert on_team == {(MARCUS, "leader"), (KENDRA, "member"), (TY, "member")}
    # The leader is listed first among the team's people.
    people = as_("owner").get(f"/planning/teams?business_id={BIZ}").json()["teams"][0]["people"]
    assert [p["name"] for p in people] == ["Marcus Hill", "Kendra Lane", "Ty Brooks"]
    assert people[0]["leader"] is True
    # Ty is trained now; Kendra comes off the place but stays on the team.
    got = train(as_, sound, [(MARCUS, "trained"), (TY, "trained")])
    assert [(p["name"], p["level"]) for p in got["people"]] == [("Marcus Hill", "trained"), ("Ty Brooks", "trained")]
    assert len(db.t["serve_trained"]) == 2 and KENDRA in {m["contact_id"] for m in db.t["group_members"]}
    r = as_("owner").put(f"/planning/positions/{sound}/people",
                         json={"business_id": BIZ, "people": [{"contact_id": ELSEWHERE}]})
    assert r.status_code == 404
    r = as_("owner").put(f"/planning/positions/{sound}/people",
                         json={"business_id": BIZ, "people": [{"contact_id": JO, "level": "expert"}]})
    assert r.status_code == 400


def test_finding_people_is_names_only(api):
    _db, as_ = api
    r = as_("owner").get(f"/planning/people?business_id={BIZ}&q=ken")
    assert r.status_code == 200 and r.json() == {"people": [{"contact_id": KENDRA, "name": "Kendra Lane", "teen": False}]}
    assert as_("owner").get(f"/planning/people?business_id={BIZ}&q=k").json() == {"people": []}
    # Another church's people never show.
    assert as_("owner").get(f"/planning/people?business_id={BIZ}&q=not here").json() == {"people": []}


# ─── the schedule ────────────────────────────────────────────────────


def test_sundays_are_added_once_at_the_churchs_time(api):
    db, as_ = api
    assert sundays(as_, 3).json() == {"added": 3}
    got = [s["starts_at"] for s in services(db)]
    # 10:30 in Chicago: daylight time on 10/25, standard time from 11/1.
    assert got == ["2026-10-25T15:30:00+00:00", "2026-11-01T16:30:00+00:00", "2026-11-08T16:30:00+00:00"]
    assert sundays(as_, 5).json() == {"added": 2}
    j = as_("owner").get(f"/planning/schedule?business_id={BIZ}").json()
    assert j["from"] == "2026-10-25"
    assert [(s["day"], s["time"]) for s in j["services"]] == [
        ("2026-10-25", "10:30"), ("2026-11-01", "10:30"), ("2026-11-08", "10:30"),
        ("2026-11-15", "10:30"), ("2026-11-22", "10:30")]
    assert as_("owner").post("/planning/sundays", json={"business_id": BIZ, "count": 9}).status_code == 400
    assert as_("owner").post("/planning/sundays", json={"business_id": BIZ, "time": "25:00"}).status_code == 400
    assert as_("owner").get(f"/planning/schedule?business_id={BIZ}&weeks=9").status_code == 400
    assert as_("owner").get(f"/planning/schedule?business_id={BIZ}&start=next week").status_code == 400


def test_an_ask_waits_for_the_sweep_and_respects_people(api):
    db, as_ = api
    sundays(as_, 2)
    s1, s2 = (s["id"] for s in services(db))
    team = make_team(as_)
    sound, slides = place(team, "Sound"), place(team, "Slides")
    train(as_, sound, [(KENDRA, "trained"), (JO, "trained")])
    train(as_, slides, [(KENDRA, "trained")])
    r = ask(as_, s1, sound, KENDRA, who="planner")
    assert r.status_code == 200, r.text
    a = r.json()["assignment"]
    assert (a["name"], a["status"], a["sent"], a["asked_by"]) == ("Kendra Lane", "asked", False, "Dana")
    # One person, one place an hour.
    r = ask(as_, s1, slides, KENDRA)
    assert r.status_code == 409 and "already on Sound" in r.json()["detail"]
    # Away that Sunday.
    away(db, JO, "2026-10-31", "2026-11-03")
    r = ask(as_, s2, sound, JO)
    assert r.status_code == 409 and "away" in r.json()["detail"]
    # Not on the team.
    assert ask(as_, s1, slides, ANA).status_code == 409
    assert ask(as_, s1, sound, ELSEWHERE).status_code == 409
    # A place with one spot has no second.
    assert ask(as_, s1, sound, JO, slot=2).status_code == 400
    # Asking someone else for the same spot replaces the ask...
    r = ask(as_, s1, sound, JO)
    assert r.status_code == 200 and len(db.t["serve_assignments"]) == 1
    aid = r.json()["assignment"]["id"]
    # ...but never a yes.
    r = as_("owner").post(f"/planning/assignments/{aid}/answer", json={"business_id": BIZ, "status": "yes"})
    assert r.status_code == 200 and r.json()["assignment"]["status"] == "yes"
    r = ask(as_, s1, sound, KENDRA)
    assert r.status_code == 409 and "Jo Park already said yes" in r.json()["detail"]
    assert as_("owner").post(f"/planning/assignments/{aid}/answer",
                             json={"business_id": BIZ, "status": "maybe"}).status_code == 400
    # Taking them off opens the place again.
    assert as_("owner").delete(f"/planning/assignments/{aid}?business_id={BIZ}").status_code == 200
    assert ask(as_, s1, sound, KENDRA).status_code == 200
    j = as_("owner").get(f"/planning/schedule?business_id={BIZ}&weeks=2").json()
    assert [(x["name"], x["status"]) for x in j["assignments"]] == [("Kendra Lane", "asked")]
    assert j["away"] == [{"contact_id": JO, "name": "Jo Park", "starts_on": "2026-10-31", "ends_on": "2026-11-03"}]
    assert db.t["business_users"] == []


def test_an_offer_goes_to_the_whole_team(api):
    db, as_ = api
    sundays(as_, 1)
    s1 = services(db)[0]["id"]
    team = make_team(as_)
    sound = place(team, "Sound")
    r = as_("owner").post("/planning/offer", json={"business_id": BIZ, "service_id": s1, "position_id": sound})
    assert r.status_code == 200
    a = r.json()["assignment"]
    assert (a["status"], a["contact_id"], a["asked_by"]) == ("offered", None, "Pastor Kevin")
    r = as_("owner").post(f"/planning/assignments/{a['id']}/answer", json={"business_id": BIZ, "status": "yes"})
    assert r.status_code == 409


def test_candidates_most_rested_first(api):
    db, as_ = api
    sundays(as_, 3)
    s1, s2, s3 = (s["id"] for s in services(db))
    team = make_team(as_)
    sound, slides = place(team, "Sound"), place(team, "Slides")
    train(as_, sound, [(KENDRA, "trained"), (JO, "trained"), (TY, "learning")])
    train(as_, slides, [(ANA, "trained")])
    db.t["group_members"].append({"group_id": PRODUCTION, "contact_id": LEE, "business_id": BIZ, "role": "member"})
    # Kendra served once already this month; Ana is on Slides at s3.
    assert ask(as_, s1, sound, KENDRA).status_code == 200
    assert ask(as_, s3, slides, ANA).status_code == 200
    away(db, JO, "2026-11-08", "2026-11-08")
    c = as_("owner").get(f"/planning/candidates?business_id={BIZ}&service_id={s2}&position_id={sound}").json()
    # 11/1 is a new month: Kendra's October doesn't count against her, and
    # Ana's 11/8 does, so Lee comes before her.
    assert [(x["name"], x["trained"], x["load"], x["ok"]) for x in c["candidates"]] == [
        ("Jo Park", "trained", 0, True), ("Kendra Lane", "trained", 0, True), ("Ty Brooks", "learning", 0, True),
        ("Lee Ford", None, 0, True), ("Ana Cruz", None, 1, True)]
    c = as_("owner").get(f"/planning/candidates?business_id={BIZ}&service_id={s3}&position_id={sound}").json()
    got = {x["name"]: x for x in c["candidates"]}
    assert got["Jo Park"]["away"] is True and got["Jo Park"]["ok"] is False
    assert got["Ana Cruz"]["clash"] == "Slides" and got["Ana Cruz"]["ok"] is False
    assert got["Ty Brooks"]["teen"] is True
    assert [x["name"] for x in c["candidates"]][-2:] == ["Jo Park", "Ana Cruz"]
    other = str(uuidlib.uuid4())
    assert as_("owner").get(f"/planning/candidates?business_id={BIZ}&service_id={s1}&position_id={other}").status_code == 404


def test_filling_the_month_is_fair(api):
    db, as_ = api
    sundays(as_, 5)
    svc = [s["id"] for s in services(db)]
    team = make_team(as_)
    as_("owner").patch(f"/planning/teams/{PRODUCTION}", json={"business_id": BIZ, "max_month": 2})
    sound, slides = place(team, "Sound"), place(team, "Slides")
    train(as_, sound, [(KENDRA, "trained"), (JO, "trained"), (TY, "learning")])
    train(as_, slides, [(KENDRA, "trained"), (ANA, "trained")])
    away(db, ANA, "2026-11-15", "2026-11-15")
    r = as_("owner").post("/planning/fill", json={"business_id": BIZ, "weeks": 5})
    assert r.status_code == 200, r.text
    j = r.json()
    rows = db.t["serve_assignments"]
    assert j["asked"] == len(rows) == len(j["ids"])
    assert all(x["asked_by"] == sp.FILLED_BY and x["status"] == "asked" and x["notified_at"] is None for x in rows)
    # Never someone learning, never anyone away, never two places an hour.
    assert TY not in {x["contact_id"] for x in rows}
    assert not any(x["contact_id"] == ANA and x["service_id"] == svc[3] for x in rows)
    for s in svc:
        held = [x["contact_id"] for x in rows if x["service_id"] == s]
        assert len(held) == len(set(held))
    # Never more than two Sundays a month each (Oct: 10/25; Nov: the other four).
    for cid in (KENDRA, JO, ANA):
        nov = [x for x in rows if x["contact_id"] == cid and x["service_id"] in svc[1:]]
        assert len(nov) <= 2, (NAMES[cid], len(nov))
    # Everything not filled is counted as still open.
    assert j["asked"] + j["still_open"] == 10
    # The fill can be taken back before it goes out; a sent ask can't.
    sent = rows[0]["id"]
    rows[0]["notified_at"] = NOW.isoformat()
    r = as_("owner").post("/planning/unfill", json={"business_id": BIZ, "ids": j["ids"]})
    assert r.status_code == 200 and r.json() == {"taken_back": j["asked"] - 1}
    assert [x["id"] for x in db.t["serve_assignments"]] == [sent]
    assert db.t["business_users"] == []


def test_fill_most_rested_first_and_one_team(api):
    db, as_ = api
    sundays(as_, 3)
    s1, s2, s3 = (s["id"] for s in services(db))
    team = make_team(as_)
    sound = place(team, "Sound")
    make_team(as_, WELCOME, ("Greeter",))
    welcome = as_("owner").get(f"/planning/teams?business_id={BIZ}").json()["teams"][1]
    train(as_, sound, [(KENDRA, "trained"), (JO, "trained")])
    train(as_, welcome["places"][0]["id"], [(LEE, "trained")])
    # Jo already serves 11/1 on Sound (asked by hand); fill three weeks of
    # Production only.
    assert ask(as_, s2, sound, JO).status_code == 200
    j = as_("owner").post("/planning/fill", json={"business_id": BIZ, "weeks": 3, "group_id": PRODUCTION}).json()
    # Slides has nobody trained, so all three stay open.
    assert j["asked"] == 2 and j["still_open"] == 3
    new = {x["service_id"]: x["contact_id"] for x in db.t["serve_assignments"] if x["id"] in j["ids"]}
    # 10/25: a tie in October, so by name. 11/8: Kendra, who hasn't served
    # in November yet, before Jo, who has.
    assert new == {s1: JO, s3: KENDRA}
    assert LEE not in {x["contact_id"] for x in db.t["serve_assignments"]}


def test_a_team_with_asks_stays(api):
    db, as_ = api
    sundays(as_, 1)
    team = make_team(as_)
    sound = place(team, "Sound")
    train(as_, sound, [(KENDRA, "trained")])
    assert ask(as_, services(db)[0]["id"], sound, KENDRA).status_code == 200
    r = as_("owner").delete(f"/planning/teams/{PRODUCTION}?business_id={BIZ}")
    assert r.status_code == 409
    db.t["serve_assignments"].clear()
    assert as_("owner").delete(f"/planning/teams/{PRODUCTION}?business_id={BIZ}").status_code == 200
    # The group, its people and its thread stay; only its Sunday turns go.
    assert db.t["serve_teams"] == [] and any(g["id"] == PRODUCTION for g in db.t["groups"])
    assert KENDRA in {m["contact_id"] for m in db.t["group_members"]}
