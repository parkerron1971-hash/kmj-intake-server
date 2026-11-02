"""The roll (church_roll.py): a church's People page in one read.

Kevin, 2026-11-01: "the design works ... the design is good", then "build
this" (canvas BF38H75nNDSaxEC1ZJFFoe). Pins:
  · Sundays are the RECORDED ones, counted the shepherding sweep's way, the
    last 8, oldest first: P in person, O online (in person wins when both),
    M missed, N before a first visit (a first_time row, else the day the
    record was made, never for an import); a day nobody recorded is
    nobody's miss;
  · drifting is the sweep's rule on the FAMILY's Sundays, or a person's own
    with no family; inactive people never drift;
  · Member / Guest / Leader / Inactive from the status, a leader role or a
    group they lead; groups apart from teams; serving from a team or the
    positions they're trained for, and the roll still opens without Who
    serves when;
  · new guests are first visits in 30 days nobody has reached; birthdays
    this week on the church's clock, Feb 29 on Feb 28; planned baptisms;
  · a person's page: family, groups, shepherd, reach, lately (a note's
    words, never a text's), Chief's next step, a care card only as a flag,
    giving only for money logins;
  · the gate: the switch, a church, a staff seat, the areas; a failed read
    is a 503, never fewer people."""
from __future__ import annotations

import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import unquote

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.dirname(os.path.abspath(__file__))):
    if p not in sys.path:
        sys.path.insert(0, p)

import business_access as ba  # noqa: E402
import church_keys  # noqa: E402
import church_roll as cr  # noqa: E402
import church_shepherd_signals as sig  # noqa: E402
import sb_clients  # noqa: E402
from test_church_shepherd_signals import SigDB  # noqa: E402
from test_church_shepherding import (  # noqa: E402
    AVA, BEN, BETH, BIZ, BUSINESS, CALVIN, DANA, GRACE, JAYLEN, KMJ, MARCUS, OWNER, PAUL, PEOPLE, TANYA, VIC, _home,
    holder)

# Sunday Nov 1 2026, 13:00 in Detroit (18:00 UTC): a Sunday that is today.
NOW = datetime(2026, 11, 1, 18, 0, tzinfo=timezone.utc)
SUNDAYS = [date(2026, 11, 1) - timedelta(weeks=i) for i in range(10)]   # 11/1 … 8/30, newest first
OWNER_EMAIL = "kevin@example.com"


class RollDB(SigDB):
    """SigDB plus the two things the roll reads with: paging (offset) and a
    uuid[] containing one id (cs.{id})."""

    def get(self, path, **kw):
        table, _, qs = path.lstrip("/").partition("?")
        keep, offset, cs = [], 0, []
        for part in qs.split("&") if qs else []:
            k, _, v = part.partition("=")
            if k == "offset":
                offset = int(v)
                continue
            vv = unquote(v)
            if vv.startswith("cs.{"):
                cs.append((k, vv[4:-1]))
                continue
            keep.append(part)
        if table in self.broken:
            return None
        rows = super().get("/" + table + ("?" + "&".join(keep) if keep else ""), **kw)
        rows = [r for r in rows if all(val in [str(x) for x in (r.get(col) or [])] for col, val in cs)]
        return rows[offset:]


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(sig, "_now", lambda: NOW)
    monkeypatch.setattr(cr, "_now", lambda: NOW)
    monkeypatch.setenv("CHURCH_ROLL", "on")
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", OWNER_EMAIL)
    monkeypatch.setenv("CHURCH_AREAS", "off")
    cr._cache.clear()


@pytest.fixture
def db(monkeypatch):
    people = [dict(p) for p in PEOPLE]
    for p in people:
        p.setdefault("created_at", "2024-01-01T12:00:00+00:00")
    fake = RollDB(
        contacts=people,
        church_leader_roles=[holder(KMJ, "pastor")],
        households=[], household_adults=[], children=[], church_shepherds=[], church_checkin_settings=[],
        attendance=[], module_entries=[], groups=[], group_members=[], serve_positions=[], serve_trained=[],
        church_register_entries=[], church_follow_ups=[], events=[], sms_messages=[], invoices=[],
        church_role_defs=[], businesses=[dict(BUSINESS)],
    )
    fake.broken = set()
    for name in ("sb_get_as_service", "sb_post_as_service", "sb_patch_as_service", "sb_delete_as_service"):
        monkeypatch.setattr(sb_clients, name, getattr(fake, name.split("_")[1]))
    return fake


def _sunday(db, day, people, *, method="self", first=()):
    eid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"svc-{day}"))
    if not any(e["id"] == eid for e in db.t["module_entries"]):
        db.t["module_entries"].append({"id": eid, "business_id": BIZ, "data": {"_checkin_day": day.isoformat()}})
    for c in people:
        db.t["attendance"].append({"id": str(uuid.uuid4()), "business_id": BIZ, "entry_id": eid, "contact_id": c,
                                   "name": "", "method": method, "first_time": c in first,
                                   "checked_in_at": f"{day.isoformat()}T15:10:00+00:00"})
    return eid


def _every_sunday(db, extra=None):
    """Kevin is there every Sunday, so every Sunday is recorded."""
    for d in SUNDAYS:
        _sunday(db, d, [KMJ] + (extra(d) if extra else []))


def _roll(db):
    return cr.roll_view(cr.build(dict(BUSINESS)), can_care=True, can_give=False)


def _p(view, cid):
    return next(p for p in view["people"] if p["id"] == cid)


# ─── Sundays ──────────────────────────────────────────────────────────

def test_the_last_eight_recorded_sundays_oldest_first_in_person_online_missed(db):
    _every_sunday(db, lambda d: [CALVIN] if d in SUNDAYS[:2] else [])
    _sunday(db, SUNDAYS[2], [CALVIN], method="online")
    _sunday(db, SUNDAYS[3], [CALVIN], method="self")
    _sunday(db, SUNDAYS[3], [CALVIN], method="online")      # both: in person wins, whichever came last
    v = _roll(db)
    assert v["sundays"] == [d.isoformat() for d in reversed(SUNDAYS[:8])]
    assert _p(v, CALVIN)["sundays"] == "MMMMPOPP"
    assert _p(v, KMJ)["sundays"] == "PPPPPPPP"
    assert v["here_today"] == 2                             # today is a Sunday


def test_a_sunday_nobody_recorded_is_nobodys_miss_and_only_the_service_day_counts(db):
    for d in SUNDAYS[:3]:
        _sunday(db, d, [KMJ])
    _sunday(db, date(2026, 10, 28), [KMJ, CALVIN])          # a Wednesday
    v = _roll(db)
    assert len(v["sundays"]) == 3
    assert _p(v, CALVIN)["sundays"] == "MMM"


def test_before_a_first_visit_is_a_dash_and_an_import_never_is(db):
    _every_sunday(db, lambda d: [VIC] if d == SUNDAYS[1] else [])
    db.t["attendance"][:] = [dict(a, first_time=True) if a["contact_id"] == VIC else a for a in db.t["attendance"]]
    new = next(p for p in db.t["contacts"] if p["id"] == PAUL)
    new["created_at"] = "2026-10-20T12:00:00+00:00"
    new["metadata"] = {}                                    # made by hand, not imported
    old = next(p for p in db.t["contacts"] if p["id"] == BEN)
    old["created_at"] = "2026-10-20T12:00:00+00:00"         # an import stamped late
    v = _roll(db)
    assert _p(v, VIC)["sundays"] == "NNNNNNPM"
    assert _p(v, VIC)["first_visit"] == SUNDAYS[1].isoformat()
    assert _p(v, PAUL)["sundays"] == "NNNNNNMM"
    assert _p(v, BEN)["sundays"] == "MMMMMMMM"


# ─── Drifting ─────────────────────────────────────────────────────────

def test_a_family_drifts_together_and_a_child_at_church_keeps_them_home(db):
    hid = _home(db, "The Carter family", [CALVIN, DANA], [JAYLEN, AVA])
    db.t["church_shepherds"].append({"household_id": hid, "business_id": BIZ, "shepherd_contact_id": MARCUS})
    _every_sunday(db, lambda d: [CALVIN] if d in SUNDAYS[3:6] else [])
    v = _roll(db)
    for c in (CALVIN, DANA, JAYLEN, AVA):
        assert _p(v, c)["drifting"] is True
        assert _p(v, c)["family"]["name"] == "The Carter family"
    fam = next(f for f in v["families"] if f["id"] == hid)
    assert fam == {"id": hid, "name": "The Carter family", "shepherd": "Marcus Grant", "drifting": True}
    assert v["week"]["drifting"] == {"families": 1, "people": 4}
    # Ava came last Sunday: the whole family is home.
    _sunday(db, SUNDAYS[0], [AVA])
    v = _roll(db)
    assert not _p(v, CALVIN)["drifting"]


def test_someone_with_no_family_drifts_on_their_own_and_inactive_never_does(db):
    next(p for p in db.t["contacts"] if p["id"] == GRACE)["status"] = "inactive"
    _every_sunday(db, lambda d: [TANYA, GRACE] if d in SUNDAYS[3:5] else [])
    v = _roll(db)
    assert _p(v, TANYA)["drifting"] is True
    assert _p(v, GRACE)["drifting"] is False and _p(v, GRACE)["status"] == "inactive"
    assert v["week"]["drifting"] == {"families": 1, "people": 1}


# ─── Who they are here ────────────────────────────────────────────────

def test_statuses_leaders_groups_and_serving(db):
    db.t["groups"] = [{"id": "g-men", "business_id": BIZ, "name": "Men of Valor", "kind": "small_group", "active": True},
                      {"id": "g-old", "business_id": BIZ, "name": "Closed group", "kind": "small_group", "active": False},
                      {"id": "t-greet", "business_id": BIZ, "name": "Greeters", "kind": "team", "active": True},
                      {"id": "t-park", "business_id": BIZ, "name": "Parking", "kind": "team", "active": True}]
    db.t["group_members"] = [{"group_id": "g-men", "business_id": BIZ, "contact_id": MARCUS, "role": "leader"},
                             {"group_id": "g-men", "business_id": BIZ, "contact_id": CALVIN, "role": "member"},
                             {"group_id": "g-old", "business_id": BIZ, "contact_id": DANA, "role": "member"},
                             {"group_id": "t-greet", "business_id": BIZ, "contact_id": DANA, "role": "member"}]
    db.t["serve_positions"] = [{"id": "pos-1", "business_id": BIZ, "group_id": "t-park", "active": True}]
    db.t["serve_trained"] = [{"position_id": "pos-1", "business_id": BIZ, "contact_id": CALVIN, "level": "trained"}]
    _every_sunday(db)
    v = _roll(db)
    assert _p(v, KMJ)["status"] == "leader"                 # a leader role
    assert _p(v, MARCUS)["status"] == "leader"              # leads a group
    assert _p(v, VIC)["status"] == "guest"
    assert _p(v, CALVIN)["status"] == "member"
    assert _p(v, CALVIN)["groups"] == ["Men of Valor"]
    assert _p(v, CALVIN)["serving"] == ["Parking"]          # trained in Who serves when
    assert _p(v, DANA)["groups"] == [] and _p(v, DANA)["serving"] == ["Greeters"]
    assert _p(v, BETH)["last"] == "BENNETT"                 # past the suffix
    assert _p(v, CALVIN)["last"] == "Carter" and _p(v, CALVIN)["first"] == "Calvin"
    # Without Who serves when the roll still opens, with the teams it knows.
    db.broken = {"serve_positions"}
    cr._cache.clear()
    v = _roll(db)
    assert _p(v, CALVIN)["serving"] == [] and _p(v, DANA)["serving"] == ["Greeters"]


def test_ages_from_birthdays_and_a_child_record(db):
    _every_sunday(db)
    _home(db, "The Carter family", [CALVIN, DANA], [JAYLEN, AVA])
    next(p for p in db.t["contacts"] if p["id"] == BEN)["tags"] = ["Youth"]
    v = _roll(db)
    assert _p(v, JAYLEN)["age_band"] == "kid" and _p(v, AVA)["age_band"] == "kid"
    assert _p(v, BEN)["age_band"] == "youth"
    assert _p(v, CALVIN)["age_band"] == ""


# ─── This week ────────────────────────────────────────────────────────

def test_new_guests_nobody_reached_and_reaching_one_takes_them_off(db):
    _every_sunday(db, lambda d: [VIC] if d == SUNDAYS[0] else [])
    for a in db.t["attendance"]:
        if a["contact_id"] == VIC:
            a["first_time"] = True
    v = _roll(db)
    assert _p(v, VIC)["new_unreached"] is True
    assert v["week"]["new_guests"]["n"] == 1 and v["week"]["new_guests"]["names"] == ["Vic Visitor"]
    assert "Vic Visitor" in v["week"]["new_guests"]["newest"]
    db.t["sms_messages"].append({"business_id": BIZ, "contact_id": VIC, "direction": "outbound", "status": "sent",
                                 "created_at": "2026-11-01T19:00:00+00:00"})
    db.t["sms_messages"][-1]["created_at"] = "2026-11-01T17:00:00+00:00"
    v = _roll(db)
    assert _p(v, VIC)["new_unreached"] is False and v["week"]["new_guests"]["n"] == 0


def test_birthdays_this_week_on_the_churchs_clock_and_feb_29(db):
    _every_sunday(db)
    rows = {p["id"]: p for p in db.t["contacts"]}
    for r in rows.values():
        r["birthdate"] = None                               # the shared fixture's are relative to the real today
    rows[CALVIN]["birthdate"] = "1980-11-04"                # Wednesday
    rows[DANA]["birthdate"] = "1982-11-01"                  # today
    rows[TANYA]["birthdate"] = "1975-11-08"                 # a day past the week
    v = _roll(db)
    assert _p(v, CALVIN)["birthday"] == "11-04" and _p(v, DANA)["birthday"] == "11-01"
    w = v["week"]["birthdays"]
    assert w["n"] == 2 and w["from"] == "2026-11-01" and w["to"] == "2026-11-07"
    assert w["first"] == [{"name": "Dana Carter", "day": "today"}, {"name": "Calvin Carter", "day": "Wednesday"}]
    assert cr._birthday_on(date(2000, 2, 29), 2027) == date(2027, 2, 28)


def test_the_next_baptism_sunday_from_the_register(db):
    _every_sunday(db)
    db.t["church_register_entries"] = [
        {"id": "e1", "business_id": BIZ, "kind": "baptism", "status": "planned", "event_on": "2026-11-15",
         "removed_at": None, "people": [{"role": "person", "contact_id": CALVIN, "name": "Calvin Carter"}],
         "contact_ids": [CALVIN]},
        {"id": "e2", "business_id": BIZ, "kind": "baptism", "status": "planned", "event_on": "2026-11-15",
         "removed_at": None, "people": [{"role": "person", "contact_id": DANA, "name": "Dana Carter"}], "contact_ids": [DANA]},
        {"id": "e3", "business_id": BIZ, "kind": "baptism", "status": "planned", "event_on": "2026-12-06",
         "removed_at": None, "people": [], "contact_ids": [TANYA]},
        {"id": "e4", "business_id": BIZ, "kind": "baptism", "status": "planned", "event_on": "2026-10-04",
         "removed_at": None, "people": [], "contact_ids": [BEN]},           # past: not planned any more
    ]
    v = _roll(db)
    assert v["week"]["baptism"] == {"n": 2, "date": "2026-11-15", "names": ["Calvin Carter", "Dana Carter"]}
    assert _p(v, TANYA)["baptism_on"] == "2026-12-06" and _p(v, BEN)["baptism_on"] == ""


# ─── One person ───────────────────────────────────────────────────────

def test_a_persons_page_family_church_reach_lately_and_chief(db):
    hid = _home(db, "The Carter family", [CALVIN, DANA], [JAYLEN, AVA])
    db.t["church_shepherds"].append({"household_id": hid, "business_id": BIZ, "shepherd_contact_id": MARCUS})
    db.t["groups"] = [{"id": "g-men", "business_id": BIZ, "name": "Men of Valor", "kind": "small_group", "active": True}]
    db.t["group_members"] = [{"group_id": "g-men", "business_id": BIZ, "contact_id": CALVIN, "role": "leader"}]
    db.t["church_register_entries"] = [{"id": "m1", "business_id": BIZ, "kind": "membership", "membership": "joined",
                                        "status": "done", "event_on": "2019-03-10", "removed_at": None,
                                        "people": [], "contact_ids": [CALVIN]}]
    db.t["events"] = [{"business_id": BIZ, "contact_id": CALVIN, "event_type": "contact_note",
                       "data": {"note": "Asked about the men's retreat."}, "created_at": "2026-10-29T15:00:00+00:00"}]
    db.t["sms_messages"] = [{"business_id": BIZ, "contact_id": CALVIN, "direction": "outbound", "status": "sent",
                             "message": "PRIVATE WORDS", "created_at": "2026-10-30T15:00:00+00:00"}]
    _every_sunday(db, lambda d: [CALVIN] if d in SUNDAYS[3:6] else [])
    ctx = cr.build(dict(BUSINESS))
    page = cr.person_view(ctx, CALVIN, can_care=True, can_give=False)
    assert page["name"] == "Calvin Carter" and page["status"] == "leader"
    assert page["family"]["shepherd"] == "Marcus Grant"
    assert [p["name"] for p in page["family"]["people"]][:2] == ["Calvin Carter", "Dana Carter"]
    assert {p["role"].split(",")[0] for p in page["family"]["people"]} == {"", "child"}
    assert {"k": "Groups", "v": "Men of Valor (leads)"} in page["church"]
    assert {"k": "Shepherd", "v": "Marcus Grant"} in page["church"]
    assert {"k": "Member since", "v": "Mar 2019"} in page["church"]
    assert {"k": "Mobile", "v": "(231) 555-0101", "href": "tel:2315550101"} in page["reach"]
    assert {"k": "Address", "v": "2948 Mason Blvd, Muskegon, MI 49444", "href": ""} in page["reach"]
    words = [x["t"] for x in page["lately"]]
    assert "Texted by the church" in words and "Note: Asked about the men's retreat." in words
    assert not any("PRIVATE" in w for w in words)
    # Judged on the family's Sundays over the rule's own span: never "Dana
    # came 0" when the family came.
    assert page["chief"]["text"].startswith("The Carter family came 3 of the 6 Sundays before, then missed the last 3.")
    assert "Marcus Grant" in page["chief"]["text"]
    assert cr.person_view(ctx, DANA, can_care=True, can_give=False)["chief"]["text"].startswith("The Carter family came 3 of the 6")
    assert page["chief"]["actions"][0]["label"] == "Draft a text to Calvin"
    assert page["sundays"][-1] == {"date": "2026-11-01", "k": "M"}
    assert page["giving"] == [] and page["care_open"] is False


def test_a_care_card_is_a_flag_never_its_words(db):
    _every_sunday(db)
    db.t["church_follow_ups"] = [{"id": "fu1", "business_id": BIZ, "contact_id": CALVIN, "status": "open",
                                  "path_kind": "care", "answers": [{"q": "How can we pray?", "a": "SECRET"}]}]
    import church_follow_up as cfu
    page = cr.person_view(cr.build(dict(BUSINESS)), CALVIN, can_care=False, can_give=False)
    want = cfu.stream_for("care", db.t["church_follow_ups"][0]["answers"])[0] == "care_need"
    assert page["care_open"] is want
    assert "SECRET" not in str(page)
    # A read that fails is "couldn't check", never "no card".
    db.broken = {"church_follow_ups"}
    assert cr.person_view(cr.build(dict(BUSINESS)), CALVIN, can_care=False, can_give=False)["care_open"] is None


def test_giving_shows_for_a_money_login_only(db):
    _every_sunday(db)
    db.t["invoices"] = [{"id": "i1", "business_id": BIZ, "contact_id": CALVIN, "is_gift": True, "status": "paid",
                         "total": 100, "refund_amount_cents": 0, "paid_at": "2026-03-01T12:00:00+00:00"},
                        {"id": "i2", "business_id": BIZ, "contact_id": CALVIN, "is_gift": True, "status": "paid",
                         "total": 50, "refund_amount_cents": 1000, "paid_at": "2026-10-25T12:00:00+00:00"}]
    ctx = cr.build(dict(BUSINESS))
    assert cr.person_view(ctx, CALVIN, can_care=True, can_give=True)["giving"] == [
        {"k": "In 2026", "v": "$140 in 2 gifts"}, {"k": "Last gift", "v": "Oct 25"}]
    assert cr.person_view(ctx, CALVIN, can_care=True, can_give=False)["giving"] == []


def test_someone_not_on_this_churchs_roll_is_not_found(db):
    _every_sunday(db)
    ctx = cr.build(dict(BUSINESS))
    with pytest.raises(HTTPException) as e:
        cr.person_view(ctx, str(uuid.uuid4()), can_care=True, can_give=False)
    assert e.value.status_code == 404


def test_a_failed_read_is_a_503_never_fewer_people(db):
    _every_sunday(db)
    for table in ("contacts", "attendance", "households", "group_members"):
        db.broken = {table}
        with pytest.raises(HTTPException) as e:
            cr.build(dict(BUSINESS))
        assert e.value.status_code == 503, table


# ─── The gate ─────────────────────────────────────────────────────────

def _client(monkeypatch, role="manager", email=OWNER_EMAIL):
    app = FastAPI()
    app.include_router(cr.router)
    monkeypatch.setattr(ba, "_resolve_role", lambda b, u: role)
    monkeypatch.setattr(ba.billing_context, "set_current", lambda b: None)
    user = SimpleNamespace(user=SimpleNamespace(id=OWNER, user_metadata={}, email=email))
    app.dependency_overrides[sb_clients.authed_request] = lambda: user
    return TestClient(app)


def test_the_routes_for_staff_with_care_and_money_flags(db, monkeypatch):
    _every_sunday(db, lambda d: [CALVIN])
    monkeypatch.setattr(church_keys, "is_open", lambda b, u, area: area == "people_care")
    import business_collaborators_router as bcr
    monkeypatch.setattr(bcr, "is_active_accountant", lambda b, u: False)
    t = _client(monkeypatch, role="manager")
    r = t.get("/church/roll", params={"business_id": BIZ})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["can_care"] is True and body["can_give"] is False
    assert not any(k.startswith("_") for p in body["people"] for k in p)
    page = t.get(f"/church/roll/person/{CALVIN}", params={"business_id": BIZ})
    assert page.status_code == 200 and page.json()["name"] == "Calvin Carter"
    assert t.get("/church/roll/person/not-a-uuid", params={"business_id": BIZ}).status_code == 404
    owner = _client(monkeypatch, role="owner")
    monkeypatch.setattr(church_keys, "is_open", lambda b, u, area: True)
    assert owner.get("/church/roll", params={"business_id": BIZ}).json()["can_give"] is True


def test_the_switch_a_seat_below_staff_and_the_areas(db, monkeypatch):
    _every_sunday(db)
    q = {"business_id": BIZ}
    assert _client(monkeypatch, role="member").get("/church/roll", params=q).status_code == 404
    monkeypatch.setenv("CHURCH_ROLL", "owner")
    assert _client(monkeypatch, email="someone@else.org").get("/church/roll", params=q).status_code == 404
    assert _client(monkeypatch).get("/church/roll", params=q).status_code == 200
    monkeypatch.setenv("CHURCH_ROLL", "off")
    assert _client(monkeypatch).get("/church/roll", params=q).status_code == 404
    monkeypatch.setenv("CHURCH_ROLL", "on")
    import church_areas
    monkeypatch.setenv("CHURCH_AREAS", "on")
    monkeypatch.setattr(church_areas, "my_areas", lambda b, u, r: {"areas": ["worship"], "by": "picked"})
    assert _client(monkeypatch).get("/church/roll", params=q).status_code == 403
    monkeypatch.setattr(church_areas, "my_areas", lambda b, u, r: {"areas": ["office"], "by": "picked"})
    assert _client(monkeypatch).get("/church/roll", params=q).status_code == 200
    monkeypatch.setattr(church_areas, "my_areas", lambda b, u, r: None)
    assert _client(monkeypatch).get("/church/roll", params=q).status_code == 503
    assert _client(monkeypatch, role="admin").get("/church/roll", params=q).status_code == 200


def test_a_business_that_isnt_a_church_has_no_roll(db, monkeypatch):
    db.t["businesses"][0]["type"] = "coach"
    assert _client(monkeypatch).get("/church/roll", params={"business_id": BIZ}).status_code == 404
