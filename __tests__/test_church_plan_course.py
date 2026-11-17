"""test_church_plan_course.py — a church's planning course (2026-11-17).

Kevin: "keep for business and build a church planning course". The
Solutionist Academy asked a pastor about the idea he wanted to launch and
what he would charge. A church now has its own eight parts on the same
page, kept in the same row, and finishing it builds nothing.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as cos  # noqa: E402 — load order: chief_of_staff imports chief_prompt
import chief_prompt as cp  # noqa: E402
import chief_strategy_actions as csa  # noqa: E402
import church_plan_course as plan  # noqa: E402

CHURCH = {"id": "c1", "name": "Grace Fellowship", "type": "church",
          "settings": {"practitioner_name": "Pastor James"}}
COACH = {"id": "b1", "name": "North Star Coaching", "type": "coaching",
         "settings": {"practitioner_name": "Dana", "track": "strategy"}}


class FakeSB:
    """One strategy_tracks row per business, and every write that was made."""

    def __init__(self, track=None):
        self.track = track
        self.writes = []

    async def __call__(self, client, method, path, body=None):
        self.writes.append((method, path.split("?")[0], body))
        if path.startswith("/strategy_tracks"):
            if method == "GET":
                return [self.track] if self.track else []
            if method == "POST":
                self.track = {"id": "t1", **body}
                return [self.track]
            if method == "PATCH":
                self.track = {**(self.track or {}), **body}
                return [self.track]
        return []


def run(coro):
    return asyncio.run(coro)


# ─── The parts ────────────────────────────────────────────────────────

def test_a_church_has_eight_parts_and_none_is_a_business_one():
    assert plan.ids() == ["calling", "community", "path", "ministries", "leaders",
                          "stewardship", "honest_look", "ninety_days"]
    assert not set(plan.ids()) & set(csa.STRATEGY_PHASES)
    for part in plan.PARTS:
        said = (part["title"] + " " + part["about"]).lower()
        for word in ("client", "customer", "lead ", "revenue", "pricing", "launch", "market", "competitor"):
            assert word not in said, (part["id"], word)


def test_what_is_kept_of_a_part_is_its_own_fields_at_a_sane_size():
    kept = plan.clean("calling", {
        "mission": "  To love   our neighbors.  ", "vision": "x" * 5000, "values": ["- Honesty", "", "Prayer"],
        "story": "", "price": "$99", "tiers": [1, 2]})
    assert kept == {"mission": "To love our neighbors.", "vision": "x" * plan.TEXT_MAX, "values": ["Honesty", "Prayer"]}
    assert plan.clean("calling", {"price": "$99"}) is None
    assert plan.clean("calling", "words") is None
    assert plan.clean("pricing_strategy", {"tiers": []}) is None
    assert plan.clean("community", {"who_to_reach": "young families\nstudents at the college"}) == {
        "who_to_reach": ["young families", "students at the college"]}
    assert len(plan.clean("honest_look", {"strengths": [f"s{i}" for i in range(40)]})["strengths"]) == plan.LIST_MAX


def test_a_ministrys_call_is_one_of_four_words_and_a_row_needs_its_name():
    kept = plan.clean("ministries", {"ministries": [
        {"name": "Youth", "leader": "Sam", "call": "GROW", "note": "needs a second adult"},
        {"name": "Choir", "call": "sunset"},
        {"leader": "nobody named"},
        "Food pantry",
    ], "start": ["A class for new members"]})
    assert kept["ministries"] == [
        {"name": "Youth", "leader": "Sam", "call": "grow", "note": "needs a second adult"},
        {"name": "Choir"},
        {"name": "Food pantry"},
    ]
    assert kept["start"] == ["A class for new members"]


def test_a_steps_link_is_kept_only_when_it_is_a_page_on_a_churchs_menu():
    known = plan.links()
    assert "operate:follow-up" in known and known["operate:follow-up"].startswith("People")
    weeks = plan.clean_weeks([
        {"week": 1, "theme": "Guests", "actions": [
            {"description": "Call every guest from the last month", "system_link": "operate/follow-up"},
            {"description": "Set what we charge", "system_link": "build:pricing"},
            "Thank the greeters", {"description": ""}]},
        {"week": "two", "actions": []},
        "not a week",
    ])
    assert weeks == [{"week": 1, "theme": "Guests", "actions": [
        {"description": "Call every guest from the last month", "completed": False, "system_link": "operate:follow-up"},
        {"description": "Set what we charge", "completed": False},
        {"description": "Thank the greeters", "completed": False}]}]
    assert plan.clean_weeks(None) == [] and plan.clean_weeks([{"week": 1}]) == []


def test_where_the_church_is_on_the_course():
    assert plan.current(None) == "calling" and plan.done(None) == []
    row = {"current_phase": "pricing_strategy", "phases": {"calling": {"mission": "m"}, "discovery": {"summary": "x"}}}
    # A row a business's course began starts at the first part not written.
    assert plan.current(row) == "community" and plan.done(row) == ["calling"]
    row = {"current_phase": "leaders", "phases": {}, "launch_plan": {"weeks": [{"week": 1, "actions": [{"description": "x"}]}]}}
    assert plan.current(row) == "leaders" and plan.done(row) == ["ninety_days"]
    assert plan.finished({"status": "completed"}) and not plan.finished({"status": "in_progress"})


# ─── The coach ────────────────────────────────────────────────────────

def test_a_church_in_a_course_session_gets_the_planning_coach():
    track = {"current_phase": "community", "phases": {
        "calling": {"mission": "To love our neighbors.", "values": ["Honesty"]},
        "session_log": [{"date": "2026-11-10", "summary": "Wrote the mission", "phases_progressed": ["calling"]}]}}
    prompt = cp._build_system_prompt({"business": CHURCH, "strategy_track": track}, True, mode="strategy_coach")
    assert "planning coach" in prompt and "Pastor James" in prompt and "Grace Fellowship" in prompt
    # The coach's own words (the menu, which names every page, comes after them).
    own = prompt.split("THIS CHURCH'S MENU")[0]
    assert "Strategy Coach" not in own and "Academy" not in own
    for verb in ("run_market_research", "save_pricing", "save_packages", "save_projections", "save_business_model", "save_swot"):
        assert verb not in prompt, verb
    for part in plan.ids()[:-1]:
        assert f'"phase": "{part}"' in prompt, part
    assert "save_launch_plan" in prompt and "complete_strategy_track" in prompt
    assert "To love our neighbors." in prompt and "OPENING (COMING BACK)" in prompt and "Wrote the mission" in prompt
    assert "community (Community)" in prompt
    assert "THIS CHURCH'S MENU" in prompt
    assert "Never invent an attendance figure" in prompt and "Do not assume a denomination" in prompt


def test_a_first_session_opens_on_why_the_church_is_here():
    prompt = cp._build_system_prompt({"business": CHURCH, "strategy_track": None}, True, mode="strategy_coach")
    assert "OPENING (FIRST SESSION)" in prompt and "why this church is here" in prompt
    assert "Do not emit actions in the opening" in prompt
    assert "OPENING" not in cp._build_system_prompt({"business": CHURCH, "strategy_track": None}, False, mode="strategy_coach")


def test_a_business_keeps_its_strategy_coach_word_for_word():
    ctx = {"business": COACH, "strategy_track": None}
    assert cp._build_system_prompt(ctx, True, mode="strategy_coach") == cp._build_coach_prompt(ctx, True)
    assert "You are the Strategy Coach" in cp._build_coach_prompt(ctx, True)
    assert "planning coach for a church" not in cp._build_coach_prompt(ctx, True)


# ─── The everyday Chief ───────────────────────────────────────────────

def test_the_everyday_chief_is_told_the_plan_and_never_the_academy():
    track = {"status": "in_progress", "phases": {
        "calling": {"mission": "To love our neighbors.", "vision": "A church for the whole street.", "values": ["Honesty"]},
        "community": {"who_to_reach": ["Young families"]}},
        "launch_plan": {"weeks": [{"week": 1, "actions": [{"description": "a", "completed": True}, {"description": "b"}]}]}}
    block = cp._format_strategy_block(CHURCH, track)
    assert "THE CHURCH'S PLAN" in block and "To love our neighbors." in block and "Young families" in block
    assert "1 of 2 steps done" in block and "Still to write: The path" in block
    for word in ("ACADEMY", "Strategy Session", "ACTION:"):
        assert word not in block, word
    assert cp._format_strategy_block(CHURCH, None) == ""
    assert cp._format_strategy_block(CHURCH, {"phases": {"session_log": []}}) == ""
    assert cp._format_strategy_block(CHURCH, track, mode="strategy_coach") == ""
    # A church flagged onto the business course by an old setting still reads as a church.
    assert "ACADEMY" not in cp._format_strategy_block({**CHURCH, "settings": {"track": "strategy"}}, track)


def test_a_business_is_still_told_about_the_academy():
    block = cp._format_strategy_block(COACH, {"current_phase": "pricing_strategy", "status": "in_progress",
                                             "phases": {"discovery": {"summary": "intensives"}}})
    assert "ACADEMY AWARENESS" in block and "THE CHURCH'S PLAN" not in block


# ─── Saving ───────────────────────────────────────────────────────────

def test_a_part_is_saved_under_its_own_name_beside_the_session_log(monkeypatch):
    sb = FakeSB({"id": "t1", "current_phase": "calling", "phases": {"session_log": [{"date": "2026-11-10"}]}})
    monkeypatch.setattr(cos, "_sb", sb)
    out = run(csa.handle_save_phase(None, CHURCH, {"type": "save_phase", "phase": "Calling", "data": {
        "mission": "To love our neighbors.", "tiers": [{"price": 99}]}}))
    assert out["result"] == "saved" and out["label"] == "Saved Calling to the church's plan"
    assert out["nav"] == {"tab": "build", "page": "strategy-track"}
    assert sb.track["phases"] == {"session_log": [{"date": "2026-11-10"}], "calling": {"mission": "To love our neighbors."}}


def test_a_new_church_row_starts_on_calling_and_a_business_one_on_discovery(monkeypatch):
    sb = FakeSB()
    monkeypatch.setattr(cos, "_sb", sb)
    run(csa.handle_save_phase(None, CHURCH, {"phase": "calling", "data": {"mission": "m"}}))
    assert sb.track["current_phase"] == "calling"
    sb2 = FakeSB()
    monkeypatch.setattr(cos, "_sb", sb2)
    run(csa.handle_save_phase(None, COACH, {"phase": "discovery", "data": {"summary": "s"}}))
    assert sb2.track["current_phase"] == "discovery" and sb2.track["phases"] == {"discovery": {"summary": "s"}}


def test_a_church_cannot_save_a_business_part_and_nothing_is_written(monkeypatch):
    sb = FakeSB({"id": "t1", "phases": {}})
    monkeypatch.setattr(cos, "_sb", sb)
    for action in ({"phase": "discovery", "data": {"summary": "an idea"}},
                   {"phase": "calling", "data": {"price": 5}},
                   {"phase": "calling", "data": None}):
        out = run(csa.handle_save_phase(None, CHURCH, action))
        assert out.get("failed") is True and out.get("result"), action
    for handler, action in ((csa.handle_save_pricing, {"tiers": [{"name": "Starter", "price": 99}]}),
                            (csa.handle_save_packages, {"packages": [{"name": "x"}]}),
                            (csa.handle_save_business_model, {"canvas": {"value_proposition": "x"}}),
                            (csa.handle_save_projections, {"scenarios": {"realistic": {}}}),
                            (csa.handle_save_swot, {"strengths": "x"})):
        out = run(handler(None, CHURCH, action))
        assert out.get("failed") is True and "business course" in out["result"], handler.__name__
    assert not [w for w in sb.writes if w[0] in ("PATCH", "POST")]


def test_moving_on_takes_a_churchs_part_only(monkeypatch):
    sb = FakeSB({"id": "t1", "current_phase": "calling", "phases": {}})
    monkeypatch.setattr(cos, "_sb", sb)
    out = run(csa.handle_advance_phase(None, CHURCH, {"to": "community"}))
    assert out["result"] == "advanced" and out["label"] == "Now on: Community" and sb.track["current_phase"] == "community"
    out = run(csa.handle_advance_phase(None, CHURCH, {"to": "market_research"}))
    assert out.get("failed") is True and sb.track["current_phase"] == "community"


def test_the_next_90_days_are_kept_in_the_launch_plans_shape(monkeypatch):
    sb = FakeSB({"id": "t1", "phases": {}})
    monkeypatch.setattr(cos, "_sb", sb)
    weeks = [{"week": 1, "theme": "Guests", "actions": [
        {"description": "Call every guest", "system_link": "operate/follow-up"}, "Thank the greeters"]}]
    out = run(csa.handle_save_launch_plan(None, CHURCH, {"weeks": weeks}))
    assert out["result"] == "1 weeks, 2 steps saved" and out["label"] == "Saved the next 90 days to the church's plan"
    assert sb.track["launch_plan"] == {"weeks": [{"week": 1, "theme": "Guests", "actions": [
        {"description": "Call every guest", "completed": False, "system_link": "operate:follow-up"},
        {"description": "Thank the greeters", "completed": False}]}]}
    # The same through save_phase, and an empty plan is refused.
    out = run(csa.handle_save_phase(None, CHURCH, {"phase": "ninety_days", "data": {"weeks": weeks}}))
    assert out["type"] == "save_phase" and out["result"] == "1 weeks, 2 steps saved"
    assert run(csa.handle_save_launch_plan(None, CHURCH, {"weeks": []})).get("failed") is True


def test_finishing_a_churchs_course_marks_the_plan_written_and_builds_nothing(monkeypatch):
    sb = FakeSB({"id": "t1", "status": "in_progress", "phases": {"calling": {"mission": "m"}},
                 "launch_plan": {"weeks": [{"week": 1, "actions": [{"description": "x"}]}]}})
    monkeypatch.setattr(cos, "_sb", sb)
    built = []
    monkeypatch.setattr(csa, "_seed_products_module_from_packages", lambda *a, **k: built.append("products"))
    monkeypatch.setattr(csa, "_seed_default_intake_form", lambda *a, **k: built.append("form"))
    monkeypatch.setattr(csa, "_generate_strategy_site", lambda *a, **k: built.append("site"))
    out = run(csa.handle_complete_strategy_track(None, CHURCH, {}))
    assert out["result"] == "the plan is written" and out["label"] == "The church's plan is written"
    assert sb.track["status"] == "completed" and sb.track["completed_at"]
    assert built == []
    touched = {path for method, path, _ in sb.writes if method in ("PATCH", "POST")}
    assert touched == {"/strategy_tracks"}, "a church's settings, site and modules are left alone"


def test_a_plan_with_no_90_days_is_not_finished(monkeypatch):
    sb = FakeSB({"id": "t1", "status": "in_progress", "phases": {"calling": {"mission": "m"}}})
    monkeypatch.setattr(cos, "_sb", sb)
    out = run(csa.handle_complete_strategy_track(None, CHURCH, {}))
    assert out.get("failed") is True and sb.track["status"] == "in_progress"


def test_a_session_note_is_kept_for_a_church_too(monkeypatch):
    sb = FakeSB()
    monkeypatch.setattr(cos, "_sb", sb)
    out = run(csa.handle_session_summary(None, CHURCH, {"summary": "Wrote the mission", "phases_progressed": ["calling"]}))
    assert out["result"] == "logged" and sb.track["current_phase"] == "calling"
    assert sb.track["phases"]["session_log"][0]["summary"] == "Wrote the mission"


def test_the_parts_and_fields_are_the_ones_the_app_shows():
    # The same list, key for key, as tests/church-plan-check.ts in the app
    # (solutionist-studio). A change here without one there means the coach
    # saves a field the page never shows.
    app_parts = {
        "calling": ["mission", "vision", "values", "story"],
        "community": ["neighborhood", "who_comes_now", "who_to_reach", "needs"],
        "path": ["steps:name,what_happens,who_owns_it,gap"],
        "ministries": ["ministries:name,leader,serves,call,note", "start", "stop"],
        "leaders": ["teams:name,leader,needs", "gaps", "raising_leaders", "care"],
        "stewardship": ["priorities", "giving_today", "goals", "risks"],
        "honest_look": ["strengths", "weaknesses", "open_doors", "risks"],
        "ninety_days": [],
    }
    mine = {p["id"]: [f"{key}:{','.join(cols)}" if kind == "rows" else key for key, kind, cols in p["fields"]]
            for p in plan.PARTS}
    assert mine == app_parts
