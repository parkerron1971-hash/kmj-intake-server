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
    first, then the church's people (found by the server, past 1,000 rows);
    none or two changes nothing
  * seats: a Manager reads and can't write; an admin writes; money is the
    owner's; a Member, a stranger, nobody signed in, an unattended run are
    refused
  * Chief's own idea waits; apply and discard; draft_map always waits
  * a part that went in: the id of the change it acted on (none when its
    row didn't save), and applying it again finishes it; a receipt that
    can't be read back, or a change whose row didn't save, is still a
    success, the second promising no Undo; a finished undo promises none;
    undoing an adopted ready-made lets its waiting change go; an older
    waiting change, once made, still gets its lines (#1729 review)
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
MEMBER = "9a000000-0000-4000-8000-000000000008"


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


def test_a_name_past_the_first_thousand_people_is_found_by_the_server(db):
    """#1729 review: one read gets 1,000 rows at most, so the server filters by the name."""
    def person(n, name):
        cid = f"4c000000-0000-4000-9000-{n:012d}"
        db.t["contacts"].append({"id": cid, "business_id": RV, "name": name, "status": "active", "metadata": {}})
        return cid
    for n in range(1100):
        person(n, f"R Filler {n}")
    zora, ann = person(2000, "Zora  Quill"), person(2001, "Ann O'Hara, Jr.")
    n = chm._Names(RV)
    assert n.person("zora quill") == n.person("Zora") == zora and n.person("ann o'hara, jr.") == ann
    person(2002, "Zora Banks")
    out = run(db, "change_map", {"changes": [{"kind": "department", "name": "Youth", "status": "draft",
                                              "leader": "Zora"}]}, RV)
    assert out["result"] == "Failed: “Zora” could be Zora Banks and Zora Quill", "its twin past row 1,000 too"


# ─── Seats and money ──────────────────────────────────────────────────

def test_a_manager_reads_an_admin_writes_and_money_is_the_owners(db):
    oversee = {"changes": [{"kind": "role", "role": "Team leader", "can_oversee": True}]}
    db.t["business_users"].append({"business_id": LC, "user_id": MEMBER, "role": "member", "status": "active",
                                   "invited_email": "web@lovecity.org", "lane": None, "areas": None,
                                   "contact_id": None, "name": "Web Team"})
    db.who[LC]["web@"] = MEMBER
    assert ok(run(db, "list_map", {}, LC, "naiya"))["label"] == "Leaders map"
    for who in ("naiya", "web", "stranger"):
        for verb in chm.WRITES:
            assert run(db, verb, oversee, LC, who)["result"] == "Failed: " + chm.NOT_YOURS, (who, verb)
    for who in ("web", "stranger"):
        assert "its admins and its Manager logins" in run(db, "list_map", {}, LC, who)["result"], who
    assert not changes(db, LC) and not role_row(db, "team_leader", LC)["can_oversee"]
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


def _departments_fail(db, monkeypatch):
    real = db.patch
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda path, body, **k: None if path.startswith(
        "/church_departments") else real(path, body, **k))
    return lambda: monkeypatch.setattr(sb_clients, "sb_patch_as_service", real)


def _log_fails(db, monkeypatch):
    real = db.post
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda path, body, prefer=None, **k: None if (
        path.startswith("/church_map_changes")) else real(path, body, prefer, **k))
    return lambda: monkeypatch.setattr(sb_clients, "sb_post_as_service", real)


def test_a_part_that_went_in_names_the_change_it_acted_on_and_applying_it_again_finishes_it(db, monkeypatch):
    """#1729 review: the change this call was, never the newest failed one."""
    a = ok(run(db, "change_map", {"stage": True, "changes": [
        {"kind": "role", "role": "deacons", "can_shepherd": True},
        {"kind": "department", "department": "Youth", "support_duty": "first_guests"}]}, LC))
    mend = _departments_fail(db, monkeypatch)
    b = run(db, "change_map", {"changes": [{"kind": "role", "role": "Team leader", "can_oversee": True},
                                           {"kind": "department", "department": "Youth", "area": "office"}]}, LC)
    assert b["failed"] and b["result"].endswith("apply it again to finish it.")
    assert b["change_id"] == changes(db, LC)[-1]["id"] != a["change_id"]
    out = run(db, "apply_map_change", {"change_id": a["change_id"]}, LC)
    assert out["failed"] and out["change_id"] == a["change_id"], "the change it was asked to make, not B"
    logged = _log_fails(db, monkeypatch)
    out = run(db, "change_map", {"changes": [{"kind": "role", "role": "Elders", "can_lead": False},
                                             {"kind": "department", "department": "Prayer", "area": "office"}]}, LC)
    assert out["failed"] and "its record didn’t save" in out["result"] and "change_id" not in out, \
        "no row: it says so, and names no other change"
    logged()
    mend()
    for c in (a, b):
        ok(run(db, "apply_map_change", {"change_id": c["change_id"]}, LC))
    assert [c["status"] for c in changes(db, LC)] == ["applied", "applied"]


def test_a_receipt_that_cant_be_read_back_still_says_it_was_made(db, monkeypatch):
    import action_inverse as ai
    import chief_of_staff as cos
    import church_map_batch as batch

    def unread(*a, **k):
        raise chm.HTTPException(503, "Your leaders map couldn’t be read just now. Try again in a moment.")
    monkeypatch.setattr(batch, "lines_of", unread)
    out = run(db, "change_map", {"changes": [{"kind": "role", "role": "deacons", "can_shepherd": True}]}, LC)
    assert out["result"] == ("Changed the leaders map. Its details couldn’t be read back just now; the map’s list "
                             "of changes shows them. It’s one change in the map’s list. Undo puts it back.")
    assert not cos._action_failed(out) and out["label"] == "A change to the map", "a success: data_changed is set"
    assert ai.build_inverse("change_map", {}, out)["change_id"] == out["change_id"]
    assert not cos._action_failed(undo(db, out, LC))


def test_a_change_whose_record_didnt_save_is_made_and_promises_no_undo(db, monkeypatch):
    import action_inverse as ai
    _log_fails(db, monkeypatch)
    out = ok(run(db, "change_map", {"changes": [{"kind": "role", "role": "deacons", "can_shepherd": True}]}, LC))
    assert out["result"] == ("Changed the leaders map as asked. Its record didn’t save, so Undo can’t put it back "
                             "from the map’s list: to reverse it, ask for it the other way.")
    assert out["changed"] and role_row(db, "deacons", LC)["can_shepherd"] is True
    assert ai.build_inverse("change_map", {}, out) is None and not changes(db, LC)
    out = ok(run(db, "adopt_template", {"kind": "role", "key": "any.media_lead"}, LC))
    assert out["result"].endswith("Their record didn’t save, so Undo can’t take them out: remove the drafts in "
                                  "Leaders & roles.") and ai.build_inverse("adopt_template", {}, out) is None


def test_a_waiting_change_whose_mark_didnt_save_promises_no_undo_until_it_reads_made(db, monkeypatch):
    """#1729 review: apply_pending made it, but marking it applied failed, so it still reads waiting."""
    import action_inverse as ai
    idea = ok(run(db, "change_map", {"stage": True, "changes": [
        {"kind": "role", "role": "Youth Minister", "can_oversee": True}]}, GRACE))
    real = db.patch
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda path, body, **k: None if path.startswith(
        "/church_map_changes") else real(path, body, **k))
    made = ok(run(db, "apply_map_change", {"change_id": idea["change_id"]}, GRACE))
    assert made["result"].endswith(chm.UNMARKED) and "Undo puts it back" not in made["result"]
    assert made["changed"] and "change_id" not in made and ai.build_inverse("apply_map_change", {}, made) is None
    assert role_row(db, "youth_minister", GRACE)["can_oversee"] is True, "it was made"
    assert run(db, "undo_map_change", {"change_id": idea["change_id"]}, GRACE)["result"] == \
        "Failed: Only a change that was made can be put back.", "which is why no Undo was promised"
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", real)
    again = ok(run(db, "apply_map_change", {"change_id": idea["change_id"]}, GRACE))
    assert again["result"].endswith("Undo puts it back.") and again["change_id"] == idea["change_id"]
    assert [c["status"] for c in changes(db, GRACE)] == ["applied"], "applying it again only marked it"
    undo(db, again, GRACE)
    assert not role_row(db, "youth_minister", GRACE)["can_oversee"]


def test_finishing_an_undo_promises_no_undo_of_it(db, monkeypatch):
    import action_inverse as ai
    made = ok(run(db, "change_map", {"changes": [
        {"kind": "department", "department": "Youth", "support_duty": "first_guests"},
        {"kind": "role", "role": "Team leader", "can_oversee": True}]}, LC))
    mend = _departments_fail(db, monkeypatch)
    half = run(db, "undo_map_change", {"change_id": made["change_id"]}, LC)
    assert half["failed"] and half["change_id"] == changes(db, LC)[-1]["id"]
    mend()
    done = ok(run(db, "apply_map_change", {"change_id": half["change_id"]}, LC))
    assert done["result"].startswith("Finished putting a change back. ") and "Undo puts it back" not in done["result"]
    assert ai.build_inverse("apply_map_change", {}, done) is None
    assert ai.build_inverse("apply_map_change", {}, {"changed": True, "change_id": "c1", "undoes": "c0"}) is None
    assert changes(db, LC)[0]["status"] == "undone"


def test_undoing_an_adopted_ready_made_lets_its_waiting_change_go(db):
    out = ok(run(db, "adopt_template", {"kind": "shape", "key": "multi_staff"}, GRACE))
    put = undo(db, out, GRACE)
    assert put["let_go"] == [out["waiting_id"]] and "was let go too" in put["result"]
    assert run(db, "apply_map_change", {"change_id": out["waiting_id"]}, GRACE)["result"] == \
        "Failed: That change isn’t waiting to be made."
    ok(run(db, "adopt_template", {"kind": "shape", "key": "multi_staff"}, GRACE))
    assert [c["status"] for c in changes(db, GRACE)].count("pending") == 1, "adopting again waits once"


def test_an_older_waiting_change_still_gets_its_lines(db):
    import church_map_batch as batch
    a = ok(run(db, "change_map", {"stage": True, "changes": [
        {"kind": "role", "role": "Team leader", "can_oversee": True}]}, LC))
    for i in range(31):         # more than the sheet's recent list
        batch.apply(church(db, LC), [{"kind": "shepherding", "cap": 9 + i % 2}], church(db, LC)["owner_id"],
                    "office", role="owner")
    out = ok(run(db, "apply_map_change", {"change_id": a["change_id"]}, LC))
    assert "Team leader: can oversee a department off → on." in out["result"]


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
