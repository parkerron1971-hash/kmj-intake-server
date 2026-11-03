"""People on drafts, the half-made mark, the pickers' choices, and who changes
a role's switches (docs/CHURCH_LEADERS_STEP2.md §1.3, §3.2, §4.3; §7 B3b).

A draft department may name anyone among the church's people, and the map
says what each needs; an active one also takes someone asked into a role that
would qualify them, with a gap, and the chain passes over them until they say
yes (decision 2), at every church; making a draft active checks its people.
Only a save that failed half-way marks a department unfinished, a retry
finishes it, and a draft saved on purpose is never taken over. A role's
switches are an admin's to change, its board yes the owner's (decision 3),
and a switch save is one change the map's Undo puts back."""
from __future__ import annotations

import inspect
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.dirname(HERE), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_follow_up as cfu  # noqa: E402
import church_map as cm  # noqa: E402
import church_map_batch as batch  # noqa: E402
import church_roles as cr  # noqa: E402
import church_router  # noqa: E402
import sb_clients  # noqa: E402
from church_three import (CHURCHES, GRACE, LOVE_CITY as LC, NAMES, NEW_HOPE as NH, RIVERSIDE as RV,  # noqa: E402
                          build, church, late_follow_up, late_task)
from test_church_map_writes import Office  # noqa: E402


def owner(db, biz=LC):
    return church(db, biz)["owner_id"]


def save(db, body, biz=LC):
    return cm.save_department(church(db, biz), body, owner(db, biz))


def refused(fn, *a, code=400):
    with pytest.raises(HTTPException) as e:
        fn(*a)
    assert e.value.status_code == code, e.value.detail
    return str(e.value.detail)


def dept(db, name, biz=LC):
    return next(d for d in db.t["church_departments"] if d["business_id"] == biz and d["name"] == name)


def role(db, key, biz=LC):
    return next(d for d in db.t["church_role_defs"] if d["business_id"] == biz and d["key"] == key)


def ask(db, biz, handle, key):
    """Asked into a role, as the office's Ask does: an invited row."""
    return cfu.add_role(biz, db.who[biz][handle], key, by_user=owner(db, biz))


def gaps(db, name, biz=LC):
    v = cm.view(church(db, biz))
    did = next(d["id"] for d in v["departments"] if d["name"] == name)
    return {(g["kind"], g["text"]) for g in v["gaps"] if g["department_id"] == did}


@pytest.fixture
def lc(monkeypatch):
    return build(monkeypatch)


# ─── People on drafts (§3.2) ──────────────────────────────────────────

def test_a_draft_names_anyone_here_says_what_each_needs_and_is_checked_when_it_goes_live(lc):
    w = lc.who[LC]
    assert "isn’t one of this church’s people" in refused(save, lc, {
        "name": "Media", "status": "draft", "leader_contact_id": lc.who[GRACE]["yvette"]})
    media = save(lc, {"name": "Media", "status": "draft", "leader_contact_id": w["gloria"],
                      "overseer_contact_id": w["calvin"]})
    assert gaps(lc, "Media") == {("leader_needs", "Gloria Hunt needs a role that leads."),
                                 ("overseer_needs", "Calvin Owens needs a role that can oversee."),
                                 ("no_duty", "No office duty is named to help Media.")}
    assert "Gloria Hunt doesn’t hold a role that leads" in refused(save, lc, {"id": media["id"], "status": "active"}), \
        "going live checks its people, though the request names none"
    ask(lc, LC, "gloria", "associate_pastor")
    ask(lc, LC, "calvin", "intercessors")             # asked, but into a role that can't oversee
    title = cr.title_of("associate_pastor", cr.defs(LC))
    assert ("leader_asked", f"Gloria Hunt was asked into {title} and hasn’t said yes yet.") in gaps(lc, "Media")
    assert "Calvin Owens doesn’t hold a role that can oversee" in refused(save, lc, {"id": media["id"],
                                                                                    "status": "active"})
    assert dept(lc, "Media")["status"] == "draft", "refused: nothing written"
    live = save(lc, {"id": media["id"], "status": "active", "overseer_contact_id": w["andre"]})
    assert (live["status"], live["leader_contact_id"]) == ("active", w["gloria"]), "asked, she is accepted"
    assert {k for k, _t in gaps(lc, "Media")} == {"leader_asked", "no_duty"}
    assert "doesn’t hold a role that leads" in refused(save, lc, {"name": "Choir", "leader_contact_id": w["calvin"]}), \
        "an active one still refuses someone neither holding nor asked into a role that leads"


def test_an_undo_that_brings_a_department_back_checks_its_people(lc):
    out = batch.apply(church(lc, LC), [{"kind": "department", "department": "Youth", "status": "archived"}],
                      owner(lc), "office", role="owner")
    next(h for h in lc.t["church_leader_roles"] if h["contact_id"] == lc.who[LC]["yolanda"])["status"] = "declined"
    with pytest.raises(HTTPException) as e:
        batch.undo(church(lc, LC), out["change"]["id"], owner(lc), role="owner")
    assert (e.value.status_code, e.value.detail) == (409, "That can’t be put back: Yolanda Reed doesn’t hold a role "
                                                          "that leads. Turn that on for their role in Leaders & roles, "
                                                          "or pick another leader.")
    assert dept(lc, "Youth")["status"] == "archived"


YOUTH_ROLES = {LC: ("associate_pastor", "youth_pastor"), GRACE: ("deacons", "youth_minister"),
               NH: ("associate_pastor", "youth_pastor")}
NEWCOMER = {LC: ("gloria", "calvin"), GRACE: ("g12", "g13"), NH: ("n024", "n025")}


@pytest.mark.parametrize("biz", CHURCHES, ids=[NAMES[b] for b in CHURCHES])
def test_someone_asked_is_accepted_with_a_gap_and_hears_nothing_until_they_say_yes(monkeypatch, biz):
    """Risk 1, at each church: Youth's overseer swapped for someone asked
    into the overseeing role, who hasn't said yes. Y's late task and late
    follow-up go exactly where they go with Youth's overseer vacant."""
    vacant = build(monkeypatch)
    dept(vacant, "Youth", biz)["overseer_contact_id"] = None
    want = (late_task(monkeypatch, vacant, biz), late_follow_up(monkeypatch, vacant, biz))
    db = build(monkeypatch)
    oversee, lead = YOUTH_ROLES[biz]
    p, q = NEWCOMER[biz]
    youth, was = dept(db, "Youth", biz), dept(db, "Youth", biz)["overseer_contact_id"]
    ask(db, biz, p, oversee)
    assert save(db, {"id": youth["id"], "overseer_contact_id": db.who[biz][p]}, biz)["overseer_contact_id"] == \
        db.who[biz][p]
    assert "overseer_asked" in {k for k, _t in gaps(db, "Youth", biz)}
    got = (late_task(monkeypatch, db, biz), late_follow_up(monkeypatch, db, biz))
    assert got == want and db.label[db.who[biz][p]] not in str(got)
    # The same for an asked leader: a Serve sign-up for Youth's team goes past
    # them to its overseer, even when the rows handed in include the ask.
    ask(db, biz, q, lead)
    save(db, {"id": youth["id"], "leader_contact_id": db.who[biz][q], "overseer_contact_id": was}, biz)
    rows = cfu.roles(biz)
    every = {}
    for h in rows:
        every.setdefault(h["role"], []).append(h)
    team = next(u["label"] for d in cm.load(biz).departments if d["name"] == "Youth" for u in d["units"]
                if u["kind"] == "serve_option")
    for held in (cr.active_holders(rows), every):
        step, row = cm.team_head(cm.load(biz), cr.defs(biz), held, team)
        assert (step["title"], row["contact_id"]) == ("Youth overseer", was)


def test_at_riverside_a_department_of_two_people_asked_routes_to_no_one(monkeypatch):
    db = build(monkeypatch)
    cr.ensure_library(church(db, RV))
    ask(db, RV, "henry", "ypd_director")
    ask(db, RV, "lois", "stewards")
    w, ypd = db.who[RV], role(db, "ypd_director", RV)
    save(db, {"name": "Youth", "leader_contact_id": w["henry"], "overseer_contact_id": w["lois"],
              "units": [{"kind": "role", "ref": ypd["id"]}]}, RV)
    m, defs = cm.load(RV), cr.defs(RV)
    assert m.active()[0]["leader_contact_id"] == w["henry"]
    assert cm.chain_for(m, defs, cr.active_holders(cfu.roles(RV)), w["walter"], ypd) == []


# ─── The half-made mark (§1.3) ────────────────────────────────────────

KIDS = {"name": "Kids", "units": [{"kind": "space", "label": "kids"}]}


def half_made(monkeypatch, db, body):
    """A save whose units, and taking the department back out, both fail."""
    post, delete = sb_clients.sb_post_as_service, sb_clients.sb_delete_as_service
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda path, b, prefer=None, **k: None
                        if path.startswith("/church_department_units") else post(path, b, prefer, **k))
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", lambda path, **k: False)
    says = refused(save, db, body, code=503)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", delete)
    return says


def test_a_draft_saved_on_purpose_is_never_taken_over(lc, monkeypatch):
    made = save(lc, {"name": "Kids", "status": "draft"})
    assert refused(save, lc, KIDS) == "There’s already a department called Kids"
    assert not dept(lc, "Kids").get("unfinished_at") and made["units"] == []
    half_made(monkeypatch, lc, dict(KIDS, name="Teens"))
    assert dept(lc, "Teens")["unfinished_at"]
    save(lc, {"id": dept(lc, "Teens")["id"], "area": "kids_youth"})
    assert dept(lc, "Teens")["unfinished_at"] is None, "a save by its id makes it the office's own"
    assert refused(save, lc, dict(KIDS, name="Teens")) == "There’s already a department called Teens"
    dept(lc, "Kids")["unfinished_at"] = "2026-11-04T12:00:00+00:00"      # as B2's backfill marks one
    assert save(lc, KIDS)["id"] == made["id"] and dept(lc, "Kids")["status"] == "active"


def test_before_step_2_nothing_is_marked_and_nothing_taken_over(monkeypatch):
    db = build(monkeypatch, migrated2=False)
    assert half_made(monkeypatch, db, KIDS) == cm.LEFT_EMPTY.format(name="Kids")
    assert dept(db, "Kids")["status"] == "draft" and "unfinished_at" not in dept(db, "Kids")
    assert refused(save, db, KIDS) == "There’s already a department called Kids"


def test_no_ten_minute_guess_is_left():
    src = inspect.getsource(cm)
    assert "LEFT_FOR" not in src and "updated_by" not in inspect.getsource(cm._left_behind)


# ─── The pickers' choices ─────────────────────────────────────────────

def test_the_pickers_choices_say_what_each_thing_already_hangs_from(lc):
    o = Office(lc).as_(LC, "naiya")
    assert "choices" not in o.get(LC).json()
    got = o.c.get(f"/church/map?business_id={LC}&with=choices")
    assert got.status_code == 200, "a manager reads them"
    ch = got.json()["choices"]
    assert set(ch) == set(cm.KINDS)
    hangs = {k: {x["label"]: (x["department"] or {}).get("name") for x in v} for k, v in ch.items()}
    assert hangs["group"] == {"Sisters in the City": None, "Youth": "Youth"}
    assert hangs["serve_option"]["Hospitality Team"] == "Outreach & Welcome" and \
        hangs["serve_option"]["Youth Ministry (YWD)"] == "Youth"
    assert hangs["space"] == {"youth": "Youth", "kids": None}
    assert hangs["board"] == {"Elder Board": None} and ch["worship_ministry"] == []
    assert hangs["role"][role(lc, "intercessors")["title"]] == "Prayer"
    assert {x["ref"] for x in ch["role"]} == {d["id"] for d in cr.defs(LC, with_drafts=True)}
    assert hangs["check_line"] == {x["name"]: None for x in __import__("church_checks").settings(LC)["lines"]}
    assert all(x["ref"] for k in cm.UNIT_REF for x in ch[k]) and not any(x["ref"] for x in ch["serve_option"])


# ─── Who changes a role's switches (decision 3) ───────────────────────

class Desk(Office):
    """Leaders & roles' routes and the map's, signed in as one login."""

    def __init__(self, db):
        super().__init__(db)
        self.c.app.include_router(church_router.router)
        self.c.app.dependency_overrides[sb_clients.authed_request] = lambda: SimpleNamespace(user=self.user)

    def patch(self, key, body, biz=LC):
        return self.c.patch(f"/church/roles/{role(self.db, key, biz)['id']}?business_id={biz}", json=body)


def test_switches_are_an_admins_the_board_yes_the_owners_and_undo_puts_them_back(lc):
    o = Desk(lc).as_(LC, "naiya")
    r = o.patch("team_leader", {"can_oversee": True})
    assert (r.status_code, r.json()["detail"]) == (403, batch.SWITCH_SEAT), "a manager: no"
    assert o.patch("team_leader", {"made_for": ["serve"]}).status_code == 403
    assert o.patch("team_leader", {"definition": "Leads one team."}).status_code == 200, "other fields as today"
    assert role(lc, "team_leader")["can_oversee"] is False and not lc.t["church_map_changes"]
    made = o.c.post(f"/church/roles?business_id={LC}", json={"title": "Usher Captain", "job": "team", "can_lead": True})
    assert made.status_code == 403, "nor in a new role"
    o.as_(LC, "minnie")
    r = o.patch("team_leader", {"can_oversee": True, "definition": "Leads and oversees."})
    assert r.status_code == 200 and r.json()["role"]["can_oversee"] is True
    change = r.json()["change"]
    row = next(x for x in lc.t["church_map_changes"] if x["id"] == change["id"])
    assert (row["origin"], row["money"], [p["kind"] for p in row["parts"]]) == ("office", False, ["role"])
    assert set(row["parts"][0]["after"]) == {"can_oversee", "definition"}
    undone = o.c.post(f"/church/map/changes/{change['id']}/undo?business_id={LC}")
    assert undone.status_code == 200 and role(lc, "team_leader")["can_oversee"] is False
    assert role(lc, "team_leader")["definition"] == "Leads one team."
    r = o.patch("team_leader", {"term_months": 12, "can_lead": False})
    parts = next(x for x in lc.t["church_map_changes"] if x["id"] == r.json()["change"]["id"])["parts"]
    assert set(parts[0]["after"]) == {"can_lead"} and role(lc, "team_leader")["term_months"] == 12, \
        "a field a change doesn't keep goes in first, as today"
    r = o.patch("elders", {"can_board_yes": True})
    assert (r.status_code, r.json()["detail"]) == (403, batch.BOARD_YES)
    assert o.patch("elders", {"can_board_yes": False, "can_lead": True}).status_code == 200, \
        "a board yes sent as it reads is no change"
    assert o.c.post(f"/church/roles?business_id={LC}",
                    json={"title": "Finance Elder", "job": "pastoral", "can_board_yes": True}).status_code == 403
    o.as_(LC)
    r = o.patch("elders", {"can_board_yes": True})
    assert r.status_code == 200 and r.json()["change"]["money"] is True and role(lc, "elders")["can_board_yes"]


@pytest.mark.parametrize("closed", ["step2_absent", "map_off"])
def test_before_step_2_or_with_the_map_closed_a_switch_save_is_todays_and_logs_nothing(monkeypatch, closed):
    db = build(monkeypatch, migrated2=closed != "step2_absent")
    if closed == "map_off":
        monkeypatch.setenv("CHURCH_MAP", "off")
    o = Desk(db).as_(LC, "minnie")
    r = o.patch("team_leader", {"can_oversee": True})
    assert r.status_code == 200 and "change" not in r.json() and role(db, "team_leader")["can_oversee"] is True
    assert not db.t["church_map_changes"]
    assert o.as_(LC, "naiya").patch("team_leader", {"can_oversee": False}).status_code == 403, "the seat rule holds"


# ─── A team role is named by its team, not its key (rule a) ───────────

def test_role_name_reads_what_the_role_covers_not_its_key():
    assert cfu.role_name({"role": "usher_board", "scope": "Greeters Team",
                          "def": {"covers": "team", "title": "Usher Board president"}}) == "the Greeters Team"
    assert cfu.role_name({"role": "team_leader", "scope": "Kitchen",
                          "def": {"covers": "church", "title": "Team leads"}}) == "Team leads", "data decides"
    assert cfu.role_name({"role": "team_leader", "scope": "Kitchen"}) == "the Kitchen team", "the first version's"
    assert "team_leader" not in inspect.getsource(cfu.role_name)
