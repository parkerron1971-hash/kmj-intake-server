"""Areas and job guesses stop deciding (docs/CHURCH_LEADERS_MAP.md §3, §4, §5 PR 8).

Where a church's map is open (church_map.opened), a role or a Serve team is
placed by the church's own pick, then the area of the active department it
hangs from, then Chief's guess stored once (church_area_places by='guess'),
then its job; a login's default areas follow the same places. Here: open and
empty, all three churches' areas and logins equal today's, and each guess is
stored once; a renamed role keeps its area, and stored guesses outlive the
word list; the department's area wins over the guess, and the church's pick
over both; closed, a filled map is today's, and so is a database before the
migration; a failed map read is a failed read. And guess_job: the five titles
of §4, and a Chief draft of a title it can't place asks the owner."""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.dirname(HERE), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import business_access  # noqa: E402
import chief_church_actions as cca  # noqa: E402
import church_areas as ca  # noqa: E402
import church_roles as cr  # noqa: E402
import sb_clients  # noqa: E402
from church_three import CHURCHES, LOVE_CITY as LC, NAMES, build, church  # noqa: E402
from test_church_duties import PLATFORM  # noqa: E402

ALL = pytest.mark.parametrize("biz", CHURCHES, ids=[NAMES[b] for b in CHURCHES])


def _areas(db, biz):
    """The areas page and every manager-type login's own view (my-role)."""
    seats = [s for s in db.t["business_users"] if s["business_id"] == biz and s["role"] not in ca.KEEPS_ALL]
    return ca.build(church(db, biz)), {s["user_id"]: ca.view_for(biz, s["user_id"], s["role"]) for s in seats}


def _role(db, biz, key):
    return next(d for d in db.t["church_role_defs"] if d["business_id"] == biz and d["key"] == key)


def _guesses(db, biz):
    return {(r["kind"], r["key"]): r["area"] for r in db.t["church_area_places"]
            if r["business_id"] == biz and r.get("by") == "guess"}


def _placed(m, kind, key):
    return next(x for x in m[kind + "s"] if x["key"] == key)


def _place(db, monkeypatch, kind, key, area):
    """PUT /church/areas/place, as the owner."""
    monkeypatch.setattr(business_access, "_resolve_role", lambda b, u: "owner")
    me = SimpleNamespace(user=SimpleNamespace(id=church(db, LC)["owner_id"], email=PLATFORM, user_metadata={}))
    return ca.place({"business_id": LC, "kind": kind, "key": key, "area": area}, me)


# ─── Open and empty: today's areas, each guess stored once ────────────

@ALL
def test_open_and_empty_every_place_and_login_is_todays_and_each_guess_is_stored_once(monkeypatch, biz):
    today = _areas(build(monkeypatch, map_on=False, filled=False), biz)
    db = build(monkeypatch, filled=False)
    assert _guesses(db, biz), "a new role's guess is stored as it is made"
    assert _areas(db, biz) == today
    stored = _guesses(db, biz)
    teams = {k for k in stored if k[0] == "team"}
    assert teams, "a Serve team's guess is stored by the first read that sees it"
    db.writes.clear()
    assert _areas(db, biz) == today
    assert not [w for w in db.writes if w[1] == "church_area_places"] and _guesses(db, biz) == stored, \
        "once stored, nothing is guessed again"


def test_closed_or_before_the_migration_no_guess_is_stored(monkeypatch):
    for kw in ({"map_on": False}, {"migrated": False}):
        db = build(monkeypatch, filled=False, **kw)
        for biz in CHURCHES:
            _areas(db, biz)
        assert not [r for r in db.t["church_area_places"] if "by" in r], kw


# ─── Renamed: the stored guess decides ────────────────────────────────

def test_a_renamed_role_keeps_its_area_once_its_guess_is_stored(monkeypatch):
    for map_on, area, why in ((True, "website_outreach", "Chief's guess, from “evangelists”"),
                              (False, "people_care", "Chief's guess, from “greeters”")):
        db = build(monkeypatch, map_on=map_on, filled=False)
        cr.update_role(LC, _role(db, LC, "evangelists")["id"], {"title": "Greeters"})
        got = _placed(ca.build(church(db, LC)), "role", "evangelists")
        assert (got["area"], got["why"]) == (area, why), map_on


def test_stored_guesses_place_every_role_and_team_without_the_word_list(monkeypatch):
    """What PR 9 does to _AREA_WORDS: open, nothing moves; closed, the words
    were all that placed them."""
    for map_on in (True, False):
        db = build(monkeypatch, map_on=map_on, filled=False)
        before = ca.build(church(db, LC))
        monkeypatch.setattr(ca, "_AREA_WORDS", ())
        after = ca.build(church(db, LC))
        same = all(_placed(after, k, x["key"])["area"] == x["area"] for k in ("role", "team") for x in before[k + "s"])
        assert same is map_on, map_on
        monkeypatch.undo()


# ─── The department, then the church's pick ───────────────────────────

def test_the_departments_area_wins_over_the_guess_and_the_churchs_pick_over_both(monkeypatch):
    db = build(monkeypatch)
    assert _guesses(db, LC)[("role", "evangelists")] == "website_outreach"
    m = ca.build(church(db, LC))
    evangelists = _placed(m, "role", "evangelists")
    assert evangelists == {**evangelists, "area": "people_care", "by": "department",
                           "why": "Its department, Outreach & Welcome, works here"}
    assert _placed(m, "team", ca.team_key("Youth Ministry (YWD)"))["by"] == "department"
    assert _place(db, monkeypatch, "role", "evangelists", "office")["area"] == "office"
    assert _placed(ca.build(church(db, LC)), "role", "evangelists")["by"] == "church"
    assert _place(db, monkeypatch, "role", "evangelists", None)["area"] is None
    assert _placed(ca.build(church(db, LC)), "role", "evangelists")["by"] == "department", "back from the pick"


def test_back_from_a_pick_is_chiefs_guess_and_back_from_a_guess_changes_nothing(monkeypatch):
    db = build(monkeypatch, filled=False)
    _place(db, monkeypatch, "role", "evangelists", "office")
    row = next(r for r in db.t["church_area_places"] if r["business_id"] == LC and r["key"] == "evangelists")
    assert (row["by"], row["area"]) == ("church", "office"), "a pick over a stored guess is the church's"
    _place(db, monkeypatch, "role", "evangelists", None)
    assert _placed(ca.build(church(db, LC)), "role", "evangelists")["area"] == "website_outreach"
    assert _guesses(db, LC)[("role", "evangelists")] == "website_outreach", "the next read stored it again"
    _place(db, monkeypatch, "role", "evangelists", None)
    assert _guesses(db, LC)[("role", "evangelists")] == "website_outreach", "a guess isn't a pick to take back"


def test_a_logins_default_areas_follow_the_same_places(monkeypatch):
    """Eve holds Evangelists: her login's guess is her department's area on
    the open map, and the words' closed."""
    for map_on, area in ((True, "people_care"), (False, "website_outreach")):
        db = build(monkeypatch, map_on=map_on)
        eve = next(c for c in db.t["contacts"] if c["id"] == db.who[LC]["eve"])
        db.t["business_users"].append({"business_id": LC, "user_id": "5a000000-0000-4000-8000-000000000001",
                                       "role": "manager", "invited_email": eve["email"], "areas": None,
                                       "status": "active"})
        mine = ca.view_for(LC, "5a000000-0000-4000-8000-000000000001", "manager")
        assert (mine["areas"], mine["by"]) == ([area], "guess"), map_on


def test_a_filled_map_closed_is_todays(monkeypatch):
    today = _areas(build(monkeypatch, map_on=False, filled=False), LC)
    assert _areas(build(monkeypatch, map_on=False), LC) == today


def test_before_the_migration_the_areas_and_a_pick_are_todays(monkeypatch):
    today = _areas(build(monkeypatch, map_on=False, filled=False), LC)
    db = build(monkeypatch, filled=False, migrated=False)
    assert _areas(db, LC) == today
    assert _place(db, monkeypatch, "role", "evangelists", "office")["area"] == "office", "names no new column"
    assert _place(db, monkeypatch, "role", "evangelists", None)["area"] is None


# ─── A failed map read ────────────────────────────────────────────────

def test_a_failed_map_read_is_a_failed_read(monkeypatch):
    for map_on in (True, False):
        db = build(monkeypatch, map_on=map_on)
        real = db.get
        monkeypatch.setattr(sb_clients, "sb_get_as_service",
                            lambda path, **kw: None if path.startswith("/church_departments") else real(path, **kw))
        jess = db.who[LC]["jessica@"]
        if map_on:
            with pytest.raises(HTTPException) as e:
                ca.build(church(db, LC))
            assert e.value.status_code == 503
            assert ca.view_for(LC, jess, "manager") is None, "a login shows what it showed before"
        else:
            assert ca.build(church(db, LC)) and ca.view_for(LC, jess, "manager")["areas"] == ["people_care"]


# ─── guess_job (§4) ───────────────────────────────────────────────────

@pytest.mark.parametrize("title,job", [("Prophet", "pastoral"), ("Apostle", "pastoral"), ("Overseer", "pastoral"),
                                       ("Board member", None), ("First Lady", None)])
def test_the_five_titles(title, job):
    got, why = cr.guess_job(title)
    assert got == job and why
    assert cr.job_for_title(title) == (job or "")


def test_a_title_another_word_placed_keeps_its_job():
    assert cr.guess_job("Youth Overseer")[0] == "ministry" and cr.guess_job("Prophetic team leader")[0] == "team"
    assert cr.guess_job("Lead Pastor") == ("senior", "Non-denominational churches use the title “Lead Pastor”")
    assert cr.guess_job("Hospitality captain") == ("welcome", "its title says “hospitality”")


def test_a_chief_draft_of_a_title_it_cant_place_asks_the_owner(monkeypatch):
    db = build(monkeypatch, filled=False)
    before = len(db.t["church_role_defs"])
    with pytest.raises(HTTPException) as e:
        cr.chief_draft(church(db, LC), "First Lady")
    assert e.value.status_code == 400 and e.value.detail == (
        "Chief can’t tell what job a First Lady does here. Pick one: Senior pastor, Pastoral, Prayer, Care, "
        "Ministry lead, Team leader, Welcome, Teachers & group leaders, Kids & youth workers, Office.")
    with pytest.raises(HTTPException) as an:
        cr.chief_draft(church(db, LC), "Organist")
    assert an.value.detail.startswith("Chief can’t tell what job an Organist does here.")
    assert len(db.t["church_role_defs"]) == before, "nothing drafted"
    monkeypatch.setattr(cca, "_caller_role", lambda b: "owner")
    asked = asyncio.run(cca.handle_draft_church_role(None, church(db, LC), {"title": "First Lady"}))
    assert asked["failed"] and asked["result"] == f"failed: {e.value.detail}", "Chief asks the owner"
    made = asyncio.run(cca.handle_draft_church_role(None, church(db, LC), {"title": "First Lady", "job": "care"}))
    assert "Drafted the role “First Lady” on the Care job" in made["result"]
    assert len(db.t["church_role_defs"]) == before + 1 and _role(db, LC, "first_lady")["status"] == "draft"
