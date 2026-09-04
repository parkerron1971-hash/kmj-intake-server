"""Missions from a non-chat trigger: the standing agent can draft a plan.

propose_mission (class A: it drafts a row and executes nothing) joins the
reviewed write tools, so the standing agent — and a write-scope
connector key — can turn an event that takes several moves into a plan
the practitioner reads and starts. start_mission stays class C and is
never a tool.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import action_registry
import chief_tool_loop as ctl
import mcp_server as mcp


def test_propose_mission_is_a_write_tool_and_start_mission_is_not():
    assert "propose_mission" in mcp.WRITE_TOOL_SCHEMAS
    assert action_registry.reversibility("propose_mission") == "A"
    assert "propose_mission" in mcp.exposed_tools(allow_writes=True)
    assert "start_mission" not in mcp.exposed_tools(allow_writes=True)
    assert "advance_mission" not in mcp.exposed_tools(allow_writes=True)
    desc, schema = mcp.WRITE_TOOL_SCHEMAS["propose_mission"]
    assert "Executes nothing" in desc
    assert set(schema["required"]) == {"title", "steps"}
    step = schema["properties"]["steps"]["items"]
    assert step["required"] == ["title", "action"]
    assert step["properties"]["action"]["required"] == ["type"]


def test_the_standing_agent_and_a_write_key_are_offered_it():
    async def agent_turn():
        ctl.reset_turn(True, surface="agent", prompted=False)
        return [t["name"] for t in ctl.tool_definitions_for_turn(True)]
    assert "propose_mission" in asyncio.run(agent_turn())
    ctl.reset_turn(False)
    write_key = mcp.Caller("token", "agent:x", user_id="u", business_id="b",
                           scopes=["read", "write"], jti="j")
    read_key = mcp.Caller("token", "agent:x", user_id="u", business_id="b",
                          scopes=["read"], jti="j")
    assert "propose_mission" in [t["name"] for t in mcp.tool_definitions(write_key)]
    assert "propose_mission" not in [t["name"] for t in mcp.tool_definitions(read_key)]


def test_a_mission_drafted_through_the_tool_executes_nothing(monkeypatch):
    """The tool loop dispatches through the door to the real handler,
    which writes ONE draft row and runs no step."""
    import chief_of_staff as cos
    import chief_missions
    posts = []

    async def _sb(client, method, path, body=None):
        posts.append((method, path, body))
        if method == "POST" and path.startswith("/chief_missions"):
            return [{"id": "m-1", **(body or {})}]
        return []
    monkeypatch.setattr(cos, "_sb", _sb)
    monkeypatch.setattr(chief_missions, "_sb", _sb, raising=False)
    ran = []
    for v in ("send_sms", "create_task"):
        monkeypatch.setitem(cos.ACTION_HANDLERS, v, (lambda *a, **k: ran.append(v) or {"result": "x", "label": "x"}))

    async def turn():
        ctl.reset_turn(True, surface="agent", prompted=False)
        return await ctl.execute_tool_use(None, {"id": "b-1", "name": "Biz", "settings": {}}, "propose_mission", {
            "title": "Collect the overdue invoice",
            "goal": "get INV-3 paid",
            "steps": [{"title": "Remind them", "action": {"type": "create_task", "title": "Call about INV-3"}},
                      {"title": "Text them", "action": {"type": "send_sms", "contact_name": "Sam", "message": "..."}}]})
    err, text = asyncio.run(turn())
    ctl.reset_turn(False)
    assert not err, text
    assert ran == [], "a draft plan runs no step"
    assert any(m == "POST" and p.startswith("/chief_missions") for m, p, _ in posts), "the plan row was written"
