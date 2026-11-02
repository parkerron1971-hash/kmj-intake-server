"""The monthly report (church_monthly_report.py; Kevin, 2026-11-01: "gathering
the reports from admin should be Jessica", with "nothing about money").

Pins:
  * one section a lane, from numbers the app keeps: tasks from meetings done
    and late, rooms booked, new leaders; first-time guests and how many were
    reached, Prayer & care received and closed, people drifting; attendance at
    each service, serving places filled and open, people new to a Sunday team;
    sermons, clips and posts
  * no money anywhere in the payload or the email (asserted), and the money
    tables are never read
  * counts only: no person's name, nothing a care request asked
  * a number the church doesn't keep is left out, and so is one whose read
    failed (said in `missing`), never invented
  * the Executive Pastor, the owner and an admin; a Manager without the duty
    is told whose job it is; below a manager, 404; the switch
  * her notes per lane, saved and read back; bad keys and long notes refused
  * the send: to the owner, from the church, once a month; a resend needs
    force; a failed email frees the month; a send in flight is a 409
  * My week: due on the first Monday to the Manager who does it, until sent

The tables are the Reports pack's in-memory PostgREST (test_church_reports)."""
from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_leaders_note as cln  # noqa: E402
import church_monthly_report as cmr  # noqa: E402
import church_reports as cr  # noqa: E402
import member_asks  # noqa: E402
import messaging_router  # noqa: E402
import sb_clients  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from test_church_reports import ReportsDB  # noqa: E402
from test_church_roles import FakeDB  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OWNER, JESS, NAIYA, ADMIN, MEMBER = (f"00000000-0000-4000-8000-00000000000{i}" for i in range(1, 6))
EMAIL = {OWNER: "kmjcreativesolution@gmail.com", JESS: "jessica@lovecity.org", NAIYA: "naiya@lovecity.org",
         ADMIN: "minnie@lovecity.org", MEMBER: "helper@lovecity.org"}
C_JESS, C_NAIYA, G1, G3, K1, L1, L2, L3, M1, M2, V1, V2, V3 = (
    f"cccccccc-0000-4000-8000-0000000000{i:02d}" for i in range(1, 14))
MOD = "eeeeeeee-0000-4000-8000-000000000001"
S0, S1, S2, S3, E1 = (f"ffffffff-0000-4000-8000-00000000000{i}" for i in range(5))
NOW = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)          # Monday, 9 AM in Chicago
MONEY = re.compile(r"amount|cents|fee|giving|gift|fund|deposit|bank|money|price|pledge|donat|payout|\bpay|total_usd|usd|\$")
SECRETS = ("Robert Drift", "Guest One", "Pat Visitor", "surgery", "Lena Leader", "Vic Volunteer", "Kid Parent")


class MonthDB(ReportsDB):
    """The Reports pack's fake, plus `or=` filters (the duties read them) and
    an upsert for the month's row, as PostgREST does on_conflict."""

    def get(self, path, **kw):
        if "&or=" in path or "?or=" in path:
            table = path.lstrip("/").split("?")[0]
            return None if table in self.missing else FakeDB.get(self, path)
        return super().get(path, **kw)

    def post(self, path, body, prefer=None, **kw):
        table = path.lstrip("/").split("?")[0]
        if table in self.missing:
            return None
        if table == cmr.TABLE:
            have = self.t.setdefault(table, [])
            old = next((r for r in have if r["business_id"] == body["business_id"] and r["month"] == body["month"]), None)
            if old:
                if "ignore-duplicates" in (prefer or ""):
                    return []
                old.update(body)
                return [dict(old)]
            row = {"send_id": None, "send_state": None, "sent_at": None, "sent_by": None, "sent_by_name": None,
                   "sends": 0, "notes": {}, "notes_at": None, "notes_by_name": None, **body}
            have.append(row)
            return [dict(row)]
        return super().post(path, body, prefer, **kw)

    def patch(self, path, body, **kw):
        if path.lstrip("/").split("?")[0] in self.missing:
            return None
        return super().patch(path, body, **kw)


def _seat(uid, role, lane=None, contact=None):
    return {"business_id": BIZ, "user_id": uid, "role": role, "status": "active", "invited_email": EMAIL[uid],
            "lane": lane, "areas": None, "contact_id": contact, "name": None}


def _c(cid, name, email=None):
    return {"id": cid, "business_id": BIZ, "name": name, "email": email, "status": "lead",
            "created_at": "2026-01-01T00:00:00+00:00", "metadata": {}}


def _svc(eid, day, title="Sunday Worship", **data):
    return {"id": eid, "business_id": BIZ, "module_id": MOD, "status": "active",
            "data": {"title": title, "date": day, "signups": [], **data}}


def _att(i, entry, at, contact=None, name="Someone", first=False):
    return {"id": f"att-{i:03d}", "business_id": BIZ, "entry_id": entry, "contact_id": contact, "name": name,
            "first_time": first, "checked_in_at": at}


@pytest.fixture
def rdb(monkeypatch):
    import church_areas
    church_areas._MY_CACHE.clear()
    cr._CACHE.clear()
    fake = MonthDB(
        businesses=[{"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": OWNER,
                     "created_at": "2024-03-01T00:00:00+00:00",
                     "settings": {"practitioner_name": "Pastor Kevin", "availability": {"timezone": "America/Chicago"}}}],
        business_users=[_seat(JESS, "manager"), _seat(NAIYA, "manager", "office_leadership", C_NAIYA),
                        _seat(ADMIN, "admin", "treasurer"), _seat(MEMBER, "member")],
        contacts=[_c(C_JESS, "Jessica McCloud", "jessica@lovecity.org"), _c(C_NAIYA, "Naiya Clark", "naiya@lovecity.org"),
                  _c(G1, "Guest One", "g1@example.com"), _c(G3, "Guest Three"), _c(K1, "Kid Parent"),
                  _c(L1, "Lena Leader"), _c(L2, "Old Leader"), _c(L3, "Asked Leader"),
                  _c(M1, "Steady Member"), _c(M2, "Robert Drift"),
                  _c(V1, "Vic Volunteer"), _c(V2, "Old Volunteer"), _c(V3, "Two Teams")],
        church_role_defs=[{"id": "def-xp", "business_id": BIZ, "key": "executive_pastor", "catalog_key": "executive_pastor",
                           "title": "Executive Pastor", "job": "pastoral", "status": "active"}],
        church_leader_roles=[
            {"id": "r0", "business_id": BIZ, "contact_id": C_JESS, "role": "executive_pastor", "status": "active",
             "answered_at": "2026-09-01T12:00:00+00:00", "created_at": "2026-09-01T12:00:00+00:00"},
            {"id": "r1", "business_id": BIZ, "contact_id": L1, "role": "team_leader", "status": "active",
             "answered_at": "2026-10-08T15:00:00+00:00", "created_at": "2026-10-01T12:00:00+00:00"},
            {"id": "r2", "business_id": BIZ, "contact_id": L2, "role": "team_leader", "status": "active",
             "answered_at": None, "created_at": "2025-05-01T12:00:00+00:00"},
            {"id": "r3", "business_id": BIZ, "contact_id": L2, "role": "care_team", "status": "active",
             "answered_at": "2026-10-09T12:00:00+00:00", "created_at": "2026-10-09T12:00:00+00:00"},
            {"id": "r4", "business_id": BIZ, "contact_id": L3, "role": "care_team", "status": "invited",
             "answered_at": None, "created_at": "2026-10-10T12:00:00+00:00"}],
        church_duty_holders=[],
        # Office & Leadership
        church_board_items=[{"id": f"bi{i}", "business_id": BIZ, "task_id": t} for i, t in
                            enumerate(["t-done", "t-late", "t-later", None])],
        tasks=[{"id": "t-done", "business_id": BIZ, "status": "done", "due_date": "2026-10-20",
                "completed_at": "2026-10-15T16:00:00+00:00", "created_at": "2026-10-01T12:00:00+00:00"},
               {"id": "t-late", "business_id": BIZ, "status": "todo", "due_date": "2026-10-10", "completed_at": None,
                "created_at": "2026-10-01T12:00:00+00:00"},
               {"id": "t-later", "business_id": BIZ, "status": "todo", "due_date": "2026-11-20", "completed_at": None,
                "created_at": "2026-10-01T12:00:00+00:00"},
               {"id": "t-other", "business_id": BIZ, "status": "done", "due_date": "2026-10-05",
                "completed_at": "2026-10-05T16:00:00+00:00", "created_at": "2026-10-01T12:00:00+00:00"}],
        church_spaces=[{"id": "sp1", "business_id": BIZ, "name": "Fellowship Hall"}],
        church_space_bookings=[
            {"id": "bk1", "business_id": BIZ, "status": "booked", "start_at": "2026-10-05T23:00:00+00:00", "kind": "use"},
            {"id": "bk2", "business_id": BIZ, "status": "booked", "start_at": "2026-10-12T23:00:00+00:00", "kind": "use"},
            {"id": "bk3", "business_id": BIZ, "status": "requested", "start_at": "2026-10-19T23:00:00+00:00", "kind": "use"},
            {"id": "bk4", "business_id": BIZ, "status": "booked", "start_at": "2026-10-20T23:00:00+00:00", "kind": "rental",
             "fee_cents": 25000, "deposit_cents": 10000},
            {"id": "bk5", "business_id": BIZ, "status": "booked", "start_at": "2026-11-03T23:00:00+00:00", "kind": "use"}],
        # People & Care
        custom_modules=[{"id": MOD, "business_id": BIZ, "archetype": "event_roster", "is_active": True,
                         "name": "Services & Events", "archetype_params": {}, "created_at": "2024-03-01T00:00:00+00:00"}],
        module_entries=[_svc(S0, "2026-09-27"), _svc(S1, "2026-10-04"), _svc(S2, "2026-10-11"), _svc(S3, "2026-10-18"),
                        _svc(E1, "2026-10-10", "Fall Festival", type="event")],
        attendance=([_att(0, S0, "2026-09-27T15:00:00+00:00", G3, "Guest Three", first=True),
                     _att(1, S1, "2026-10-04T15:00:00+00:00", G1, "Guest One", first=True),
                     _att(2, S1, "2026-10-04T15:01:00+00:00", G3, "Guest Three", first=True),
                     _att(3, S2, "2026-10-11T15:00:00+00:00", None, "Pat Visitor", first=True)]
                    + [_att(10 + i, S2, "2026-10-11T15:05:00+00:00") for i in range(3)]),
        attendance_headcounts=[{"id": "h1", "business_id": BIZ, "entry_id": S1, "area": "Sanctuary", "count": 120},
                               {"id": "h2", "business_id": BIZ, "entry_id": S2, "area": "Sanctuary", "count": 98}],
        church_follow_ups=[{"id": "fu1", "business_id": BIZ, "contact_id": K1, "source_event": "first-visit:h:hh1",
                            "created_at": "2026-10-18T16:00:00+00:00"}],
        sms_messages=[{"id": "sm1", "business_id": BIZ, "contact_id": G1, "direction": "outbound", "status": "sent",
                       "created_at": "2026-10-06T16:00:00+00:00"},
                      {"id": "sm2", "business_id": BIZ, "contact_id": G3, "direction": "outbound", "status": "failed",
                       "created_at": "2026-10-06T16:00:00+00:00"}],
        events=[{"id": "ev1", "business_id": BIZ, "contact_id": K1, "event_type": "activity_logged",
                 "created_at": "2026-10-10T16:00:00+00:00"}],
        ministry_care_requests=[
            {"id": "cq1", "business_id": BIZ, "status": "new", "created_at": "2026-10-03T16:00:00+00:00",
             "status_changed_at": None, "legacy_source": None, "submission": {"text": "Pray for my sister's surgery"}},
            {"id": "cq2", "business_id": BIZ, "status": "closed", "created_at": "2026-10-20T16:00:00+00:00",
             "status_changed_at": "2026-10-25T16:00:00+00:00", "legacy_source": None, "submission": {}},
            {"id": "cq3", "business_id": BIZ, "status": "closed", "created_at": "2026-09-28T16:00:00+00:00",
             "status_changed_at": "2026-10-02T16:00:00+00:00", "legacy_source": None, "submission": {}}],
        groups=[{"id": "g1", "business_id": BIZ, "kind": "small_group", "active": True, "name": "Tuesday Women"},
                {"id": "gt", "business_id": BIZ, "kind": "team", "active": True, "name": "Greeters"},
                {"id": "gt2", "business_id": BIZ, "kind": "team", "active": True, "name": "Ushers"}],
        group_members=[{"id": "gm1", "business_id": BIZ, "group_id": "g1", "contact_id": M1, "joined_on": "2026-01-01"},
                       {"id": "gm2", "business_id": BIZ, "group_id": "g1", "contact_id": M2, "joined_on": "2026-01-01"},
                       {"id": "gm3", "business_id": BIZ, "group_id": "gt", "contact_id": V1, "joined_on": "2026-10-07"},
                       {"id": "gm4", "business_id": BIZ, "group_id": "gt", "contact_id": V2, "joined_on": "2026-03-01"},
                       {"id": "gm5", "business_id": BIZ, "group_id": "gt", "contact_id": V3, "joined_on": "2026-10-09"},
                       {"id": "gm6", "business_id": BIZ, "group_id": "gt2", "contact_id": V3, "joined_on": "2026-02-01"}],
        group_meetings=[{"id": f"mt{i}", "business_id": BIZ, "group_id": "g1", "met_on": d}
                        for i, d in enumerate(["2026-10-13", "2026-10-20", "2026-10-27"])],
        group_meeting_attendance=[{"business_id": BIZ, "meeting_id": f"mt{i}", "contact_id": M1} for i in range(3)],
        # Sunday & Serving
        serve_teams=[{"business_id": BIZ, "group_id": "gt", "sort": 0}, {"business_id": BIZ, "group_id": "gt2", "sort": 1}],
        serve_positions=[{"id": "pos1", "business_id": BIZ, "group_id": "gt", "needed": 2, "active": True},
                         {"id": "pos2", "business_id": BIZ, "group_id": "gt", "needed": 1, "active": True}],
        worship_services=[
            {"id": "ws1", "business_id": BIZ, "archived_at": None, "is_template": False, "starts_at": "2026-10-04T15:00:00+00:00"},
            {"id": "ws2", "business_id": BIZ, "archived_at": None, "is_template": False, "starts_at": "2026-10-11T15:00:00+00:00"},
            {"id": "ws9", "business_id": BIZ, "archived_at": "2026-10-01T00:00:00+00:00", "is_template": False,
             "starts_at": "2026-10-18T15:00:00+00:00"}],
        serve_assignments=[
            {"id": "a1", "business_id": BIZ, "service_id": "ws1", "position_id": "pos1", "slot": 1, "status": "yes"},
            {"id": "a2", "business_id": BIZ, "service_id": "ws1", "position_id": "pos1", "slot": 2, "status": "no"},
            {"id": "a3", "business_id": BIZ, "service_id": "ws1", "position_id": "pos2", "slot": 1, "status": "yes"},
            {"id": "a4", "business_id": BIZ, "service_id": "ws2", "position_id": "pos1", "slot": 1, "status": "asked"},
            {"id": "a5", "business_id": BIZ, "service_id": "ws2", "position_id": "pos2", "slot": 1, "status": "yes"}],
        # Media & Communications
        sermons=[{"id": f"sr{i}", "business_id": BIZ, "published": p, "preached_on": d} for i, (p, d) in
                 enumerate([(True, "2026-10-05"), (True, "2026-10-12"), (False, "2026-10-19"), (True, "2026-09-28")])],
        social_connections=[{"id": "sc1", "business_id": BIZ, "status": "connected"}],
        social_publications=[
            {"id": "p1", "business_id": BIZ, "status": "posted", "media": [], "scheduled_at": None,
             "created_at": "2026-10-03T16:00:00+00:00"},
            {"id": "p2", "business_id": BIZ, "status": "partly_posted", "media": [{"kind": "video", "clip_id": "clip-1"}],
             "scheduled_at": None, "created_at": "2026-10-10T16:00:00+00:00"},
            {"id": "p3", "business_id": BIZ, "status": "failed", "media": [], "scheduled_at": None,
             "created_at": "2026-10-12T16:00:00+00:00"},
            {"id": "p4", "business_id": BIZ, "status": "posted", "media": [], "scheduled_at": "2026-10-20T16:00:00+00:00",
             "created_at": "2026-09-25T16:00:00+00:00"},
            {"id": "p5", "business_id": BIZ, "status": "posted", "media": [], "scheduled_at": None,
             "created_at": "2026-11-01T16:00:00+00:00"}],
        # Money the report must never read.
        invoices=[{"id": "inv1", "business_id": BIZ, "is_gift": True, "status": "paid", "total": 500}],
        church_help_given=[{"id": "hg1", "business_id": BIZ, "amount_cents": 20000}],
        church_monthly_reports=[],
    )
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    monkeypatch.setattr(cmr, "_now", lambda: NOW)
    monkeypatch.setenv("CHURCH_MONTHLY_REPORT", "on")
    monkeypatch.delenv("CHURCH_AREAS", raising=False)
    monkeypatch.setattr(messaging_router, "_owner_email", lambda uid: "pastor@lovecity.org" if uid == OWNER else "")
    fake.sent, fake.fail = [], False

    def deliver(biz, to, name, subject, html, key, reply_to=None):
        if fake.fail:
            raise RuntimeError("Resend said no")
        fake.sent.append({"to": to, "name": name, "subject": subject, "html": html, "key": key, "reply_to": reply_to})
    monkeypatch.setattr(cln, "deliver", deliver)
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow", lambda bucket, key: True)
    return fake


@pytest.fixture
def app(rdb, monkeypatch):
    import business_access
    who = {"id": JESS}
    roles = {OWNER: "owner", JESS: "manager", NAIYA: "manager", ADMIN: "admin", MEMBER: "member"}
    monkeypatch.setattr(business_access, "_resolve_role", lambda b, u: roles.get(str(u)))
    a = FastAPI()
    a.include_router(cmr.router)
    a.dependency_overrides[require_user] = lambda: AuthedUser(id=who["id"], email=EMAIL[who["id"]], role="authenticated")
    c = TestClient(a)
    c.who = who
    return c


def _get(app, month=""):
    r = app.get(f"/church/monthly-report?business_id={BIZ}" + (f"&month={month}" if month else ""))
    assert r.status_code == 200, r.text
    return r.json()


def _lines(report):
    return {ln["key"]: ln["value"] for s in report["sections"] for ln in s["lines"]}


def _keys(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from _keys(v)
    elif isinstance(x, list):
        for v in x:
            yield from _keys(v)


def _send(app, **body):
    return app.post("/church/monthly-report/send", json={"business_id": BIZ, **body})


# ─── The numbers ──────────────────────────────────────────────────────

def test_last_month_by_default_one_section_a_lane(app):
    rep = _get(app)
    assert rep["month"] == "2026-10" and rep["month_words"] == "October 2026" and not rep["current"]
    assert [s["key"] for s in rep["sections"]] == ["office_leadership", "people_care", "sunday_serving", "media_comms"]
    assert [s["label"] for s in rep["sections"]] == ["Office & Leadership", "People & Care", "Sunday & Serving",
                                                     "Media & Communications"]
    assert rep["due"] == {"day": "2026-11-02", "words": "Monday, November 2"} and rep["to"] == {"name": "Pastor Kevin"}
    assert rep["through"] == "2026-10-31" and rep["months"][0]["month"] == "2026-11"


def test_each_lanes_numbers(app):
    got = _lines(_get(app))
    assert got["meeting_tasks_done"] == 1 and got["meeting_tasks_late"] == 1
    assert got["rooms_booked"] == 3, "booked ones that month, a rental counted without its fee"
    assert got["new_leaders"] == 1, "a person whose first role began that month"
    assert got["guests"] == 3, "a check-in, a name-only visit and a family the kids desk welcomed; a September guest isn't"
    assert got["guests_reached"] == 1, "a text that went counts; a failed one, or a call before the visit, doesn't"
    assert got["care_opened"] == 2 and got["care_closed"] == 2
    assert got["drifting"] == 1
    assert got["attendance"] == [{"day": "2026-10-04", "title": "Sunday Worship", "total": 120},
                                 {"day": "2026-10-11", "title": "Sunday Worship", "total": 98}]
    assert got["serving_filled"] == 3 and got["serving_open"] == 3
    assert got["new_volunteers"] == 1, "new to every Sunday team, not just this one"
    assert got["sermons"] == 2 and got["clips"] == 1 and got["posts"] == 3


def test_nothing_about_money_anywhere(app, rdb):
    rep = _get(app)
    bad = [k for k in _keys(rep) if MONEY.search(k.lower())]
    assert not bad, bad
    said = str(rep).lower()
    assert "$" not in said and "fee" not in said and "25000" not in said
    read = " ".join(rdb.reads)
    for table in ("invoices", "church_help_given", "church_help_requests", "business_budgets", "giving_counts",
                  "plaid_transactions", "bills", "business_expenses"):
        assert f"/{table}?" not in read, table
    assert "fee_cents" not in read and "amount" not in read


def test_counts_only_never_a_name_or_what_was_asked(app):
    said = str(_get(app))
    for word in SECRETS:
        assert word not in said, word
    assert "@" not in said


def test_a_number_the_church_doesnt_keep_is_left_out(app, rdb):
    for t in ("church_spaces", "church_board_items", "serve_teams", "sermons", "social_connections", "groups"):
        rdb.t[t] = []
    got = _lines(_get(app))
    for key in ("rooms_booked", "meeting_tasks_done", "meeting_tasks_late", "serving_filled", "serving_open",
                "new_volunteers", "sermons", "clips", "posts", "drifting"):
        assert key not in got, key
    assert got["new_leaders"] == 1 and got["guests"] == 3


def test_a_read_that_fails_leaves_its_line_out_and_says_so(app, rdb):
    rdb.missing |= {"church_space_bookings", "social_publications"}
    rep = _get(app)
    got = _lines(rep)
    assert "rooms_booked" not in got and "posts" not in got and "clips" not in got
    office = next(s for s in rep["sections"] if s["key"] == "office_leadership")
    assert office["missing"] == ["Rooms couldn't be read just now, so it's left out."]
    assert got["meeting_tasks_done"] == 1, "the rest of the report stands"


def test_drifting_is_todays_so_only_for_recent_months(app):
    assert "drifting" in _lines(_get(app, "2026-11"))
    assert "drifting" not in _lines(_get(app, "2026-09"))


def test_care_counts_are_people_and_cares(app, monkeypatch):
    monkeypatch.setattr(cr, "_areas", lambda b, u, r: ["office"])
    rep = _get(app)
    assert "care_opened" not in _lines(rep) and rep["care"] is False


def test_the_month_is_checked(app):
    for bad in ("2026-13", "October", "2026-12", "2025-09"):
        r = app.get(f"/church/monthly-report?business_id={BIZ}&month={bad}")
        assert r.status_code == 400, bad
    assert _get(app, "2026-11")["current"] is True


# ─── Who ──────────────────────────────────────────────────────────────

def test_the_owner_and_an_admin_can_too(app):
    for uid in (OWNER, ADMIN):
        app.who["id"] = uid
        assert _get(app)["month"] == "2026-10"


def test_a_manager_without_the_duty_is_told_whose_job_it_is(app):
    app.who["id"] = NAIYA
    r = app.get(f"/church/monthly-report?business_id={BIZ}")
    assert r.status_code == 403 and "Executive Pastor's job" in r.json()["detail"]
    assert app.put("/church/monthly-report", json={"business_id": BIZ, "notes": {}}).status_code == 403
    assert _send(app).status_code == 403
    app.who["id"] = MEMBER
    assert app.get(f"/church/monthly-report?business_id={BIZ}").status_code == 404


def test_the_duty_moved_to_naiya_moves_the_report(app, rdb):
    rdb.t["church_duty_holders"] = [{"business_id": BIZ, "duty": "monthly_report", "user_id": NAIYA}]
    assert app.get(f"/church/monthly-report?business_id={BIZ}").status_code == 403
    app.who["id"] = NAIYA
    assert _get(app)["month"] == "2026-10"


def test_the_switch(app, rdb, monkeypatch):
    monkeypatch.setenv("CHURCH_MONTHLY_REPORT", "off")
    assert app.get(f"/church/monthly-report?business_id={BIZ}").status_code == 404
    monkeypatch.setenv("CHURCH_MONTHLY_REPORT", "owner")
    monkeypatch.setattr(member_asks, "platform_church", lambda b: False)
    assert app.get(f"/church/monthly-report?business_id={BIZ}").status_code == 404
    monkeypatch.setattr(member_asks, "platform_church", lambda b: str(b) == BIZ)
    assert app.get(f"/church/monthly-report?business_id={BIZ}").status_code == 200
    rdb.t["businesses"][0]["type"] = "salon"
    assert app.get(f"/church/monthly-report?business_id={BIZ}").status_code == 404


# ─── Her notes ────────────────────────────────────────────────────────

def test_her_notes_per_lane_are_saved_and_read_back(app, rdb):
    r = app.put("/church/monthly-report", json={"business_id": BIZ, "month": "2026-10",
                                                 "notes": {"people_care": "  Two families came back.  ",
                                                           "media_comms": "", "office_leadership": None}})
    assert r.status_code == 200, r.text
    assert r.json()["notes"] == {"people_care": "Two families came back."}
    rep = _get(app)
    assert rep["notes"] == {"people_care": "Two families came back."}
    assert next(s for s in rep["sections"] if s["key"] == "people_care")["note"] == "Two families came back."
    assert rep["notes_saved"]["by_name"] == "Jessica McCloud"
    app.put("/church/monthly-report", json={"business_id": BIZ, "month": "2026-10", "notes": {"media_comms": "Clips up."}})
    assert _get(app)["notes"] == {"media_comms": "Clips up."}, "the page sends every lane's note each time"
    assert len(rdb.t[cmr.TABLE]) == 1


def test_bad_notes_are_refused(app):
    put = lambda notes: app.put("/church/monthly-report", json={"business_id": BIZ, "notes": notes})  # noqa: E731
    assert put({"treasurer": "Giving was up"}).status_code == 400, "no money lane"
    assert put({"people_care": "x" * (cmr.NOTE_MAX + 1)}).status_code == 400
    assert put({"people_care": 5}).status_code == 400
    assert put("words").status_code == 400


def test_before_the_migration_the_page_is_a_503(app, rdb):
    rdb.missing.add(cmr.TABLE)
    assert app.get(f"/church/monthly-report?business_id={BIZ}").status_code == 503


# ─── The send ─────────────────────────────────────────────────────────

def test_the_send_goes_to_the_owner_from_the_church_once_a_month(app, rdb):
    app.put("/church/monthly-report", json={"business_id": BIZ, "month": "2026-10",
                                             "notes": {"sunday_serving": "We need two more greeters."}})
    r = _send(app, month="2026-10")
    assert r.status_code == 200, r.text
    assert r.json()["sent"] and r.json()["to"] == "Pastor Kevin"
    m = rdb.sent[0]
    assert m["to"] == "pastor@lovecity.org" and m["subject"] == "The October 2026 report"
    assert m["reply_to"] == "jessica@lovecity.org"
    html = m["html"]
    assert "Hi Pastor Kevin" in html and "gathered by Jessica McCloud" in html
    assert "Nothing about money is in it." in html
    assert "Rooms booked: 3" in html and "Attendance: Sun Oct 4: 120 · Sun Oct 11: 98" in html
    assert "Note: We need two more greeters." in html
    plain = re.sub(r"<[^>]+>", " ", html).lower()
    assert "$" not in plain and "fee" not in plain.replace("feel", "")
    for word in SECRETS:
        assert word.lower() not in plain, word
    again = _send(app, month="2026-10")
    assert again.status_code == 409 and "already went to Pastor Kevin" in again.json()["detail"]
    assert len(rdb.sent) == 1
    row = rdb.t[cmr.TABLE][0]
    assert row["send_state"] == "sent" and row["sends"] == 1 and row["sent_by_name"] == "Jessica McCloud"
    assert _get(app)["last_send"]["by_name"] == "Jessica McCloud"


def test_a_resend_needs_force(app, rdb):
    assert _send(app).status_code == 200
    r = _send(app, force=True)
    assert r.status_code == 200 and len(rdb.sent) == 2
    assert rdb.sent[0]["key"] != rdb.sent[1]["key"], "a resend is its own email"
    assert rdb.t[cmr.TABLE][0]["sends"] == 2


def test_a_failed_email_frees_the_month(app, rdb):
    rdb.fail = True
    assert _send(app).status_code == 503
    row = rdb.t[cmr.TABLE][0]
    assert row["send_id"] is None and row["sends"] == 0 and row["send_state"] is None
    rdb.fail = False
    assert _send(app).status_code == 200 and len(rdb.sent) == 1


def test_a_send_in_flight_is_a_409_and_a_stale_one_can_go_again(app, rdb):
    rdb.t[cmr.TABLE].append({"business_id": BIZ, "month": "2026-10", "notes": {}, "send_id": "a" * 32,
                             "send_state": "sending", "sent_at": "2026-11-02T14:55:00Z", "sends": 1})
    r = _send(app)
    assert r.status_code == 409 and "right now" in r.json()["detail"] and not rdb.sent
    rdb.t[cmr.TABLE][0]["sent_at"] = "2026-11-02T13:00:00Z"
    assert _send(app).status_code == 200 and len(rdb.sent) == 1


def test_no_owner_email_sends_nothing(app, monkeypatch, rdb):
    monkeypatch.setattr(messaging_router, "_owner_email", lambda uid: "")
    assert _send(app).status_code == 409 and not rdb.sent


# ─── My week ──────────────────────────────────────────────────────────

def _biz(rdb):
    return rdb.t["businesses"][0]


def test_my_week_shows_it_due_on_the_first_monday_until_its_sent(app, rdb):
    item = cmr.week_item(_biz(rdb), JESS, "manager", date(2026, 11, 2))
    assert item["kind"] == "report" and item["title"] == "October's monthly report is due today." and not item["late"]
    assert item["door"]["id"] == "monthly-report"
    late = cmr.week_item(_biz(rdb), JESS, "manager", date(2026, 11, 5))
    assert late["late"] and late["title"] == "October's monthly report was due Monday, November 2."
    assert cmr.week_item(_biz(rdb), JESS, "manager", date(2026, 12, 1)) is None, "December's first Monday is the 7th"
    assert _send(app).status_code == 200
    assert cmr.week_item(_biz(rdb), JESS, "manager", date(2026, 11, 5)) is None, "sent: off her week"


def test_my_week_line_is_only_the_managers_who_do_it_and_never_fails_the_week(rdb):
    assert cmr.week_item(_biz(rdb), NAIYA, "manager", date(2026, 11, 2)) is None
    assert cmr.week_item(_biz(rdb), OWNER, "owner", date(2026, 11, 2)) is None, "the owner gets the report, not the reminder"
    assert cmr.week_item(_biz(rdb), ADMIN, "admin", date(2026, 11, 2)) is None
    rdb.missing.add(cmr.TABLE)
    assert cmr.week_item(_biz(rdb), JESS, "manager", date(2026, 11, 2)) is None, "before the migration: left out"


def test_my_week_carries_the_line(monkeypatch):
    """church_my_week.build asks for it and puts it with the week's needs."""
    import church_my_week as mw
    src = open(mw.__file__, encoding="utf-8").read()
    assert "church_monthly_report.week_item(business, user_id, role, today)" in src
    assert '"report": 3' in src
