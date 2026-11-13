"""Chief reads and moves a church's duties (chief_duties.py). Kevin, 2026-11-01:
"give chief the ability to make adjustment and help the churches make
adjustments like these … you would make the changes for love city directly
but chief would do other churches".

Pins:
  * wiring: three handlers, classified (a read and two class-A writes, all
    Chief's alone), placed in chief_areas, in the prompt; list_duties is a
    mid-turn read, move_duty and undo_duty are action tags, never native
    write tools; undo_last's inverse of a move is undo_duty
  * every handler returns a result and a label, whatever happens
  * the owner or an Admin moves a duty; a Manager is refused plainly, at the
    handler and at the lane gate
  * names resolve exactly (a whole name, a first name only one login has, an
    id); an unknown or shared name changes nothing
  * the duties page's own rules: a money duty never to a Manager, never a
    Member
  * the record (before, now, logged, undo) and the log row; undo puts it
    back, and undo_last's inverse only while that move is the last change
  * list_duties: by lane, follows the lanes or moved to whom, which need
    someone, the office logins
  * the THIS LOGIN line: a church login that isn't the owner or an Admin is
    told its jobs
  * the switch: off, the platform owner's own login, on

The church is the duties tests' Love City (test_church_duties' fake)."""
from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import chief_areas as ca  # noqa: E402
import chief_duties as chd  # noqa: E402
import church_duties as cd  # noqa: E402
import sb_clients  # noqa: E402
from test_church_duties import (ADMIN, BIZ, C_JESS, JESS, LAQ, MEM, NAIYA, OWNER, PLATFORM,  # noqa: E402,F401
                                SHAP, STRANGER, TIARA, _fresh_cache, _seat, db)

EXTRA = "ab000000-0000-4000-8000-0000000000ab"
CHURCH = {"id": BIZ, "owner_id": OWNER, "name": "Love City Church", "type": "ministry",
          "settings": {"practitioner_name": "Pastor Kevin"}}
ASK = {"duty": "weekly_text", "to": ["Tiara Adams"]}
BEFORE_WT = "the Office & Leadership lane, by default (Naiya Clark and Jessica McCloud)"


@pytest.fixture
def church(db, monkeypatch):
    """Love City's office with Jessica's login tied to her person, and the
    duties switched on."""
    next(s for s in db.t["business_users"] if s["user_id"] == JESS)["contact_id"] = C_JESS
    monkeypatch.setenv("CHURCH_DUTIES", "on")
    chd._EMAILS.clear()
    ca.forget()
    yield db
    chd._EMAILS.clear()


@contextlib.contextmanager
def signed_in(uid):
    import chief_of_staff as cos
    token = cos._TURN_USER_ID.set(uid or "")
    try:
        yield
    finally:
        cos._TURN_USER_ID.reset(token)


def run(verb, action, uid=OWNER):
    import chief_of_staff as cos
    with signed_in(uid):
        return asyncio.run(cos.ACTION_HANDLERS[verb](None, {"id": BIZ}, dict(action)))


def _u(uid):
    return SimpleNamespace(id=uid)


# ─── Wiring ───────────────────────────────────────────────────────────

def test_the_verbs_are_wired_classified_placed_and_in_the_prompt():
    import action_inverse as ai
    import action_registry as ar
    import chief_of_staff as cos
    import chief_tool_loop as ctl
    import mcp_server
    from __tests__._chief_source import chief_source
    for verb in ("list_duties", "move_duty", "undo_duty"):
        assert verb in cos.ACTION_HANDLERS, verb
        assert ar.classification(verb).get("chief_only"), verb
        assert not ar.may_expose_to_agent(verb, allow_writes=True), verb
        assert verb not in mcp_server.WRITE_TOOL_SCHEMAS and verb not in mcp_server.TOOL_SCHEMAS, verb
    assert ar.effect("list_duties") == "read"
    assert ar.reversibility("move_duty") == ar.reversibility("undo_duty") == "A"
    assert not ar.is_bulk("move_duty") and not ar.is_bulk("undo_duty")
    # list_duties is a mid-turn read; moving is a tag, never a native write tool.
    assert "list_duties" in {t["name"] for t in ctl.read_tool_definitions()}
    ctl.reset_turn(writes_allowed=True)
    assert not {"move_duty", "undo_duty"} & {t["name"] for t in ctl.write_tool_definitions()}
    ctl.reset_turn()
    # Placed: anyone who may open the duties page may ask; moving is the owner's and admins'.
    assert ca.VERBS["list_duties"] == (ca.ALL,)
    assert {"move_duty", "undo_duty"} <= ca.OWNERS
    src = chief_source()
    assert "list_duties" in src and '"type":"move_duty"' in src and '"type":"undo_duty"' in src
    assert "Jessica does the monthly report now" in src
    # undo_last's inverse of a move names the change it puts back.
    assert ai.build_inverse("move_duty", {}, {"changed": True, "duty": "weekly_text", "change_id": "c1"}) == {
        "type": "undo_duty", "duty": "weekly_text", "change_id": "c1"}
    assert ai.build_inverse("move_duty", {}, {"changed": False, "duty": "weekly_text"}) is None
    assert ai.build_inverse("move_duty", {}, {"failed": True, "result": "Failed: x"}) is None


def test_list_duties_is_a_mid_turn_read_and_moving_goes_through_a_tag(church):
    import chief_tool_loop as ctl
    with signed_in(OWNER):
        err, text = asyncio.run(ctl.execute_tool_use(None, {"id": BIZ}, "list_duties", {}))
        assert not err and "The weekly text and email" in text and "Office logins" in text
        err, text = asyncio.run(ctl.execute_tool_use(None, {"id": BIZ}, "move_duty", ASK))
        assert err and "[ACTION:]" in text
        ctl.reset_turn(writes_allowed=True)
        err, text = asyncio.run(ctl.execute_tool_use(None, {"id": BIZ}, "move_duty", ASK))
        assert err and "[ACTION:]" in text
        ctl.reset_turn()
    assert church.rpcs == []


SCENES = [
    ("list_duties", {}, OWNER), ("list_duties", {}, NAIYA), ("list_duties", {}, MEM), ("list_duties", {}, None),
    ("move_duty", ASK, OWNER), ("move_duty", ASK, NAIYA), ("move_duty", ASK, None),
    ("move_duty", {"duty": "sunday_lunch", "to": []}, OWNER), ("move_duty", {"duty": "weekly_text"}, OWNER),
    ("move_duty", {"duty": "books", "to": ["Naiya Clark"]}, ADMIN), ("move_duty", {"duty": "weekly_text", "to": ["Bob"]}, OWNER),
    ("move_duty", {**ASK, "_unattended": True}, OWNER),
    ("undo_duty", {"duty": "weekly_text"}, OWNER), ("undo_duty", {"duty": "weekly_text"}, NAIYA),
    ("undo_duty", {"duty": "nope"}, OWNER),
]


@pytest.mark.parametrize("verb,action,uid", SCENES)
def test_every_answer_has_a_result_and_a_label(church, verb, action, uid):
    out = run(verb, action, uid)
    assert isinstance(out.get("result"), str) and out["result"], out
    assert isinstance(out.get("label"), str) and out["label"], out
    assert out["type"] == verb


@pytest.mark.parametrize("verb,action,uid", SCENES[:6])
def test_a_read_that_fails_still_answers_with_a_result_and_a_label(church, monkeypatch, verb, action, uid):
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda *a, **k: None)
    out = run(verb, action, uid)
    assert out.get("failed") and out.get("result", "").startswith("Failed: ") and out.get("label"), out
    assert church.rpcs == []


# ─── Who may move a duty ──────────────────────────────────────────────

def test_a_manager_is_refused_a_move_plainly(church):
    for uid in (NAIYA, JESS, MEM, STRANGER):
        out = run("move_duty", ASK, uid)
        assert out["failed"] and out["result"] == "Failed: Moving a duty is the owner's or an admin's.", uid
        out = run("undo_duty", {"duty": "weekly_text"}, uid)
        assert out["failed"] and out["result"] == "Failed: Moving a duty is the owner's or an admin's.", uid
    assert run("move_duty", ASK, None)["failed"]
    assert run("move_duty", {**ASK, "_unattended": True}, OWNER)["failed"], "never on nobody's word"
    assert church.rpcs == []
    # A login kept to its lane is stopped at the lane gate, in the same plain words.
    care = {"areas": ["people_care", "kids_youth", "groups_classes"], "role": "manager", "lane": "people_care"}
    for verb in ("move_duty", "undo_duty"):
        assert ca.refusal(verb, {}, care).startswith("That's for the church's owner or an admin, not this login.")
    assert ca.refusal("list_duties", {}, care) is None


def test_the_owner_moves_a_duty_by_name_and_hears_the_record(church):
    assert cd.holds(BIZ, _u(NAIYA), "weekly_text")
    out = run("move_duty", {"duty": "The weekly text and email", "to": ["tiara  ADAMS"]}, OWNER)
    assert not out.get("failed"), out
    assert out["result"] == (f"Moved “The weekly text and email”. Before: {BEFORE_WT}. Now: Tiara Adams. The owner and every "
                             "Admin still do it too. It's in the duties' change log, and undo_duty puts it back.")
    assert out["label"] == "“The weekly text and email” → Tiara"
    assert out["from"] == ["Naiya Clark", "Jessica McCloud"] and out["to"] == ["Tiara Adams"]
    assert out["holders"] == [TIARA] and out["changed"] and not out["follows_lanes"]
    # One change through the duties page's own move, and its log row.
    assert church.rpcs == [{"p_business_id": BIZ, "p_duty": "weekly_text", "p_user_ids": [TIARA], "p_by": OWNER,
                            "p_undoes": None}]
    [log] = church.t["church_duty_changes"]
    assert (log["duty"], log["from_holders"], log["to_holders"], log["changed_by"]) == ("weekly_text", None, [TIARA],
                                                                                        OWNER)
    assert out["change_id"] == log["id"]
    assert cd.holds(BIZ, _u(TIARA), "weekly_text") and not cd.holds(BIZ, _u(NAIYA), "weekly_text")
    # The same names again change nothing and log nothing.
    same = run("move_duty", {"duty": "weekly_text", "to": ["Tiara"]}, ADMIN)
    assert not same.get("failed") and same["changed"] is False and same["result"].startswith("Nothing changed")
    assert len(church.t["church_duty_changes"]) == 1
    # [] puts it back to the lanes, logged by the admin who did it.
    back = run("move_duty", {"duty": "weekly_text", "to": []}, ADMIN)
    assert back["result"].startswith(f"Put “The weekly text and email” back to the lanes. Before: Tiara Adams. Now: {BEFORE_WT}.")
    assert back["label"] == "“The weekly text and email” → the lanes" and back["follows_lanes"]
    assert church.t["church_duty_changes"][-1]["changed_by"] == ADMIN and church.t["church_duty_holders"] == []


def test_names_resolve_exactly_or_nothing_changes(church):
    logins = cd.build(cd._business(BIZ))["logins"]
    assert chd.resolve(logins, ["  tiara   ADAMS "]) == ([TIARA], [])
    assert chd.resolve(logins, ["Laquesha"]) == ([LAQ], [])
    assert chd.resolve(logins, [SHAP.upper()]) == ([SHAP], [])
    assert chd.resolve(logins, ["Tiara", "Tiara Adams"]) == ([TIARA], [])
    assert chd.resolve(logins, ["Pastor Kevin"]) == ([OWNER], [])
    ids, problems = chd.resolve(logins, ["Tia"])
    assert ids == [] and problems == ["no login on this church's office is named “Tia”"]
    # Two Jessicas: the first name alone is nobody's.
    church.t["business_users"].append(_seat(EXTRA, "manager", "jess.adams@lovecity.org", name="Jessica Adams"))
    out = run("move_duty", {"duty": "weekly_text", "to": ["Jessica"]}, OWNER)
    assert out["failed"] and "“Jessica” could be Jessica Adams and Jessica McCloud. Nothing changed." in out["result"]
    assert "The office logins: Pastor Kevin (owner)" in out["result"]
    out = run("move_duty", {"duty": "weekly_text", "to": ["Jessica McCloud", "Bob"]}, OWNER)
    assert out["failed"] and "no login on this church's office is named “Bob”" in out["result"]
    assert church.rpcs == [], "nothing unknown or shared moved anything"
    out = run("move_duty", {"duty": "weekly_text", "to": ["Jessica McCloud", "Naiya"]}, OWNER)
    assert not out.get("failed") and out["holders"] == sorted([JESS, NAIYA])
    assert run("move_duty", {"duty": "weekly_text", "to": [""]}, OWNER)["failed"]
    unknown = run("move_duty", {"duty": "sunday lunch", "to": ["Naiya"]}, OWNER)
    assert unknown["failed"] and "there's no duty called “sunday lunch”" in unknown["result"]
    assert "The monthly report (monthly_report)" in unknown["result"]
    assert chd.find_duty("the Monthly Report") == chd.find_duty("monthly report") == "monthly_report"


def test_a_money_duty_never_goes_to_a_manager_nor_any_duty_to_a_member(church):
    out = run("move_duty", {"duty": "books", "to": ["Naiya Clark"]}, ADMIN)
    assert out["failed"] and out["result"] == ("Failed: “The books” is a money job: only the owner or an Admin login "
                                               "can do it. Nothing changed.")
    out = run("move_duty", {"duty": "weekly_text", "to": ["web@lovecity.org"]}, OWNER)
    assert out["failed"] and "A Member or Viewer login doesn't do office jobs" in out["result"]
    assert church.rpcs == []
    ok = run("move_duty", {"duty": "books", "to": ["Minnie Tatum"]}, OWNER)
    assert not ok.get("failed") and ok["holders"] == [ADMIN]


def test_undo_puts_it_back_and_undo_last_only_while_it_is_the_last_change(church):
    import action_inverse as ai
    run("move_duty", ASK, ADMIN)
    out = run("undo_duty", {"duty": "The weekly text and email"}, ADMIN)
    assert not out.get("failed"), out
    assert out["result"].startswith(f"Put back the last change to “The weekly text and email”. Before: Tiara Adams. Now: {BEFORE_WT}.")
    assert out["label"] == "Put back “The weekly text and email”" and out["follows_lanes"]
    assert church.t["church_duty_holders"] == [] and cd.holds(BIZ, _u(NAIYA), "weekly_text")
    first, second = church.t["church_duty_changes"]
    assert second["undoes"] == first["id"] and first["undone_at"] and second["changed_by"] == ADMIN
    again = run("undo_duty", {"duty": "weekly_text"}, ADMIN)
    assert again["failed"] and again["result"] == "Failed: Nothing to put back for “The weekly text and email”."
    # undo_last's inverse names its change: once another came after, it's refused.
    one = run("move_duty", {"duty": "rooms", "to": ["Laquesha"]}, OWNER)
    two = run("move_duty", {"duty": "rooms", "to": ["Naiya"]}, OWNER)
    stale = ai.build_inverse("move_duty", {}, one)
    out = run("undo_duty", {k: v for k, v in stale.items() if k != "type"}, OWNER)
    assert out["failed"] and "has changed again since then" in out["result"]
    assert [h["user_id"] for h in church.t["church_duty_holders"] if h["duty"] == "rooms"] == [NAIYA]
    latest = ai.build_inverse("move_duty", {}, two)
    out = run("undo_duty", {k: v for k, v in latest.items() if k != "type"}, OWNER)
    assert not out.get("failed") and out["holders"] == [LAQ]


# ─── list_duties ──────────────────────────────────────────────────────

def test_list_duties_by_lane_with_who_does_each_and_what_needs_someone(church):
    run("move_duty", {"duty": "rooms", "to": ["Laquesha"]}, OWNER)
    next(s for s in church.t["business_users"] if s["user_id"] == LAQ)["status"] = "revoked"
    out = run("list_duties", {}, NAIYA)          # any Manager may read it, as the page
    assert not out.get("failed"), out
    lines = out["result"].split("\n")
    assert lines[0].startswith("Who does what at Love City Church. The owner and every Admin login do every duty")
    heads = [ln for ln in lines if ln.endswith(":") and not ln.startswith("-")]
    assert heads == ["Office & Leadership:", "People & Care:", "Sunday & Serving:", "Media & Communications:",
                     "Treasurer:", "Executive Pastor:"]
    assert "- The weekly text and email (weekly_text; Wed): lanes: Naiya Clark, Jessica McCloud." in lines
    assert ("- Rooms (rooms; Fri): moved to nobody who can do it now (named but can't do it "
            "now: Someone who has left the office).") in lines
    # Sunday's schedule, split by team: one line under each lane.
    assert "- Who serves when (serve_schedule; Wed): lanes: Jessica McCloud." in lines
    assert "- Worship and production teams (production_schedule; Wed): lanes: Jessica McCloud, Shapretta McClain." \
        in lines
    assert "- The books (books; Mon, monthly; money): lanes: Minnie Tatum." in lines
    assert "- The monthly report (monthly_report; first Monday): lanes: Jessica McCloud." in lines
    assert any(ln.startswith("Needs someone (") and ln.endswith(": Rooms.") for ln in lines)
    assert lines[-1].startswith("Office logins: Pastor Kevin (owner); Minnie Tatum (Admin, Treasurer); ")
    assert "Naiya Clark (Manager, Office & Leadership)" in lines[-1]
    assert "Jessica McCloud (Manager, Executive Pastor)" in lines[-1]
    assert "web@lovecity.org" not in lines[-1], "a Member login does no duties"
    assert out["needs_someone"] == ["rooms"] and out["moved"] == ["rooms"]
    assert out["label"] == "Who does what · 1 need someone" and out["nav"] == chd.NAV
    assert "$" not in out["result"]
    for uid in (MEM, STRANGER):
        refused = run("list_duties", {}, uid)
        assert refused["failed"] and "its admins and its Manager logins" in refused["result"], uid
    church.t["businesses"][0]["type"] = "salon"
    assert run("list_duties", {}, OWNER)["result"] == "Failed: Duties are for a church's office."


def test_a_bigger_churchs_list_reaches_chief_whole(church):
    import chief_tool_loop as ctl
    lanes = ["office_leadership", "people_care", "sunday_serving", "media_comms"]
    for i in range(16):
        church.t["business_users"].append(_seat(f"bb000000-0000-4000-8000-0000000000{i:02d}", "manager", f"p{i}@x.org",
                                                lane=lanes[i % 4], name=f"Firstname{i} Lastname-Longer"))
    text = ctl._shrink(run("list_duties", {}, OWNER))
    assert "truncated" not in text and "Store orders" in text and "Firstname15 Lastname-Longer" in text


# ─── The THIS LOGIN line ──────────────────────────────────────────────

def test_a_church_login_is_told_its_jobs(church, monkeypatch):
    line = chd.jobs_line(BIZ, NAIYA)
    assert line.startswith("Their jobs here: The front desk; The Monday leaders note; Meetings and minutes; "
                           "Decisions to done; The weekly text and email; The church calendar; Rooms; "
                           "The building and safety; Records, files and policies; Chat rules; "
                           "The leaders list and department sheet; Welcoming new leaders; Supplies; "
                           "Church email addresses. "
                           "Any other duty is someone else's")
    for uid in (OWNER, ADMIN, STRANGER):
        assert chd.jobs_line(BIZ, uid) is None, uid
    assert chd.jobs_line(BIZ, MEM) == "Their jobs here: none. A Member or Viewer login doesn't do the office's duties."
    church.t["business_users"].append(_seat(EXTRA, "manager", "pat@lovecity.org", lane="treasurer", name="Pat Doe"))
    assert chd.jobs_line(BIZ, EXTRA).startswith("Their jobs here: none of the office's duties yet.")
    # A duty just moved shows on the next turn.
    run("move_duty", ASK, OWNER)
    assert "The weekly text and email" not in chd.jobs_line(BIZ, NAIYA)
    assert chd.jobs_line(BIZ, TIARA).startswith(
        "Their jobs here: The weekly text and email; First-time guests and welcome calls; Care and visits; "
        "Prayer; Help requests; Shepherding; Groups and classes; Member records and the directory; Kids; "
        "Youth and Teen Bible Study; Devotionals and the reading plan.")

    # In the THIS LOGIN block, after the lane's words; and without a lane too.
    who = {"role": "manager", "name": "Naiya Clark", "first_name": "Naiya", "jobs": line}
    office = {"areas": ["messages_safety", "office"], "role": "manager", "lane": "office_leadership"}
    text = ca.block(office, who, CHURCH)
    assert line in text and text.index("THIS LOGIN — not the owner.") < text.index("Their jobs here")
    assert line in ca.block(None, who, CHURCH)
    assert "Their jobs" not in ca.block(office, {k: v for k, v in who.items() if k != "jobs"}, CHURCH)

    # turn_for carries it, for a church login that isn't the owner or an Admin.
    seats = {NAIYA: {"role": "manager", "name": "Naiya Clark", "first_name": "Naiya"},
             ADMIN: {"role": "admin", "name": "Minnie Tatum", "first_name": "Minnie"}}
    monkeypatch.setattr(ca, "scope_for", lambda b, uid, owner_id=None: None)
    monkeypatch.setattr(ca, "who_for", lambda b, uid, owner_id=None: seats.get(uid))
    assert ca.turn_for(BIZ, NAIYA)[1]["jobs"] == chd.jobs_line(BIZ, NAIYA)
    assert "jobs" not in ca.turn_for(BIZ, ADMIN)[1] and ca.turn_for(BIZ, OWNER)[1] is None
    assert "jobs" not in seats[NAIYA], "the kept speaker isn't changed"
    monkeypatch.setattr(chd, "jobs_line", lambda *a: 1 / 0)
    assert "jobs" not in ca.turn_for(BIZ, NAIYA)[1], "a line that fails is left out, never the turn"


def test_the_line_says_so_when_duties_cant_be_read_and_nothing_outside_a_church(church, monkeypatch):
    real = church.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **kw: None if path.lstrip("/").startswith(
        "church_duty_holders") else real(path, **kw))
    assert chd.jobs_line(BIZ, NAIYA) == chd.UNREAD
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda *a, **k: None)
    assert chd.jobs_line(BIZ, NAIYA) is None, "the church's row unread: nobody knows it's a church"
    monkeypatch.setattr(sb_clients, "sb_get_as_service", real)
    church.t["businesses"][0]["type"] = "salon"
    cd._CACHE.clear()
    assert chd.jobs_line(BIZ, NAIYA) is None


# ─── The switch ───────────────────────────────────────────────────────

def test_the_switch_follows_the_routes(church, monkeypatch):
    import platform_suite
    emails = {OWNER: PLATFORM, ADMIN: "minnie@lovecity.org"}
    monkeypatch.setattr(platform_suite, "_owner_email", lambda uid: emails.get(uid))
    monkeypatch.setenv("CHURCH_DUTIES", "off")
    for verb, action in (("list_duties", {}), ("move_duty", ASK), ("undo_duty", {"duty": "weekly_text"})):
        out = run(verb, action, OWNER)
        assert out["failed"] and out["result"] == "Failed: " + chd.NOT_ON and out["label"], verb
    # Owner: the platform owner's own login only, as the routes.
    monkeypatch.setenv("CHURCH_DUTIES", "owner")
    assert run("move_duty", ASK, ADMIN)["result"] == "Failed: " + chd.NOT_ON
    assert run("list_duties", {}, NAIYA)["result"] == "Failed: " + chd.NOT_ON
    assert not run("move_duty", ASK, OWNER).get("failed")
    # Who's signed in can't be read: not a yes.
    chd._EMAILS.clear()

    def down(uid):
        raise RuntimeError("auth unreachable")
    monkeypatch.setattr(platform_suite, "_owner_email", down)
    out = run("list_duties", {}, OWNER)
    assert out["failed"] and "couldn't be checked just now" in out["result"]
    monkeypatch.setenv("CHURCH_DUTIES", "on")
    assert not run("list_duties", {}, ADMIN).get("failed")
    assert len(church.rpcs) == 1
    # The line isn't switched: the job gates read duties whatever it says.
    monkeypatch.setenv("CHURCH_DUTIES", "off")
    assert chd.jobs_line(BIZ, TIARA).startswith("Their jobs here: The weekly text and email;")


def test_the_platform_owners_church_moves_its_duties_through_its_own_admins_chief(church, monkeypatch):
    """11-06 (church_duties.office_open): under `owner` Chief's duty verbs follow the login or the church,
    as the routes and the leaders map do, so Love City's admin moves and puts back a duty through Chief; a
    Manager there reads them and moves nothing; a church that isn't the platform owner's stays closed (the
    three churches: test_church_map_asks)."""
    import member_asks
    import messaging_router
    import platform_suite
    emails = {OWNER: PLATFORM, ADMIN: "minnie@lovecity.org", NAIYA: "naiya@lovecity.org"}
    monkeypatch.setattr(platform_suite, "_owner_email", lambda uid: emails.get(uid))
    monkeypatch.setattr(messaging_router, "_owner_email", lambda uid: emails.get(str(uid), ""))
    monkeypatch.setenv("CHURCH_DUTIES", "owner")
    monkeypatch.setenv("CHURCH_MAP", "off")             # this fake has no leaders map
    moved = run("move_duty", ASK, ADMIN)
    assert not moved.get("failed") and moved["changed"], moved["result"]
    assert run("undo_duty", {"duty": "weekly_text"}, ADMIN)["changed"]
    assert not run("list_duties", {}, NAIYA).get("failed"), "a Manager reads them"
    assert run("move_duty", ASK, NAIYA)["result"] == "Failed: " + chd.NOT_YOURS
    emails[OWNER] = "pastor@lovecity.org"
    monkeypatch.setattr(member_asks, "_OWNER_CACHE", {})
    for verb, action in (("list_duties", {}), ("move_duty", ASK), ("undo_duty", {"duty": "weekly_text"})):
        assert run(verb, action, ADMIN)["result"] == "Failed: " + chd.NOT_ON, verb
    assert len(church.rpcs) == 2
