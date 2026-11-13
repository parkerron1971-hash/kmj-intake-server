"""Chief puts people into a church's leader roles and takes them off
(chief_church_roles.py; docs/CHURCH_LEADERS_STEP2.md §4 ask_into_role).

Kevin, 2026-11-13: "allow for chief to be able to place people in leaders
position in the system so upon request, chief can do it. also make sure chief
is aware that they are members not clients."

Pins:
  * wiring: two handlers, class C and Chief's alone, never native tools, the
    Office's area, in the prompt; undo of an ask is take_off_role while it is
    unanswered
  * an ask is Leaders & roles' Ask: the row starts asked, the email goes, the
    receipt says asked (never said yes); asked again sends nothing; a team
    leader's role names a Serve card team
  * the page's own refusals say why and change nothing: an office role, a
    draft, no team, a team that isn't on the card, a role or person that
    isn't there
  * then the map: someone asked can be named a department's leader at once
  * take_off_role: an unanswered ask is taken back; a role they said yes to
    goes with what it handed them, and the receipt names the department
    they're still on; two of a role asks which; undo after a yes refuses
  * seats: the owner and a Manager may; a stranger, nobody signed in, an
    unattended run and a tainted turn may not
  * members, not clients: the ministry lens, the vertical block and the
    prompt say it"""
from __future__ import annotations

import asyncio
import contextlib
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.dirname(HERE), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from church_three import LOVE_CITY as LC, _mail, build, church  # noqa: E402

VERBS = ("ask_into_role", "take_off_role")
STRANGER = "9a000000-0000-4000-8000-000000000009"


@pytest.fixture
def db(monkeypatch):
    d = build(monkeypatch)
    d.sent = _mail(monkeypatch)
    return d


@contextlib.contextmanager
def signed_in(uid):
    import chief_of_staff as cos
    token = cos._TURN_USER_ID.set(uid or "")
    try:
        yield
    finally:
        cos._TURN_USER_ID.reset(token)


def run(db, verb, action, who=None, biz=LC):
    import chief_of_staff as cos
    uid = {None: church(db, biz)["owner_id"], "nobody": None, "stranger": STRANGER}[who] if who in (
        None, "nobody", "stranger") else db.who[biz][who + "@"]
    with signed_in(uid):
        out = asyncio.run(cos.ACTION_HANDLERS[verb](None, {"id": biz}, dict(action)))
    assert out.get("result") and out.get("label"), out
    return out


def ok(out):
    assert not out.get("failed"), out["result"]
    return out


def rows(db, who, key=None):
    cid = db.who[LC][who]
    return [r for r in db.t["church_leader_roles"] if r["business_id"] == LC and r["contact_id"] == cid
            and (key is None or r["role"] == key)]


# ─── Wiring ───────────────────────────────────────────────────────────

def test_the_verbs_are_wired_classified_placed_and_in_the_prompt():
    import action_registry as ar
    import chief_areas as ca
    import chief_church_roles as ccr
    import chief_of_staff as cos
    import chief_prompt
    import mcp_server
    for verb in VERBS:
        assert cos.ACTION_HANDLERS[verb] is ccr.HANDLERS[verb], verb
        assert ar.reversibility(verb) == "C", verb
        assert ar.classification(verb).get("chief_only") and not ar.may_expose_to_agent(verb, allow_writes=True)
        assert verb not in mcp_server.WRITE_TOOL_SCHEMAS and verb not in mcp_server.TOOL_SCHEMAS, verb
        assert ca.VERBS[verb] == ca.OFFICE, verb
        assert cos._ACTION_PHRASES[verb] == ccr.PROGRESS[verb], verb
    src = open(chief_prompt.__file__, encoding="utf-8").read()
    assert '"type":"ask_into_role"' in src and '"type":"take_off_role"' in src
    assert "never call them clients, customers, leads or patients" in src


def test_an_ask_is_the_pages_ask_and_says_asked_never_yes(db):
    out = ok(run(db, "ask_into_role", {"who": "Gloria Hunt", "role": "Worship Leader"}))
    got = rows(db, "gloria", "worship_leader")
    assert len(got) == 1 and got[0]["status"] == "invited" and got[0]["invited_by"] == church(db, LC)["owner_id"]
    assert out["changed"] and out["emailed"] and out["row_id"] == str(got[0]["id"])
    assert [to for to, _k in db.sent] == ["gloria@lovecity.org"]
    assert "Asked Gloria Hunt to be Love City Church's Worship Leader" in out["result"]
    assert "says yes on their member page" in out["result"] and "Gloria said yes" not in out["result"]
    assert "asked, not held yet" in out["result"]
    # Asked again: nothing new is sent, and it says so.
    again = ok(run(db, "ask_into_role", {"who": "Gloria", "role": "worship leader"}))
    assert not again["changed"] and "already asked" in again["result"] and len(db.sent) == 1
    assert len(rows(db, "gloria", "worship_leader")) == 1
    # Someone who already holds it: nothing sent either.
    held = ok(run(db, "ask_into_role", {"who": "Ruth Okafor", "role": "Intercessor leader"}))
    assert not held["changed"] and "already" in held["result"] and len(db.sent) == 1


def test_a_team_leader_names_a_team_on_the_serve_card(db):
    no_team = run(db, "ask_into_role", {"who": "Calvin Owens", "role": "Team leader"})
    assert no_team["failed"] and "say which team" in no_team["result"]
    wrong = run(db, "ask_into_role", {"who": "Calvin Owens", "role": "Team leader", "team": "Parking Lot"})
    assert wrong["failed"] and "isn’t one of the teams on your Serve card" in wrong["result"]
    assert "Hospitality Team" in wrong["result"] and not rows(db, "calvin")
    out = ok(run(db, "ask_into_role", {"who": "Calvin Owens", "role": "Team leader", "team": "hospitality"}))
    got = rows(db, "calvin", "team_leader")
    assert len(got) == 1 and got[0]["scope"] == "Hospitality Team" and out["team"] == "Hospitality Team"
    assert "the Hospitality Team's leader" in out["result"]


@pytest.mark.parametrize("action,said", [
    ({"who": "Gloria Hunt", "role": "Administrator"}, "Office roles work with an office login"),
    ({"who": "Gloria Hunt", "role": "Armor Bearer"}, "There’s no role called “Armor Bearer”"),
    ({"who": "Zed Nobody", "role": "Deacons"}, "Nobody at this church is called “Zed Nobody”"),
    ({"role": "Deacons"}, "say who to ask"),
    ({"who": "Gloria Hunt"}, "say which role"),
])
def test_the_pages_refusals_say_why_and_change_nothing(db, action, said):
    before = len(db.t["church_leader_roles"])
    out = run(db, "ask_into_role", action)
    assert out["failed"] and said in out["result"], out["result"]
    assert len(db.t["church_leader_roles"]) == before and not db.sent


def test_a_draft_role_is_saved_first(db):
    import church_roles as cr
    cr.chief_draft(church(db, LC), "Armor Bearer", "care", "Serves the pastor.")
    out = run(db, "ask_into_role", {"who": "Gloria Hunt", "role": "Armor Bearer"})
    assert out["failed"] and "That role is a draft. Save it first" in out["result"] and not rows(db, "gloria")


def test_someone_asked_can_be_named_a_departments_leader_at_once(db):
    ok(run(db, "ask_into_role", {"who": "Gloria Hunt", "role": "Intercessor leader"}))
    made = ok(run(db, "change_map", {"changes": [{"kind": "department", "department": "Prayer",
                                                  "leader": "Gloria Hunt"}], "said": "Gloria leads Prayer"}))
    prayer = next(d for d in db.t["church_departments"] if d["business_id"] == LC and d["name"] == "Prayer")
    assert prayer["leader_contact_id"] == db.who[LC]["gloria"], made["result"]


# ─── take_off_role ────────────────────────────────────────────────────

def test_an_ask_is_taken_back_in_words_and_never_after_a_yes(db):
    import action_inverse as ai
    out = ok(run(db, "ask_into_role", {"who": "Gloria Hunt", "role": "Worship Leader"}))
    # No undo: taking an ask back is class C too, and no inverse may be. The reason says what to do.
    assert not ai.can_undo("ask_into_role") and ai.build_inverse("ask_into_role", {}, out) is None
    assert "take the ask back" in ai.why_not("ask_into_role")
    assert "only_if_asked" in out["note_for_chief"] and out["row_id"] in str(out)
    back = ok(run(db, "take_off_role", {"row_id": out["row_id"], "only_if_asked": True}))
    assert back["was"] == "asked" and "Took back the ask" in back["result"] and not rows(db, "gloria")
    assert "can't be unsent" in back["result"]
    # Asked again, and this time they said yes: only_if_asked would take the role away, so it refuses.
    out = ok(run(db, "ask_into_role", {"who": "Gloria Hunt", "role": "Worship Leader"}))
    rows(db, "gloria", "worship_leader")[0]["status"] = "active"
    no = run(db, "take_off_role", {"row_id": out["row_id"], "only_if_asked": True})
    assert no["failed"] and "already said yes" in no["result"] and rows(db, "gloria", "worship_leader")
    # A row that is gone, or another church's, changes nothing.
    gone = run(db, "take_off_role", {"row_id": "9a000000-0000-4000-8000-0000000000aa"})
    assert gone["failed"] and "already gone" in gone["result"] and rows(db, "gloria", "worship_leader")


def test_a_role_taken_away_goes_with_its_work_and_names_the_department(db):
    out = ok(run(db, "take_off_role", {"who": "Ruth Okafor", "role": "Intercessor leader"}))
    assert out["was"] == "held" and not rows(db, "ruth", "intercessor_leader")
    assert "Took Ruth Okafor off Love City Church's Intercessor leader" in out["result"]
    assert "still named on the leaders map for Prayer" in out["result"]
    assert "asking them again" in out["result"]


def test_two_of_a_role_asks_which_and_none_says_so(db):
    db.t["church_leader_roles"].append({
        "id": db.nid("church_leader_roles"), "business_id": LC, "contact_id": db.who[LC]["tasha"],
        "role": "team_leader", "scope": "Youth Ministry (YWD)", "status": "active",
        "invited_at": "2026-10-01T00:00:00+00:00", "answered_at": None, "answers_to_contact_id": None})
    two = run(db, "take_off_role", {"who": "Tasha Williams", "role": "Team leader"})
    assert two["failed"] and "more than one" in two["result"] and len(rows(db, "tasha", "team_leader")) == 2
    # "hospitality" is the Hospitality Team, as the ask matches it; the role's work stays with her through
    # the other team, so nothing went back, and the receipt doesn't say nothing was left (#1831 review).
    one = ok(run(db, "take_off_role", {"who": "Tasha Williams", "role": "Team leader", "team": "hospitality"}))
    left = rows(db, "tasha", "team_leader")
    assert one["was"] == "held" and [r["scope"] for r in left] == ["Youth Ministry (YWD)"]
    assert "Nothing went back." in one["result"] and "left with them" not in one["result"]
    none = run(db, "take_off_role", {"who": "Gloria Hunt", "role": "Deacons"})
    assert none["failed"] and "don't hold that role" in none["result"]


# ─── Seats and the turn ───────────────────────────────────────────────

def test_a_manager_may_and_nobody_else_does(db):
    ok(run(db, "ask_into_role", {"who": "Gloria Hunt", "role": "Worship Leader"}, who="naiya"))
    for who in ("stranger", "nobody"):
        for verb in VERBS:
            out = run(db, verb, {"who": "Ruth Okafor", "role": "Intercessor leader"}, who=who)
            assert out["failed"], (who, verb)
    assert rows(db, "ruth", "intercessor_leader")


def test_an_unattended_run_changes_nothing(db):
    for verb in VERBS:
        out = run(db, verb, {"who": "Gloria Hunt", "role": "Worship Leader", "_unattended": True})
        assert out["failed"] and "only when someone at the church asks" in out["result"]
    assert not rows(db, "gloria") and not db.sent


def test_a_tainted_turn_is_the_gates_to_hold_naming_who_and_the_role(db, monkeypatch):
    """The class C gate holds a tainted turn and reads back who and which role; its go-ahead releases this
    exact action, so the handler must not hold it a second time (#1831 review: that made the go-ahead a dead
    end)."""
    import chief_of_staff as cos
    monkeypatch.setattr(cos, "untrusted_taint", lambda: True)
    action = {"type": "ask_into_role", "who": "Calvin Owens", "role": "Team leader", "team": "Hospitality Team"}
    verdict, held = asyncio.run(cos._gate_class_c(None, {"id": LC}, "ask_into_role", dict(action), 0))
    assert verdict == "handled" and held["needs_confirmation"]
    assert "Calvin Owens" in held["label"] and "Team leader (Hospitality Team)" in held["label"]
    out = ok(run(db, "ask_into_role", action))         # the go-ahead's run: the handler doesn't hold again
    assert out["changed"] and rows(db, "calvin", "team_leader")
    assert "Ruth Okafor · Intercessor leader" == cos._confirmation_subject(
        {"type": "take_off_role", "who": "Ruth Okafor", "role": "Intercessor leader"})


def test_a_first_name_two_people_share_asks_which_even_when_one_holds_a_role(db):
    """Holders first would ask Ruth Okafor (she leads the intercessors) when the new Ruth was meant; an ask
    counts everyone at once (#1831 review)."""
    db.t["contacts"].append({"id": "9a000000-0000-4000-8000-0000000000a1", "business_id": LC, "name": "Ruth Jones",
                             "status": "active", "birthdate": None, "metadata": {}, "phone": "",
                             "email": "ruthj@lovecity.org"})
    out = run(db, "ask_into_role", {"who": "Ruth", "role": "Worship Leader"})
    assert out["failed"] and "could be Ruth Jones or Ruth Okafor" in out["result"], out["result"]
    assert not db.sent and not rows(db, "ruth", "worship_leader")
    # Taking someone off still finds the holder first: only Ruth Okafor holds a role.
    ok(run(db, "take_off_role", {"who": "Ruth", "role": "Intercessor leader"}))
    assert not rows(db, "ruth", "intercessor_leader")
    ok(run(db, "ask_into_role", {"who": "Ruth Jones", "role": "Worship Leader"}))
    assert [to for to, _k in db.sent] == ["ruthj@lovecity.org"] and not rows(db, "ruth", "worship_leader")


def test_taking_back_an_ask_leaves_their_other_work_where_it_is(db):
    """remove_role handed a volunteer's tasks back to the owner when only an ask was taken back (#1831 review);
    an ask hands nothing, so nothing goes back. The page's Remove is the same function."""
    cid = db.who[LC]["calvin"]
    db.t["tasks"].append({"id": "9a000000-0000-4000-8000-0000000000b1", "business_id": LC, "status": "todo",
                          "title": "Set up chairs", "description": None, "due_date": "2026-11-20",
                          "assigned_contact_id": cid, "assigned_to": None, "leader_told_at": None,
                          "late_told_at": None, "done_by_contact_id": None, "completed_at": None,
                          "created_at": "2026-11-10T12:00:00+00:00", "handed_by": church(db, LC)["owner_id"]})
    ok(run(db, "ask_into_role", {"who": "Calvin Owens", "role": "Worship Leader"}))
    back = ok(run(db, "take_off_role", {"who": "Calvin Owens", "role": "Worship Leader", "only_if_asked": True}))
    assert back["was"] == "asked" and "Also went back" not in back["result"]
    task = next(t for t in db.t["tasks"] if t["id"] == "9a000000-0000-4000-8000-0000000000b1")
    assert task["assigned_contact_id"] == cid and not rows(db, "calvin")


def test_a_role_named_by_an_id_that_isnt_the_churchs_is_refused(db):
    out = run(db, "take_off_role", {"who": "Ruth Okafor", "role": "9a000000-0000-4000-8000-0000000000ee"})
    assert out["failed"] and "There’s no role called" in out["result"]
    assert rows(db, "ruth", "intercessor_leader")
    out = run(db, "ask_into_role", {"who": "Gloria Hunt", "role": "9a000000-0000-4000-8000-0000000000ee"})
    assert out["failed"] and not rows(db, "gloria") and not db.sent


def test_not_a_church(db):
    db.t["businesses"][0]["type"] = "coach"
    out = run(db, "ask_into_role", {"who": "Gloria Hunt", "role": "Worship Leader"})
    assert out["failed"] and "for churches" in out["result"]


# ─── Members, not clients ─────────────────────────────────────────────

def test_chief_knows_a_churchs_people_are_members_not_clients():
    import chief_of_staff as cos
    from vertical_context import build_vertical_context_block
    lens = cos.CHIEF_ARCHETYPE_SHIFTS["ministry"]
    assert "Its people are members" in lens and "never clients, customers or leads" in lens
    block = build_vertical_context_block({"type": "church"})
    assert "Its people are members (newcomers are guests), never clients, customers or leads" in block
    assert "customer=Member" in block
