"""The leaders map's read core (church_map.py) and the role switches as data
(church_roles.py), docs/CHURCH_LEADERS_MAP.md §3 and §5 PR 3.

The switch is like the others; ready() is one probe, remembered once true;
before the migration every role write leaves the new columns out (and
test_church_three_today runs every baseline that way too); the catalog
carries the backfill's values, and what a new church is filled with equals
them; each job's switches, and the job-change rule; load() reads back what a
church wrote and is None on any failed read; can()'s seven switches; the
office's page, Chief and the routes. Nothing here reads a switch to decide
anything: that is PR 4 on."""
from __future__ import annotations

import copy
import json
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.dirname(HERE), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_map as cm  # noqa: E402
import church_roles as cr  # noqa: E402
import member_portal_messaging as mpm  # noqa: E402
import sb_clients  # noqa: E402
from church_three import CHURCHES, GRACE, LOVE_CITY as LC, MAP_NEW, NAMES, NEW_HOPE, build, church  # noqa: E402
from test_church_duties import PLATFORM  # noqa: E402
from test_church_map_vectors import VECTORS  # noqa: E402
from test_church_roles import BIZ, db, office  # noqa: E402,F401

K = (*cr.SWITCHES, "made_for")


def _vectors():
    with open(VECTORS, encoding="utf-8") as f:
        return {c["church"]: c for c in json.load(f)["churches"]}


def _sw(row):
    return {k: row.get(k) for k in K}


def _role(db, biz, key):
    return next(d for d in db.t["church_role_defs"] if d["business_id"] == biz and d["key"] == key)


# ─── The switch, and ready() ──────────────────────────────────────────

def test_the_switch_is_off_owner_or_on_and_owner_is_the_platform_owners_church(monkeypatch):
    db = build(monkeypatch, filled=False)
    me, other = SimpleNamespace(email=PLATFORM.upper()), SimpleNamespace(email="pastor@gracebaptist.org")
    monkeypatch.delenv("CHURCH_MAP")
    assert cm.mode() == "owner"
    assert (cm.open_to(me), cm.open_to(other)) == (True, False)
    assert (cm.church_open(LC), cm.church_open(church(db, LC)), cm.church_open(GRACE)) == (True, True, False)
    monkeypatch.setenv("CHURCH_MAP", "on")
    assert cm.open_to(other) and cm.church_open(GRACE)
    for m in ("off", "sideways"):
        monkeypatch.setenv("CHURCH_MAP", m)
        assert cm.mode() == "off" and not cm.open_to(me) and not cm.church_open(LC)


def test_ready_is_one_probe_remembered_once_true_and_false_on_any_error(monkeypatch):
    db = build(monkeypatch, filled=False, migrated=False)
    calls, real = [], sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p, **k: calls.append(p) or real(p, **k))
    assert (cm.ready(), cm.ready(), len(calls)) == (False, False, 2), "asked again while the columns aren't there"
    db.migrated = True
    assert (cm.ready(), cm.ready(), len(calls)) == (True, True, 3), "remembered once they are"
    cm._READY.clear()

    def down(p, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(sb_clients, "sb_get_as_service", down)
    assert cm.ready() is False


def test_before_the_migration_every_role_write_leaves_the_new_columns_out(monkeypatch):
    """The fake refuses a read or write naming them, as PostgREST would; every
    write still saves (an update naming a switch says it can't: the next
    test), and no row or page carries a switch."""
    db = build(monkeypatch, filled=False, migrated=False)
    nh = church(db, NEW_HOPE)
    made = cr.create_role(nh, {"title": "Care Ministers", "job": "care", "can_shepherd": True, "made_for": ["care_need"]})
    cr.update_role(NEW_HOPE, _role(db, NEW_HOPE, "deacons")["id"], {"handles": ["care_need"]})
    cr.set_type(nh, "baptist", ["mothers_board"])
    cr.chief_draft(church(db, GRACE), "Armor Bearer", "team")
    assert made["key"] == "care_ministers" and _role(db, NEW_HOPE, "mothers_board")
    assert not [k for d in db.t["church_role_defs"] + db.t["church_role_settings"] for k in d if MAP_NEW.search(k)]
    lib = cr.library(nh)
    assert lib and not [k for r in lib["roles"] for k in r if MAP_NEW.search(k)]
    assert not any("Switches:" in line for line in cr.chief_lines(church(db, LC))), "Love City's map is open"


@pytest.mark.parametrize("migrated", [False, True], ids=["before_the_migration", "a_failed_probe"])
def test_an_update_naming_a_switch_it_cant_write_says_so_and_changes_nothing(monkeypatch, migrated):
    """ready() is false before the migration and on a failed probe (a blip):
    an update naming a switch is a 503, never dropped and answered as saved."""
    db = build(monkeypatch, filled=False, migrated=migrated)
    monkeypatch.setattr(cm, "ready", lambda: False)
    deacons = _role(db, GRACE, "deacons")
    before = dict(deacons)
    for body in ({"can_shepherd": True}, {"title": "Deacon Council", "made_for": ["care_need"]}):
        with pytest.raises(HTTPException) as e:
            cr.update_role(GRACE, deacons["id"], body)
        assert (e.value.status_code, e.value.detail) == (503, "Couldn’t save that just now; try again.")
        assert _role(db, GRACE, "deacons") == before, "nothing half-saved"
    assert cr.update_role(GRACE, deacons["id"], {"title": "Deacon Council"})["title"] == "Deacon Council", \
        "an update naming no switch saves"


# ─── The catalog, and what a new church is filled with ────────────────

def test_every_catalog_row_carries_the_backfills_switches():
    v = _vectors()
    for t in cr.TYPE_ORDER:
        assert [_sw(r) for r in cr.TYPES[t]["rows"]] == [_sw(r) for r in v[f"type:{t}"]["roles"]], t
    assert [_sw(r) for r in cr.LEGACY.values()] == [_sw(r) for r in v["legacy"]["roles"]]
    assert [(t, r["key"]) for t in cr.TYPE_ORDER for r in cr.TYPES[t]["rows"] if r["office"]] == \
        [("nondenom", "executive_pastor")]


def test_a_church_filled_after_the_migration_gets_what_the_backfill_gives(monkeypatch):
    """ensure_library, create_role (Love City's two, New Hope's Director of
    Operations) and three retitles write exactly the vectors' switches, and
    the nondenom Executive Pastor names itself to oversee the office."""
    db, v = build(monkeypatch, filled=False), _vectors()
    keys = {d["id"]: d["key"] for d in db.t["church_role_defs"]}
    for b in CHURCHES:
        want = v[f"fixture:{NAMES[b]}"]
        assert {d["key"]: _sw(d) for d in db.t["church_role_defs"] if d["business_id"] == b} == \
            {r["key"]: _sw(r) for r in want["roles"]}, NAMES[b]
        st = next(s for s in db.t["church_role_settings"] if s["business_id"] == b)
        assert ([keys[i] for i in st.get("office_overseer_roles") or []] or None) == want["office_overseer_roles"]
    grace = church(db, GRACE)
    cr.set_type(grace, "nondenom", ["executive_pastor"])
    st = next(s for s in db.t["church_role_settings"] if s["business_id"] == GRACE)
    assert st["office_overseer_roles"] == [_role(db, GRACE, "executive_pastor")["id"]], "a church that never named one"
    nh = next(s for s in db.t["church_role_settings"] if s["business_id"] == NEW_HOPE)
    nh["office_overseer_roles"] = []
    db.t["church_role_defs"] = [d for d in db.t["church_role_defs"] if d["key"] != "executive_pastor"]
    cr.set_type(church(db, NEW_HOPE), "nondenom", ["executive_pastor"])
    assert nh["office_overseer_roles"] == [], "'{}' is the church's own answer: none"


def test_every_insert_names_all_six_so_a_role_saved_all_off_stays_off(monkeypatch):
    """The live insert trigger fills today's rule into a row with none of its
    switches said (all at the column defaults); the fake runs it. Every insert
    names all six, so a role the church saves with everything off keeps it."""
    db = build(monkeypatch, filled=False)
    g = church(db, GRACE)
    off = dict.fromkeys(cr.SWITCHES[1:], False)
    cr.set_type(g, "nondenom", ["executive_pastor", "care_team"])
    cr.chief_draft(g, "Armor Bearer", "team")
    quiet = cr.create_role(g, {"title": "Shepherds", "job": "pastoral", "can_shepherd": False, **off})
    unsure = cr.create_role(g, {"title": "Shepherds", "job": "pastoral", "can_shepherd": None, **off})
    assert len(db.role_inserts) > 40 and all(set(K) <= set(b) for b in db.role_inserts), "ensure_library too"
    assert _sw(_role(db, GRACE, quiet["key"])) == dict(off, can_shepherd=False, made_for=[]), "never overwritten"
    assert _role(db, GRACE, unsure["key"])["can_shepherd"] is False, "null with all else off would read as none said"
    sb_clients.sb_post_as_service("/church_role_defs", {"business_id": GRACE, "key": "raw", "title": "Shepherds",
                                                        "job": "pastoral", "handles": ["pastor_ask"]})
    assert _role(db, GRACE, "raw")["can_lead"] is True, "the fake's trigger does fill a row that says none"


# ─── Each job's switches, and changing a job ──────────────────────────

def test_each_job_has_switches_and_a_new_pastoral_role_shepherds(monkeypatch):
    for j in cr.JOB_ORDER:
        sw = cr.JOBS[j]["switches"]
        assert sw == {"can_shepherd": j in ("senior", "pastoral"), "can_oversee": j in ("senior", "pastoral"),
                      "can_lead": j in mpm.LEADER_JOBS, "can_board_yes": False, "can_see_all": j == "senior"}, j
    db = build(monkeypatch, filled=False)
    g = church(db, GRACE)
    seer = cr.create_role(g, {"title": "Prophets", "job": "pastoral"})
    care = cr.create_role(g, {"title": "Care Ministers", "job": "care"})
    lic = cr.create_role(g, {"title": "Licensed Ministers", "job": "pastoral", "can_shepherd": None})
    odd = cr.create_role(g, {"title": "Nurses", "job": "care", "can_shepherd": None, "made_for": ["baptism"]})
    assert _sw(seer) == dict(cr.JOBS["pastoral"]["switches"], made_for=[]), "decision 2: no shepherd word needed"
    assert (care["can_lead"], care["made_for"]) == (False, ["care_need"]), "its own words suggest it, once"
    assert (lic["can_shepherd"], odd["can_shepherd"]) == (None, False), "only a pastoral role follows Ministers"
    assert odd["made_for"] == [], "made_for is only ever among its handles"


def test_a_job_change_starts_the_switches_again_from_the_new_jobs_unless_the_request_says(monkeypatch):
    db = build(monkeypatch, filled=False)
    row = cr.create_role(church(db, NEW_HOPE), {"title": "Care Pastors", "job": "care", "can_lead": True})
    assert (row["can_lead"], row["made_for"]) == (True, ["care_need"])
    row = cr.update_role(NEW_HOPE, row["id"], {"job": "pastoral"})
    assert _sw(row) == dict(cr.JOBS["pastoral"]["switches"], made_for=[]) and row["handles"] == ["pastor_ask"]
    row = cr.update_role(NEW_HOPE, row["id"], {"job": "welcome", "can_oversee": True})
    assert (row["can_shepherd"], row["can_oversee"], row["can_lead"]) == (False, True, True)
    ap = _role(db, NEW_HOPE, "associate_pastor")
    row = cr.update_role(NEW_HOPE, ap["id"], {"title": "Associate Pastors", "handles": ["care_need"]})
    assert (row["can_shepherd"], row["made_for"]) == (True, []), "a retitle keeps them; handles that move trim made_for"
    with pytest.raises(HTTPException) as e:
        cr.update_role(NEW_HOPE, ap["id"], {"job": "care"})
    assert e.value.status_code == 400 and e.value.detail == "Take the people out of this role before changing its job"


# ─── load(), can() ────────────────────────────────────────────────────

def test_the_fixtures_map_lands_in_the_tables_and_loads_back_church_by_church(monkeypatch):
    db = build(monkeypatch)
    w = db.who
    assert [len([d for d in db.t["church_departments"] if d["business_id"] == b]) for b in CHURCHES] == [3, 1, 4]
    m = cm.load(LC)
    youth_group = next(g["id"] for g in db.t["groups"] if g["business_id"] == LC and g["name"] == "Youth")
    youth = m.department_of("serve_option", "youth ministry (YWD) ")
    assert youth is m.department_of("space", "youth") is m.department_of("group", youth_group)
    assert (youth["name"], youth["leader_contact_id"], youth["overseer_contact_id"], youth["support_duty"]) == \
        ("Youth", w[LC]["yolanda"], w[LC]["andre"], "youth")
    assert m.department_of("role", _role(db, LC, "intercessors")["id"])["name"] == "Prayer"
    assert (m.led_by(w[LC]["yolanda"]), m.overseen_by(w[LC]["andre"])) == ([youth], [youth])
    assert (m.answers_to(w[LC]["marcus"], "elders"), m.answers_to(w[LC]["tanya"])) == (w[LC]["jessica"], None)
    assert m.settings["office_overseer_roles"] == [_role(db, LC, "executive_pastor")["id"]]
    assert cm.can(m, _role(db, LC, "evangelists"))["oversee"] is True, "flipped"
    g, nh = cm.load(GRACE), cm.load(NEW_HOPE)
    assert [d["name"] for d in g.departments] == ["Youth"] and g.department_of("space", "kids") is None
    assert (g.settings["pastor_from_cents"], g.settings["board_over_cents"]) == (20_000, 100_000)
    assert cm.can(g, _role(db, GRACE, "deacons")) == {"shepherd": True, "oversee": True, "lead": False,
                                                      "board_yes": False, "see_all": False, "prayer": False, "care": True}
    assert nh.settings["office_overseer_roles"] == [_role(db, NEW_HOPE, "director_of_operations")["id"]]
    assert len(nh.links) == 5 and not g.links and cm.can(nh, _role(db, NEW_HOPE, "elders"))["board_yes"]
    db = build(monkeypatch, filled=False)
    empty = cm.load(GRACE)
    assert empty is not None and (empty.departments, empty.links) == ([], []), "an empty map is a map, not None"
    before = copy.deepcopy(db.t)
    assert cm.propose(LC) == {} and db.t == before, "a stub for step 2, and it never writes"


@pytest.mark.parametrize("table", ["church_role_defs", "church_leader_roles", "church_role_settings",
                                   "church_departments", "church_department_units"])
def test_a_failed_read_loads_no_map(monkeypatch, table):
    build(monkeypatch)
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p, **k: None if p.startswith(f"/{table}?") else real(p, **k))
    assert cm.load(LC) is None


def test_the_seven_switches(monkeypatch):
    db = build(monkeypatch, filled=False)
    m, d = cm.load(LC), cr.by_key(cr.defs(LC))
    assert cm.can(m, d["pastor"]) == {"shepherd": True, "oversee": True, "lead": True, "board_yes": False,
                                      "see_all": True, "prayer": False, "care": False}
    assert cm.can(m, d["intercessor_leader"])["prayer"] and cm.can(m, d["associate_pastor"])["care"]
    assert [cm.can(m, d["ministers"], ministers=x)["shepherd"] for x in (None, False, True)] == [None, False, True]
    legacy = {"id": "legacy:baptism_minister", "key": "baptism_minister", "job": "pastoral", "handles": ["baptism"]}
    assert cm.can(m, legacy)["shepherd"] is None, "a legacy role: its catalog row's"
    assert cm.can(None, {"id": "x", "job": "team", "handles": ["serve"]})["lead"], "else its job's"


# ─── The office's page, Chief, the routes ─────────────────────────────

def test_the_leaders_page_shows_the_switches_and_chief_reads_them_where_the_map_is_open(monkeypatch):
    db = build(monkeypatch)
    lib = cr.library(church(db, GRACE))
    deacons = next(r for r in lib["roles"] if r["key"] == "deacons")
    assert _sw(deacons) == {"can_shepherd": True, "can_oversee": True, "can_lead": False, "can_board_yes": False,
                            "can_see_all": False, "made_for": []}
    assert lib["jobs"]["pastoral"]["switches"]["can_shepherd"] is True
    monkeypatch.setenv("CHURCH_MAP", "on")
    lines = "\n".join(cr.chief_lines(church(db, GRACE)))
    assert "Handed: Care needs on a card: someone sick, in the hospital, grieving, or needing a meal. Switches: " \
           "shepherds families, can oversee a department. Definition: The Deacon Board" in lines
    assert "Switches: shepherds families when the church’s Ministers setting is on" in lines
    monkeypatch.setenv("CHURCH_MAP", "owner")
    assert "Switches:" not in "\n".join(cr.chief_lines(church(db, GRACE))), "closed: Chief reads what it does today"


def test_the_roles_routes_take_the_switches(office, db):  # noqa: F811
    office.get(f"/church/leaders?business_id={BIZ}")
    r = office.post(f"/church/roles?business_id={BIZ}", json={"title": "Licensed Ministers", "job": "pastoral",
                                                              "can_shepherd": None})
    role = r.json()["role"]
    assert r.status_code == 200 and role["can_shepherd"] is None and role["can_oversee"] is True
    r = office.patch(f"/church/roles/{role['id']}?business_id={BIZ}",
                     json={"can_board_yes": True, "made_for": ["pastor_ask", "baptism"]})
    assert (r.json()["role"]["can_board_yes"], r.json()["role"]["made_for"]) == (True, ["pastor_ask"])
    r = office.patch(f"/church/roles/{role['id']}?business_id={BIZ}", json={"can_shepherd": True})
    assert r.json()["role"]["can_shepherd"] is True and r.json()["role"]["can_board_yes"] is True
