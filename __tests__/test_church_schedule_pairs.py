"""The leaders schedule, step 2: people who can't be away together
(church_schedule_limits.pairs / add_pair / drop_pair, the `pair` flag, and
the routes GET / POST / DELETE /church/schedule/pairs; docs/CHURCH_SCHEDULE.md,
PR S2-4).

At New Hope (church_three: a made-up church of 500, every name in it made
up), on church_schedule_fake's tables with step 2's file applied
(build(limits=True)), through the real engine and the office routes. Pins:

  * pairs are read and changed by the owner and whoever oversees the office
    ONLY: an Admin, a Manager who doesn't oversee the office, a department's
    leader and a member-app session are all refused, for reading too
  * a pair is two different people, both this church's own (another
    church's id is refused) and both on the leaders schedule, saved once
    with the smaller id first; the same two again are a 409
  * the second ask of a pair goes up (an away date of the other, whatever
    made it, or an ask of theirs still waiting, on any of the same days),
    never refused, to whoever may give the exception
  * the recheck at the yes catches a pair that arose after the ask; the
    other's waiting ask made AFTER this one never sends this one up
  * an exception over `pair` lands only when `pair` was shown
  * "can't make it" and the owner's own are never looked at for a pair, and
    count for the other who asks next
  * a pair is never named to the one asking, never on the calendar for
    anyone who doesn't read the reason, and the other's waiting ask is
    never shown to anyone who may not already read it
  * a pair with someone off the schedule does nothing, and the owner sees why
  * the nearest open days never give the other's days away
  * with no pairs, an ask makes ONE read more (its asker's pairs) and
    nothing else changes; a database with step 1's file alone reads nothing
    of pairs
  * every value in an address is quoted; 1,003 pairs are listed whole
  * the fake refuses a pair as the SQL does
"""
from __future__ import annotations

import inspect
import itertools
import json
import os
import re
import sys
import uuid
from datetime import date

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_over as co  # noqa: E402
import church_schedule as cs  # noqa: E402
import church_schedule_fake as fake  # noqa: E402
import church_schedule_limits as csl  # noqa: E402
import church_three as c3  # noqa: E402
import sb_clients  # noqa: E402
from church_schedule_fake import NOW, as_, day  # noqa: E402
from fastapi import HTTPException  # noqa: E402

HOPE = c3.NEW_HOPE                       # a made-up church of 500: every name in it is made up
GRACE = c3.GRACE
SECRET = "Surgery for my mother that week"
SUN = day(32)                            # Sunday 20 December 2026; an ask for day(30)..day(37) holds it
TUE = day(34)                            # Tuesday 22 December: no service, and still one of the same days
SEATED = ("elena", "yusuf", "wren", "kara", "celia", "amara", "abel", "esther")   # leaders with a Member login


@pytest.fixture
def db(monkeypatch):
    d = fake.build(monkeypatch, limits=True)
    for h in SEATED:
        fake.seat(d, HOPE, h)
    for t in ("worship_services", "serve_teams", "serve_assignments"):
        d.t[t] = []
    return d


@pytest.fixture
def app(db):
    return fake.client(db)


# ─── helpers ──────────────────────────────────────────────────────────

def church(db, biz=HOPE):
    return co.Church(c3.church(db, biz))


def cid(db, handle, biz=HOPE):
    return db.who[biz][handle]


def person(db, handle, biz=HOPE):
    return co.who(co.PERSON, cid(db, handle, biz))


def login(db, handle, biz=HOPE):
    return co.who(co.LOGIN, fake.uid(db, biz, handle))


def asks(db, biz=HOPE):
    return [r for r in db.t["church_away_asks"] if r["business_id"] == biz]


def row(db, ask_id):
    return next(r for r in db.t["church_away_asks"] if r["id"] == ask_id)


def away(db, handle, start=SUN, end=None, biz=HOPE):
    """An away date as it sits in serve_away: a fact, however it got there."""
    r = {"id": str(uuid.uuid4()), "business_id": biz, "contact_id": cid(db, handle, biz), "starts_on": start,
         "ends_on": end or start, "note": "", "ask_id": None, "kind": None, "created_at": NOW.isoformat()}
    db.t["serve_away"].append(r)
    return r


def get(app, who, path, biz=HOPE, **q):
    as_(app, biz, who)
    return app.get(f"/church/schedule/{path}", params={"business_id": biz, **q})


def ask(app, who, biz=HOPE, status=200, **kw):
    as_(app, biz, who)
    r = app.post("/church/schedule/asks", json={"business_id": biz, "starts_on": day(30), "ends_on": day(37),
                                                 "kind": "time_off", **kw})
    assert r.status_code == status, r.text
    return r.json().get("saved") if status == 200 else r.json()


def answer(app, who, ask_id, yes=True, biz=HOPE, status=200, shown="what the ask shows", **kw):
    """An answer through the office route, posting with its yes what a
    screen showed (the ask's own flags, by default; None: nothing said)."""
    as_(app, biz, who)
    if shown == "what the ask shows":
        shown = [f for f in row(app.db, ask_id).get("flags") or [] if f in cs.UP_FLAGS]
    if shown is not None:
        kw["shown"] = shown
    r = app.post(f"/church/schedule/asks/{ask_id}/answer", json={"business_id": biz, "yes": yes, **kw})
    assert r.status_code == status, r.text
    return r.json().get("saved") if status == 200 else r.json()["detail"]


def pair(app, a, b, who="owner", note=None, status=200, biz=HOPE):
    """Pair two of the church's people (handles, or raw values)."""
    db = app.db
    as_(app, biz, who)
    body = {"business_id": biz, "a_contact_id": db.who[biz].get(a, a), "b_contact_id": db.who[biz].get(b, b)}
    if note is not None:
        body["note"] = note
    r = app.post("/church/schedule/pairs", json=body)
    assert r.status_code == status, r.text
    return r.json().get("saved") if status == 200 else r.json()["detail"]


def drop(app, pair_id, who="owner", status=200, biz=HOPE):
    as_(app, biz, who)
    r = app.delete(f"/church/schedule/pairs/{pair_id}", params={"business_id": biz})
    assert r.status_code == status, r.text
    return r.json().get("removed") if status == 200 else r.json()["detail"]


def raw_pair(db, a, b, biz=HOPE):
    """A pair as it sits in the table (the smaller id first)."""
    x, y = sorted((cid(db, a, biz), cid(db, b, biz)))
    r = {"id": str(uuid.uuid4()), "business_id": biz, "a_contact_id": x, "b_contact_id": y, "note": None,
         "created_by": c3.NH_OWNER, "created_at": NOW.isoformat()}
    db.t["church_away_pairs"].append(r)
    return r


def pair_reads(db):
    return [p for p in db.reads if p.startswith("/church_away_pairs")]


def full(app, db, on=SUN):
    """A Sunday with as many leaders away as may be: two, with the number at two."""
    as_(app, HOPE, "owner")
    assert app.put("/church/schedule/limits", json={"business_id": HOPE, "group": "leaders",
                                                    "at_most": 2}).status_code == 200
    away(db, "wren", on)
    away(db, "kara", on)


# ─── Who reads and changes pairs ──────────────────────────────────────

def test_only_the_owner_and_whoever_oversees_the_office_read_or_change_pairs(app, db):
    saved = pair(app, "yusuf", "esther", note="Both carry the youth trip")
    assert saved["a"]["name"] in ("Yusuf Grant", "Esther Moss") and saved["note"] == "Both carry the youth trip"
    assert saved["in_force"] is True and {saved["a"]["name"], saved["b"]["name"]} == {"Yusuf Grant", "Esther Moss"}
    other = pair(app, "elena", "celia", who="owen")
    assert len(db.t["church_away_pairs"]) == 2
    before = [dict(r) for r in db.t["church_away_pairs"]]
    # An Admin, a Manager who doesn't oversee the office, a department's leader on a Member seat, one of the pair.
    for who in ("tessa", "olive", "wren", "yusuf"):
        r = get(app, who, "pairs")
        assert r.status_code == 403 and r.json()["detail"] == csl.NOT_PAIRS, who
        assert pair(app, "abel", "asher", who=who, status=403) == csl.NOT_PAIRS, who
        assert drop(app, other["id"], who=who, status=403) == csl.NOT_PAIRS, who
    assert db.t["church_away_pairs"] == before, "nothing changed"
    # A member-app session is a person, whoever it is: never the owner's or the overseer's standing.
    ch = church(db)
    for handle in ("nathan", "owen", "yusuf"):
        for fn, args in ((csl.view_pairs, ()), (csl.add_pair, (cid(db, "abel"), cid(db, "asher"))),
                         (csl.drop_pair, (other["id"],))):
            with pytest.raises(HTTPException) as e:
                fn(ch, person(db, handle), *args)
            assert e.value.status_code == 403 and e.value.detail == csl.NOT_PAIRS, (handle, fn.__name__)
    assert db.t["church_away_pairs"] == before
    for who in ("owner", "owen"):
        got = get(app, who, "pairs").json()
        assert got["can_change"] is True and len(got["pairs"]) == 2, who
        assert {frozenset((p["a"]["name"], p["b"]["name"])) for p in got["pairs"]} == {
            frozenset(("Celia Ward", "Elena Ruiz")), frozenset(("Esther Moss", "Yusuf Grant"))}, "by name"
        assert all(p["a"]["contact_id"] < p["b"]["contact_id"] for p in got["pairs"])
        assert [p["note"] for p in got["pairs"] if "Esther Moss" in (p["a"]["name"], p["b"]["name"])] == [
            "Both carry the youth trip"]
    assert drop(app, other["id"], who="owen")["id"] == other["id"]
    assert [r["id"] for r in db.t["church_away_pairs"]] == [saved["id"]]


def test_a_pair_is_two_different_people_of_this_church_on_the_schedule_saved_once_the_smaller_id_first(
        app, db, monkeypatch):
    assert pair(app, "yusuf", "yusuf", status=400) == csl.PAIR_SELF
    assert pair(app, "yusuf", "nobody", status=400) == "That person isn't valid"
    assert pair(app, "yusuf", cid(db, "yvette", GRACE), status=400) == cs.NOT_PERSON, "another church's person"
    assert pair(app, "hugo", "yusuf", status=400) == csl.PAIR_OFF, "Hugo isn't on the leaders schedule"
    assert pair(app, "yusuf", "esther", note="x" * 141, status=400) == csl.PAIR_NOTE
    assert db.t["church_away_pairs"] == [] and db.refused == [], "each refused before the database was asked"
    hi, lo = sorted((cid(db, "yusuf"), cid(db, "esther")), reverse=True)
    saved = pair(app, hi, lo, note="x" * 140)
    [r] = db.t["church_away_pairs"]
    assert (r["a_contact_id"], r["b_contact_id"]) == (lo, hi) and r["a_contact_id"] < r["b_contact_id"]
    assert (saved["a"]["contact_id"], saved["b"]["contact_id"]) == (lo, hi)
    assert r["created_by"] == c3.NH_OWNER and r["note"] == "x" * 140
    assert ("/church_away_pairs", True) in db.posts, "sent redacted: the note is private"
    assert pair(app, lo, hi, status=409) == csl.PAIR_TWICE
    assert pair(app, hi, lo, who="owen", status=409) == csl.PAIR_TWICE, "either way round"
    # Two presses at once: neither read saw the other, and the table keeps one.
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **k: [] if "a_contact_id=eq." in path else real(path, **k))
    monkeypatch.setattr(sb_clients, "last_error", lambda: {"status": 409, "code": "23505", "message": "duplicate key"})
    assert pair(app, lo, hi, status=409) == csl.PAIR_TWICE
    assert db.refused == ["unique: church_away_pairs_one"] and len(db.t["church_away_pairs"]) == 1
    monkeypatch.setattr(sb_clients, "sb_get_as_service", real)
    monkeypatch.setattr(sb_clients, "last_error", lambda: None)
    db.fail = {"post": "/church_away_pairs"}
    assert pair(app, "elena", "celia", status=503) == cs.UNSAVED
    db.fail = {"get": "/church_away_pairs"}
    assert pair(app, "elena", "celia", status=503) == cs.UNREAD
    assert len(db.t["church_away_pairs"]) == 1


def test_another_churchs_pair_is_not_found_not_removed_and_never_counted(app, db):
    saved = pair(app, "yusuf", "esther")
    assert get(app, "owner", "pairs", biz=GRACE).json()["pairs"] == []
    assert drop(app, saved["id"], biz=GRACE, status=404) == csl.NO_PAIR
    assert len(db.t["church_away_pairs"]) == 1
    # New Hope's people named at Grace: not Grace's.
    assert pair(app, cid(db, "yusuf"), cid(db, "esther"), biz=GRACE, status=400) == cs.NOT_PERSON
    away(db, "esther")
    assert ask(app, "yusuf")["flags"] == ["pair"]
    got = cs.ask(church(db, GRACE), login(db, "owner", GRACE), {
        "starts_on": day(30), "ends_on": day(37), "kind": "time_off", "for": f"person:{cid(db, 'yvette', GRACE)}"})
    assert got["flags"] == [], "New Hope's pair is nothing to Grace"


def test_before_step_twos_file_the_pairs_routes_are_a_404_and_nothing_of_pairs_is_read(monkeypatch):
    bare = fake.build(monkeypatch)
    for h in SEATED:
        fake.seat(bare, HOPE, h)
    app = fake.client(bare)
    assert get(app, "owner", "pairs").status_code == 404
    as_(app, HOPE, "owner")
    assert app.post("/church/schedule/pairs", json={"business_id": HOPE, "a_contact_id": cid(bare, "yusuf"),
                                                    "b_contact_id": cid(bare, "esther")}).status_code == 404
    assert app.delete(f"/church/schedule/pairs/{uuid.uuid4()}", params={"business_id": HOPE}).status_code == 404
    away(bare, "esther")
    assert ask(app, "yusuf")["flags"] == []
    assert pair_reads(bare) == [] and "absent: step 2" not in bare.refused


# ─── The second ask of a pair goes up ─────────────────────────────────

def test_the_second_ask_of_a_pair_goes_up_never_refused_and_the_first_does_not(app, db):
    pair(app, "yusuf", "kara")
    first = ask(app, "yusuf", reason=SECRET)
    assert first["flags"] == [] and first["to"]["name"] == "Amara Stone", "nothing of Kara's yet"
    second = ask(app, "kara")
    assert second["state"] == "asked" and second["flags"] == ["pair"], "her days overlap his waiting ask"
    assert second["to"] == {"kind": "login", "id": fake.uid(db, HOPE, "owen"), "name": "Owen Diaz"}, "up"
    # An away date of the other, on a day with no service: still one of the same days.
    pair(app, "celia", "esther")
    away(db, "esther", TUE)
    assert ask(app, "celia")["flags"] == ["pair"]
    # Days that miss it.
    pair(app, "abel", "asher")
    away(db, "asher", day(40))
    assert ask(app, "abel")["flags"] == []


def test_a_guarded_persons_ask_that_overlaps_their_pair_goes_to_the_owner_alone(app, db):
    pair(app, "elena", "esther")
    away(db, "esther")
    got = ask(app, "elena")
    assert got["flags"] == ["pair"] and got["to"]["id"] == c3.NH_OWNER
    assert answer(app, "owen", got["id"], status=403) == cs.NOT_TO_YOU
    assert answer(app, "amara", got["id"], status=403) == cs.NOT_TO_YOU, "the one over her no longer answers it"
    said = answer(app, "owner", got["id"])
    assert said["state"] == "yes" and said["excepted"] == ["pair"]
    [call] = db.rpcs
    assert call["p_excepted"] == ["pair"], "saved as the exception, in one transaction"


def test_a_pair_and_a_full_day_are_one_ask_with_both_flags(app, db):
    full(app, db)
    pair(app, "yusuf", "kara")                  # Kara is one of the two away that Sunday
    got = ask(app, "yusuf")
    assert got["flags"] == ["over_limit", "pair"]
    assert answer(app, "owen", got["id"])["excepted"] == ["over_limit", "pair"], "each flag once, in order"


# ─── The recheck at the yes ───────────────────────────────────────────

def test_a_pair_that_arose_after_the_ask_is_caught_at_the_yes(app, db):
    got = ask(app, "yusuf", reason=SECRET)
    assert got["flags"] == [] and got["to"]["name"] == "Amara Stone"
    pair(app, "yusuf", "kara")                  # paired after he asked, and she is away that week
    away(db, "kara", TUE)
    db.later.clear()
    said = answer(app, "amara", got["id"], status=409)
    assert said == cs.WENT_UP_NEEDS.format(name="Owen Diaz")
    assert "pair" not in said and "Kara" not in said and "away with" not in said, "never said to her"
    r = row(db, got["id"])
    assert (r["state"], r["flags"], r["to_user_id"], r["to_contact_id"], r["told_at"]) == (
        "asked", ["pair"], fake.uid(db, HOPE, "owen"), None, None)
    assert len(db.later) == 1 and db.rpcs == [], "nothing decided; whoever it went up to is told"
    assert answer(app, "owen", got["id"])["excepted"] == ["pair"]


def test_the_others_cant_make_it_after_the_ask_is_caught_at_the_yes_and_marked_for_the_owner(app, db):
    pair(app, "amara", "abel")
    mine = ask(app, "amara", starts_on=day(1), ends_on=day(2))
    assert mine["flags"] == ["short_notice"] and mine["to"]["id"] == c3.NH_OWNER
    cant = ask(app, "abel", kind="cant", starts_on=day(1), ends_on=day(1))
    assert cant["state"] == "yes" and "pair" not in cant["flags"], "can't make it is never looked at"
    said = answer(app, "owner", mine["id"], status=409)
    assert said == cs.YOURS_NEEDS, "his to give: marked, and his next yes is the exception"
    assert row(db, mine["id"])["flags"] == ["short_notice", "pair"] and row(db, mine["id"])["to_user_id"] == c3.NH_OWNER
    assert answer(app, "owner", mine["id"])["excepted"] == ["pair"]


def test_a_later_waiting_ask_of_the_other_never_sends_the_first_one_up(app, db):
    """First asked, first answered: his yes lands as a plain yes; hers is the
    one that needs the exception."""
    pair(app, "yusuf", "kara")
    his = ask(app, "yusuf")
    hers = ask(app, "kara")
    assert (his["flags"], hers["flags"]) == ([], ["pair"])
    said = answer(app, "amara", his["id"])
    assert said["state"] == "yes" and said["excepted"] == [] and len(db.rpcs) == 1
    assert sorted(db.rpcs[0]) == ["p_ask_id", "p_business_id", "p_by_contact", "p_by_user", "p_note", "p_state"]
    # Hers, at the yes: his time away is a fact now, and still in the way.
    assert answer(app, "owen", hers["id"])["excepted"] == ["pair"]


def test_an_exception_over_a_pair_lands_only_when_pair_was_shown(app, db):
    pair(app, "yusuf", "kara")
    away(db, "yusuf")
    got = ask(app, "kara")
    assert got["flags"] == ["pair"]
    for shown in (None, [], ["over_limit"], ["protected_day", "serving"]):
        assert answer(app, "owen", got["id"], shown=shown, status=409) == cs.YOURS_NEEDS, shown
    assert row(db, got["id"])["state"] == "asked" and db.rpcs == [], "nothing written"
    said = answer(app, "owen", got["id"], shown=["pair"])
    assert said["excepted"] == ["pair"] and db.rpcs[0]["p_excepted"] == ["pair"]


def test_a_pair_dropped_before_the_yes_makes_it_a_plain_yes(app, db):
    saved = pair(app, "yusuf", "kara")
    away(db, "yusuf")
    got = ask(app, "kara")
    drop(app, saved["id"])
    said = answer(app, "owen", got["id"])
    assert said["state"] == "yes" and said["excepted"] == [] and row(db, got["id"])["flags"] == ["pair"]


# ─── Never looked at, and still counted ───────────────────────────────

def test_cant_make_it_and_the_owners_own_are_never_looked_at_for_a_pair_and_count_for_the_other(app, db):
    pair(app, "nathan", "abel")                 # the one person the church's owner is, and someone
    pair(app, "yusuf", "kara")
    away(db, "abel")
    away(db, "kara", day(1))
    db.reads.clear()
    own = cs.ask(church(db), login(db, "owner"), {"starts_on": day(30), "ends_on": day(37), "kind": "time_off",
                                                   "for": f"person:{cid(db, 'nathan')}"})
    cant = ask(app, "yusuf", kind="cant", starts_on=day(1), ends_on=day(1))
    assert own["state"] == "yes" and own["flags"] == [] and cant["state"] == "yes" and "pair" not in cant["flags"]
    assert pair_reads(db) == [], "never looked at: not one read of a pair"
    # Their away dates count for the other who asks next.
    assert ask(app, "abel")["flags"] == ["pair"]
    assert ask(app, "kara", starts_on=day(0), ends_on=day(2))["flags"] == ["short_notice", "pair"]


# ─── Private ──────────────────────────────────────────────────────────

def test_a_pair_is_never_named_to_the_one_asking_and_never_on_the_calendar_for_anyone_else(app, db):
    pair(app, "yusuf", "kara")
    away(db, "yusuf", TUE)
    hers = ask(app, "kara", reason=SECRET)
    assert hers["flags"] == ["pair"], "she is told it went up because of a pair"
    yusuf = (cid(db, "yusuf"), "Yusuf", fake.uid(db, HOPE, "yusuf"))
    for words in (json.dumps(hers), json.dumps(get(app, "kara", "asks", box="mine").json())):
        assert not any(x in words for x in yusuf), "never who"
    answer(app, "owen", hers["id"])

    def entry(who):
        cal = get(app, who, "leaders", **{"from": day(28), "to": day(40)}).json()
        return next(a for g in cal["groups"] for a in g["away"] if a["contact_id"] == cid(db, "kara"))
    for who in ("wren", "celia", "tessa", "yusuf"):      # on the calendar; an Admin; the other of the pair
        r = get(app, who, "leaders", **{"from": day(28), "to": day(40)})
        if r.status_code == 403:
            continue
        e = entry(who)
        assert e["flags"] == [] and e["excepted"] == [], who
    for who in ("owner", "owen", "kara"):                # who reads the reason reads the flag
        e = entry(who)
        assert e["flags"] == ["pair"] and e["excepted"] == ["pair"], who


def test_the_others_waiting_ask_is_never_shown_to_anyone_who_may_not_already_read_it(app, db):
    """Yusuf asks first (it waits on Amara, with a private reason). Kara's
    ask overlaps it and goes up. She is told it overlaps with someone she
    can't be away with, and nothing more: not who, not which days, not what
    kind. Nobody else learns that his ask is there."""
    pair(app, "yusuf", "kara")
    his = ask(app, "yusuf", starts_on=day(33), ends_on=day(35), kind="commitment", reason=SECRET)
    hers = ask(app, "kara")
    assert hers["flags"] == ["pair"]
    told = json.dumps([hers, get(app, "kara", "asks", box="mine").json(),
                       get(app, "kara", "leaders", **{"from": day(28), "to": day(40)}).json()])
    for x in (his["id"], cid(db, "yusuf"), "Yusuf", day(33), day(35), "commitment", SECRET):
        assert x not in told, x
    for who in ("wren", "celia", "esther", "elena"):
        seen = json.dumps(get(app, who, "leaders", **{"from": day(28), "to": day(40)}).json())
        assert his["id"] not in seen and SECRET not in seen, who
    # The look before sending says the same, with no days of his.
    got = csl.look(church(db), cid(db, "kara"), date.fromisoformat(day(30)), date.fromisoformat(day(37)))
    assert got["flags"] == ["pair"] and [w for w in got["why"] if w["flag"] == "pair"] == [{"flag": "pair"}]
    assert got["open"] == {"before": None, "after": None}, "no open days offered for a pair alone"
    assert cid(db, "yusuf") not in json.dumps(got) and day(33) not in json.dumps(got)


def test_the_nearest_open_days_never_give_the_others_days_away(app, db):
    full(app, db)                             # Sun, Dec 20 is full
    a, z = date.fromisoformat(day(30)), date.fromisoformat(day(37))
    before = csl.look(church(db), cid(db, "yusuf"), a, z)
    assert before["open"] == {"before": day(25), "after": day(39)}
    pair(app, "yusuf", "esther")
    away(db, "esther", day(39))                 # the next Sunday, the nearest open one
    away(db, "esther", day(25))                 # and the one before
    after = csl.look(church(db), cid(db, "yusuf"), a, z)
    assert after["open"] == before["open"] and after["flags"] == ["over_limit"], "nothing changes"
    away(db, "esther", TUE)
    both = csl.look(church(db), cid(db, "yusuf"), a, z)
    assert both["flags"] == ["over_limit", "pair"] and both["open"] == before["open"]


def test_a_pair_with_someone_off_the_schedule_does_nothing_and_the_owner_sees_why(app, db):
    saved = pair(app, "yusuf", "kara")
    away(db, "kara", day(30))
    ask(app, "kara", starts_on=day(31), ends_on=day(37))       # still waiting when she is taken off the schedule
    as_(app, HOPE, "owner")
    assert app.put("/church/schedule/people", json={"business_id": HOPE, "contact_id": cid(db, "kara"),
                                                    "listed": "remove"}).status_code == 200
    assert ask(app, "yusuf")["flags"] == [], "kept, and in force only while both are on the schedule"
    [p] = get(app, "owner", "pairs").json()["pairs"]
    assert p["id"] == saved["id"] and p["in_force"] is False
    assert {p["a"]["name"]: p["a"]["on_schedule"], p["b"]["name"]: p["b"]["on_schedule"]} == {
        "Kara Bell": False, "Yusuf Grant": True}
    assert pair(app, "kara", "elena", status=400) == csl.PAIR_OFF, "a new one needs both on it"
    assert app.put("/church/schedule/people", json={"business_id": HOPE, "contact_id": cid(db, "kara"),
                                                    "listed": None}).status_code == 200
    db.t["church_away_asks"] = [r for r in db.t["church_away_asks"] if r["contact_id"] != cid(db, "yusuf")]
    assert ask(app, "yusuf")["flags"] == ["pair"], "back on the schedule, back in force"


# ─── Reads ────────────────────────────────────────────────────────────

def test_with_no_pairs_an_ask_and_its_yes_each_make_one_read_more_and_nothing_else_changes(app, db, monkeypatch):
    """The same ask and yes twice: once as built, once with every picture
    asked for no one's pairs (what S2-3 did). The reads differ by one, the
    answers not at all."""
    full(app, db)

    def run():
        db.t["church_away_asks"].clear()
        db.t["serve_away"] = [f for f in db.t["serve_away"] if not f.get("ask_id")]
        db.reads.clear()
        db.rpcs.clear()
        got = ask(app, "yusuf", reason=SECRET)
        asked = [p.replace(got["id"], "ASK") for p in db.reads]
        db.reads.clear()
        said = answer(app, "owen", got["id"])
        yes = [p.replace(got["id"], "ASK") for p in db.reads]
        strip = ("id", "created_at", "decided")
        return ({k: v for k, v in got.items() if k not in strip}, {k: v for k, v in said.items() if k not in strip},
                asked, yes, [{k: v for k, v in r.items() if k != "p_ask_id"} for r in db.rpcs])
    run()                                       # what a replica keeps (an owner's address, say) is kept for both
    built = run()
    real = csl.picture
    monkeypatch.setattr(csl, "picture", lambda ch, lo, hi, now=None, who=None: real(ch, lo, hi, now=now))
    before = run()
    assert built[0] == before[0] and built[1] == before[1] and built[4] == before[4], "the same answers"
    for now, then in ((built[2], before[2]), (built[3], before[3])):
        assert [p for p in now if not p.startswith("/church_away_pairs")] == then, "nothing else read"
        [one] = [p for p in now if p.startswith("/church_away_pairs")]
        assert f"business_id=eq.{HOPE}" in one and cid(db, "yusuf") in one


def test_with_no_pairs_nothing_else_reads_one(app, db):
    full(app, db)
    got = ask(app, "yusuf")
    db.reads.clear()
    for who, path, q in (("owner", "days", {}), ("owner", "limits", {}), ("owner", "leaders", {}),
                         ("owner", "protected-days", {}), ("owner", "asks", {"box": "all"}),
                         ("amara", "asks", {"box": "to_me"})):
        assert get(app, who, path, **q).status_code == 200, path
    assert pair_reads(db) == []
    answer(app, "owen", got["id"], yes=False)
    assert pair_reads(db) == [], "not this one is never rechecked"


def test_with_a_pair_the_others_waiting_asks_are_read_once_naming_who_which_days_and_when(app, db):
    pair(app, "yusuf", "kara")
    db.reads.clear()
    ask(app, "yusuf")
    [p] = pair_reads(db)
    waits = [r for r in db.reads if r.startswith("/church_away_asks") and "contact_id=in." in r]
    assert len(waits) == 1 and cid(db, "kara") in waits[0] and "state=eq.asked" in waits[0]
    assert "select=id,business_id,contact_id,state,starts_on,ends_on,created_at" in waits[0], "never a reason"


@pytest.mark.parametrize("path", ["/church_away_pairs", "/church_away_asks?business_id=eq." + HOPE + "&state=eq.asked"
                                                        "&contact_id=in."])
def test_a_failed_read_of_a_pair_while_asking_or_at_the_yes_is_a_503_with_nothing_saved(app, db, path):
    pair(app, "yusuf", "kara")
    got = ask(app, "yusuf")
    db.fail = {"get": path}
    assert ask(app, "kara", status=503)["detail"] == cs.UNREAD
    assert len(asks(db)) == 1
    before = dict(row(db, got["id"]))
    assert answer(app, "amara", got["id"], status=503) == cs.UNREAD
    assert row(db, got["id"]) == before and db.rpcs == []


def test_every_value_in_a_pairs_address_is_quoted_and_nothing_typed_reaches_one(app, db):
    saved = pair(app, "yusuf", "kara")
    away(db, "kara")
    ask(app, "yusuf")
    get(app, "owner", "pairs")
    drop(app, saved["id"])
    mine = [p for p in db.reads if p.startswith("/church_away_pairs") or "contact_id=in." in p]
    assert len(mine) >= 4
    for p in mine:
        assert "+" not in p and " " not in p and "'" not in p, p
        assert f"business_id=eq.{HOPE}" in p, p
    db.reads.clear()
    sneak = f"{cid(db, 'kara')}&business_id=eq.{GRACE}"
    assert pair(app, "yusuf", sneak, status=400) == "That person isn't valid"
    assert drop(app, f"x&business_id=eq.{GRACE}", status=400) == "That pair isn't valid"
    assert all(GRACE not in p for p in db.reads), "nothing typed reached an address"


def test_a_thousand_and_three_pairs_are_all_listed(app, db):
    people = sorted(c["id"] for c in db.t["contacts"] if c["business_id"] == HOPE)
    for a, b in itertools.islice(itertools.combinations(people, 2), 1003):
        db.t["church_away_pairs"].append({"id": str(uuid.uuid4()), "business_id": HOPE, "a_contact_id": a,
                                          "b_contact_id": b, "note": None, "created_by": None,
                                          "created_at": NOW.isoformat()})
    db.reads.clear()
    got = get(app, "owner", "pairs").json()["pairs"]
    assert len(got) == 1003 and len(pair_reads(db)) == 2, "no first 1,000 taken for all of them"


# ─── The fake, as the SQL ─────────────────────────────────────────────

def test_the_fake_refuses_a_pair_as_the_sql_does(app, db):
    lo, hi = sorted((cid(db, "yusuf"), cid(db, "kara")))
    good = {"business_id": HOPE, "a_contact_id": lo, "b_contact_id": hi}
    for body, why in (({**good, "a_contact_id": hi, "b_contact_id": lo}, "check: church_away_pairs_ordered"),
                      ({**good, "b_contact_id": lo}, "trigger: A pair is two people in this church"),
                      ({**good, "b_contact_id": cid(db, "yvette", GRACE)}, "trigger: A pair is two people in this church"),
                      ({**good, "note": "x" * 141}, "check: note")):
        db.refused.clear()
        assert db.post("/church_away_pairs", body) is None and db.refused == [why], why
    assert db.post("/church_away_pairs", good)
    db.refused.clear()
    assert db.post("/church_away_pairs", good) is None and db.refused == ["unique: church_away_pairs_one"]
    [r] = db.t["church_away_pairs"]
    db.refused.clear()
    assert db.patch(f"/church_away_pairs?id=eq.{r['id']}", {"a_contact_id": hi, "b_contact_id": lo}) is None
    assert db.refused == ["check: church_away_pairs_ordered"]
    db.refused.clear()
    assert db.patch(f"/church_away_pairs?id=eq.{r['id']}", {"b_contact_id": cid(db, "yvette", GRACE)}) is None
    assert db.refused == ["trigger: A pair is two people in this church"]
    assert db.patch(f"/church_away_pairs?id=eq.{r['id']}", {"note": "Kept apart"}) and r["note"] == "Kept apart"


# ─── The rule code reads the church's data, never a title ─────────────

def test_no_title_word_or_role_key_decides_who_reads_pairs_or_what_is_flagged():
    keys = re.compile(r"\b(pastor|executive_pastor|associate_pastor|elders|deacons|ministers|youth_pastor|"
                      r"worship_leader|team_leader|director_of_operations|childrens_director)\b")
    titles = re.compile(r"\b(pastors?|elders?|deacons?|ministers?|bishops?|directors?|executive|treasurers?|"
                        r"secretary|trustees?|reverend|apostles?|prophets?)\b", re.I)
    for fn in (csl.pairs, csl.view_pairs, csl.add_pair, csl.drop_pair, csl._partners, csl._waiting, csl._made_before,
               csl.flags_of, csl.Picture.pair_hits, csl.look, csl.nearest_open, cs.shape, cs._now_words):
        code = re.sub(r"#.*", "", re.sub(r'""".*?"""', "", inspect.getsource(fn), flags=re.S))
        assert not keys.search(code) and not titles.search(code), (fn.__name__, keys.search(code), titles.search(code))
    for words in (csl.NOT_PAIRS, csl.PAIR_SELF, csl.PAIR_OFF, csl.PAIR_TWICE, csl.PAIR_NOTE, csl.NO_PAIR, cs.NEEDS_NOW,
                  cs.WENT_UP_NEEDS, cs.YOURS_NEEDS):
        assert not titles.search(words.replace("the owner", "")) and "pair" not in cs.NEEDS_NOW, words


def test_a_waiting_ask_made_at_the_same_moment_or_one_whose_moment_cant_be_read_counts():
    assert csl._made_before("2026-11-18T15:00:01+00:00", "2026-11-18T15:00:02.5+00:00")
    assert csl._made_before("2026-11-18T15:00:02.5+00:00", "2026-11-18T15:00:02.5+00:00"), "the same moment"
    assert not csl._made_before("2026-11-18T15:00:02.51+00:00", "2026-11-18T15:00:02.5+00:00")
    assert not csl._made_before("2026-11-18T16:00:00Z", "2026-11-18T15:00:00.123456+00:00")
    assert csl._made_before("", "2026-11-18T15:00:00+00:00") and csl._made_before("2026-11-18T16:00:00Z", None)
