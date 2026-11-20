"""Things that repeat on the leaders schedule (church_schedule_repeats.py;
docs/CHURCH_SCHEDULE.md, PR S1-7). Kevin, 2026-11-18: "this is for when
leaders are planning time off and have certain obiligations so that we as a
church can plan around meeting". A leader says once "I work every other
Saturday", and the schedule remembers it.

At New Hope (church_three: a made-up church of 500, every name in it made
up), through the real office routes and engine, on church_schedule_fake's
tables (church_away_commitments as step 1's file makes it). Pins:

  * THE DAYS: every week, every other week counted from its first day, the
    nth of the month with 5 the last (in a month with four of that weekday
    too), from and until, 366 days at most, and a row that can't be read
    falls on no day
  * no yes and never blocked: saved at once, never an ask and never an away
    date; ten a person in force, the eleventh refused in plain words; the
    same one twice is one
  * who adds (a leader for their own person; the owner and whoever oversees
    the office for anyone on the schedule, as an ask's `for`), who reads the
    list (their own; every one for those two), who takes one off (their
    own; those two anyone's)
  * THE LABEL IS READ EXACTLY AS AN ASK'S REASON: by the person, whoever an
    ask of theirs would go to, the owner and whoever oversees the office;
    for anyone else on the calendar the key is absent
  * never counted toward a limit, never a pair, with step 2's file there
  * closed, the switch off or before the tables: a 404 and nothing read
  * a failed read or write is a 503 with nothing saved; another church's
    is never read
  * no title word or role key in the rule code

The scheduler's hold is pinned in test_sunday_planning_holds.py, the notice in
test_church_schedule_tell.py and the Dates page in test_member_portal_dates.py.
"""
from __future__ import annotations

import inspect
import os
import re
import sys
from datetime import date, timedelta

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_over as co  # noqa: E402
import church_schedule as cs  # noqa: E402
import church_schedule_fake as fake  # noqa: E402
import church_schedule_repeats as crep  # noqa: E402
import church_three as c3  # noqa: E402
from church_schedule_fake import TODAY, as_, day  # noqa: E402

HOPE = c3.NEW_HOPE                       # a made-up church of 500: every name in it is made up
SHIFT = "Night shift at the plant"       # what Elena typed: as private as a reason
SECRET = "Surgery for my mother that week"
SEATED = ("elena", "yusuf", "amara", "esther")      # leaders who sign in to the office app on a Member seat
SAT, SUN, WED = 6, 7, 3
TITLE_WORDS = re.compile(r"\b(pastors?|elders?|deacons?|ministers?|bishops?|overseers?|directors?|executive|"
                         r"treasurers?|secretary|owners?|trustees?|reverend|apostles?|prophets?)\b", re.I)
ROLE_KEYS = re.compile(r"\b(pastor|executive_pastor|associate_pastor|elders|deacons|ministers|youth_pastor|"
                       r"worship_leader|team_leader|director_of_operations|childrens_director)\b")


@pytest.fixture
def db(monkeypatch, request):
    """A database with step 1's file alone; `db` asked for with True
    (indirect) has step 2's file too."""
    d = fake.build(monkeypatch, limits=bool(getattr(request, "param", False)))
    for h in SEATED:
        fake.seat(d, HOPE, h)
    return d


@pytest.fixture
def app(db):
    return fake.client(db)


def add(app, who, *, status=200, biz=HOPE, **kw):
    as_(app, biz, who)
    body = {"business_id": biz, "label": SHIFT, "weekday": SAT, "pattern": "every_other", "starts_on": day(17), **kw}
    r = app.post("/church/schedule/commitments", json={k: v for k, v in body.items() if v is not ...})
    assert r.status_code == status, r.text
    return r.json()["saved"] if status == 200 else r.json()["detail"]


def mine(app, who, box="mine", status=200, biz=HOPE):
    as_(app, biz, who)
    r = app.get(f"/church/schedule/commitments?business_id={biz}&box={box}")
    assert r.status_code == status, r.text
    return r.json()["commitments"] if status == 200 else r.json()["detail"]


def drop(app, who, rid, status=200, biz=HOPE):
    as_(app, biz, who)
    r = app.delete(f"/church/schedule/commitments/{rid}?business_id={biz}")
    assert r.status_code == status, r.text
    return r.json()


def cal(app, who, lo=0, hi=60, biz=HOPE):
    as_(app, biz, who)
    r = app.get(f"/church/schedule/leaders?business_id={biz}&from={day(lo)}&to={day(hi)}")
    assert r.status_code == 200, r.text
    return {g["key"]: g for g in r.json()["groups"]}


def rows(db, biz=HOPE):
    return [r for r in db.t["church_away_commitments"] if r["business_id"] == biz]


def put(db, who, biz=HOPE, **kw):
    """A row as it would sit in the table (what the routes can't be made to
    leave: an old one, a thousand of them)."""
    cid = kw.pop("contact_id", None) or db.who[biz][who]
    r = {"id": db.nid("church_away_commitments"), "business_id": biz, "contact_id": cid,
         "label": SHIFT, "weekday": SAT, "pattern": "weekly", "nth": None, "starts_on": day(0), "until_on": None,
         "told_at": None, "created_at": fake.NOW.isoformat(), **kw}
    db.t["church_away_commitments"].append(r)
    return r


def church(db, biz=HOPE):
    return co.Church(c3.church(db, biz))


def D(s: str) -> date:
    return date.fromisoformat(s)


# ─── The days it falls on ─────────────────────────────────────────────

def days(row, lo, hi):
    return [d.isoformat() for d in crep.commitment_days([dict({"id": "x"}, **row)], D(lo), D(hi)).get("x", [])]


def test_every_week_falls_on_that_weekday_and_nothing_else():
    row = {"weekday": WED, "pattern": "weekly", "starts_on": "2026-11-18"}
    assert days(row, "2026-11-18", "2026-12-09") == ["2026-11-18", "2026-11-25", "2026-12-02", "2026-12-09"]
    assert days(row, "2026-11-19", "2026-11-24") == [], "no Wednesday in there"
    assert days({**row, "weekday": SUN}, "2026-11-18", "2026-12-01") == ["2026-11-22", "2026-11-29"]


def test_every_other_week_is_counted_from_its_first_day_whatever_the_window():
    row = {"weekday": SAT, "pattern": "every_other", "starts_on": "2026-12-05"}
    assert days(row, "2026-11-18", "2027-01-20") == ["2026-12-05", "2026-12-19", "2027-01-02", "2027-01-16"]
    # A window that opens on the off week still keeps the same Saturdays.
    assert days(row, "2026-12-12", "2027-01-09") == ["2026-12-19", "2027-01-02"]
    assert days(row, "2026-12-06", "2026-12-18") == [], "the Saturday in between is the off one"
    # Counted from a start long ago: the same rhythm, never re-anchored to the window.
    old = {"weekday": SAT, "pattern": "every_other", "starts_on": "2026-01-03"}
    assert days(old, "2026-11-18", "2026-12-31") == ["2026-11-21", "2026-12-05", "2026-12-19"]


def test_once_a_month_on_the_nth_and_the_fifth_is_the_last_one_of_the_month():
    for nth, want in ((1, ["2026-12-06", "2027-01-03", "2027-02-07"]), (2, ["2026-12-13", "2027-01-10", "2027-02-14"]),
                      (3, ["2026-12-20", "2027-01-17", "2027-02-21"]), (4, ["2026-12-27", "2027-01-24", "2027-02-28"])):
        assert days({"weekday": SUN, "pattern": "month_nth", "nth": nth, "starts_on": "2026-12-01"},
                    "2026-12-01", "2027-02-28") == want, nth
    last = {"weekday": SUN, "pattern": "month_nth", "nth": 5, "starts_on": "2026-11-01"}
    # November 2026 has five Sundays (the 29th is the fifth); December, January have four and five; February four.
    assert days(last, "2026-11-01", "2027-02-28") == ["2026-11-29", "2026-12-27", "2027-01-31", "2027-02-28"]
    # The last Wednesday: December 2026 has five (the 30th), February 2027 four (the 24th).
    assert days({"weekday": WED, "pattern": "month_nth", "nth": 5, "starts_on": "2026-12-01"},
                "2026-12-01", "2027-02-28") == ["2026-12-30", "2027-01-27", "2027-02-24"]
    assert crep._nth_day(2026, 12, SUN, 5) == date(2026, 12, 27) and crep._nth_day(2026, 11, SUN, 5) == date(2026, 11, 29)


def test_from_and_until_bound_the_days_and_until_is_one_of_them():
    row = {"weekday": WED, "pattern": "weekly", "starts_on": "2026-12-02", "until_on": "2026-12-16"}
    assert days(row, "2026-11-18", "2027-01-31") == ["2026-12-02", "2026-12-09", "2026-12-16"]
    month = {"weekday": SUN, "pattern": "month_nth", "nth": 1, "starts_on": "2026-12-07", "until_on": "2027-02-07"}
    assert days(month, "2026-11-01", "2027-03-31") == ["2027-01-03", "2027-02-07"], "the first Sunday after it starts"


def test_no_more_than_366_days_are_worked_out_whatever_the_window():
    row = {"weekday": WED, "pattern": "weekly", "starts_on": "2026-11-18"}
    got = days(row, "2026-11-18", "2028-11-18")
    assert got[0] == "2026-11-18" and got[-1] == "2027-11-17" and len(got) == 53
    assert D(got[-1]) - D(got[0]) < timedelta(days=crep.SPAN_DAYS)
    assert crep.commitment_days([], "2026-11-18", "2026-11-01") == {} and crep.commitment_days(None, "x", "y") == {}
    assert crep.commitment_days([{"id": "x", **row}], date(9999, 12, 1), date(9999, 12, 31)) == {"x": [
        date(9999, 12, d) for d in (1, 8, 15, 22, 29)]}, "the very end of the calendar is no error"


def test_a_row_that_cant_be_read_falls_on_no_day():
    for bad in ({"weekday": 0, "pattern": "weekly"}, {"weekday": 8, "pattern": "weekly"},
                {"weekday": SAT, "pattern": "fortnightly"}, {"weekday": SAT, "pattern": "month_nth", "nth": None},
                {"weekday": SAT, "pattern": "month_nth", "nth": 6}, {"weekday": SAT, "pattern": "weekly",
                                                                    "starts_on": "someday"},
                {"weekday": SAT, "pattern": "weekly", "until_on": "never"}, {"weekday": True, "pattern": "weekly"}):
        assert days({"starts_on": "2026-11-18", **bad}, "2026-11-18", "2027-01-31") == [], bad


def test_the_first_day_it_falls_on_is_what_is_saved_as_its_start():
    assert crep.first_day(SAT, "every_other", None, date(2026, 12, 3)) == date(2026, 12, 5)
    assert crep.first_day(SAT, "weekly", None, date(2026, 12, 5)) == date(2026, 12, 5)
    assert crep.first_day(SUN, "month_nth", 1, date(2026, 12, 7)) == date(2027, 1, 3), "December's first had passed"
    assert crep.first_day(SUN, "month_nth", 5, date(2026, 12, 1)) == date(2026, 12, 27)


def test_in_plain_words_and_never_the_label():
    today = TODAY
    assert crep.said({"weekday": SAT, "pattern": "every_other", "starts_on": "2026-12-05"}, today) == \
        "Every other Saturday, from Dec 5"
    assert crep.said({"weekday": SUN, "pattern": "month_nth", "nth": 5, "starts_on": "2026-11-01"}, today) == \
        "The last Sunday of each month"
    assert crep.said({"weekday": WED, "pattern": "weekly", "starts_on": "2026-11-18", "until_on": "2027-03-31"},
                     today) == "Every Wednesday until Mar 31, 2027"
    assert crep.said({"weekday": WED, "pattern": "weekly", "starts_on": "2026-11-11", "until_on": "2026-12-30"},
                     today) == "Every Wednesday until Dec 30"
    assert crep.said({"weekday": SUN, "pattern": "month_nth", "nth": 2, "starts_on": "2026-12-13"}, today,
                     long=True) == "The second Sunday of each month, from Sunday, December 13"
    assert SHIFT not in crep.said({"weekday": SAT, "pattern": "weekly", "starts_on": "2026-11-21", "label": SHIFT},
                                  today)


# ─── Adding one: no yes, never blocked ────────────────────────────────

def test_a_leader_adds_one_and_it_needs_no_yes(app, db):
    w = db.who[HOPE]
    got = add(app, "elena")
    assert set(got) == {"id", "contact_id", "name", "label", "weekday", "pattern", "nth", "starts_on", "until_on",
                        "said", "mine", "can_remove", "created_at"}
    assert (got["contact_id"], got["name"], got["label"]) == (w["elena"], "Elena Ruiz", SHIFT)
    assert (got["weekday"], got["pattern"], got["nth"], got["starts_on"], got["until_on"]) == (
        SAT, "every_other", None, "2026-12-05", None)
    assert got["said"] == "Every other Saturday, from Dec 5" and got["mine"] is True and got["can_remove"] is True
    saved = rows(db)
    assert len(saved) == 1 and saved[0]["told_at"] is None and saved[0]["label"] == SHIFT
    assert db.t["church_away_asks"] == [] and db.t["serve_away"] == [], "never an ask, never an away date"
    assert len(db.later) == 1, "whoever it would go to is told, once the write is back"
    assert ("/church_away_commitments", True) in db.posts, "sent redacted: a refusal never logs the label"


def test_every_other_week_is_saved_from_a_day_it_falls_on(app, db):
    got = add(app, "elena", starts_on=day(15))                    # Thursday, December 3
    assert got["starts_on"] == "2026-12-05" and rows(db)[0]["starts_on"] == "2026-12-05"
    assert db.refused == [], "the table's anchor check is met, never tripped"
    monthly = add(app, "yusuf", pattern="month_nth", nth=1, weekday=SUN, starts_on=day(19))      # Dec 7
    assert monthly["starts_on"] == "2027-01-03" and monthly["said"] == "The first Sunday of each month, from Jan 3, 2027"
    today = add(app, "amara", pattern="weekly", weekday=WED, starts_on=..., label="Bible study at the jail")
    assert today["starts_on"] == day(0) and today["said"] == "Every Wednesday", "no start named: from today"


def test_ten_a_person_and_the_eleventh_is_refused_in_plain_words(app, db):
    for n in range(crep.MAX_EACH):
        add(app, "elena", label=f"Shift {n}")
    assert add(app, "elena", label="One more", status=400) == crep.TOO_MANY
    assert len(rows(db)) == crep.MAX_EACH
    add(app, "yusuf", label="His own")                            # everyone has their own ten
    # One that has ended no longer counts.
    rows(db)[0]["until_on"] = day(-1)
    add(app, "elena", label="Now there is room")
    assert sum(1 for r in rows(db) if r["contact_id"] == db.who[HOPE]["elena"]) == crep.MAX_EACH + 1


def test_the_same_one_twice_is_one(app, db):
    a = add(app, "elena")
    b = add(app, "elena", label="  night SHIFT at the plant ")
    assert a["id"] == b["id"] and len(rows(db)) == 1 and len(db.later) == 1
    add(app, "elena", until_on=day(100))
    assert len(rows(db)) == 2, "with an end, it is another one"


@pytest.mark.parametrize("body,said", [
    ({"label": ""}, crep.LABEL), ({"label": "   "}, crep.LABEL), ({"label": "x" * 81}, crep.LABEL),
    ({"weekday": 0}, crep.BAD_WEEKDAY), ({"weekday": 8}, crep.BAD_WEEKDAY), ({"weekday": True}, crep.BAD_WEEKDAY),
    ({"weekday": "Saturday"}, crep.BAD_WEEKDAY), ({"weekday": "²"}, crep.BAD_WEEKDAY),
    ({"weekday": "①"}, crep.BAD_WEEKDAY), ({"weekday": "6" * 5000}, crep.BAD_WEEKDAY),
    ({"pattern": "month_nth", "nth": "³"}, crep.BAD_NTH), ({"pattern": "fortnightly"}, crep.BAD_PATTERN),
    ({"pattern": "month_nth"}, crep.BAD_NTH), ({"pattern": "month_nth", "nth": 6}, crep.BAD_NTH),
    ({"starts_on": "2028-01-01"}, crep.BAD_START), ({"starts_on": "2025-11-01"}, crep.BAD_START),
    ({"starts_on": "soon"}, crep.BAD_START), ({"until_on": day(-1), "starts_on": day(-20)}, crep.BAD_UNTIL),
    ({"until_on": day(10)}, crep.BAD_UNTIL), ({"until_on": day(18), "starts_on": day(18)}, crep.NONE_BETWEEN)])
def test_what_cant_be_saved_is_said_plainly_and_nothing_is_written(app, db, body, said):
    assert add(app, "elena", status=400, **body) == said
    assert rows(db) == [] and db.later == []


def test_a_failed_read_or_write_is_a_503_with_nothing_saved(app, db):
    db.fail = {"post": "/church_away_commitments"}
    assert add(app, "elena", status=503) == cs.UNSAVED
    db.fail = {"get": "/church_away_commitments"}
    assert add(app, "elena", status=503) == cs.UNREAD, "how many they have couldn't be read: nothing saved"
    mine(app, "elena", status=503)
    as_(app, HOPE, "amara")
    assert app.get(f"/church/schedule/leaders?business_id={HOPE}").status_code == 503, "never an empty calendar"
    db.fail = {}
    assert rows(db) == [] and db.later == []


# ─── Who adds, who reads the list, who takes one off ──────────────────

def test_only_someone_on_the_schedule_adds_one_and_only_for_their_own_person(app, db):
    w = db.who[HOPE]
    fake.seat(db, HOPE, "hugo")                                   # one of the church's people, on no schedule
    assert add(app, "hugo", status=403) == cs.NOT_ON
    nobody = "3e000000-0000-4000-8000-999999999999"               # a login matched to nobody here
    db.t["business_users"].append({"business_id": HOPE, "user_id": nobody, "role": "member", "status": "active",
                                   "invited_email": "nobody@example.invalid", "lane": None, "areas": None,
                                   "contact_id": None, "name": "Pat"})
    db.who[HOPE]["pat@"] = nobody
    assert add(app, "pat", status=409) == cs.NO_PERSON
    # `for`, as an ask's: the owner and whoever oversees the office, for someone on the schedule.
    got = add(app, "owner", **{"for": f"person:{w['esther']}"})
    assert got["contact_id"] == w["esther"] and got["mine"] is False and got["label"] == SHIFT
    assert add(app, "owen", **{"for": f"person:{w['ezra']}"})["contact_id"] == w["ezra"]
    for who in ("tessa", "elena", "sunny"):                       # an Admin, a leader, the volunteers' keeper
        assert add(app, who, status=403, **{"for": f"person:{w['ezra']}"}) == cs.NOT_FOR, who
    assert add(app, "owner", status=400, **{"for": f"person:{w['hugo']}"}) == cs.THEY_NOT_ON
    assert add(app, "owner", status=400, **{"for": f"person:{c3.pid(2, 1)}"}) == cs.NOT_PERSON, "another church's"
    assert add(app, "owner", status=400, **{"for": f"login:{w['owen@']}"})
    assert {r["contact_id"] for r in rows(db)} == {w["esther"], w["ezra"]}


def test_their_own_list_and_every_one_for_the_owner_and_whoever_oversees_the_office(app, db):
    w = db.who[HOPE]
    add(app, "elena")
    add(app, "yusuf", label="Coaching the team", weekday=WED, pattern="weekly")
    put(db, "esther", until_on=day(-1))                           # ended: no longer on any list
    assert [(c["name"], c["label"]) for c in mine(app, "elena")] == [("Elena Ruiz", SHIFT)]
    assert [c["label"] for c in mine(app, "yusuf")] == ["Coaching the team"]
    assert mine(app, "amara") == [], "nothing of her own"
    for who in ("owner", "owen"):
        got = mine(app, who, "all")
        assert [(c["name"], c["label"], c["mine"], c["can_remove"]) for c in got] == [
            ("Elena Ruiz", SHIFT, False, True), ("Yusuf Grant", "Coaching the team", False, True)], who
    for who in ("tessa", "elena", "amara", "sunny"):
        assert mine(app, who, "all", status=403) == cs.NOT_ALL, who
    mine(app, "elena", "everyone", status=400)
    assert all(c["contact_id"] != w["esther"] for c in mine(app, "owner", "all"))


def test_their_own_is_theirs_to_take_off_and_the_owner_and_the_office_overseer_take_off_anyones(app, db):
    a = add(app, "elena")
    b = add(app, "elena", label="Second", weekday=WED, pattern="weekly")
    c = add(app, "yusuf", label="His")
    for who in ("yusuf", "amara", "tessa", "sunny"):              # another leader, the one over her, an Admin
        assert drop(app, who, a["id"], status=403)["detail"] == crep.NOT_YOURS, who
    assert len(rows(db)) == 3
    got = drop(app, "elena", a["id"])["removed"]
    assert got["id"] == a["id"] and got["label"] == SHIFT and got["can_remove"] is False
    assert drop(app, "owner", b["id"])["removed"]["id"] == b["id"]
    assert drop(app, "owen", c["id"])["removed"]["id"] == c["id"]
    assert rows(db) == [] and len(db.later) == 3, "taking one off tells nobody"
    assert drop(app, "elena", a["id"], status=404)["detail"] == crep.GONE
    drop(app, "elena", "not-an-id", status=400)
    theirs = put(db, "elena", biz=c3.GRACE, contact_id=c3.pid(2, 1))
    assert drop(app, "owner", theirs["id"], status=404)["detail"] == crep.GONE, "another church's is not found here"
    assert theirs in db.t["church_away_commitments"]


def test_a_removal_that_fails_is_a_503_and_it_stays(app, db, monkeypatch):
    a = add(app, "elena")
    db.fail = {"delete": "/church_away_commitments"}
    drop(app, "elena", a["id"], status=503)
    assert len(rows(db)) == 1


# ─── The label is as private as a reason ──────────────────────────────

READERS = ("elena", "amara", "owner", "owen", "yusuf", "esther", "tessa", "sunny", "olive", "kira")


def test_the_label_is_read_by_the_person_the_owner_and_the_office_overseer_only(app, db):
    """Elena asks with a private reason and Amara says yes, so the away date
    is on everyone's calendar; she also has a thing that repeats. The reason
    is read by Amara, who answered it; the label is not (nothing about it
    waits on anyone's yes): only Elena, the owner and whoever oversees the
    office read it (the #1990 review)."""
    w = db.who[HOPE]
    as_(app, HOPE, "elena")
    asked = app.post("/church/schedule/asks", json={"business_id": HOPE, "starts_on": day(30), "ends_on": day(31),
                                                    "kind": "time_off", "reason": SECRET}).json()["saved"]
    as_(app, HOPE, "amara")
    assert app.post(f"/church/schedule/asks/{asked['id']}/answer",
                    json={"business_id": HOPE, "yes": True}).status_code == 200
    add(app, "elena")
    seen = {}
    for who in READERS:
        g = cal(app, who)["leaders"]
        away = next(a for a in g["away"] if a["contact_id"] == w["elena"])
        standing = [s for s in g["standing"] if s["contact_id"] == w["elena"]]
        assert [s["day"] for s in standing] == ["2026-12-05", "2026-12-19", "2027-01-02", "2027-01-16"], who
        reads = "label" in standing[0]
        assert all(("label" in s) == reads for s in standing), who
        for s in standing:
            assert set(s) == ({"contact_id", "name", "day", "label"} if reads else {"contact_id", "name", "day"})
            assert s.get("label", SHIFT) == SHIFT and s["name"] == "Elena Ruiz"
        seen[who] = (reads, away.get("reason") == SECRET)
    assert {w for w, (yes, _r) in seen.items() if yes} == {"elena", "owner", "owen"}
    assert seen["amara"] == (False, True), "Amara reads the reason she answered, never the label"
    # And nowhere else on the calendar for those who don't read it.
    for who in ("yusuf", "tessa", "sunny"):
        as_(app, HOPE, who)
        assert SHIFT not in app.get(f"/church/schedule/leaders?business_id={HOPE}").text, who


def test_nobody_over_them_reads_it_whoever_they_answer_to(app, db):
    """Elena's asks go to Amara; once she answers to Abel on the map, they go
    to Abel. Neither reads what her thing that repeats is, before or after."""
    w = db.who[HOPE]
    fake.seat(db, HOPE, "abel")
    add(app, "elena")
    assert "label" not in cal(app, "amara")["leaders"]["standing"][0]
    for r in db.t["church_leader_roles"]:
        if r["business_id"] == HOPE and r["contact_id"] == w["elena"]:
            r["answers_to_contact_id"] = w["abel"]
    assert cs.goes_to(church(db), w["elena"])["id"] == w["abel"], "she answers to Abel now"
    for who in ("abel", "amara"):
        assert "label" not in cal(app, who)["leaders"]["standing"][0], who
    assert cal(app, "owner")["leaders"]["standing"][0]["label"] == SHIFT


@pytest.mark.parametrize("who", ["yusuf", "amara", "owner"])
def test_the_calendar_costs_the_same_however_many_have_one(app, db, who):
    """Who reads a label is worked out with no read, so the calendar makes
    the same reads with one person's thing that repeats as with twenty (it
    once worked out who an ask would go to for each: about four reads a
    person, the #1990 review)."""
    people = sorted(cs.roster(church(db)).people())[:20]
    assert len(people) == 20

    def reads_with(n):
        db.t["church_away_commitments"][:] = [
            {"id": f"7a000000-0000-4000-8000-{i:012d}", "business_id": HOPE, "contact_id": cid, "label": SHIFT,
             "weekday": SAT, "pattern": "weekly", "nth": None, "starts_on": day(0), "until_on": None,
             "told_at": day(0), "created_at": day(0)} for i, cid in enumerate(people[:n])]
        as_(app, HOPE, who)
        db.reads.clear()
        got = cal(app, who, 0, 30)
        assert sum(len(g["standing"]) for g in got.values() if isinstance(g, dict) and "standing" in g) >= n * 4
        return len(db.reads)
    reads_with(1)                       # what is kept a minute is read on the first call only
    assert reads_with(1) == reads_with(20), who


def test_the_calendar_lists_each_day_in_its_window_under_their_group(app, db):
    w = db.who[HOPE]
    add(app, "elena", pattern="weekly", weekday=WED, starts_on=..., until_on=day(21))
    add(app, "owner", **{"for": f"person:{w['tessa']}"}, label="Payroll run", pattern="month_nth", nth=5,
        weekday=SUN, starts_on=...)
    g = cal(app, "owner", 0, 45)
    assert [s["day"] for s in g["leaders"]["standing"]] == ["2026-11-18", "2026-11-25", "2026-12-02", "2026-12-09"]
    assert [(s["name"], s["day"], s["label"]) for s in g["office"]["standing"]] == [
        ("Tessa Hale", "2026-11-29", "Payroll run"), ("Tessa Hale", "2026-12-27", "Payroll run")]
    assert [s["day"] for s in cal(app, "owner", 20, 30)["leaders"]["standing"]] == ["2026-12-09"]


def test_someone_taken_off_the_schedule_is_not_on_the_calendar(app, db):
    w = db.who[HOPE]
    add(app, "elena")
    as_(app, HOPE, "owner")
    assert app.put("/church/schedule/people", json={"business_id": HOPE, "contact_id": w["elena"],
                                                     "listed": "remove"}).status_code == 200
    assert cal(app, "owner")["leaders"]["standing"] == [], "the calendar lists the people on it today"
    assert [c["contact_id"] for c in mine(app, "owner", "all")] == [w["elena"]], "the office still sees it"
    assert add(app, "elena", status=403, label="Another") == cs.NOT_ON, "nor can she add one"
    assert [c["label"] for c in mine(app, "elena")] == [SHIFT], "her own, still hers to see"


# ─── Never counted toward a limit, never a pair ───────────────────────

@pytest.mark.parametrize("db", [True], indirect=True)
def test_never_counted_toward_a_limit_or_a_pair(app, db):
    """The leaders may have one away at once; Elena has a thing that repeats
    every Sunday, and she and Yusuf are a pair. Yusuf's ask for a Sunday is
    neither full nor overlapping: a commitment is never an away date."""
    w = db.who[HOPE]
    as_(app, HOPE, "owner")
    assert app.put("/church/schedule/limits", json={"business_id": HOPE, "group": "leaders",
                                                     "at_most": 1}).status_code == 200
    assert app.post("/church/schedule/pairs", json={"business_id": HOPE, "a_contact_id": w["elena"],
                                                     "b_contact_id": w["yusuf"]}).status_code == 200
    add(app, "elena", pattern="weekly", weekday=SUN)
    as_(app, HOPE, "owner")
    sundays = app.get(f"/church/schedule/days?business_id={HOPE}&from={day(30)}&to={day(40)}").json()["days"]
    assert sundays and all(d["leaders"]["away"] == 0 and not d["leaders"]["full"] for d in sundays)
    as_(app, HOPE, "yusuf")
    r = app.post("/church/schedule/asks", json={"business_id": HOPE, "starts_on": day(32), "ends_on": day(32),
                                                "kind": "time_off"})
    assert r.status_code == 200 and r.json()["saved"]["flags"] == [], "not full, not a pair, not sent up"


# ─── The switch, the tables, other churches ───────────────────────────

@pytest.mark.parametrize("how", ["off", "another church on owner", "before its tables"])
def test_closed_or_before_its_tables_every_route_is_a_404_and_nothing_is_read(app, db, monkeypatch, how):
    a = add(app, "elena")
    if how == "off":
        monkeypatch.setenv("CHURCH_SCHEDULE", "off")
    elif how == "another church on owner":
        monkeypatch.setenv("CHURCH_SCHEDULE", "owner")             # the platform owner's own church, and login, only
    else:
        monkeypatch.setattr(cs, "_FORCE", False)
    db.reads.clear()
    for who in ("elena", "owner"):
        assert add(app, who, status=404, label="Another") in ("Not Found",)
        mine(app, who, status=404)
        drop(app, who, a["id"], status=404)
    assert not [r for r in db.reads if r.startswith("/church_away_commitments")], how
    assert len(rows(db)) == 1
    assert cs.holds(HOPE, date(2026, 12, 1), date(2026, 12, 31)) == []
    assert not [r for r in db.reads if r.startswith("/church_away_commitments")], "nor does the scheduler"


def test_another_churchs_are_never_read_or_held_here(app, db):
    put(db, "elena", biz=c3.GRACE, contact_id=c3.pid(2, 1))
    add(app, "elena")
    held = cs.holds(HOPE, date(2026, 12, 1), date(2026, 12, 31))
    assert {h["contact_id"] for h in held} == {db.who[HOPE]["elena"]}
    assert [c["contact_id"] for c in mine(app, "owner", "all")] == [db.who[HOPE]["elena"]]
    db.reads.clear()
    cal(app, "owner")
    reads = [r for r in db.reads if r.startswith("/church_away_commitments")]
    assert reads and all(f"business_id=eq.{HOPE}" in r for r in reads)


def test_every_read_is_by_church_bounded_and_paged(app, db):
    people = sorted(cs.roster(church(db)).people())
    for n in range(1003):
        put(db, "elena", contact_id=people[n % len(people)], id=f"7a000000-0000-4000-8000-{n:012d}",
            weekday=1 + n % 7)
    db.reads.clear()
    got = mine(app, "owner", "all")
    assert len(got) == 1003, "every one, never the first 1,000"
    reads = [r for r in db.reads if r.startswith("/church_away_commitments")]
    assert len(reads) >= 2 and all("limit=1000" in r and "order=id.asc" in r for r in reads)
    g = cal(app, "owner", 0, 6)
    assert sum(len(x["standing"]) for x in g.values()) == 1003, "each one falls once in a week"


# ─── The rule code reads the church's data, never a title ─────────────

def test_no_title_word_or_role_key_decides_anything_here():
    src = inspect.getsource(crep)
    code = re.sub(r'""".*?"""', "", src, flags=re.S)
    code = re.sub(r"#.*", "", code)
    assert not ROLE_KEYS.search(code), ROLE_KEYS.search(code)
    assert not TITLE_WORDS.search(code), TITLE_WORDS.search(code)
    for words in (crep.LABEL, crep.BAD_WEEKDAY, crep.BAD_PATTERN, crep.BAD_NTH, crep.BAD_START, crep.BAD_UNTIL,
                  crep.NONE_BETWEEN, crep.TOO_MANY, crep.NOT_YOURS, crep.GONE):
        assert not TITLE_WORDS.search(words) and not re.search(r"\b[a-z]+_[a-z_]+\b", words), words


def test_held_days_and_the_sweep_never_select_the_label():
    import church_schedule_tell as tell
    assert "label" not in crep.DAYS_FIELDS.split(",") and "label" not in tell.REPEAT_FIELDS.split(",")
    assert tell._bare_repeat({"id": "a", "label": SHIFT, "weekday": SAT}) == {"id": "a", "weekday": SAT}
