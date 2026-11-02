"""The Executive Pastor's view of her team (church_team_week.py, church_my_week
See as; Kevin, 2026-11-01: "Jessica will be over the admin team").

Pins:
  * See as: whoever is over the lanes (oversee_lanes: the Executive Pastor by
    default) sees another Manager login's week, never an Admin's, the owner's
    or a Member's; the page says whose week it is; a Manager without the duty
    is refused; the owner and admins are unaffected; the switch
  * the team page: each Manager login with its name (never an email) and
    lane, its open and late tasks (the church's day), its open follow-ups and
    care as counts, and what's due this week from its duties; no money and
    no names of the people in follow-up; one login's failed read is a 503
    for its row alone; a Manager without the duty gets whose job it is
  * the Monday roll-up: in the church's own Monday morning, once a ISO week,
    one email and a push to each Manager over the lanes (never the owner or
    an admin), with who's late on what and what's due; quiet when no Manager
    is over the lanes; an email that fails frees the week; the switch

The tables are My week's in-memory PostgREST (test_church_areas' fake)."""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_duties as cd  # noqa: E402
import church_leader_tasks as clt  # noqa: E402
import church_my_week as mw  # noqa: E402
import church_team_week as ctw  # noqa: E402
import member_asks  # noqa: E402
import sb_clients  # noqa: E402
from test_church_areas import db  # noqa: E402,F401
from test_church_follow_up import BIZ, MARCUS, OWNER, ROBERT, TASHA  # noqa: E402
from test_church_my_week import MARCUS_SEAT, week  # noqa: E402,F401

JESS = "a5000000-0000-4000-8000-000000000005"       # the Executive Pastor (a Manager, by her record)
NAIYA = "a2000000-0000-4000-8000-000000000002"      # Office & Leadership (a Manager, stored lane)
ADMIN = "a1000000-0000-4000-8000-000000000001"      # the treasurer (an Admin login)
MEMBER = "a7000000-0000-4000-8000-000000000007"     # a Member login
C_JESS = "c5000000-0000-4000-8000-000000000005"
C_NAIYA = "c2000000-0000-4000-8000-000000000002"
MONDAY = datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc)     # Monday, 8:00 AM in Chicago
EVERY_AREA = [a for a in ("worship_media", "people_care", "kids_youth", "groups_classes", "messages_safety",
                          "website_outreach", "office")]
MONEY = re.compile(r"amount|cents|fee|giving|gift|fund|deposit|bank|money|price|pledge|donat|payout|\bpay\b|total")


def _jsonpath(row, col):
    base, *path = re.split(r"->>?", col)
    v = row.get(base)
    for k in path:
        v = v.get(k) if isinstance(v, dict) else None
    return v


@pytest.fixture
def team(week, monkeypatch):
    t = week.t
    from test_church_roles import _cmp
    real_match = type(week)._match

    def match(self, row, filters):        # settings->church_team_rollup->>id, as PostgREST reads it
        plain = []
        for f in filters:
            if f[0] != "or" and "->" in f[0]:
                if not _cmp({"v": _jsonpath(row, f[0])}, "v", f[1], f[2]):
                    return False
            else:
                plain.append(f)
        return real_match(self, row, plain)
    monkeypatch.setattr(type(week), "_match", match)
    t["businesses"][0]["settings"] = {"practitioner_name": "Pastor Kevin",
                                      "availability": {"timezone": "America/Chicago"}}
    t["business_users"] += [
        # The leadership plan: "Manager login with every area picked".
        {"business_id": BIZ, "user_id": JESS, "invited_email": "jessica@lovecity.org", "role": "manager",
         "status": "active", "areas": EVERY_AREA, "lane": None, "contact_id": None, "name": None},
        {"business_id": BIZ, "user_id": NAIYA, "invited_email": "naiya@lovecity.org", "role": "manager",
         "status": "active", "areas": None, "lane": "office_leadership", "contact_id": C_NAIYA, "name": None},
        {"business_id": BIZ, "user_id": ADMIN, "invited_email": "minnie@lovecity.org", "role": "admin",
         "status": "active", "areas": None, "lane": "treasurer", "contact_id": None, "name": "Minnie Tatum"},
        {"business_id": BIZ, "user_id": MEMBER, "invited_email": "helper@lovecity.org", "role": "member",
         "status": "active", "areas": None, "lane": None, "contact_id": None, "name": None},
    ]
    t["contacts"] += [{"id": C_JESS, "business_id": BIZ, "name": "Jessica McCloud", "email": "Jessica@LoveCity.org"},
                      {"id": C_NAIYA, "business_id": BIZ, "name": "Naiya Clark", "email": "naiya@lovecity.org"}]
    if not any(d.get("key") == "executive_pastor" for d in t["church_role_defs"]):
        t["church_role_defs"].append({"id": "def-xp", "business_id": BIZ, "key": "executive_pastor",
                                      "catalog_key": "executive_pastor", "title": "Executive Pastor",
                                      "job": "pastoral", "status": "active"})
    t["church_leader_roles"].append({"id": "r-xp", "business_id": BIZ, "contact_id": C_JESS, "role": "executive_pastor",
                                     "scope": "", "status": "active"})
    day = lambda n: (MONDAY + timedelta(days=n)).date().isoformat()  # noqa: E731
    t["tasks"] = [
        {"id": "t1", "business_id": BIZ, "title": "Book the fellowship hall", "status": "todo", "due_date": day(-3),
         "assigned_to": NAIYA},
        {"id": "t2", "business_id": BIZ, "title": "Order the paper", "status": "todo", "due_date": day(2),
         "assigned_to": NAIYA},
        {"id": "t3", "business_id": BIZ, "title": "Done already", "status": "done", "due_date": day(-5),
         "assigned_to": NAIYA},
        {"id": "t4", "business_id": BIZ, "title": "Print the youth flyers", "status": "todo", "due_date": day(-1),
         "assigned_to": MARCUS_SEAT},
        {"id": "t5", "business_id": BIZ, "title": "Jessica's own", "status": "todo", "due_date": day(-1),
         "assigned_to": JESS},
    ]
    t["church_follow_ups"] += [
        {"id": "f-naiya", "business_id": BIZ, "contact_id": TASHA, "leader_contact_id": C_NAIYA, "status": "open",
         "due_at": (MONDAY - timedelta(days=1)).isoformat(), "created_at": (MONDAY - timedelta(days=4)).isoformat(),
         "card_key": "connect", "card_name": "Connect card"},
        {"id": "f-marcus", "business_id": BIZ, "contact_id": ROBERT, "leader_contact_id": MARCUS, "status": "open",
         "due_at": (MONDAY + timedelta(days=2)).isoformat(), "created_at": (MONDAY - timedelta(days=1)).isoformat(),
         "card_key": "connect", "card_name": "Connect card"},
    ]
    t["ministry_care_requests"] += [
        {"id": "c-naiya", "business_id": BIZ, "assigned_to": NAIYA, "status": "reviewed",
         "submission": {"text": "Pray for my brother's surgery"}},
        {"id": "c-closed", "business_id": BIZ, "assigned_to": NAIYA, "status": "closed", "submission": {}}]
    monkeypatch.setattr(ctw, "_now", lambda: MONDAY)
    monkeypatch.setattr(mw, "_now", lambda: MONDAY)
    import church_areas
    church_areas._MY_CACHE.clear()
    monkeypatch.setenv("CHURCH_TEAM_ROLLUP", "on")
    # Who sees what is on (as it is live): Marcus, whom no lane names, works
    # the areas Chief's guess gives him (Kids & youth), so he isn't over the
    # lanes. With it off, church_duties gives an unplaced Manager every
    # non-money duty, this one too.
    monkeypatch.setenv("CHURCH_AREAS", "on")
    week.sent, week.pushes, week.fail_to = [], [], set()

    def deliver(biz, to, name, subject, html, key, reply_to=None):
        if to in week.fail_to:
            raise RuntimeError("Resend said no")
        week.sent.append({"to": to, "name": name, "subject": subject, "html": html, "key": key})
    monkeypatch.setattr(clt, "deliver", deliver)
    import push_notifications
    monkeypatch.setattr(push_notifications, "send_to_user", lambda uid, **kw: week.pushes.append({"to": uid, **kw}) or 1)
    return week


@pytest.fixture
def app(team, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import business_access
    who = {"id": JESS, "email": "jessica@lovecity.org"}
    roles = {OWNER: "owner", JESS: "manager", NAIYA: "manager", MARCUS_SEAT: "manager", ADMIN: "admin",
             MEMBER: "member"}
    monkeypatch.setattr(business_access, "_resolve_role", lambda b, u: roles.get(str(u)))
    monkeypatch.setenv("CHURCH_AREAS", "on")
    a = FastAPI()
    a.include_router(mw.router)
    a.include_router(ctw.router)
    a.dependency_overrides[sb_clients.authed_request] = (
        lambda: SimpleNamespace(user=SimpleNamespace(id=who["id"], email=who["email"], user_metadata={})))
    c = TestClient(a)
    c.who = who
    return c


def _as(app, uid):
    app.who.update(id=uid, email={OWNER: "kmjcreativesolution@gmail.com", NAIYA: "naiya@lovecity.org",
                                  ADMIN: "minnie@lovecity.org", MARCUS_SEAT: "marcus@example.com"}.get(uid, "jessica@lovecity.org"))


def _see(app, target):
    return app.get(f"/church/my-week?business_id={BIZ}&as_user={target}")


def _keys(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from _keys(v)
    elif isinstance(x, list):
        for v in x:
            yield from _keys(v)


# ─── See as ───────────────────────────────────────────────────────────

def test_the_executive_pastor_sees_another_managers_week_and_the_page_says_whose(app):
    r = _see(app, MARCUS_SEAT)
    assert r.status_code == 200, r.text
    w = r.json()
    assert w["me"]["role"] == "manager" and [a["key"] for a in w["areas"]] == ["kids_youth"], "Marcus's week"
    assert w["seeing_as"] == {"user_id": MARCUS_SEAT, "name": "Marcus Taylor", "role": "manager", "lane": None}
    naiya = _see(app, NAIYA).json()
    assert naiya["seeing_as"]["name"] == "Naiya Clark" and naiya["seeing_as"]["lane"] == "Office & Leadership"
    assert "@" not in str(naiya["seeing_as"])


def test_an_admins_week_the_owners_and_a_members_stay_theirs(app):
    for target in (ADMIN, OWNER, MEMBER):
        r = _see(app, target)
        assert r.status_code == 403, (target, r.status_code)
        assert "Manager logins' weeks" in r.json()["detail"]


def test_a_manager_without_the_duty_is_refused(app):
    _as(app, NAIYA)
    r = _see(app, MARCUS_SEAT)
    assert r.status_code == 403 and "Only the owner, an admin or whoever is over the lanes" in r.json()["detail"]
    assert app.get(f"/church/my-week?business_id={BIZ}").status_code == 200, "her own week is fine"


def test_a_duty_moved_away_takes_see_as_with_it(app, team):
    team.t["church_duty_holders"] = [{"business_id": BIZ, "duty": "oversee_lanes", "user_id": NAIYA}]
    assert _see(app, MARCUS_SEAT).status_code == 403, "moved to Naiya: Jessica no longer oversees"
    _as(app, NAIYA)
    assert _see(app, MARCUS_SEAT).status_code == 200


def test_the_owner_and_an_admin_are_unaffected_and_see_anyone(app, monkeypatch):
    monkeypatch.setenv("CHURCH_TEAM_ROLLUP", "off")
    _as(app, OWNER)
    assert _see(app, ADMIN).status_code == 200 and _see(app, JESS).status_code == 200
    _as(app, ADMIN)
    w = _see(app, NAIYA).json()
    assert w["seeing_as"]["name"] == "Naiya Clark"


def test_the_switch_closes_the_overseers_see_as(app, monkeypatch):
    monkeypatch.setenv("CHURCH_TEAM_ROLLUP", "off")
    assert _see(app, MARCUS_SEAT).status_code == 403
    monkeypatch.setenv("CHURCH_TEAM_ROLLUP", "owner")
    monkeypatch.setattr(member_asks, "platform_church", lambda b: False)
    assert _see(app, MARCUS_SEAT).status_code == 403
    monkeypatch.setattr(member_asks, "platform_church", lambda b: str(b) == BIZ)
    assert _see(app, MARCUS_SEAT).status_code == 200, "owner: the platform owner's own church"


def _jess_works(team, areas):
    import church_areas
    next(s for s in team.t["business_users"] if s["user_id"] == JESS)["areas"] = areas
    church_areas._MY_CACHE.clear()
    cd._CACHE.clear()


def test_see_as_stays_inside_her_own_areas(app, team):
    """A duty never widens what a login sees: over the lanes but working only
    the Office, she sees Marcus's own tasks, never his People & care or Kids
    & youth."""
    _jess_works(team, ["office"])
    w = _see(app, MARCUS_SEAT).json()
    assert w["areas"] == [] and w["handed"] == []
    items = [w["next"]] + w["needs"]
    assert [i["kind"] for i in items] == ["task"] and items[0]["title"] == "Print the youth flyers"
    assert "Robert" not in str(w) and "background check" not in str(w)
    assert w["seeing_as"]["name"] == "Marcus Taylor"
    _jess_works(team, EVERY_AREA)
    w = _see(app, MARCUS_SEAT).json()
    assert [a["key"] for a in w["areas"]] == ["kids_youth"] and "Robert Hayes was handed to you." in str(w)


def test_how_their_week_goes_stays_inside_her_own_areas_too(app, team):
    """The rhythm (church_my_week.rhythm) follows within's rule: over the
    lanes but working only the Office, she sees Naiya's office jobs, never
    the member chat's rules (Messages & safety) or Marcus's Kids check-in."""
    _jess_works(team, ["office"])
    naiya = _see(app, NAIYA).json()["rhythm"]
    jobs = {i["key"] for d in naiya["days"] for i in d["items"]}
    assert "weekly_text" in jobs and "leaders_note" in jobs and "chat_rules" not in jobs
    assert naiya["count"] == len(jobs) and naiya["every_job"] is False
    marcus = _see(app, MARCUS_SEAT).json()["rhythm"]
    assert marcus["days"] == [] and marcus["count"] == 0
    _jess_works(team, EVERY_AREA)
    marcus = _see(app, MARCUS_SEAT).json()["rhythm"]
    assert [i["key"] for d in marcus["days"] for i in d["items"]] == ["kids"]


def test_a_failed_duty_read_is_a_503_never_a_yes(app, team, monkeypatch):
    real = team.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.lstrip("/").startswith("church_duty_holders") else real(path, **kw))
    assert _see(app, MARCUS_SEAT).status_code == 503


# ─── The team page ────────────────────────────────────────────────────

def _team(app):
    r = app.get(f"/church/my-week/team?business_id={BIZ}")
    assert r.status_code == 200, r.text
    return r.json()


def test_the_team_page_says_each_managers_week_in_counts(app):
    page = _team(app)
    rows = {r["user_id"]: r for r in page["team"]}
    assert set(rows) == {NAIYA, MARCUS_SEAT}, "Manager logins only, and never her own row"
    n = rows[NAIYA]
    assert n["name"] == "Naiya Clark" and n["lane"] == "Office & Leadership" and n["ok"] and n["status"] == 200
    assert n["tasks"]["open"] == 2 and n["tasks"]["late"] == 1
    assert n["tasks"]["items"][0] == {"title": "Book the fellowship hall", "due": "2026-10-30",
                                      "due_text": "3 days late", "late": True}
    assert n["follow_ups"] == {"open": 1, "late": 1} and n["care"] == {"open": 1}
    assert n["this_week_text"] == ("Mon: The Monday leaders note · Tue: Meetings and minutes · Wed: The weekly text"
                                   " · Fri: Rooms")
    m = rows[MARCUS_SEAT]
    assert m["name"] == "Marcus Taylor" and m["tasks"]["late"] == 1 and m["follow_ups"] == {"open": 1, "late": 0}
    assert page["week"] == {"monday": "2026-11-02", "words": "the week of November 2"}
    assert page["counts"] == {"logins": 2, "late_tasks": 2, "unread": 0}


def test_the_team_page_has_no_money_no_emails_and_no_names_from_follow_up_or_care(app, team):
    page = _team(app)
    assert not [k for k in _keys(page) if MONEY.search(k.lower())], "no money key anywhere"
    said = str(page)
    assert "@" not in said, "never an email"
    assert "Tasha" not in said and "Robert" not in said, "counts only: no one in follow-up by name"
    assert "surgery" not in said, "nothing of what a care request asked"
    duties = {w["duty"] for r in page["team"] for w in r.get("this_week", [])}
    assert not duties & {k for k, d in cd.CATALOG.items() if d["money"]}


def test_whats_due_this_week_follows_the_catalogs_days():
    from datetime import date
    first = ctw.due_this_week(["monthly_report", "stream", "website", "care_board"], date(2026, 11, 2))
    assert [w["text"] for w in first] == ["Mon, Tue: The care board", "Mon: The monthly report", "Sat, Sun: The livestream"]
    later = ctw.due_this_week(["monthly_report", "deposit"], date(2026, 11, 9))
    assert later == [], "the first Monday only, and never money"


def test_the_owner_and_an_admin_see_every_manager_including_her(app):
    _as(app, OWNER)
    rows = {r["user_id"]: r for r in _team(app)["team"]}
    assert set(rows) == {JESS, NAIYA, MARCUS_SEAT} and ADMIN not in rows
    assert rows[JESS]["name"] == "Jessica McCloud" and rows[JESS]["lane"] == "Executive Pastor"
    _as(app, ADMIN)
    assert set(r["user_id"] for r in _team(app)["team"]) == {JESS, NAIYA, MARCUS_SEAT}


def test_a_manager_without_the_duty_is_told_whose_job_it_is(app):
    _as(app, NAIYA)
    r = app.get(f"/church/my-week/team?business_id={BIZ}")
    assert r.status_code == 403 and "Executive Pastor's job" in r.json()["detail"]
    app.who.update(id=MEMBER, email="helper@lovecity.org")
    assert app.get(f"/church/my-week/team?business_id={BIZ}").status_code == 404, "below a manager seat"


def test_one_logins_failed_read_is_a_503_for_its_row_alone(app, team, monkeypatch):
    real = team.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/tasks") and NAIYA in path else real(path, **kw))
    rows = {r["user_id"]: r for r in _team(app)["team"]}
    assert rows[NAIYA]["ok"] is False and rows[NAIYA]["status"] == 503 and "tasks" not in rows[NAIYA]
    assert "couldn't be read" in rows[NAIYA]["error"] and rows[NAIYA]["name"] == "Naiya Clark"
    assert rows[MARCUS_SEAT]["ok"] and rows[MARCUS_SEAT]["tasks"]["late"] == 1


def test_the_page_is_a_503_when_the_seats_cant_be_read(app, team, monkeypatch):
    real = team.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/business_users") and "status=eq.active&select=user_id,role,lane"
                        in path else real(path, **kw))
    assert app.get(f"/church/my-week/team?business_id={BIZ}").status_code == 503


def test_the_team_page_switch_and_churches(app, team, monkeypatch):
    monkeypatch.setenv("CHURCH_TEAM_ROLLUP", "off")
    assert app.get(f"/church/my-week/team?business_id={BIZ}").status_code == 404
    monkeypatch.setenv("CHURCH_TEAM_ROLLUP", "on")
    team.t["businesses"][0]["type"] = "salon"
    assert app.get(f"/church/my-week/team?business_id={BIZ}").status_code == 404


# ─── The Monday roll-up ───────────────────────────────────────────────

def test_on_the_churchs_monday_morning_she_gets_one_email_and_a_push(team):
    stats = ctw.rollup_tick(MONDAY)
    assert stats["sent"] == 1
    assert [m["to"] for m in team.sent] == ["jessica@lovecity.org"], "the Manager over the lanes, never the owner or an admin"
    m = team.sent[0]
    assert m["subject"] == "Your team this week: 2 tasks late" and m["name"] == "Jessica McCloud"
    html = m["html"]
    assert "Hi Jessica" in html and "Naiya Clark, Office &amp; Leadership" in html
    assert "Late: “Book the fellowship hall” (due Friday, October 30)." in html
    assert "This week: Mon: The Monday leaders note" in html and "Print the youth flyers" in html
    assert "Jessica's own" not in html, "her own week is My week"
    assert "$" not in html and "deposit" not in html.lower() and "Treasurer" not in html, "no money"
    assert "surgery" not in html and "Tasha" not in html and "@" not in re.sub(r"<[^>]+>", " ", html).split("You’re")[0]
    assert [p["to"] for p in team.pushes] == [JESS] and team.pushes[0]["nav"] == "operate:my-week"
    assert team.pushes[0]["body"] == "2 tasks late on the team." and team.pushes[0]["business_id"] == BIZ
    rec = team.t["businesses"][0]["settings"][ctw.KEY]
    assert rec["week"] == "2026-W45" and rec["state"] == "sent" and rec["to"] == [JESS]
    assert team.t["businesses"][0]["settings"]["practitioner_name"] == "Pastor Kevin", "no other setting touched"


def test_once_a_week(team):
    ctw.rollup_tick(MONDAY)
    again = ctw.rollup_tick(MONDAY + timedelta(hours=1))
    assert again["sent"] == 0 and again["already"] == 1 and len(team.sent) == 1
    next_week = ctw.rollup_tick(MONDAY + timedelta(days=7))
    assert next_week["sent"] == 1 and len(team.sent) == 2
    assert team.t["businesses"][0]["settings"][ctw.KEY]["week"] == "2026-W46"


@pytest.mark.parametrize("at", [
    datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc),     # Monday 7:00 AM in Chicago: too early
    datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc),     # Monday noon in Chicago: the morning is over
    datetime(2026, 11, 3, 14, 0, tzinfo=timezone.utc),     # Tuesday morning
    datetime(2026, 11, 2, 5, 0, tzinfo=timezone.utc),      # Monday in UTC, still Sunday night in Chicago
])
def test_only_in_the_churchs_own_monday_morning(team, at):
    assert ctw.rollup_tick(at)["sent"] == 0 and not team.sent


def test_the_churchs_own_clock_decides(team):
    team.t["businesses"][0]["settings"]["availability"] = {"timezone": "America/Los_Angeles"}
    assert ctw.rollup_tick(MONDAY)["sent"] == 0, "6:00 AM in Los Angeles"
    assert ctw.rollup_tick(MONDAY + timedelta(hours=2))["sent"] == 1, "8:00 AM there"


def test_quiet_when_no_manager_is_over_the_lanes(team):
    # No Executive Pastor: Jessica is a Manager working People & care only.
    team.t["church_leader_roles"] = [r for r in team.t["church_leader_roles"] if r.get("role") != "executive_pastor"]
    next(s for s in team.t["business_users"] if s["user_id"] == JESS)["areas"] = ["people_care"]
    stats = ctw.rollup_tick(MONDAY)
    assert stats["sent"] == 0 and stats["no_one"] == 1 and not team.sent and not team.pushes
    assert ctw.KEY not in team.t["businesses"][0]["settings"], "no claim: a holder named later this morning still hears"


def test_a_duty_moved_to_an_admin_alone_sends_nothing(team):
    team.t["church_duty_holders"] = [{"business_id": BIZ, "duty": "oversee_lanes", "user_id": ADMIN}]
    assert ctw.rollup_tick(MONDAY)["no_one"] == 1 and not team.sent, "admins and the owner never get it"


def test_an_email_that_fails_frees_the_week_for_the_next_hour(team):
    team.fail_to = {"jessica@lovecity.org"}
    assert ctw.rollup_tick(MONDAY)["unsent"] == 1 and not team.pushes
    assert ctw.KEY not in team.t["businesses"][0]["settings"]
    team.fail_to = set()
    assert ctw.rollup_tick(MONDAY + timedelta(hours=1))["sent"] == 1


def test_the_roll_up_switch(team, monkeypatch):
    monkeypatch.setenv("CHURCH_TEAM_ROLLUP", "off")
    assert ctw.rollup_tick(MONDAY)["churches"] == 0 and not team.sent
    monkeypatch.setenv("CHURCH_TEAM_ROLLUP", "owner")
    monkeypatch.setattr(member_asks, "platform_church", lambda b: False)
    assert ctw.rollup_tick(MONDAY)["sent"] == 0 and not team.sent
    monkeypatch.setattr(member_asks, "platform_church", lambda b: str(b) == BIZ)
    assert ctw.rollup_tick(MONDAY)["sent"] == 1


def test_follow_up_and_care_counts_are_people_and_cares(app, team):
    _jess_works(team, ["office"])
    page = _team(app)
    assert page["care"] is False
    assert all("follow_ups" not in r and "care" not in r for r in page["team"])
    assert next(r for r in page["team"] if r["user_id"] == NAIYA)["tasks"]["late"] == 1, "her team's tasks stand"
    ctw.rollup_tick(MONDAY)
    html = team.sent[0]["html"]
    assert "follow-up" not in html and "care request" not in html and "Book the fellowship hall" in html


def test_a_week_that_reached_some_tries_the_rest_and_no_one_twice(team):
    team.t["church_duty_holders"] = [{"business_id": BIZ, "duty": "oversee_lanes", "user_id": u} for u in (JESS, NAIYA)]
    team.fail_to = {"naiya@lovecity.org"}
    first = ctw.rollup_tick(MONDAY)
    assert first["sent"] == 1 and first["unsent"] == 1
    rec = team.t["businesses"][0]["settings"][ctw.KEY]
    assert rec["state"] == "partial" and rec["to"] == [JESS]
    team.fail_to = set()
    again = ctw.rollup_tick(MONDAY + timedelta(hours=1))
    assert again["sent"] == 1 and [m["to"] for m in team.sent] == ["jessica@lovecity.org", "naiya@lovecity.org"]
    rec = team.t["businesses"][0]["settings"][ctw.KEY]
    assert rec["state"] == "sent" and sorted(rec["to"]) == sorted([JESS, NAIYA])
    assert ctw.rollup_tick(MONDAY + timedelta(hours=2))["already"] == 1 and len(team.sent) == 2


def test_a_record_that_doesnt_save_is_counted(team, monkeypatch):
    real = ctw.swap
    calls = []

    def swap(b, expect, rec):
        calls.append(rec)
        return real(b, expect, rec) if len(calls) == 1 else False
    monkeypatch.setattr(ctw, "swap", swap)
    stats = ctw.rollup_tick(MONDAY)
    assert stats["sent"] == 1 and stats["unrecorded"] == 1


def test_a_claim_another_replica_took_sends_nothing(team, monkeypatch):
    monkeypatch.setattr(ctw, "swap", lambda *a, **k: False)
    assert ctw.rollup_tick(MONDAY)["sent"] == 0 and not team.sent


def test_manager_holders_names_only_managers_that_do_the_duty(team):
    assert cd.manager_holders(BIZ, "oversee_lanes") == [JESS]
    assert set(cd.manager_holders(BIZ, "weekly_text")) == {JESS, NAIYA}
    team.t["businesses"][0]["type"] = "salon"
    cd._forget(BIZ)
    assert cd.manager_holders(BIZ, "oversee_lanes") == []
