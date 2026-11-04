"""Chief changes a church's leaders map in plain words, with Undo (chief_map.py;
docs/CHURCH_LEADERS_STEP2.md §4, §7 B5).

Pins:
  * wiring: eight handlers, classified (two reads, six class-A writes, all
    Chief's alone), placed in chief_areas, in the prompt with Kevin's three
    examples; list_map and search_templates are mid-turn reads, the writes are
    action tags; undo_last's inverse of a change is undo_map_change
  * every answer has a result and a label, a failure too
  * Kevin's examples at the churches: the overseer whose role can't oversee
    (refused with words, then made with the role part first), Deacons
    shepherding, a Media department from a ready-made; each before → now and
    "Undo puts it back", and Undo through the inverse
  * names: a whole name, a unique first name, a title and last name, holders
    first, then the church's people; none or two changes nothing
  * seats: a Manager reads and can't write; an admin writes; money is the
    owner's; nobody signed in, a stranger, an unattended run are refused
  * Chief's own idea waits; apply and discard; draft_map always waits
  * a part that went in: the change id, and applying it again finishes it
  * the switch (off, the platform owner's login) and step 2's file
  * the reads write nothing at any of the four churches"""
from __future__ import annotations

import asyncio
import contextlib
import copy
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.dirname(HERE), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import chief_areas as ca  # noqa: E402
import chief_map as chm  # noqa: E402
import sb_clients  # noqa: E402
from church_three import FOUR, GRACE, LOVE_CITY as LC, NAMES, NEW_HOPE as NH, OWNER_EMAIL, RIVERSIDE as RV, build, \
    church  # noqa: E402
from test_church_map_changes import changes, state  # noqa: E402

VERBS = ("list_map", "change_map", "draft_map", "undo_map_change", "apply_map_change", "discard_map_change",
         "search_templates", "adopt_template")
STRANGER = "9a000000-0000-4000-8000-000000000009"


@pytest.fixture
def db(monkeypatch):
    return build(monkeypatch)


@contextlib.contextmanager
def signed_in(uid):
    import chief_of_staff as cos
    token = cos._TURN_USER_ID.set(uid or "")
    try:
        yield
    finally:
        cos._TURN_USER_ID.reset(token)


def run(db, verb, action, biz=LC, who=None):
    """`who`: a login's handle (db.who), "nobody", "stranger", else the church's owner."""
    import chief_of_staff as cos
    uid = {None: church(db, biz)["owner_id"], "nobody": None, "stranger": STRANGER}[who] if who in (
        None, "nobody", "stranger") else db.who[biz][who + "@"]
    with signed_in(uid):
        return asyncio.run(cos.ACTION_HANDLERS[verb](None, {"id": biz}, dict(action)))


def ok(out):
    assert not out.get("failed"), out["result"]
    return out


def role_row(db, key, biz):
    return next(r for r in db.t["church_role_defs"] if r["business_id"] == biz and r["key"] == key)


def undo(db, out, biz):
    import action_inverse as ai
    inv = ai.build_inverse(out["type"], {}, out)
    assert inv and inv["type"] == "undo_map_change", out
    return ok(run(db, "undo_map_change", inv, biz))


# ─── Wiring ───────────────────────────────────────────────────────────

def test_the_verbs_are_wired_classified_placed_and_in_the_prompt():
    import action_inverse as ai
    import action_registry as ar
    import chief_of_staff as cos
    import chief_tool_loop as ctl
    import mcp_server
    from __tests__._chief_source import chief_source
    for verb in VERBS:
        assert cos.ACTION_HANDLERS[verb] is getattr(cos, f"handle_{verb}"), verb
        assert ar.classification(verb).get("chief_only") and not ar.may_expose_to_agent(verb, allow_writes=True)
        assert verb not in mcp_server.WRITE_TOOL_SCHEMAS and verb not in mcp_server.TOOL_SCHEMAS, verb
        assert (ar.effect(verb) == "read") == (verb in ("list_map", "search_templates")), verb
        assert ar.effect(verb) == "read" or (ar.reversibility(verb) == "A" and not ar.is_bulk(verb)), verb
    assert ar.is_sensitive("list_map")
    assert {"list_map", "search_templates"} <= {t["name"] for t in ctl.read_tool_definitions()}
    ctl.reset_turn(writes_allowed=True)
    assert not set(VERBS) & {t["name"] for t in ctl.write_tool_definitions()}
    ctl.reset_turn()
    assert ca.VERBS["list_map"] == ca.VERBS["search_templates"] == (ca.ALL,)
    assert set(chm.WRITES) <= ca.OWNERS
    src = chief_source()
    for said in ("Make Deacon Brown the overseer of Youth", "Deacons shepherd families now",
                 "Add a Media department, helped by the office", '"type":"change_map"', '"type":"adopt_template"',
                 '"type":"undo_map_change"', "list_map", "search_templates"):
        assert said in src, said
    for verb in ("change_map", "adopt_template", "apply_map_change"):
        assert ai.build_inverse(verb, {}, {"changed": True, "change_id": "c1"}) == {
            "type": "undo_map_change", "change_id": "c1"}
        assert ai.build_inverse(verb, {}, {"changed": False, "change_id": "c1", "waiting": True}) is None
        assert ai.build_inverse(verb, {}, {"failed": True, "result": "Failed: x"}) is None


def test_the_reads_are_mid_turn_and_a_change_goes_through_a_tag(db):
    import chief_tool_loop as ctl
    with signed_in(church(db, LC)["owner_id"]):
        err, text = asyncio.run(ctl.execute_tool_use(None, {"id": LC}, "list_map", {}))
        assert not err and "Departments:" in text and "Yolanda Reed" in text
        err, text = asyncio.run(ctl.execute_tool_use(None, {"id": LC}, "search_templates", {"q": "greeter"}))
        assert not err and "Usher Board president" in text
        err, text = asyncio.run(ctl.execute_tool_use(None, {"id": LC}, "change_map", {"changes": []}))
        assert err and "[ACTION:]" in text
    assert not changes(db, LC)


SCENES = [(v, a, b, w) for v, a in (
    ("list_map", {}), ("search_templates", {"q": "youth"}), ("adopt_template", {"kind": "role", "key": "nope"}),
    ("change_map", {"changes": [{"kind": "role", "role": "Youth Pastor", "can_oversee": True}]}),
    ("change_map", {"changes": [{"kind": "department", "department": "Nope", "leader": "Zed"}]}),
    ("draft_map", {"phase": "leaders", "changes": [{"kind": "department", "name": "Media", "status": "draft"}]}),
    ("undo_map_change", {}), ("apply_map_change", {"change_id": STRANGER}), ("discard_map_change", {"change_id": 1}))
    for b, w in ((LC, None), (LC, "naiya"), (LC, "nobody"), (RV, None), (LC, "stranger"))]


@pytest.mark.parametrize("verb,action,biz,who", SCENES)
def test_every_answer_has_a_result_and_a_label(db, verb, action, biz, who):
    for out in (run(db, verb, action, biz, who), run(db, verb, {**action, "_unattended": True}, biz)):
        assert isinstance(out.get("result"), str) and out["result"] and isinstance(out.get("label"), str) \
            and out["label"] and out["type"] == verb, out


@pytest.mark.parametrize("verb", VERBS)
def test_a_read_that_fails_still_answers_and_an_unattended_run_is_refused(db, monkeypatch, verb):
    out = run(db, verb, {"_unattended": True})
    assert out["failed"] and "only when someone in the church's office asks" in out["result"] and out["label"]
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda *a, **k: None)
    out = run(db, verb, {"changes": [{"kind": "shepherding", "cap": 9}], "change_id": STRANGER, "q": "x"})
    assert out["failed"] and out["result"].startswith("Failed: ") and out["label"], out


# ─── Kevin's three examples ───────────────────────────────────────────

def test_make_deacon_ward_the_overseer_of_youth_after_asking_about_her_role(db):
    youth = [{"kind": "department", "department": "youth", "overseer": "Deacon Ward"}]
    out = run(db, "change_map", {"said": "Make Deacon Ward the overseer of Youth", "changes": youth}, NH)
    assert out["failed"] and "Celia Ward doesn’t hold a role that can oversee a department" in out["result"]
    assert "role part" in out["note_for_chief"] and not changes(db, NH), "refused with words, nothing changed"
    before = state(db, NH)
    out = ok(run(db, "change_map", {"changes": [{"kind": "role", "role": "Deacons", "can_oversee": True}] + youth}, NH))
    assert out["result"] == ("Changed the leaders map. Deacons: can oversee a department off → on. Youth: overseer "
                             "Amara Stone → Celia Ward. It’s one change in the map’s list. Undo puts it back.")
    assert out["label"] == "2 changes to the map" and out["changed"] and not out["money"]
    [row] = changes(db, NH)
    assert (row["origin"], row["status"], row["said"]) == ("chief", "applied", "")
    put = undo(db, out, NH)
    assert put["result"].startswith("Put that change back. Youth: overseer Celia Ward → Amara Stone. Deacons: can "
                                    "oversee a department on → off.")
    assert state(db, NH) == before


@pytest.mark.parametrize("biz", (LC, NH), ids=lambda b: NAMES[b])
def test_deacons_shepherd_families_now(db, biz):
    out = ok(run(db, "change_map", {"changes": [{"kind": "role", "role": "deacons", "can_shepherd": True}]}, biz))
    assert out["result"].startswith("Changed the leaders map. Deacons: shepherds families ") and \
        out["result"].endswith("→ on. It’s one change in the map’s list. Undo puts it back.")
    assert role_row(db, "deacons", biz)["can_shepherd"] is True
    undo(db, out, biz)
    assert role_row(db, "deacons", biz)["can_shepherd"] is not True


@pytest.mark.parametrize("biz", (LC, RV), ids=lambda b: NAMES[b])
def test_add_a_media_department_helped_by_the_office(db, biz):
    before = state(db, biz)
    out = ok(run(db, "adopt_template", {"kind": "ministry", "key": "Media & Production"}, biz))
    assert out["result"] == ("Added 2 drafts: Media lead, Media & Production. They come in as drafts: nothing goes to "
                             "them until they’re live. Undo puts it back.")
    dept = next(d for d in db.t["church_departments"] if d["business_id"] == biz and d["name"] == "Media & Production")
    assert (dept["status"], dept["support_duty"]) == ("draft", "stream")
    same = ok(run(db, "change_map", {"changes": [{"kind": "department", "department": "media & production",
                                                  "support_duty": "stream"}]}, biz))
    assert same["result"] == "Nothing changed: the leaders map already reads that way." and not same["changed"]
    undo(db, out, biz)
    assert state(db, biz) == before, "the drafts it made are gone"


# ─── Names ────────────────────────────────────────────────────────────

def test_names_resolve_exactly_holders_first_or_nothing_changes(db):
    db.t["contacts"].append({"id": "2c000000-0000-4000-8000-000000000999", "business_id": GRACE,
                             "name": "Daniel Price", "status": "active", "email": "dp@x.org", "metadata": {}})
    n = chm._Names(GRACE)
    moore = db.who[GRACE]["daniel"]
    assert n.person("daniel") == n.person("  DANIEL moore ") == n.person("Deacon Moore") == moore, "holders first"
    assert n.person("Daniel Price") == "2c000000-0000-4000-8000-000000000999", "then the church's people"
    assert n.role("Deacon Board") == n.role("deacons") == role_row(db, "deacons", GRACE)["id"]
    db.t["church_leader_roles"].append({"id": "2d000000-0000-4000-8000-000000000999", "business_id": GRACE,
                                        "contact_id": "2c000000-0000-4000-8000-000000000999", "role": "deacons",
                                        "scope": "", "status": "active", "answers_to_contact_id": None})
    for raw, says in (("Daniel", "“Daniel” could be Daniel Moore and Daniel Price"),
                      ("Zed", "Nobody at this church is called “Zed”")):
        out = run(db, "change_map", {"changes": [{"kind": "department", "department": "Youth", "overseer": raw}]},
                  GRACE)
        assert out["failed"] and says in out["result"], out["result"]
    out = run(db, "change_map", {"changes": [{"kind": "department", "department": "Teens", "area": "kids_youth"}]},
              GRACE)
    assert out["result"] == "Failed: There’s no department called “Teens” here"
    assert not changes(db, GRACE), "nothing unknown or shared changed anything"
    # Riverside holds no roles: its people, by a first name only one has, on a draft.
    out = ok(run(db, "change_map", {"changes": [{"kind": "department", "name": "Youth", "status": "draft",
                                                 "area": "Kids & youth", "leader": "Henry"}]}, RV))
    assert out["result"].startswith("Changed the leaders map. Made Youth as a draft.")
    d = next(d for d in db.t["church_departments"] if d["business_id"] == RV)
    assert (d["leader_contact_id"], d["area"], d["source"]) == (db.who[RV]["henry"], "kids_youth", "chief")


# ─── Seats and money ──────────────────────────────────────────────────

def test_a_manager_reads_an_admin_writes_and_money_is_the_owners(db):
    oversee = {"changes": [{"kind": "role", "role": "Team leader", "can_oversee": True}]}
    assert ok(run(db, "list_map", {}, LC, "naiya"))["label"] == "Leaders map"
    for verb in chm.WRITES:
        assert run(db, verb, oversee, LC, "naiya")["result"] == "Failed: " + chm.NOT_YOURS, verb
    assert "its admins and its Manager logins" in run(db, "list_map", {}, LC, "stranger")["result"]
    assert "signed in" in run(db, "list_map", {}, LC, "nobody")["result"]
    assert ok(run(db, "change_map", oversee, LC, "minnie"))["changed"], "an admin changes the map"
    for part, says in (({"kind": "settings", "pastor_from_cents": 30_000}, "Only the owner changes the church’s money"),
                       ({"kind": "role", "role": "Elders", "can_board_yes": True}, "who gives the board’s yes")):
        out = run(db, "change_map", {"changes": [part]}, LC, "minnie")
        assert out["failed"] and says in out["result"], out["result"]
    money = ok(run(db, "change_map", {"changes": [{"kind": "settings", "pastor_from_cents": 30_000}]}, LC))
    assert "Your church: the pastor’s yes from the usual → $300." in money["result"] and money["money"]
    assert "Only the owner" in run(db, "undo_map_change", {"change_id": money["change_id"]}, LC, "minnie")["result"]
    undo(db, money, LC)


def test_chiefs_own_idea_waits_then_is_made_or_let_go(db):
    idea = {"stage": True, "changes": [{"kind": "role", "role": "Youth Minister", "can_oversee": True}]}
    out = ok(run(db, "change_map", idea, GRACE))
    assert out["result"] == ("Saved for a yes; nothing changed yet. Youth Minister: can oversee a department off → "
                             "on. It waits under “Waiting for your yes” in Leaders & roles until the owner or an admin "
                             "says yes.") and out["waiting"] and not out["changed"]
    assert not role_row(db, "youth_minister", GRACE)["can_oversee"]
    assert f"- change {out['change_id']} (by Chief" in run(db, "list_map", {}, GRACE, "sharon")["result"]
    made = ok(run(db, "apply_map_change", {"change_id": out["change_id"]}, GRACE, "thelma"))
    assert made["result"].endswith("Undo puts it back.") and role_row(db, "youth_minister", GRACE)["can_oversee"]
    undo(db, made, GRACE)
    again = ok(run(db, "change_map", idea, GRACE))
    gone = ok(run(db, "discard_map_change", {"change_id": again["change_id"]}, GRACE))
    assert gone["result"].startswith("Let the waiting change go; nothing on the map changed.")
    coach = ok(run(db, "draft_map", {"phase": "ministries", "changes": [{"kind": "department", "name": "Media"}]},
                   GRACE))
    row = next(r for r in changes(db, GRACE) if r["id"] == coach["change_id"])
    assert (row["status"], row["origin"], row["phase"]) == ("pending", "session", "ministries"), "always waits"
    assert [r["status"] for r in changes(db, GRACE)] == ["undone", "applied", "discarded", "pending"]


def test_a_part_that_went_in_names_the_change_and_applying_it_again_finishes_it(db, monkeypatch):
    real = db.patch
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda path, body, **k: None if path.startswith(
        "/church_departments") else real(path, body, **k))
    two = {"changes": [{"kind": "role", "role": "Team leader", "can_oversee": True},
                       {"kind": "department", "department": "Youth", "support_duty": "first_guests"}]}
    out = run(db, "change_map", two, LC)
    assert out["failed"] and out["result"].endswith("apply it again to finish it.")
    assert out["change_id"] == changes(db, LC)[0]["id"] and changes(db, LC)[0]["status"] == "failed"
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", real)
    ok(run(db, "apply_map_change", {"change_id": out["change_id"]}, LC))
    assert changes(db, LC)[0]["status"] == "applied"


# ─── The switch and step 2's file ─────────────────────────────────────

def test_the_switch_follows_the_routes_and_needs_step_2s_file(db, monkeypatch):
    import platform_suite
    monkeypatch.setattr(platform_suite, "_owner_email", lambda uid: OWNER_EMAIL.get(str(uid)))
    monkeypatch.setattr(chm, "_EMAILS", {})
    monkeypatch.setenv("CHURCH_MAP", "off")
    assert run(db, "list_map", {})["result"] == "Failed: " + chm.NOT_ON
    monkeypatch.setenv("CHURCH_MAP", "owner")
    assert ok(run(db, "list_map", {}))
    assert run(db, "list_map", {}, GRACE)["result"] == "Failed: " + chm.NOT_ON, "not the platform owner's login"
    chm._EMAILS.clear()
    monkeypatch.setattr(platform_suite, "_owner_email", lambda uid: 1 / 0)
    assert "couldn't be checked" in run(db, "list_map", {})["result"]


def test_before_step_2s_file_chief_says_the_map_isnt_ready(monkeypatch):
    db = build(monkeypatch, migrated2=False)
    for verb in VERBS:
        assert run(db, verb, {"changes": [{"kind": "shepherding", "cap": 9}]})["result"] == "Failed: " + chm.NOT_READY


def test_the_reads_write_nothing_at_any_of_the_four_churches(db):
    before = copy.deepcopy(db.t)
    for biz in FOUR:
        assert ok(run(db, "list_map", {}, biz))["result"].startswith("The leaders map at ")
        assert ok(run(db, "search_templates", {"q": "greeter", "kind": "role"}, biz))["found"] == 4
    assert db.t == before
