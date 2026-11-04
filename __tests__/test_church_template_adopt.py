"""Adopting a ready-made makes the church its own copy (docs/CHURCH_LEADERS_STEP2.md
§2.4, §2.5; §7 B4b).

A role, a department and a shape, adopted at each of the four churches, come
in as drafts (source 'template', with where they came from) in one change that
Undo takes back out. What they would change on a live row waits for a yes, the
board's yes the owner's; a live row is never edited. What a church already
has is named and left alone, so adopting again makes and logs nothing, and a
later version never touches a copy. The route is the owner's or an admin's,
behind CHURCH_MAP, and a 503 before step 2's file."""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.dirname(HERE), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_map as cm  # noqa: E402
import church_map_batch as batch  # noqa: E402
import church_roles as cr  # noqa: E402
import church_templates as ct  # noqa: E402
import sb_clients  # noqa: E402
from church_three import (CHURCHES, FOUR, GRACE, LOVE_CITY as LC, NAMES, NEW_HOPE as NH,  # noqa: E402
                          RIVERSIDE as RV, build, church)
from test_church_map_changes import changes, owner, refused, state  # noqa: E402
from test_church_map_writes import Office  # noqa: E402


@pytest.fixture
def db(monkeypatch):
    return build(monkeypatch)


def adopt(db, biz, kind, key, *, role="owner", by=None, **k):
    return ct.adopt(church(db, biz), kind, key, by or owner(db, biz), role=role, **k)


def row(db, x):
    return next(r for r in db.t["church_role_defs" if x["kind"] == "role" else "church_departments"]
                if r["id"] == x["id"])


def live(db, biz):
    """What adopting never touches: the active roles and departments, what
    hangs from those, who holds what, the settings and Shepherding's."""
    s, on = state(db, biz), ("status", repr("active"))
    act = {("department_id", repr(d["id"])) for d in db.t["church_departments"]
           if d["business_id"] == biz and d["status"] == "active"}
    return {**s, "roles": [r for r in s["roles"] if on in r], "departments": [d for d in s["departments"] if on in d],
            "units": [u for u in s["units"] if act & set(u)]}


def waiting_lines(db, biz):
    return [x for c in batch.recent(church(db, biz), "owner")["pending"] for x in c["lines"]]


# ─── Each kind, at every church ───────────────────────────────────────

@pytest.mark.parametrize("biz", FOUR, ids=lambda b: NAMES[b])
def test_each_kind_comes_in_as_drafts_and_never_touches_a_live_row(db, biz):
    before = live(db, biz)
    for kind, key in (("role", "any.media_lead"), ("department", "outreach"), ("shape", "pastor_led")):
        out = adopt(db, biz, kind, key)
        assert out["made"] and out["change"]["status"] == "applied", (kind, out["said"])
        logged = next(r for r in changes(db, biz) if r["id"] == out["change"]["id"])
        assert (logged["origin"], logged["money"], len(logged["parts"])) == ("template", False, len(out["made"]))
        for m in out["made"]:
            r = row(db, m)
            assert (r["status"], r["source"], r["template_key"], r["template_version"]) == (
                "draft", "template", m["key"], ct.ALL[m["key"]]["version"]), m
            if m["kind"] == "role":
                assert (r["title"], r["catalog_key"]) == (ct.ROLES[m["key"]]["title"], ct.ROLES[m["key"]]["row"])
            else:
                assert (r.get("leader_contact_id"), r.get("overseer_contact_id")) == (None, None), "no people named"
    assert live(db, biz) == before, "a live row is never edited: what it would change there waits"
    assert not [r for r in db.t["church_role_settings"] if r["business_id"] == RV], "Riverside stays unseeded"


def test_the_three_churches_adopting_one_shape_differ_only_in_titles(monkeypatch):
    """Once each one's waiting change is made. What hangs from a department
    is the church's own data, and made_for is its tradition's row (Grace's
    Baptist prayer rows are first in line for prayer), so neither is compared."""
    db = build(monkeypatch, filled=False)
    got, titles = {}, {}
    for biz in CHURCHES:
        out = adopt(db, biz, "shape", "pastor_led")
        batch.apply_pending(church(db, biz), out["waiting"]["id"], owner(db, biz), role="owner")
        ids = {x["key"]: x["id"] for x in out["made"] + out["yours"]}
        home = ct.tradition_of(church(db, biz), cr.settings(biz))
        seats = [(s["seat"], row(db, {"kind": "role", "id": ids[s["keys"][home]]}))
                 for s in ct.SHAPES["pastor_led"]["roles"]]
        got[biz] = ([(s, r["job"], *(r[k] for k in cr.SWITCHES)) for s, r in seats], sorted(
            (d["name"], d["area"], d["support_duty"], d["status"], d["template_key"])
            for d in db.t["church_departments"] if d["business_id"] == biz))
        titles[biz] = [r["title"] for _s, r in seats]
    assert got[LC] == got[GRACE] == got[NH]
    assert [d[0] for d in got[LC][1]] == ["Children", "Prayer", "Welcome & Guest Services", "Worship & Arts"]
    assert titles == {
        LC: ["Lead Pastor", "Intercessor leader", "Intercessors", "Team leader", "Welcome Team lead", "Worship Leader",
             "Children’s Director"],
        GRACE: ["Pastor", "Prayer ministry leader", "Prayer warriors", "Team leader", "Hospitality ministry lead",
                "Minister of Music", "Children’s Director"],
        NH: ["Senior Pastor", "Intercessor leader", "Intercessors", "Team leader", "Welcome Team lead",
             "Worship Director", "Children’s Director"]}


# ─── Already yours, a second copy, a newer version ────────────────────

def test_what_the_church_has_is_named_and_name_makes_a_second_copy(db):
    for biz, says in ((LC, "Youth Pastor is already yours."), (NH, "Youth Pastor is already yours, as Youth Director.")):
        out = adopt(db, biz, "role", "nondenom.youth_pastor")
        assert (out["said"], out["made"], out["change"], out["waiting"]) == (says, [], None, None)
    assert adopt(db, GRACE, "department", "youth")["said"] == "Youth is already yours."
    assert not changes(db, LC) + changes(db, NH) + changes(db, GRACE), "nothing made, nothing logged"
    two = adopt(db, LC, "role", "nondenom.youth_pastor", name="Youth Pastor (Teens)")["made"][0]
    r = row(db, two)
    assert (r["title"], r["template_key"], r["catalog_key"], r["status"]) == (
        "Youth Pastor (Teens)", "nondenom.youth_pastor", "youth_pastor", "draft")
    assert r["key"] == "youth_pastor_teens" and "Youth Pastor (Teens)" in r["definition"]
    assert refused(adopt, db, LC, "role", "nondenom.youth_pastor", name="lead pastor", code=400) == \
        "There’s already a role called lead pastor"
    assert refused(adopt, db, GRACE, "department", "youth", name="Youth", code=400) == \
        "There’s already a department called Youth", "step 1's plain 400"
    assert row(db, adopt(db, GRACE, "department", "youth", name="Teens")["made"][0])["name"] == "Teens"
    for k, says in (({"name": "Ours"}, "not a whole church"), ({"tradition": "mormon"}, "one of the church types")):
        assert says in refused(adopt, db, GRACE, "shape", "pastor_deacons", code=400, **k)
    assert refused(adopt, db, GRACE, "role", "baptist.nobody", code=404) == "That ready-made isn’t here"


def test_a_copy_is_the_churchs_own_and_a_later_version_never_touches_it(db, monkeypatch):
    made = adopt(db, LC, "role", "baptist.usher_board")["made"][0]
    was = dict(row(db, made))
    assert (was["title"], was["template_version"], was["job"]) == ("Usher Board president", 1, "team")
    monkeypatch.setitem(ct.ROLES["baptist.usher_board"], "title", "Head usher")
    monkeypatch.setitem(ct.ROLES["baptist.usher_board"], "version", 2)
    out = adopt(db, LC, "role", "baptist.usher_board")
    assert out["said"] == "Head usher is already yours, as Usher Board president." and out["made"] == []
    assert row(db, made) == was and len(changes(db)) == 1, "the copy is a fork: the platform never writes it again"


# ─── Again, Undo, and what waits ──────────────────────────────────────

def test_adopting_again_makes_and_logs_nothing_and_undo_takes_out_exactly_the_drafts(db):
    before = state(db, GRACE)
    out = adopt(db, GRACE, "shape", "multi_staff")
    assert [m["name"] for m in out["made"] if m["kind"] == "role"][:2] == ["Executive Pastor", "Elders"]
    n = len(changes(db, GRACE))
    again = adopt(db, GRACE, "shape", "multi_staff")
    assert (again["made"], again["change"], again["waiting"], len(changes(db, GRACE))) == ([], None, None, n)
    assert again["said"] == "Everything in it is already yours."
    batch.undo(church(db, GRACE), out["change"]["id"], owner(db, GRACE), role="owner")
    assert state(db, GRACE) == before, "exactly the drafts it made are gone"


def test_a_shape_waits_for_a_yes_on_each_live_change_and_the_boards_yes_is_the_owners(db):
    admin = db.who[LC]["minnie@"]
    said = [w["line"] for w in ct.here(church(db, LC), ct.SHAPES["multi_staff"], "nondenom", cr.settings(LC))["waits"]]
    before = live(db, LC)
    out = adopt(db, LC, "shape", "multi_staff", role="admin", by=admin)
    assert live(db, LC) == before and out["said"].endswith(" What it would change on your live roles waits for your yes.")
    w = next(r for r in changes(db) if r["id"] == out["waiting"]["id"])
    assert (w["status"], w["money"], w["origin"]) == ("pending", True, "template")
    assert waiting_lines(db, LC) == said == ["Elders: gives the board’s yes on money off → on",
                                             "Your church: who gives the pastor’s yes the usual → Lead Pastor"]
    assert "Only the owner" in refused(batch.apply_pending, church(db, LC), w["id"], admin, role="admin", code=403)
    batch.apply_pending(church(db, LC), w["id"], owner(db), role="owner")
    assert next(r for r in db.t["church_role_defs"] if r["business_id"] == LC and r["key"] == "elders")["can_board_yes"]
    # A department: its leader's switch on a live role waits; on a new copy it is the copy's own.
    adopt(db, NH, "department", "prayer")
    assert waiting_lines(db, NH) == ["Intercessor leader: leads off → on"]
    made = adopt(db, RV, "department", "prayer")["made"]
    assert [(m["kind"], m["name"]) for m in made] == [("role", "Prayer leader"), ("department", "Prayer")]
    assert row(db, made[0])["can_lead"] is True and not changes(db, RV)[0]["money"]


def test_a_failed_read_of_what_waits_stops_before_any_draft_is_made(db, monkeypatch):
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **k: None if "origin=eq.template" in path else real(path, **k))
    before = state(db, GRACE)
    assert refused(adopt, db, GRACE, "shape", "multi_staff", code=503) == cm.UNREAD
    assert state(db, GRACE) == before and not changes(db, GRACE), "the plain 503, and nothing made"


def test_when_what_waits_didnt_save_adding_it_again_finishes_it(db, monkeypatch):
    """#1728 review: the drafts went in and the waiting change's row failed
    once. Its words say "Add it again to finish", and that does: the board's
    yes on the new Elders draft waits for the owner, once."""
    real, fails = db.post, [1]

    def post(path, body, prefer=None, **k):
        if path.startswith("/church_map_changes") and body.get("status") == "pending" and fails:
            return fails.pop() and None
        return real(path, body, prefer, **k)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    assert refused(adopt, db, GRACE, "shape", "multi_staff", code=503).endswith("Add it again to finish.")
    assert [c["status"] for c in changes(db, GRACE)] == ["applied"], "the drafts are in, nothing waits"
    out = adopt(db, GRACE, "shape", "multi_staff")
    assert out["made"] == [] and out["change"] is None and out["waiting"]
    w = next(r for r in changes(db, GRACE) if r["id"] == out["waiting"]["id"])
    assert (w["status"], w["money"]) == ("pending", True), "the owner's to make"
    assert waiting_lines(db, GRACE) == ["Prayer ministry leader: leads off → on",
                                        "Elders: gives the board’s yes on money off → on",
                                        "Your church: who gives the pastor’s yes the usual → Pastor",
                                        "Your church: who oversees the office the usual → Executive Pastor"]
    assert adopt(db, GRACE, "shape", "multi_staff")["waiting"] is None, "and only once"


def test_a_pick_of_a_draft_waits_until_that_role_is_live(db):
    out = adopt(db, RV, "shape", "bishop_led")
    assert waiting_lines(db, RV) == ["Your church: who gives the pastor’s yes the usual → Pastor",
                                     "Your church: who oversees the office the usual → Pastor"]
    assert refused(batch.apply_pending, church(db, RV), out["waiting"]["id"], owner(db, RV), role="owner") == \
        "That can’t be made now: A draft role can be picked once it’s live"


# ─── What hangs from a new department ─────────────────────────────────

def test_a_unit_is_filled_only_where_exactly_one_of_the_churchs_things_matches(db):
    def units(biz, key, **k):
        made = next(m for m in adopt(db, biz, "department", key, **k)["made"] if m["kind"] == "department")
        return [(u["kind"], u["label"] or u["group_id"]) for u in db.t["church_department_units"]
                if u["department_id"] == made["id"]]
    assert units(GRACE, "ushers") == [("serve_option", "Usher Board")]
    assert units(NH, "welcome") == [("serve_option", "Guest Experience")]
    assert units(LC, "welcome") == [], "Hospitality Team already hangs from Outreach & Welcome"
    assert units(LC, "womens") == [("group", next(g["id"] for g in db.t["groups"] if g["name"] == "Sisters in the City"))]
    assert units(RV, "children") == [("space", "kids")]
    form = next(f for f in db.t["intake_forms"] if f["business_id"] == GRACE)
    next(x for x in form["fields"] if x["name"] == "team")["options"] += ["Praise Team", "Mass Choir"]
    assert units(GRACE, "worship") == [], "two match: neither is picked"


# ─── The route ────────────────────────────────────────────────────────

def _post(o, biz, **body):
    return o.c.post(f"/church/map/templates/adopt?business_id={biz}", json=body)


def test_the_route_is_the_owners_or_an_admins_behind_the_switch(db, monkeypatch):
    o = Office(db)
    media = {"kind": "role", "key": "any.media_lead"}
    assert _post(o.as_(LC, "naiya"), LC, **media).status_code == 404, "a manager seat: the stranger's 404"
    assert "owner or an admin" in refused(adopt, db, LC, "role", "any.media_lead", role="manager", code=403)
    r = _post(o.as_(LC, "minnie"), LC, **media)
    assert r.status_code == 200 and r.json()["made"][0]["name"] == "Media lead", "an admin adopts"
    assert _post(o.as_(LC), LC, **media).json()["said"] == "Media lead is already yours."
    assert _post(o, LC, kind="team", key="youth").status_code == 404
    monkeypatch.setenv("CHURCH_MAP", "owner")
    assert _post(o.as_(GRACE), GRACE, **media).status_code == 404, "closed for this login"
    monkeypatch.setenv("CHURCH_MAP", "off")
    assert _post(o.as_(LC), LC, **media).status_code == 404


def test_before_step_2s_file_adopting_is_a_503(monkeypatch):
    db = build(monkeypatch, migrated2=False)
    r = _post(Office(db).as_(LC), LC, kind="role", key="any.media_lead")
    assert (r.status_code, r.json()["detail"]) == (503, batch.NOT_READY)
    assert not [x for x in db.t["church_role_defs"] if x.get("source") == "template"]
