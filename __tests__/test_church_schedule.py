"""The leaders schedule: asking to be away, the yes, and who reads what
(church_schedule.py; docs/CHURCH_SCHEDULE.md section 5 step 1, PR S1-3).
Kevin, 2026-11-18: "this is for when leaders are planning time off and have
certain obiligations so that we as a church can plan around meeting", and on
the five calls: "Yes build to all five" (the person over a leader on the
leaders map says yes; two weeks' notice for planned time off; sickness and
emergencies are never blocked).

Pins, at the four test churches (church_three), through the real routes, with
church_away_settle modelled on the migration's function (church_schedule_fake;
the PGlite check runs the real one):
  * every step-1 row of the decision table: planned, short notice, can't make
    it, an office login's person, a leader who is also an office login, the
    add list, the owner's own person, someone not on the schedule
  * answers and withdrawals: who may, what is written, and that two answers
    at once (or an answer after a withdraw) are a 409
  * the refusals: the days, the same days already waiting, too many waiting,
    who covers, a long reason
  * PRIVACY: the reason (and the note that came with the answer) reaches the
    one who asked, whoever it went to, the owner and whoever oversees the
    office, and nobody else on any route: not an Admin, not another leader,
    not the holder of the serve_schedule duty, who gets a 403 on the calendar
    unless on the schedule themselves. serve_away.note stays ''. A member-app
    session never carries the owner's standing
  * a failed read or write is a 503 with nothing saved, and asking again
    never makes a second copy
  * the calendar reads the facts, never an ask's state; nothing crosses
    churches; lists past 1,000 rows are read whole
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_duties as cd  # noqa: E402
import church_over as co  # noqa: E402
import church_schedule as cs  # noqa: E402
import church_schedule_fake as fake  # noqa: E402
import church_three as c3  # noqa: E402
import sb_clients  # noqa: E402
from church_schedule_fake import as_, day  # noqa: E402
from church_three import GRACE, LOVE_CITY, NEW_HOPE, RIVERSIDE  # noqa: E402

SECRET = "Surgery for my mother that week"
NOTE = "Praying for her and for you"
SEATED = ("yolanda", "andre", "ruth", "tyrone")      # leaders signed in on a Member seat


@pytest.fixture
def db(monkeypatch):
    d = fake.build(monkeypatch)
    for h in SEATED:
        fake.seat(d, LOVE_CITY, h)
    return d


@pytest.fixture
def app(db):
    return fake.client(db)


def ask(app, biz=LOVE_CITY, **kw):
    kw = {"starts_on": day(30), "ends_on": day(37), "kind": "time_off", **kw}
    return app.post("/church/schedule/asks", json={"business_id": biz, **kw})


def saved(r):
    assert r.status_code == 200, r.text
    return r.json()["saved"]


def planned(app, who="yolanda", **kw):
    """A planned ask with a private reason, six weeks out."""
    as_(app, LOVE_CITY, who)
    return saved(ask(app, reason=SECRET, **kw))


def answer(app, ask_id, yes, biz=LOVE_CITY, **kw):
    return app.post(f"/church/schedule/asks/{ask_id}/answer", json={"business_id": biz, "yes": yes, **kw})


def withdraw(app, ask_id, biz=LOVE_CITY):
    return app.post(f"/church/schedule/asks/{ask_id}/withdraw", json={"business_id": biz})


def box(app, which, biz=LOVE_CITY):
    r = app.get(f"/church/schedule/asks?business_id={biz}&box={which}")
    assert r.status_code == 200, r.text
    return r.json()["asks"]


def cal(app, biz=LOVE_CITY, lo=0, hi=60):
    return app.get(f"/church/schedule/leaders?business_id={biz}&from={day(lo)}&to={day(hi)}")


def groups(app, **kw):
    r = cal(app, **kw)
    assert r.status_code == 200, r.text
    return {g["key"]: g for g in r.json()["groups"]}


def row(db, ask_id):
    return next(r for r in db.t["church_away_asks"] if r["id"] == ask_id)


def facts(db, biz=LOVE_CITY):
    return [s for s in db.t["serve_away"] if s["business_id"] == biz]


# ─── The decision table ───────────────────────────────────────────────

def test_a_planned_ask_goes_to_the_person_over_them_and_waits(app, db):
    w = db.who[LOVE_CITY]
    got = planned(app, cover_contact_id=w["tyrone"])
    assert set(got) == {"id", "contact_id", "name", "group", "department", "kind", "starts_on", "ends_on", "state",
                        "flags", "to", "cover", "decided", "reason", "reason_hidden", "mine", "can_answer",
                        "can_withdraw", "created_at"}
    assert (got["name"], got["group"], got["kind"], got["state"]) == ("Yolanda Reed", "leaders", "time_off", "asked")
    assert (got["starts_on"], got["ends_on"], got["flags"]) == (day(30), day(37), [])
    assert got["to"] == {"kind": "person", "id": w["andre"], "name": "Andre Wallace"}
    assert got["department"]["name"] == "Youth" and got["cover"] == {"contact_id": w["tyrone"], "name": "Tyrone Banks"}
    assert got["decided"] is None and got["reason"] == SECRET and got["reason_hidden"] is False
    assert (got["mine"], got["can_answer"], got["can_withdraw"]) == (True, False, True)
    saved_row = row(db, got["id"])
    assert saved_row["made_by"] == db.who[LOVE_CITY]["yolanda@"] and saved_row["to_user_id"] is None
    assert facts(db) == [], "nothing is an away date until someone says yes"
    assert not db.rpcs and not db.refused


def test_short_notice_is_flagged_never_blocked_and_goes_to_the_same_person(app, db):
    as_(app, LOVE_CITY, "yolanda")
    got = saved(ask(app, starts_on=day(13), ends_on=day(15)))
    assert got["flags"] == ["short_notice"] and got["state"] == "asked"
    assert got["to"]["name"] == "Andre Wallace"
    assert saved(ask(app, starts_on=day(14), ends_on=day(15)))["flags"] == [], "fourteen days out is in time"
    as_(app, LOVE_CITY, "owner")
    app.put("/church/schedule/settings", json={"business_id": LOVE_CITY, "notice_days": 3})
    as_(app, LOVE_CITY, "yolanda")
    assert saved(ask(app, starts_on=day(5), ends_on=day(6)))["flags"] == [], "the church's own notice days"
    assert saved(ask(app, starts_on=day(2), ends_on=day(2), kind="commitment"))["flags"] == ["short_notice"]


def test_cant_make_it_is_a_yes_at_once_with_nobody_deciding(app, db):
    as_(app, LOVE_CITY, "yolanda")
    got = saved(ask(app, starts_on=day(0), ends_on=day(0), kind="cant", reason=SECRET))
    assert got["state"] == "yes" and got["decided"]["by"] is None and got["decided"]["at"]
    assert got["flags"] == ["short_notice"] and got["to"]["name"] == "Andre Wallace", "told, never asked"
    assert got["can_answer"] is False and got["can_withdraw"] is True
    r = row(db, got["id"])
    assert r["decided_by_user_id"] is None and r["decided_by_contact_id"] is None
    assert db.rpcs == [{"p_business_id": LOVE_CITY, "p_ask_id": got["id"], "p_state": "yes", "p_by_user": None,
                        "p_by_contact": None, "p_note": None}]
    [f] = facts(db)
    assert (f["ask_id"], f["kind"], f["note"], f["contact_id"]) == (got["id"], "cant", "", db.who[LOVE_CITY]["yolanda"])
    assert (f["starts_on"], f["ends_on"]) == (day(0), day(0))
    as_(app, LOVE_CITY, "andre")
    assert box(app, "to_me") == [], "nothing waits for his yes"


def test_an_office_logins_person_goes_by_the_office_rule(app, db):
    owner = c3.church(db, LOVE_CITY)["owner_id"]
    as_(app, LOVE_CITY, "naiya")
    got = saved(ask(app))
    assert got["group"] == "office" and got["to"] == {"kind": "login", "id": db.who[LOVE_CITY]["jessica@"],
                                                      "name": "Jessica McCloud"}
    assert row(db, got["id"])["to_contact_id"] is None and got["department"] is None
    as_(app, LOVE_CITY, "minnie")
    got = saved(ask(app))
    assert got["group"] == "office" and got["to"] == {"kind": "login", "id": owner, "name": "Pastor Kevin"}
    as_(app, LOVE_CITY, "jessica")
    got = saved(ask(app))
    assert got["group"] == "leaders", "she leads, so she is counted with the leaders"
    assert got["to"]["id"] == owner, "and routed as her login: whoever oversees the office goes to the owner"
    assert got["can_answer"] is False, "never her own, whatever her standing"
    assert answer(app, got["id"], True).status_code == 403


def test_someone_on_the_add_list_asks_as_anyone_does(app, db):
    w = db.who[LOVE_CITY]
    as_(app, LOVE_CITY, "owner")
    app.put("/church/schedule/people", json={"business_id": LOVE_CITY, "contact_id": w["calvin"], "listed": "add",
                                             "group": "office"})
    got = saved(ask(app, **{"for": f"person:{w['calvin']}"}))
    assert (got["name"], got["group"], got["state"]) == ("Calvin Owens", "office", "asked")
    assert got["to"]["name"] == "Pastor Kevin" and got["mine"] is False
    assert got["can_answer"] is True and got["can_withdraw"] is True, "the owner entered it"


def test_the_owners_own_person_needs_no_yes(app, db):
    as_(app, LOVE_CITY, "owner")
    got = saved(ask(app, starts_on=day(3), ends_on=day(9), reason=SECRET))
    assert got["state"] == "yes" and got["to"] is None and got["flags"] == [], "nobody is over them"
    assert got["decided"]["by"] is None and got["name"] == "Kevin McCloud"
    [f] = facts(db)
    assert (f["ask_id"], f["kind"], f["note"]) == (got["id"], "time_off", "")
    as_(app, GRACE, "owner")
    assert saved(ask(app, GRACE))["state"] == "yes", "at every church"


def test_someone_not_on_the_schedule_is_told_so(app, db):
    w = db.who[LOVE_CITY]
    fake.seat(db, LOVE_CITY, "calvin")
    as_(app, LOVE_CITY, "calvin")
    r = ask(app)
    assert r.status_code == 403 and r.json()["detail"] == cs.NOT_ON
    as_(app, LOVE_CITY, "owner")
    r = ask(app, **{"for": f"person:{w['iris']}"})
    assert r.status_code == 400 and r.json()["detail"] == cs.THEY_NOT_ON
    app.put("/church/schedule/people", json={"business_id": LOVE_CITY, "contact_id": w["gloria"], "listed": "remove"})
    assert ask(app, **{"for": f"person:{w['gloria']}"}).status_code == 400, "taken off the schedule"
    as_(app, RIVERSIDE, "owner")
    assert ask(app, RIVERSIDE).status_code == 403, "nobody is on Riverside's until it adds a name"
    assert db.t["church_away_asks"] == []


def test_a_login_matched_to_no_person_gets_plain_words(app, db):
    """Decision 3."""
    seat = next(s for s in db.t["business_users"] if s["user_id"] == db.who[LOVE_CITY]["shapretta@"])
    seat.update(invited_email="media@lovecity.org", contact_id=None)
    as_(app, LOVE_CITY, "shapretta")
    r = ask(app)
    assert r.status_code == 409 and r.json()["detail"].startswith("This login isn't matched to a person here yet")
    assert box(app, "mine") == [] and db.t["church_away_asks"] == []


def test_only_the_owner_and_the_office_overseer_ask_for_someone_else(app, db):
    w = db.who[LOVE_CITY]
    for handle in ("minnie", "naiya", "laquesha", "andre"):
        as_(app, LOVE_CITY, handle)
        r = ask(app, **{"for": f"person:{w['yolanda']}"})
        assert r.status_code == 403 and r.json()["detail"] == cs.NOT_FOR, handle
    as_(app, LOVE_CITY, "jessica")
    got = saved(ask(app, **{"for": f"person:{w['yolanda']}"}))
    assert got["name"] == "Yolanda Reed" and got["to"]["name"] == "Andre Wallace"
    assert row(db, got["id"])["made_by"] == db.who[LOVE_CITY]["jessica@"]
    assert ask(app, **{"for": f"login:{db.who[LOVE_CITY]['naiya@']}"}).status_code == 400
    assert ask(app, **{"for": f"person:{db.who[GRACE]['yvette']}"}).status_code == 400, "another church's person"
    assert len(db.t["church_away_asks"]) == 1


# ─── Answers and withdrawals ──────────────────────────────────────────

def test_yes_from_the_one_it_went_to_writes_the_away_date(app, db):
    got = planned(app)
    as_(app, LOVE_CITY, "andre")
    [mine_to_answer] = box(app, "to_me")
    assert mine_to_answer["id"] == got["id"] and mine_to_answer["can_answer"] is True
    assert mine_to_answer["reason"] == SECRET, "it went to him"
    said = saved(answer(app, got["id"], True, note=NOTE))
    assert said["state"] == "yes" and said["decided"]["by"] == "Andre Wallace" and said["decided"]["note"] == NOTE
    r = row(db, got["id"])
    assert r["decided_by_user_id"] == db.who[LOVE_CITY]["andre@"] and r["decided_by_contact_id"] is None
    [f] = facts(db)
    assert (f["ask_id"], f["kind"], f["note"], f["starts_on"], f["ends_on"]) == (got["id"], "time_off", "", day(30),
                                                                                  day(37))
    assert box(app, "to_me") == []
    as_(app, LOVE_CITY, "yolanda")
    [mine] = box(app, "mine")
    assert mine["state"] == "yes" and mine["decided"] == said["decided"] and mine["can_withdraw"] is True


def test_not_this_one_writes_no_away_date(app, db):
    got = planned(app)
    as_(app, LOVE_CITY, "andre")
    said = saved(answer(app, got["id"], False, note=NOTE))
    assert said["state"] == "no" and said["decided"]["note"] == NOTE and facts(db) == []
    as_(app, LOVE_CITY, "yolanda")
    [mine] = box(app, "mine")
    assert mine["state"] == "no" and mine["can_withdraw"] is False and mine["decided"]["note"] == NOTE
    assert saved(ask(app))["state"] == "asked", "once answered, the days can be asked again"


def test_the_owner_and_the_office_overseer_may_answer_any(app, db):
    got = planned(app)
    as_(app, LOVE_CITY, "jessica")
    assert box(app, "to_me") == [], "it didn't go to her"
    assert [a["id"] for a in box(app, "all")] == [got["id"]]
    assert saved(answer(app, got["id"], True))["decided"]["by"] == "Jessica McCloud"
    other = planned(app, "tyrone")
    as_(app, LOVE_CITY, "owner")
    assert saved(answer(app, other["id"], False))["decided"]["by"] == "Pastor Kevin"
    assert len(facts(db)) == 1


def test_with_two_who_oversee_the_office_it_goes_to_the_first_and_either_may_answer(app, db):
    """Decision 1: one name on the ask, so one more person reads the reason,
    not everyone at that step. Whoever oversees the office is whoever does
    that duty today, never a title: moved to two others, it is theirs."""
    w = db.who[LOVE_CITY]
    db.t["church_duty_holders"] += [{"business_id": LOVE_CITY, "duty": "oversee_lanes", "user_id": w[h + "@"]}
                                    for h in ("naiya", "tiara")]
    cd._CACHE.clear()
    as_(app, LOVE_CITY, "laquesha")
    got = saved(ask(app, reason=SECRET))
    assert got["to"] == {"kind": "login", "id": w["naiya@"], "name": "Naiya Clark"}
    as_(app, LOVE_CITY, "tiara")
    assert box(app, "to_me") == [] and [a["reason"] for a in box(app, "all")] == [SECRET]
    as_(app, LOVE_CITY, "jessica")
    assert answer(app, got["id"], True).status_code == 403, "she no longer oversees the office"
    assert SECRET not in everything_read(app)
    as_(app, LOVE_CITY, "tiara")
    assert saved(answer(app, got["id"], True))["decided"]["by"] == "Tiara Adams"


@pytest.mark.parametrize("handle", ["minnie", "naiya", "laquesha", "ruth", "tyrone", "yolanda"])
def test_nobody_else_answers(app, db, handle):
    got = planned(app)
    as_(app, LOVE_CITY, handle)
    for yes in (True, False):
        r = answer(app, got["id"], yes)
        assert r.status_code == 403 and r.json()["detail"] == cs.NOT_TO_YOU, (handle, yes)
    assert row(db, got["id"])["state"] == "asked" and facts(db) == [] and not db.rpcs


def test_what_an_answer_refuses(app, db):
    got = planned(app)
    as_(app, LOVE_CITY, "andre")
    assert answer(app, got["id"], "yes").status_code == 400, "yes is true or false"
    assert answer(app, got["id"], True, note="x" * 301).status_code == 400
    assert answer(app, "nothing", True).status_code == 400
    assert answer(app, "5e000000-0000-4000-8000-000000000001", True).status_code == 404
    assert row(db, got["id"])["state"] == "asked" and not db.rpcs


def test_the_asker_takes_it_back_waiting_or_already_a_yes(app, db):
    got = planned(app)
    taken = saved(withdraw(app, got["id"]))
    assert taken["state"] == "withdrawn" and taken["can_withdraw"] is False and taken["decided"] is None
    assert withdraw(app, got["id"]).status_code == 409
    again = saved(ask(app, reason=SECRET))
    as_(app, LOVE_CITY, "andre")
    saved(answer(app, again["id"], True))
    assert len(facts(db)) == 1
    as_(app, LOVE_CITY, "yolanda")
    taken = saved(withdraw(app, again["id"]))
    assert taken["state"] == "withdrawn" and taken["decided"]["by"] == "Andre Wallace", "it keeps who had said yes"
    assert facts(db) == [], "its away date goes with it"


def test_who_may_take_one_back(app, db):
    as_(app, LOVE_CITY, "jessica")
    got = saved(ask(app, **{"for": f"person:{db.who[LOVE_CITY]['yolanda']}"}))
    for handle in ("andre", "minnie", "owner", "ruth"):
        as_(app, LOVE_CITY, handle)
        r = withdraw(app, got["id"])
        assert r.status_code == 403 and r.json()["detail"] == cs.NOT_ASKER, handle
    as_(app, LOVE_CITY, "jessica")
    assert saved(withdraw(app, got["id"]))["state"] == "withdrawn", "the login that entered it"
    got = planned(app)
    as_(app, LOVE_CITY, "andre")
    saved(answer(app, got["id"], False))
    as_(app, LOVE_CITY, "yolanda")
    r = withdraw(app, got["id"])
    assert r.status_code == 409 and r.json()["detail"] == cs.NOT_OPEN, "a no is already settled"


def test_a_second_answer_is_a_409(app, db):
    got = planned(app)
    as_(app, LOVE_CITY, "andre")
    saved(answer(app, got["id"], True))
    r = answer(app, got["id"], False)
    assert r.status_code == 409 and r.json()["detail"] == "That one was already answered."
    assert row(db, got["id"])["state"] == "yes" and len(facts(db)) == 1


def test_two_answers_at_once_land_one_after_the_other(app, db):
    """The race: both read the ask as waiting; the database takes them in
    turn and tells the second nothing changed."""
    got = planned(app)
    owner = c3.church(db, LOVE_CITY)["owner_id"]
    db.before_settle = lambda: fake.settle(db, {"p_business_id": LOVE_CITY, "p_ask_id": got["id"], "p_state": "no",
                                                "p_by_user": owner})
    as_(app, LOVE_CITY, "andre")
    r = answer(app, got["id"], True)
    assert r.status_code == 409 and r.json()["detail"] == cs.ALREADY
    assert row(db, got["id"])["state"] == "no" and row(db, got["id"])["decided_by_user_id"] == owner
    assert facts(db) == [], "the yes that lost wrote nothing"


def test_an_answer_after_a_withdraw_is_a_409_and_so_is_a_withdraw_after_a_no(app, db):
    got = planned(app)
    db.before_settle = lambda: fake.settle(db, {"p_business_id": LOVE_CITY, "p_ask_id": got["id"],
                                                "p_state": "withdrawn"})
    as_(app, LOVE_CITY, "andre")
    assert answer(app, got["id"], True).status_code == 409
    assert row(db, got["id"])["state"] == "withdrawn" and facts(db) == []
    got = planned(app)
    db.before_settle = lambda: fake.settle(db, {"p_business_id": LOVE_CITY, "p_ask_id": got["id"], "p_state": "no",
                                                "p_by_contact": db.who[LOVE_CITY]["andre"]})
    r = withdraw(app, got["id"])
    assert r.status_code == 409 and r.json()["detail"] == cs.NOT_OPEN and row(db, got["id"])["state"] == "no"


# ─── The refusals ─────────────────────────────────────────────────────

def test_the_days_an_ask_refuses(app, db):
    as_(app, LOVE_CITY, "yolanda")
    for kw in ({"starts_on": day(-3), "ends_on": day(-1)}, {"starts_on": day(9), "ends_on": day(8)},
               {"starts_on": day(1), "ends_on": day(368)}, {"starts_on": "soon", "ends_on": day(8)},
               {"starts_on": "", "ends_on": ""}):
        r = ask(app, **kw)
        assert r.status_code == 400 and r.json()["detail"] == cs.BAD_DAYS, kw
    assert saved(ask(app, starts_on=day(-1), ends_on=day(2)))["starts_on"] == day(-1), "already away, still away"
    assert saved(ask(app, starts_on=day(1), ends_on=day(367)))["ends_on"] == day(367), "a year at most"
    assert saved(ask(app, starts_on=day(40), ends_on=""))["ends_on"] == day(40), "one day"
    assert not db.refused


def test_what_else_an_ask_refuses(app, db):
    w = db.who[LOVE_CITY]
    as_(app, LOVE_CITY, "yolanda")
    assert ask(app, kind="holiday").status_code == 400
    assert ask(app, reason="x" * 501).status_code == 400
    assert saved(ask(app, reason="x" * 500, starts_on=day(50), ends_on=day(50)))["reason"] == "x" * 500
    r = ask(app, cover_contact_id=w["yolanda"])
    assert r.status_code == 400 and "Someone else covers" in r.json()["detail"]
    assert ask(app, cover_contact_id=db.who[GRACE]["yvette"]).status_code == 400, "another church's person"
    assert ask(app, cover_contact_id="nobody").status_code == 400
    assert ask(app, cover_name="x" * 81).status_code == 400
    assert saved(ask(app, cover_name="  My  sister "))["cover"] == {"contact_id": None, "name": "My sister"}
    assert len(db.t["church_away_asks"]) == 2 and not db.refused, "each refused before the database was asked"


def test_the_same_days_already_waiting_are_a_409(app, db, monkeypatch):
    planned(app)
    r = ask(app)
    assert r.status_code == 409 and r.json()["detail"] == cs.WAITING
    assert ask(app, kind="commitment").status_code == 409, "whatever the kind"
    assert len(db.t["church_away_asks"]) == 1
    # Two presses at once: neither saw the other, and the table keeps one.
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **k: [] if "state=eq.asked" in path else real(path, **k))
    monkeypatch.setattr(sb_clients, "last_error", lambda: {"status": 409, "code": "23505", "message": "duplicate key"})
    r = ask(app)
    assert r.status_code == 409 and r.json()["detail"] == cs.WAITING
    assert db.refused == ["unique: church_away_asks_one_open"] and len(db.t["church_away_asks"]) == 1


def test_no_more_than_twenty_waiting_at_once(app, db):
    as_(app, LOVE_CITY, "yolanda")
    for n in range(cs.MAX_OPEN):
        saved(ask(app, starts_on=day(40 + n), ends_on=day(40 + n)))
    r = ask(app, starts_on=day(90), ends_on=day(90))
    assert r.status_code == 400 and r.json()["detail"] == cs.TOO_MANY
    assert saved(ask(app, starts_on=day(0), ends_on=day(0), kind="cant"))["state"] == "yes", "sickness is never blocked"
    as_(app, LOVE_CITY, "tyrone")
    assert saved(ask(app))["state"] == "asked", "the count is each person's own"


# ─── Privacy ──────────────────────────────────────────────────────────

READS = ("status?business_id={b}", "people?business_id={b}", "settings?business_id={b}",
         "leaders?business_id={b}&from={lo}&to={hi}", "asks?business_id={b}&box=mine", "asks?business_id={b}&box=to_me",
         "asks?business_id={b}&box=all")


def everything_read(app, biz=LOVE_CITY):
    """Every read this login can make, as the wire carries it."""
    return "\n".join(app.get("/church/schedule/" + p.format(b=biz, lo=day(0), hi=day(60))).text for p in READS)


def laquesha_keeps_who_serves_when(db):
    return cd.holds(LOVE_CITY, SimpleNamespace(id=db.who[LOVE_CITY]["laquesha@"]), "serve_schedule")


MAY_READ = ("yolanda", "andre", "owner", "jessica")              # asked, it went to him, the owner, the overseer
MAY_NOT = ("minnie", "naiya", "tiara", "laquesha", "shapretta", "ruth", "tyrone")


@pytest.mark.parametrize("state", ["asked", "yes", "no", "withdrawn"])
def test_the_reason_and_the_note_reach_four_people_and_nobody_else(app, db, state):
    got = planned(app)
    if state in ("yes", "no"):
        as_(app, LOVE_CITY, "andre")
        saved(answer(app, got["id"], state == "yes", note=NOTE))
    elif state == "withdrawn":
        saved(withdraw(app, got["id"]))
    assert laquesha_keeps_who_serves_when(db)
    for handle in MAY_READ:
        as_(app, LOVE_CITY, handle)
        seen = everything_read(app)
        # Once it is a no, or taken back, it is on nobody's list but the asker's and the two who see every ask.
        reaches = handle != "andre" or state in ("asked", "yes")
        assert (SECRET in seen) == reaches, (handle, state)
        assert (NOTE in seen) == (reaches and state in ("yes", "no")), (handle, state)
    for handle in MAY_NOT:
        as_(app, LOVE_CITY, handle)
        seen = everything_read(app)
        assert SECRET not in seen and NOTE not in seen, (handle, state)
        r = app.get(f"/church/schedule/asks?business_id={LOVE_CITY}&box=all")
        assert r.status_code == 403 and r.json()["detail"] == cs.NOT_ALL, handle
    assert all(s["note"] == "" for s in facts(db))
    assert SECRET not in str(db.t["serve_away"]) and NOTE not in str(db.t["serve_away"])


def test_everyone_on_the_schedule_sees_an_approved_away_date_without_its_reason(app, db):
    got = planned(app, cover_contact_id=db.who[LOVE_CITY]["tyrone"])
    as_(app, LOVE_CITY, "andre")
    saved(answer(app, got["id"], True, note=NOTE))
    for handle in MAY_NOT:
        as_(app, LOVE_CITY, handle)
        [away] = groups(app)["leaders"]["away"]
        assert (away["name"], away["starts_on"], away["ends_on"], away["kind"]) == ("Yolanda Reed", day(30), day(37),
                                                                                    "time_off"), handle
        assert away["cover"]["name"] == "Tyrone Banks"
        assert away["reason"] is None and away["reason_hidden"] is True and away["decided"]["note"] is None
        assert (away["mine"], away["can_answer"], away["can_withdraw"]) == (False, False, False)
    as_(app, LOVE_CITY, "owner")
    [away] = groups(app)["leaders"]["away"]
    assert away["reason"] == SECRET and away["reason_hidden"] is False and away["decided"]["note"] == NOTE


def test_a_waiting_ask_is_shown_to_nobody_it_isnt_for(app, db):
    got = planned(app)
    for handle in MAY_NOT:
        as_(app, LOVE_CITY, handle)
        g = groups(app)
        assert g["leaders"]["waiting"] == [] and g["leaders"]["away"] == [], handle
        assert box(app, "to_me") == [] and box(app, "mine") == [], handle
        assert got["id"] not in everything_read(app), handle
    for handle in MAY_READ:
        as_(app, LOVE_CITY, handle)
        assert [a["id"] for a in groups(app)["leaders"]["waiting"]] == [got["id"]], handle


def test_the_one_who_keeps_who_serves_when_gets_a_403_unless_on_the_schedule(app, db):
    """She is on it as one of the office; taken off, the duty alone opens nothing."""
    planned(app)
    assert laquesha_keeps_who_serves_when(db)
    as_(app, LOVE_CITY, "laquesha")
    assert cal(app).status_code == 200
    as_(app, LOVE_CITY, "owner")
    app.put("/church/schedule/people", json={"business_id": LOVE_CITY, "contact_id": db.who[LOVE_CITY]["laquesha"],
                                             "listed": "remove"})
    as_(app, LOVE_CITY, "laquesha")
    assert laquesha_keeps_who_serves_when(db)
    r = cal(app)
    assert r.status_code == 403 and r.json()["detail"] == cs.NOT_ON
    assert app.get(f"/church/schedule/settings?business_id={LOVE_CITY}").status_code == 403
    assert app.get(f"/church/schedule/people?business_id={LOVE_CITY}").status_code == 403
    assert SECRET not in everything_read(app)


def test_an_admin_off_the_schedule_reads_the_roster_and_nothing_else(app, db):
    planned(app)
    as_(app, LOVE_CITY, "owner")
    app.put("/church/schedule/people", json={"business_id": LOVE_CITY, "contact_id": db.who[LOVE_CITY]["minnie"],
                                             "listed": "remove"})
    as_(app, LOVE_CITY, "minnie")
    assert app.get(f"/church/schedule/people?business_id={LOVE_CITY}").status_code == 200
    assert cal(app).status_code == 403 and SECRET not in everything_read(app)


def test_an_admin_reads_and_answers_only_one_that_went_to_them(app, db):
    """Decision 7: no standing over every ask, but an ask can still be theirs."""
    got = planned(app)
    row(db, got["id"]).update(to_contact_id=None, to_user_id=db.who[LOVE_CITY]["minnie@"])
    other = planned(app, "tyrone")
    as_(app, LOVE_CITY, "minnie")
    [mine] = box(app, "to_me")
    assert mine["id"] == got["id"] and mine["reason"] == SECRET and mine["can_answer"] is True
    assert answer(app, other["id"], True).status_code == 403
    assert saved(answer(app, got["id"], True))["decided"]["by"] == "Minnie Tatum"


def test_a_member_app_session_never_carries_the_owners_standing(app, db):
    """Decision 6: there, a person reads and answers only what went to them
    (or to the login tied to exactly them), whoever that person is."""
    w = db.who[LOVE_CITY]
    to_andre = row(db, planned(app)["id"])
    to_jess = row(db, planned(app, "naiya")["id"])
    ch = co.Church(c3.church(db, LOVE_CITY))
    kevin, jess, andre, yolanda = (co.who(co.PERSON, w[h]) for h in ("kevin", "jessica", "andre", "yolanda"))
    for me in (kevin, jess):
        assert not cs.over_all(ch, me)
        assert not cs.may_decide(ch, me, to_andre) and not cs.sees_reason(ch, me, to_andre)
        assert cs.shape(ch, me, to_andre, cs._names(ch, [to_andre]))["reason"] is None
    assert cs.may_decide(ch, andre, to_andre) and cs.sees_reason(ch, andre, to_andre)
    assert cs.sees_reason(ch, yolanda, to_andre) and not cs.may_decide(ch, yolanda, to_andre), "never your own"
    assert cs.may_decide(ch, jess, to_jess) and cs.sees_reason(ch, jess, to_jess), "the login it went to is her"
    assert not cs.may_decide(ch, kevin, to_jess) and not cs.sees_reason(ch, kevin, to_jess)
    owner = co.who(co.LOGIN, ch.owner)
    assert cs.may_decide(ch, owner, to_andre) and cs.sees_reason(ch, owner, to_jess), "the office app does"


def test_one_whose_login_has_left_the_office_is_the_owners_to_answer(app, db):
    got = planned(app, "naiya")
    gone = next(s for s in db.t["business_users"] if s["user_id"] == db.who[LOVE_CITY]["jessica@"])
    gone["status"] = "revoked"
    as_(app, LOVE_CITY, "owner")
    [mine] = box(app, "to_me")
    assert mine["id"] == got["id"] and mine["to"]["name"] == cs.LEFT and mine["can_answer"] is True
    row(db, got["id"]).update(to_user_id=None)                   # or the login is gone altogether
    assert [a["id"] for a in box(app, "to_me")] == [got["id"]]
    assert saved(answer(app, got["id"], True))["state"] == "yes"


def test_nothing_crosses_churches(app, db):
    got = planned(app)
    as_(app, NEW_HOPE, "owner")
    assert saved(ask(app, NEW_HOPE, reason="A New Hope reason"))["state"] == "yes"
    assert box(app, "all", NEW_HOPE)[0]["name"] == "Nathan Cole" and len(box(app, "all", NEW_HOPE)) == 1
    assert SECRET not in everything_read(app, NEW_HOPE)
    assert answer(app, got["id"], True, NEW_HOPE).status_code == 404, "Love City's ask, named at New Hope"
    assert withdraw(app, got["id"], NEW_HOPE).status_code == 404
    as_(app, LOVE_CITY, "owner")
    assert "A New Hope reason" not in everything_read(app)
    assert answer(app, got["id"], True, NEW_HOPE).status_code == 404, "no seat there"
    assert row(db, got["id"])["state"] == "asked"


# ─── A failed read or write ───────────────────────────────────────────

def test_a_failed_write_is_a_503_with_nothing_saved(app, db):
    as_(app, LOVE_CITY, "yolanda")
    db.fail = {"post": "/church_away_asks"}
    r = ask(app)
    assert r.status_code == 503 and r.json()["detail"] == cs.UNSAVED
    assert db.t["church_away_asks"] == [] and facts(db) == []
    db.fail = {}
    got = saved(ask(app))
    as_(app, LOVE_CITY, "andre")
    db.fail = {"post": "/rpc/church_away_settle"}
    assert answer(app, got["id"], True).status_code == 503
    as_(app, LOVE_CITY, "yolanda")
    assert withdraw(app, got["id"]).status_code == 503
    assert row(db, got["id"])["state"] == "asked" and facts(db) == []


@pytest.mark.parametrize("table", ["/church_schedule_settings", "/church_schedule_people", "/church_leader_roles",
                                   "/church_away_asks", "/contacts", "/church_departments"])
def test_a_failed_read_is_a_503_before_anything_is_written(app, db, table):
    as_(app, LOVE_CITY, "yolanda")
    db.fail = {"get": table}
    assert ask(app, cover_contact_id=db.who[LOVE_CITY]["tyrone"]).status_code == 503, table
    assert db.t["church_away_asks"] == [] and not db.rpcs
    db.fail = {}
    assert saved(ask(app, cover_contact_id=db.who[LOVE_CITY]["tyrone"]))["state"] == "asked"


def test_a_list_that_cant_be_read_is_a_503_never_empty(app, db):
    planned(app)
    as_(app, LOVE_CITY, "owner")
    db.fail = {"get": "/church_away_asks"}
    for which in ("mine", "to_me", "all"):
        assert app.get(f"/church/schedule/asks?business_id={LOVE_CITY}&box={which}").status_code == 503, which
    assert cal(app).status_code == 503
    db.fail = {"get": "/serve_away"}
    assert cal(app).status_code == 503


def test_a_cant_that_doesnt_settle_leaves_nothing_and_asking_again_makes_one(app, db):
    as_(app, LOVE_CITY, "yolanda")
    db.fail = {"post": "/rpc/church_away_settle"}
    r = ask(app, starts_on=day(0), ends_on=day(0), kind="cant")
    assert r.status_code == 503 and db.t["church_away_asks"] == [] and facts(db) == [], "taken back: nothing waits"
    db.fail = {}
    got = saved(ask(app, starts_on=day(0), ends_on=day(0), kind="cant"))
    assert got["state"] == "yes" and len(db.t["church_away_asks"]) == 1 and len(facts(db)) == 1


def test_one_that_couldnt_be_taken_back_is_finished_not_copied(app, db):
    as_(app, LOVE_CITY, "yolanda")
    db.fail = {"post": "/rpc/church_away_settle", "delete": "/church_away_asks"}
    assert ask(app, starts_on=day(0), ends_on=day(0), kind="cant", reason=SECRET).status_code == 503
    [left] = db.t["church_away_asks"]
    assert left["state"] == "asked" and facts(db) == []
    db.fail = {}
    got = saved(ask(app, starts_on=day(0), ends_on=day(0), kind="cant", reason=SECRET))
    assert got["id"] == left["id"] and got["state"] == "yes"
    assert len(db.t["church_away_asks"]) == 1 and len(facts(db)) == 1 and not db.refused


def test_an_answer_that_was_lost_on_the_way_back_isnt_made_twice(app, db, monkeypatch):
    """The settle landed and its answer didn't: asking again answers with
    the one that is there."""
    as_(app, LOVE_CITY, "yolanda")
    real = sb_clients.sb_post_as_service

    def lost(path, body, prefer=None, **k):
        got = real(path, body, prefer, **k)
        return None if path.startswith("/rpc/") else got
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lost)
    assert ask(app, starts_on=day(0), ends_on=day(0), kind="cant").status_code == 503
    monkeypatch.setattr(sb_clients, "sb_post_as_service", real)
    [there] = db.t["church_away_asks"]
    assert there["state"] == "yes" and len(facts(db)) == 1, "it did land"
    got = saved(ask(app, starts_on=day(0), ends_on=day(0), kind="cant"))
    assert got["id"] == there["id"] and len(db.t["church_away_asks"]) == 1 and len(facts(db)) == 1
    db.t["serve_away"].clear()                                   # she took that day off again, the old way
    again = saved(ask(app, starts_on=day(0), ends_on=day(0), kind="cant"))
    assert again["id"] != there["id"] and len(facts(db)) == 1, "then it is a new one"


def test_the_owners_own_that_doesnt_settle_is_taken_back_too(app, db):
    as_(app, LOVE_CITY, "owner")
    db.fail = {"post": "/rpc/church_away_settle"}
    assert ask(app).status_code == 503 and db.t["church_away_asks"] == []
    db.fail = {}
    assert saved(ask(app))["state"] == "yes" and len(facts(db)) == 1


# ─── The calendar and the lists ───────────────────────────────────────

def test_the_calendar_reads_the_facts_never_an_asks_state(app, db):
    w = db.who[LOVE_CITY]
    got = planned(app)
    as_(app, LOVE_CITY, "andre")
    saved(answer(app, got["id"], True))
    as_(app, LOVE_CITY, "naiya")
    held = saved(ask(app, starts_on=day(20), ends_on=day(21)))
    db.t["serve_away"] += [
        {"id": "f-plain", "business_id": LOVE_CITY, "contact_id": w["marcus"], "starts_on": day(10), "ends_on": day(12),
         "note": "", "ask_id": None, "kind": None, "created_at": "2026-11-01T00:00:00+00:00"},
        {"id": "f-volunteer", "business_id": LOVE_CITY, "contact_id": w["calvin"], "starts_on": day(10),
         "ends_on": day(12), "note": "", "ask_id": None, "kind": None, "created_at": "2026-11-01T00:00:00+00:00"},
        {"id": "f-later", "business_id": LOVE_CITY, "contact_id": w["tanya"], "starts_on": day(61), "ends_on": day(70),
         "note": "", "ask_id": None, "kind": None, "created_at": "2026-11-01T00:00:00+00:00"},
        {"id": "f-other", "business_id": GRACE, "contact_id": db.who[GRACE]["yvette"], "starts_on": day(10),
         "ends_on": day(12), "note": "", "ask_id": None, "kind": None, "created_at": "2026-11-01T00:00:00+00:00"}]
    as_(app, LOVE_CITY, "owner")
    r = cal(app)
    assert r.status_code == 200 and (r.json()["from"], r.json()["to"]) == (day(0), day(60))
    g = {x["key"]: x for x in r.json()["groups"]}
    assert [(x["key"], x["name"], x["people"]) for x in r.json()["groups"]] == [("leaders", "Leaders", 14),
                                                                                ("office", "The office", 5)]
    assert [(a["name"], a["id"], a["kind"]) for a in g["leaders"]["away"]] == [("Marcus Taylor", None, None),
                                                                              ("Yolanda Reed", got["id"], "time_off")]
    plain = g["leaders"]["away"][0]
    assert (plain["starts_on"], plain["ends_on"], plain["state"], plain["reason"]) == (day(10), day(12), "yes", None)
    assert plain["can_withdraw"] is False and plain["reason_hidden"] is False
    assert g["leaders"]["waiting"] == [] and g["leaders"]["standing"] == [] and g["office"]["standing"] == []
    assert g["office"]["away"] == [] and [a["id"] for a in g["office"]["waiting"]] == [held["id"]]
    # The away date taken off the old way: the ask still says yes, and nobody is shown as away.
    db.t["serve_away"] = [s for s in db.t["serve_away"] if s.get("ask_id") != got["id"]]
    assert row(db, got["id"])["state"] == "yes"
    assert [a["name"] for a in groups(app)["leaders"]["away"]] == ["Marcus Taylor"]
    assert [a["name"] for a in groups(app, lo=61, hi=80)["leaders"]["away"]] == ["Tanya Brooks"]


def test_my_own_plain_away_date_is_shown_as_mine_with_nothing_to_take_back_here(app, db):
    """It was added on Serving, Away, and comes off there."""
    db.t["serve_away"].append({"id": "f-mine", "business_id": LOVE_CITY, "contact_id": db.who[LOVE_CITY]["naiya"],
                               "starts_on": day(10), "ends_on": day(12), "note": "", "ask_id": None, "kind": None,
                               "created_at": "2026-11-01T00:00:00+00:00"})
    as_(app, LOVE_CITY, "naiya")
    [away] = groups(app)["office"]["away"]
    assert (away["name"], away["id"], away["mine"], away["can_withdraw"], away["can_answer"]) == (
        "Naiya Clark", None, True, False, False)


def test_the_calendars_window(app, db):
    as_(app, LOVE_CITY, "owner")
    assert cal(app, lo=0, hi=93).status_code == 200
    assert cal(app, lo=0, hi=94).status_code == 400
    assert cal(app, lo=5, hi=4).status_code == 400
    assert app.get(f"/church/schedule/leaders?business_id={LOVE_CITY}&from=soon").status_code == 400
    r = app.get(f"/church/schedule/leaders?business_id={LOVE_CITY}")
    assert (r.json()["from"], r.json()["to"]) == (day(0), day(62)), "from today, on the church's clock"
    fake.seat(db, LOVE_CITY, "calvin")
    as_(app, LOVE_CITY, "calvin")
    assert cal(app).status_code == 403, "a seat that isn't on the schedule"


def test_my_asks_come_waiting_first_then_newest(app, db):
    as_(app, LOVE_CITY, "yolanda")
    first = saved(ask(app, starts_on=day(20), ends_on=day(21)))
    saved(ask(app, starts_on=day(0), ends_on=day(0), kind="cant"))
    last = saved(ask(app, starts_on=day(50), ends_on=day(52)))
    db.t["church_away_asks"].append(dict(row(db, first["id"]), id="5e000000-0000-4000-8000-00000000000a",
                                         state="no", decided_at="2026-06-01T00:00:00+00:00", starts_on="2026-06-01",
                                         ends_on="2026-06-02"))
    assert [(a["starts_on"], a["state"]) for a in box(app, "mine")] == [(day(50), "asked"), (day(20), "asked"),
                                                                        (day(0), "yes")], "old ones drop off"
    as_(app, LOVE_CITY, "andre")
    assert [a["id"] for a in box(app, "to_me")] == [first["id"], last["id"]], "soonest first"
    assert box(app, "mine") == []
    assert app.get(f"/church/schedule/asks?business_id={LOVE_CITY}&box=theirs").status_code == 400


def test_every_ask_is_read_whole_past_a_thousand(app, db):
    """New Hope's 500 people: 1,050 waiting asks are all listed (a read never
    takes the first 1,000 rows for every row)."""
    people = [c["id"] for c in db.t["contacts"] if c["business_id"] == NEW_HOPE][:350]
    owner = c3.church(db, NEW_HOPE)["owner_id"]
    n = 0
    for cid in people:
        for k in range(3):
            n += 1
            db.t["church_away_asks"].append({
                "id": f"5e000000-0000-4000-8000-{n:012d}", "business_id": NEW_HOPE, "contact_id": cid, "made_by": None,
                "grp": "leaders", "department_id": None, "kind": "time_off", "starts_on": day(10 + k),
                "ends_on": day(10 + k), "reason": None, "cover_contact_id": None, "cover_name": None,
                "to_user_id": owner, "to_contact_id": None, "state": "asked", "flags": [], "decided_by_user_id": None,
                "decided_by_contact_id": None, "decided_at": None, "decided_note": None, "withdrawn_at": None,
                "created_at": "2026-11-01T00:00:00+00:00"})
    as_(app, NEW_HOPE, "owner")
    mine = db.who[NEW_HOPE]["nathan"]
    assert len(box(app, "all", NEW_HOPE)) == 1050
    assert len(box(app, "to_me", NEW_HOPE)) == 1050 - sum(1 for r in db.t["church_away_asks"] if r["contact_id"] == mine)
