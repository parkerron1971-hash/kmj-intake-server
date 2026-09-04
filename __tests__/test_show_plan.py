"""show_plan — Chief can put an action plan on the screen.

Kevin, 2026-08-18: "also add artifact where if requested an action
plan, Chief can produce that as well."

Every other display verb draws rows the SERVER fetched, and the
guarantee is that the model never touches a cell. A plan inverts that:
there is no table behind it, because it is Chief's own thinking.

So the guarantee changes shape rather than being dropped — the payload
is bounded and stamped authored:"chief", and the surface renders it as
visibly Chief's words. These tests pin the bounds and the stamp,
because an unstamped plan sitting beside a fetched table is exactly how
advice starts reading as data.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from __tests__._chief_source import chief_source  # noqa: E402
import chief_of_staff as cos

_BIZ = {"id": "biz-1", "name": "KMJ Creative Solutions", "type": "coach",
        "owner_id": "user-1", "settings": {}}


def _plan(action):
    return asyncio.run(cos.handle_show_plan(None, _BIZ, action))


def test_a_plan_comes_back_as_typed_steps():
    r = _plan({"type": "show_plan", "title": "Get the overdue money in", "steps": [
        {"step": "Call Dana Okoye", "why": "94 days is past what a reminder fixes", "when": "today"},
        {"step": "Send reminders to Bright Path and Marcus", "when": "today"},
        {"step": "Put net-14 terms on the next three invoices", "why": "stops the queue refilling"},
    ]})
    assert r["type"] == "show_plan"
    assert r.get("result") and r.get("label"), "the house contract"
    assert r["title"] == "Get the overdue money in"
    assert [s["step"] for s in r["steps"]] == [
        "Call Dana Okoye",
        "Send reminders to Bright Path and Marcus",
        "Put net-14 terms on the next three invoices",
    ]
    assert r["steps"][0]["why"].startswith("94 days")
    assert r["steps"][1]["when"] == "today"
    assert "why" not in r["steps"][1], "optional fields stay absent rather than empty"


def test_the_plan_is_stamped_as_chiefs_own_words():
    """The one line that keeps advice from reading as data."""
    r = _plan({"type": "show_plan", "steps": ["Call Dana"]})
    assert r["authored"] == "chief"


def test_a_bare_list_of_strings_is_accepted():
    """The shape a model reaches for first. Refusing it costs a turn to
    say so and teaches nothing."""
    r = _plan({"type": "show_plan", "steps": ["Call Dana", "Send the reminders"]})
    assert [s["step"] for s in r["steps"]] == ["Call Dana", "Send the reminders"]


def test_a_plan_with_no_steps_fails_instead_of_drawing_an_empty_card():
    for bad in ({}, {"steps": []}, {"steps": "call dana"}, {"steps": [{}, {"why": "no step"}]}):
        r = _plan({"type": "show_plan", **bad})
        assert r.get("success") is False or "fail" in str(r).lower() or "error" in str(r).lower(), bad


def test_steps_are_capped_and_the_truncation_is_declared():
    """A silently trimmed plan reads as complete. The cap must reach the
    model's own summary so it can say what was left out."""
    r = _plan({"type": "show_plan", "steps": [f"step {i}" for i in range(20)]})
    assert len(r["steps"]) == cos._PLAN_MAX_STEPS
    assert "dropped" in r["result"], r["result"]


def test_long_prose_is_bounded():
    r = _plan({"type": "show_plan", "title": "T" * 900,
               "steps": [{"step": "S" * 900, "why": "W" * 900}]})
    assert len(r["title"]) <= cos._PLAN_FIELD_MAX
    assert len(r["steps"][0]["step"]) <= cos._PLAN_FIELD_MAX
    assert len(r["steps"][0]["why"]) <= cos._PLAN_FIELD_MAX


def test_the_second_pass_can_say_the_plan_aloud():
    """`speak` is the seam every display verb uses so the spoken reply
    carries the substance instead of gesturing at a card."""
    r = _plan({"type": "show_plan", "steps": ["Call Dana", "Send reminders", "Tighten terms"]})
    assert "Call Dana" in r["speak"] and "Tighten terms" in r["speak"]


def test_show_plan_is_registered_as_UI_not_a_read():
    """Default-deny: an unregistered verb cannot dispatch at all.

    And the classification is UI rather than READ on purpose. The MCP
    tripwire caught this the moment it was added as a read — correctly.
    show_plan fetches nothing and returns only what the model supplied,
    so an outside agent calling it would be pushing a card at someone
    rather than reading anything. UI verbs are never offered off-app,
    and that exclusion is derived rather than listed."""
    import action_registry, mcp_server
    assert "show_plan" in cos.ACTION_HANDLERS
    assert "show_plan" in action_registry.REGISTRY
    assert action_registry.REGISTRY["show_plan"]["effect"] == action_registry.UI
    assert "show_plan" not in {t["name"] for t in mcp_server.tool_definitions()}


def test_the_prompt_names_it_and_forbids_inventing_figures():
    """The prompt is the capability surface — and a plan is the one
    display verb the model authors, so the no-invented-numbers rule has
    to live where the model reads it."""
    import inspect
    src = chief_source()
    assert '"type":"show_plan"' in src
    assert "no invented figures" in src.lower()
