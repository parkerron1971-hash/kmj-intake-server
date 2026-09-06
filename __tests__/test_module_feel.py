"""
test_module_feel.py — Chief knows how a module looks and can change how
it feels.

Live, 9/06: asked "how does my Leads module look?", Chief ran the health
check, said it had no tool for a design look, and when asked for
animation queued a build request for a capability the surfaces already
have. Three things are pinned here: inspect starts the look itself,
set_module_feel is a real lever, and the prompt says motion is built in.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_module_actions as cma

BIZ = {"id": "b1", "owner_id": "u1", "name": "Score Up"}
ROW = {"id": "m1", "name": "Leads", "slug": "leads", "archetype": "work_pipeline",
       "schema": {"fields": [{"name": "title", "type": "text", "label": "Lead"}]},
       "agent_config": {}, "presentation": {"empty_line": "First call is the pipeline."}}


@pytest.fixture
def wired(monkeypatch):
    import module_check
    import module_check_router
    import sb_clients
    state = {"enqueued": [], "patched": []}

    async def fake_sb(client, method, path, body=None):
        return [dict(ROW)] if method == "GET" else None
    monkeypatch.setattr(cma, "_sb", fake_sb)
    monkeypatch.setattr(module_check, "latest_report", lambda b, m: None)

    async def fake_enqueue(user_id, business_id, module_id, reason="accepted"):
        state["enqueued"].append((user_id, business_id, module_id, reason))
    monkeypatch.setattr(module_check_router, "enqueue_after_accept", fake_enqueue)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body: (state["patched"].append((path, body)), [body])[1])
    return state


def test_inspect_starts_the_design_look_when_there_is_no_verdict(wired):
    out = asyncio.run(cma.handle_inspect_module(None, BIZ, {"type": "inspect_module", "module": "leads"}))
    assert out["type"] == "inspect_module"
    assert "started the design look" in out["result"]
    assert wired["enqueued"] == [("u1", "b1", "m1", "asked")]


def test_inspect_reads_a_verdict_back_instead(wired, monkeypatch):
    import module_check
    monkeypatch.setattr(module_check, "latest_report", lambda b, m: {
        "ok": True, "summary": "Leads: nothing out of place; design 4/5.", "design_score": 4,
        "first_impression": "A confident board.", "findings": [], "next": ["a subtotal per column"],
        "finished_at": "2026-09-06T21:00:00+00:00"})
    out = asyncio.run(cma.handle_inspect_module(None, BIZ, {"type": "inspect_module", "module": "leads"}))
    assert "Last look:" in out["result"] and "design 4/5" in out["label"]
    assert not wired["enqueued"]


def test_set_module_feel_changes_the_tone_and_looks_again(wired):
    out = asyncio.run(cma.handle_set_module_feel(None, BIZ, {"type": "set_module_feel", "module": "leads", "tone": "bold"}))
    assert out["type"] == "set_module_feel" and "reads bold" in out["label"]
    path, body = wired["patched"][0]
    assert path == "/custom_modules?id=eq.m1"
    assert body["presentation"] == {"empty_line": "First call is the pipeline.", "tone": "bold"}
    assert wired["enqueued"] == [("u1", "b1", "m1", "feel")]


def test_set_module_feel_refuses_a_made_up_tone_and_an_empty_ask(wired):
    out = asyncio.run(cma.handle_set_module_feel(None, BIZ, {"type": "set_module_feel", "module": "leads", "tone": "sassy"}))
    assert "Failed" in out.get("result", "") or out.get("failed") or "tone must be" in str(out)
    out = asyncio.run(cma.handle_set_module_feel(None, BIZ, {"type": "set_module_feel", "module": "leads"}))
    assert not wired["patched"]


def test_set_module_feel_takes_an_empty_line_too(wired):
    out = asyncio.run(cma.handle_set_module_feel(
        None, BIZ, {"type": "set_module_feel", "module_id": "m1", "empty_line": "Nobody in the door yet — the first call changes that."}))
    assert "empty line says" in out["label"]
    assert wired["patched"][0][1]["presentation"]["empty_line"].startswith("Nobody in the door")


def test_the_prompt_the_palette_and_the_registry_carry_it():
    import chief_of_staff as cos
    import chief_prompt
    import action_registry as reg
    import module_spec_generator as msg
    assert "set_module_feel" in cos.ACTION_HANDLERS
    assert reg.REGISTRY["set_module_feel"]["reversibility"] == "A"
    src = pathlib.Path(chief_prompt.__file__).read_text(encoding="utf-8")
    assert '"type":"set_module_feel"' in src and "never say a module cannot have animation" in src
    assert "how does [module] look" in src
    palette = msg.module_palette_block()
    assert "already MOVES" in palette and "set_module_feel" in palette


@pytest.mark.parametrize("msg, allowed", [
    ("How do you the lead module look?", False),
    ("can you add to the design. animation?", False),
    ("does my dashboard look right", False),
    ("what do coaches charge in Michigan?", True),
    ("what's trending in leadership this month?", True),
])
def test_search_stays_off_for_the_products_own_surfaces(msg, allowed):
    import chief_of_staff as cos
    assert cos._web_search_allowed(msg) is allowed
