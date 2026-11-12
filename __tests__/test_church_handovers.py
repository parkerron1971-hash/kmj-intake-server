"""From the office (church_handovers.py; docs/CHURCH_ASSIGNMENTS.md, PR C1).
Kevin, 2026-11-12: "admins can not give work to elders and pastors but they
can give them things that is related to their area that they need for them
to have."

Pins, at the four test churches (church_three), through the real routes:
  * who may send to whom: the owner and an Admin to any leader (the owner's
    own person too, never yourself); a Manager to the leader or overseer of a
    department whose support duty it holds or whose area is one of its own,
    each with why; a Member seat, nobody; Riverside, nobody set up
  * the rule beside it: an Admin can't hand an elder an assignment, and can
    send that elder something for their area
  * what a hand-over says: a title (140), a note (1000), an https link only,
    a day, a department the sender may send for; every write answers with
    what it saved, and a failed one is a 503; never a task
  * seen: Got it from My week (the owner's own person) and the sender's
    Seen / Not yet seen; once, and nobody else's
  * told: one email a person a sweep, from the church, naming who sent each;
    claimed once, let go when the send fails, never again once told
  * the switch closes every route; the migration is a server-only table
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_assignments as cas  # noqa: E402
import church_handovers as cho  # noqa: E402
import church_leader_tasks as clt  # noqa: E402
import church_my_week as mw  # noqa: E402
import church_over as co  # noqa: E402
import church_three as c3  # noqa: E402
import sb_clients  # noqa: E402
from church_three import FOUR, GRACE, LOVE_CITY, NEW_HOPE, RIVERSIDE  # noqa: E402

NOW = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)      # Thursday, 10 AM in Detroit


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "on")
    d = c3.build(monkeypatch)
    d.t["church_handovers"] = []
    real_post = d.post
    tick = iter(range(10_000))

    def post(path, body, prefer=None, **kw):
        if path.startswith("/church_handovers"):               # the table's default: now, a second apart
            body = dict(body, created_at=body.get("created_at") or (NOW + timedelta(seconds=next(tick))).isoformat())
        return real_post(path, body, prefer, **kw)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    d.post = post
    for b in d.t["businesses"]:
        tz = (b.get("settings") or {}).get("timezone")
        if tz:
            b["settings"] = {**b["settings"], "availability": {"timezone": tz}}
    monkeypatch.setattr(cho, "_now", lambda: NOW)
    monkeypatch.setattr(cas, "_now", lambda: NOW)
    monkeypatch.setattr(mw, "_now", lambda: NOW)
    d.sent, d.fail_to = [], set()

    def deliver(biz, to, name, subject, html, key, reply_to=None):
        if to in d.fail_to:
            raise RuntimeError("Resend said no")
        d.sent.append({"to": to, "name": name, "subject": subject, "html": html, "key": key, "biz": biz["id"]})
    monkeypatch.setattr(clt, "deliver", deliver)
    return d


@pytest.fixture
def app(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    a = FastAPI()
    a.include_router(cho.router)
    a.include_router(cas.router)
    a.include_router(mw.router)
    who = {"id": None, "email": None}
    a.dependency_overrides[sb_clients.authed_request] = (
        lambda: SimpleNamespace(user=SimpleNamespace(id=who["id"], email=who["email"], user_metadata={})))
    c = TestClient(a)
    c.who, c.db = who, db
    return c


def uid(db, biz, handle):
    return c3.church(db, biz)["owner_id"] if handle == "owner" else db.who[biz][handle + "@"]


def as_(app, biz, handle):
    u = uid(app.db, biz, handle)
    seat = next((s for s in app.db.t["business_users"] if s["user_id"] == u), None)
    app.who.update(id=u, email=seat["invited_email"] if seat else c3.OWNER_EMAIL[u])


def leaders(app, biz):
    r = app.get(f"/church/handovers/leaders?business_id={biz}")
    assert r.status_code == 200, r.text
    return {app.db.label[x["contact_id"]]: x for x in r.json()["leaders"]}


def send(app, biz, handle, **kw):
    return app.post("/church/handovers", json={"business_id": biz, "contact_id": app.db.who[biz][handle], **kw})


def dept(db, biz, name):
    return next(d["id"] for d in db.t["church_departments"] if d["business_id"] == biz and d["name"] == name)


# ─── Who may send to whom ─────────────────────────────────────────────

def test_love_city_an_admin_may_send_any_leader_pastors_elders_and_the_owners_person_included(app, db):
    as_(app, LOVE_CITY, "minnie")
    got = leaders(app, LOVE_CITY)
    assert {"Andre", "Marcus", "Tanya", "Jessica", "Kevin", "Yolanda", "Ruth", "Tyrone", "Gloria"} <= set(got)
    assert "Minnie" not in got, "never yourself"
    assert got["Andre"]["why"] == "Oversees Youth" and [d["name"] for d in got["Andre"]["departments"]] == ["Youth"]
    assert got["Marcus"]["why"] == "Elders" and got["Kevin"]["why"] == "Lead Pastor"
    as_(app, LOVE_CITY, "owner")
    assert "Kevin" not in leaders(app, LOVE_CITY), "the owner's own person is never their own"


def test_love_city_a_manager_sends_for_the_departments_it_helps(app, db):
    as_(app, LOVE_CITY, "tiara")
    got = leaders(app, LOVE_CITY)
    assert set(got) == {"Andre", "Eve", "Paul", "Ruth", "Tasha", "Yolanda"}
    assert got["Yolanda"]["why"] == "Leads Youth · you help it as Youth and Teen Bible Study"
    assert got["Paul"]["why"] == "Oversees Prayer · you help it as Prayer"
    for h in ("naiya", "laquesha", "shapretta"):
        as_(app, LOVE_CITY, h)
        assert leaders(app, LOVE_CITY) == {}, h


def test_grace_the_secretary_sends_the_youth_minister_and_its_deacon_overseer(app, db):
    as_(app, GRACE, "sharon")
    got = leaders(app, GRACE)
    assert set(got) == {"Daniel", "Yvette"}
    assert got["Daniel"]["why"] == "Oversees Youth · you help it as Youth and Teen Bible Study"
    as_(app, GRACE, "thelma")
    assert {"Daniel", "Doris", "Dwight", "Della", "Samuel", "Yvette"} <= set(leaders(app, GRACE))


def test_new_hope_by_duty_or_by_area_and_each_says_which(app, db):
    as_(app, NEW_HOPE, "kira")                                  # areas: kids & youth
    got = leaders(app, NEW_HOPE)
    assert set(got) == {"Amara", "Kara", "Yusuf"}
    assert got["Amara"]["why"] == ("Oversees Youth · you help it as Youth and Teen Bible Study; "
                                   "Oversees Kids · you help it as Kids")
    as_(app, NEW_HOPE, "sunny")                                 # Sunday & serving: Worship is in its area
    got = leaders(app, NEW_HOPE)
    assert set(got) == {"Abel", "Wren"} and got["Wren"]["why"] == "Leads Worship · it's in your Worship & media area"
    as_(app, NEW_HOPE, "mila")
    assert leaders(app, NEW_HOPE)["Wren"]["why"] == "Leads Worship · you help it as the order of service"
    as_(app, NEW_HOPE, "olive")
    assert leaders(app, NEW_HOPE) == {}


def test_riverside_with_nobody_set_up_has_no_one_to_send_to(app, db):
    as_(app, RIVERSIDE, "owner")
    assert leaders(app, RIVERSIDE) == {}


def test_a_member_seat_sends_nothing(app, db):
    celia = "3a000000-0000-4000-8000-000000000099"
    db.t["business_users"].append({"business_id": NEW_HOPE, "user_id": celia, "role": "member",
                                   "invited_email": "celia@newhope.church", "lane": None, "areas": None,
                                   "contact_id": db.who[NEW_HOPE]["celia"], "name": "Celia Ward", "status": "active"})
    app.who.update(id=celia, email="celia@newhope.church")
    assert app.get(f"/church/handovers/leaders?business_id={NEW_HOPE}").status_code == 403
    assert send(app, NEW_HOPE, "kara", title="x").status_code == 403
    assert app.get(f"/church/handovers?business_id={NEW_HOPE}").status_code == 403


# ─── The rule beside it ───────────────────────────────────────────────

def test_an_admin_cant_hand_an_elder_an_assignment_but_can_send_him_what_he_needs(app, db):
    as_(app, LOVE_CITY, "minnie")
    r = app.post("/church/assignments", json={"business_id": LOVE_CITY, "for": f"person:{db.who[LOVE_CITY]['marcus']}",
                                              "title": "Plan the elders' retreat"})
    assert r.status_code == 403, r.text
    r = send(app, LOVE_CITY, "marcus", title="The retreat center's address", note="Pine Lodge, 14 Lake Rd.")
    assert r.status_code == 200, r.text
    assert not [t for t in db.t["tasks"] if t.get("assigned_contact_id") == db.who[LOVE_CITY]["marcus"]
                and t["title"].startswith("The retreat")], "never a task"
    as_(app, LOVE_CITY, "owner")
    r = app.post("/church/assignments", json={"business_id": LOVE_CITY, "for": f"person:{db.who[LOVE_CITY]['marcus']}",
                                              "title": "Plan the elders' retreat"})
    assert r.status_code == 200, "the owner hands him work"
    as_(app, LOVE_CITY, "jessica")
    r = app.post("/church/assignments", json={"business_id": LOVE_CITY, "for": f"person:{db.who[LOVE_CITY]['marcus']}",
                                              "title": "Call the lodge"})
    assert r.status_code == 200, "he answers to her person on the map"


def test_the_hand_to_list_offers_no_pastor_or_elder_to_anyone_but_the_owner(app, db, monkeypatch):
    """The office writes tasks straight to the database, so the list is
    where the rule holds (the database itself doesn't refuse: the known
    limit)."""
    monkeypatch.setenv("CHURCH_LEADER_TASKS", "on")

    def hand_to(handle):
        as_(app, LOVE_CITY, handle)
        r = app.get(f"/church/my-week/people?business_id={LOVE_CITY}")
        assert r.status_code == 200, r.text
        got = r.json()
        return ({db.label.get(p["user_id"], p["name"]) for p in got["people"]},
                {db.label[x["contact_id"]] for x in got.get("leaders") or []})
    logins, leaders_ = hand_to("minnie")
    assert "Jessica" not in logins and {"Naiya", "owner", "Minnie"} <= logins
    assert not {"Andre", "Marcus", "Tanya"} & leaders_ and {"Yolanda", "Ruth"} <= leaders_
    logins, leaders_ = hand_to("jessica")
    assert "Jessica" in logins, "a task to yourself stays"
    logins, leaders_ = hand_to("owner")
    assert "Jessica" in logins and {"Andre", "Marcus", "Tanya"} <= leaders_
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "off")
    logins, leaders_ = hand_to("minnie")
    assert "Jessica" in logins and "Andre" in leaders_, "closed, the list is as it was"


def test_a_hand_to_list_whose_guard_cant_be_read_is_a_503_never_unfiltered(app, db, monkeypatch):
    monkeypatch.setenv("CHURCH_LEADER_TASKS", "on")
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/church_shepherd_settings") else real(path, **kw))
    as_(app, LOVE_CITY, "minnie")
    assert app.get(f"/church/my-week/people?business_id={LOVE_CITY}").status_code == 503


# ─── What a hand-over says ────────────────────────────────────────────

def test_a_manager_sends_an_associate_pastor_something_for_kids_and_it_says_what_it_saved(app, db):
    as_(app, NEW_HOPE, "kira")
    r = send(app, NEW_HOPE, "amara", title="  The new check-in   tablets  ", note="Two in the closet.\nCharged.",
             link="https://example.org/tablets", for_date="2026-11-15", department_id=dept(db, NEW_HOPE, "Kids"))
    assert r.status_code == 200, r.text
    s = r.json()["saved"]
    assert s["title"] == "The new check-in tablets" and s["note"] == "Two in the closet.\nCharged."
    assert s["to"]["name"] == "Amara Stone" and s["department"] == "Kids" and s["from"] == "Kira Moon"
    assert s["for_date"] == "2026-11-15" and s["for_date_text"] == "Sunday, Nov 15"
    assert s["seen"] is False and s["seen_text"] == "Not yet seen"
    row = db.t["church_handovers"][0]
    assert row["business_id"] == NEW_HOPE and row["sent_by"] == uid(db, NEW_HOPE, "kira")
    assert set(row) >= {"contact_id", "title", "note", "link", "for_date", "department_id"}


@pytest.mark.parametrize("kw,code", [
    ({"title": ""}, 400), ({"title": "x" * 141}, 400), ({"title": "x", "note": "n" * 1001}, 400),
    ({"title": "x", "link": "http://example.org"}, 400), ({"title": "x", "link": "javascript:alert(1)"}, 400),
    ({"title": "x", "link": "https://user:pw@example.org"}, 400), ({"title": "x", "link": "https://exa mple.org"}, 400),
    ({"title": "x", "for_date": "next week"}, 400), ({"title": "x", "department_id": "nope"}, 400),
])
def test_what_it_says_is_checked(app, db, kw, code):
    as_(app, NEW_HOPE, "kira")
    assert send(app, NEW_HOPE, "kara", **kw).status_code == code
    assert db.t["church_handovers"] == []


def test_only_to_a_leader_you_may_send_to_and_only_for_your_departments(app, db):
    as_(app, NEW_HOPE, "kira")
    assert send(app, NEW_HOPE, "celia", title="x").status_code == 403, "Care isn't hers"
    assert send(app, NEW_HOPE, "kara", title="x", department_id=dept(db, NEW_HOPE, "Care")).status_code == 403
    assert send(app, NEW_HOPE, "kara", title="x", department_id=dept(db, GRACE, "Youth")).status_code == 400
    r = app.post("/church/handovers", json={"business_id": NEW_HOPE, "contact_id": db.who[GRACE]["yvette"], "title": "x"})
    assert r.status_code == 403, "another church's person is nobody here"
    assert send(app, NEW_HOPE, "hugo", title="x").status_code == 403, "a member who leads nothing"
    assert db.t["church_handovers"] == []
    as_(app, NEW_HOPE, "tessa")                                  # an Admin: any department of the church's
    assert send(app, NEW_HOPE, "elena", title="x", department_id=dept(db, NEW_HOPE, "Care")).status_code == 200


def test_a_failed_write_is_a_503_never_a_200(app, db, monkeypatch):
    as_(app, NEW_HOPE, "kira")
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda path, body, *a, **kw: None)
    assert send(app, NEW_HOPE, "kara", title="x").status_code == 503


def test_a_failed_read_is_a_503_never_nobody(app, db, monkeypatch):
    as_(app, NEW_HOPE, "kira")
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/church_handovers") else real(path, **kw))
    assert app.get(f"/church/handovers?business_id={NEW_HOPE}").status_code == 503


# ─── Seen ─────────────────────────────────────────────────────────────

def test_the_owners_person_reads_it_on_my_week_and_got_it_says_seen_to_the_sender(app, db):
    as_(app, LOVE_CITY, "minnie")
    r = send(app, LOVE_CITY, "kevin", title="The insurance renewal", note="Due by the 30th.")
    hid = r.json()["saved"]["id"]
    owner = uid(db, LOVE_CITY, "owner")
    week = mw.build(c3.church(db, LOVE_CITY), owner, c3.PLATFORM, "owner")
    assert [(x["title"], x["from"], x["seen"]) for x in week["from_office"]] == [
        ("The insurance renewal", "Minnie Tatum", False)]
    assert week["counts"]["from_office"] == 1
    assert not [n for n in week["needs"] + ([week["next"]] if week["next"] else []) if "insurance" in n["title"]], \
        "never one of the needs"
    as_(app, LOVE_CITY, "jessica")
    assert app.post(f"/church/handovers/{hid}/seen", json={"business_id": LOVE_CITY}).status_code == 404, "not hers"
    as_(app, LOVE_CITY, "owner")
    r = app.post(f"/church/handovers/{hid}/seen", json={"business_id": LOVE_CITY})
    assert r.status_code == 200 and r.json()["saved"]["seen"] is True
    first = db.t["church_handovers"][0]["seen_at"]
    assert app.post(f"/church/handovers/{hid}/seen", json={"business_id": LOVE_CITY}).json()["saved"]["seen_at"] == first
    as_(app, LOVE_CITY, "minnie")
    got = app.get(f"/church/handovers?business_id={LOVE_CITY}").json()
    assert [(x["to"]["name"], x["seen_text"]) for x in got["sent"]] == [("Kevin McCloud", "Seen")]
    assert got["counts"] == {"sent": 1, "seen": 1, "not_seen": 0}


def test_a_leaders_list_is_what_they_havent_seen_then_two_weeks_of_what_they_have(db):
    yolanda = db.who[LOVE_CITY]["yolanda"]
    jess = uid(db, LOVE_CITY, "jessica")
    for n, (title, created, seen) in enumerate((("Old and seen", NOW - timedelta(days=20), NOW - timedelta(days=15)),
                                                ("Seen last week", NOW - timedelta(days=8), NOW - timedelta(days=7)),
                                                ("New", NOW - timedelta(days=1), None),
                                                ("Older, never seen", NOW - timedelta(days=30), None))):
        db.t["church_handovers"].append({"id": f"5d000000-0000-4000-8000-00000000000{n}", "business_id": LOVE_CITY,
                                         "contact_id": yolanda, "sent_by": jess, "title": title, "note": None,
                                         "link": None, "for_date": None, "department_id": None,
                                         "created_at": created.isoformat(), "seen_at": seen.isoformat() if seen else None,
                                         "told_at": None})
    got = cho.for_people(c3.church(db, LOVE_CITY), [yolanda], NOW)
    assert [(x["title"], x["seen"], x["from"]) for x in got] == [
        ("New", False, "Jessica McCloud"), ("Older, never seen", False, "Jessica McCloud"),
        ("Seen last week", True, "Jessica McCloud")]
    assert cho.for_people(c3.church(db, GRACE), [yolanda], NOW) == [], "another church's never"


# ─── Told ─────────────────────────────────────────────────────────────

def test_one_email_a_person_a_sweep_from_the_church_naming_who_sent_each(app, db):
    for h in ("jessica", "minnie"):
        as_(app, LOVE_CITY, h)
        assert send(app, LOVE_CITY, "yolanda", title=f"From {h}", for_date="2026-11-20").status_code == 200
    as_(app, LOVE_CITY, "tiara")
    assert send(app, LOVE_CITY, "ruth", title="The prayer room key", note="Under the mat.",
                link="https://example.org/key").status_code == 200
    stats = cho.sweep_tick(NOW)
    assert stats["emails"] == 2 and stats["told"] == 3
    by = {m["name"]: m for m in db.sent}
    y = by["Yolanda Reed"]
    assert y["subject"] == "Love City Church: Jessica McCloud and Minnie Tatum sent you 2 things"
    assert "From jessica" in y["html"] and "From minnie" in y["html"] and "Friday, Nov 20" in y["html"]
    r = by["Ruth Okafor"]
    assert r["subject"] == "Love City Church: Tiara Adams sent you something"
    assert "Under the mat." in r["html"] and "https://example.org/key" in r["html"] and "Got it" in r["html"]
    assert all(h["told_at"] for h in db.t["church_handovers"])
    assert cho.sweep_tick(NOW + timedelta(hours=1))["emails"] == 0, "never again once told"
    assert not [t for t in db.t["tasks"] if t["title"].startswith("From ")], "never a task"


def test_the_owners_person_is_told_its_on_my_week(app, db):
    as_(app, LOVE_CITY, "minnie")
    send(app, LOVE_CITY, "kevin", title="The insurance renewal")
    cho.sweep_tick(NOW)
    assert len(db.sent) == 1 and "My week" in db.sent[0]["html"]


def test_a_send_that_fails_is_let_go_and_goes_next_hour(app, db):
    as_(app, LOVE_CITY, "tiara")
    send(app, LOVE_CITY, "ruth", title="The prayer room key")
    email = next(c["email"] for c in db.t["contacts"] if c["id"] == db.who[LOVE_CITY]["ruth"])
    db.fail_to.add(email)
    assert cho.sweep_tick(NOW)["unsent"] == 1 and db.t["church_handovers"][0]["told_at"] is None
    db.fail_to.clear()
    assert cho.sweep_tick(NOW + timedelta(hours=1))["emails"] == 1 and db.t["church_handovers"][0]["told_at"]


def test_no_email_on_file_is_told_anyway_and_an_old_untold_one_is_left(app, db):
    as_(app, LOVE_CITY, "tiara")
    send(app, LOVE_CITY, "ruth", title="The prayer room key")
    next(c for c in db.t["contacts"] if c["id"] == db.who[LOVE_CITY]["ruth"])["email"] = ""
    assert cho.sweep_tick(NOW)["no_email"] == 1 and db.t["church_handovers"][0]["told_at"]
    db.t["church_handovers"].append(dict(db.t["church_handovers"][0], id="5d000000-0000-4000-8000-000000000099",
                                         told_at=None, created_at=(NOW - timedelta(days=8)).isoformat()))
    assert cho.sweep_tick(NOW)["told"] == 0


def test_the_sweep_is_quiet_with_the_switch_off(app, db, monkeypatch):
    as_(app, LOVE_CITY, "tiara")
    send(app, LOVE_CITY, "ruth", title="The prayer room key")
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "off")
    assert cho.sweep_tick(NOW)["told"] == 0 and db.sent == []


# ─── The switch, the migration ────────────────────────────────────────

def test_the_switch_closes_every_route(app, db, monkeypatch):
    as_(app, LOVE_CITY, "minnie")
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "off")
    assert app.get(f"/church/handovers/leaders?business_id={LOVE_CITY}").status_code == 404
    assert app.get(f"/church/handovers?business_id={LOVE_CITY}").status_code == 404
    assert send(app, LOVE_CITY, "marcus", title="x").status_code == 404
    week = mw.build(c3.church(db, LOVE_CITY), uid(db, LOVE_CITY, "owner"), c3.PLATFORM, "owner")
    assert week["from_office"] == []
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "owner")
    assert app.get(f"/church/handovers/leaders?business_id={LOVE_CITY}").status_code == 200, "the platform's church"
    as_(app, GRACE, "thelma")
    assert app.get(f"/church/handovers/leaders?business_id={GRACE}").status_code == 404


def test_my_week_stands_when_what_the_office_sent_cant_be_read(db, monkeypatch):
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/church_handovers") else real(path, **kw))
    week = mw.build(c3.church(db, LOVE_CITY), uid(db, LOVE_CITY, "owner"), c3.PLATFORM, "owner")
    assert week["from_office"] is None and week["counts"]["from_office"] == 0


def test_every_church_answers_a_leaders_list(db):
    for biz in FOUR:
        for u, role, _e in c3.logins(db, biz):
            ch = co.Church(c3.church(db, biz))
            if role in cho.SENDERS:
                assert isinstance(cho.leaders(ch, u), list), (c3.NAMES[biz], db.label.get(u))


def test_the_migration_is_a_server_only_table():
    sql = open(os.path.join(ROOT, "supabase", "APPLY-2026-11-12-church-handovers.sql"), encoding="utf-8").read()
    body = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    assert body.strip().startswith("begin;") and body.rstrip().endswith("commit;")
    assert not re.search(r"\bdrop\s+(table|column)\b", body, re.I)
    assert "create table if not exists public.church_handovers" in body
    assert "alter table public.church_handovers enable row level security" in body
    assert "revoke all on public.church_handovers from anon, authenticated" in body
    assert "create policy" not in body.lower()
    assert "create trigger church_handovers_same_business" in body
    import account_lifecycle
    assert "church_handovers" in account_lifecycle.EXPORT_EXCLUDED
