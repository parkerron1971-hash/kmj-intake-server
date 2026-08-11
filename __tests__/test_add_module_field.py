"""
test_add_module_field.py — Chief can change what it built.

Until this verb, Chief's module surface was create / accept / reject /
upgrade-archetype / inspect plus row CRUD. Nothing edited a schema, so
"add a phone number to my bookings" had no answer from the one surface
whose entire promise is that you can just ask.

The two things that must hold:
  1. ADDITIVE ONLY. Removing or retyping a field does not delete
     module_entries.data — it is jsonb and keeps every key — it makes the
     value INVISIBLE, with no way for the practitioner to know it is
     still there. Adding is reversible; that kind of removing is not.
  2. CHECK BEFORE WRITING. validateModuleSchema is a hard render gate:
     one bad field takes the WHOLE module and every row off the screen.
"""

import asyncio

import pytest

import chief_of_staff as cos

BIZ = {"id": "b1", "type": "coach"}
MODULE = {
    "id": "11111111-1111-1111-1111-111111111111",
    "name": "Bookings", "slug": "bookings",
    "schema": {"fields": [{"name": "title", "type": "text", "label": "Title"}],
               "views": ["list"]},
    "agent_config": {"enabled": True, "triggers": []},
}


def _run(action, module=MODULE, patch_ok=True, landed=None):
    """Drive the handler with a fake Supabase. `landed` is what the
    read-back returns, so a lying PATCH can be simulated."""
    calls = []

    async def fake_sb(client, method, path, body=None):
        calls.append((method, path, body))
        if method == "GET" and "select=schema" in path:
            fields = module["schema"]["fields"] if landed is None else landed
            return [{"schema": {**module["schema"], "fields": fields}}]
        if method == "GET":
            return [module] if module else []
        if method == "PATCH":
            if patch_ok and landed is None:
                # reflect the write so the read-back sees it
                module["schema"] = body["schema"]
            return [{"id": module["id"]}] if patch_ok else None
        return None

    orig = cos._sb
    cos._sb = fake_sb
    try:
        out = asyncio.run(cos.handle_add_module_field(None, BIZ, action))
    finally:
        cos._sb = orig
    return out, calls


def _fresh():
    import copy
    return copy.deepcopy(MODULE)


def test_adds_a_field_and_says_so():
    m = _fresh()
    out, calls = _run({"module": "bookings", "name": "phone", "type": "phone"}, m)
    assert "✅" in out["label"] and "Bookings" in out["label"]
    assert [f["name"] for f in m["schema"]["fields"]] == ["title", "phone"]
    assert any(c[0] == "PATCH" for c in calls)


def test_label_defaults_to_a_readable_form_of_the_name():
    m = _fresh()
    _run({"module": "bookings", "name": "next_action_date", "type": "date"}, m)
    assert m["schema"]["fields"][-1]["label"] == "Next Action Date"


def test_refuses_a_field_type_that_does_not_exist():
    out, calls = _run({"module": "bookings", "name": "x", "type": "colour"}, _fresh())
    assert out.get("failed") or "Failed" in out["result"]
    assert not any(c[0] == "PATCH" for c in calls), "must not write"


def test_refuses_a_duplicate_name():
    out, calls = _run({"module": "bookings", "name": "title", "type": "text"}, _fresh())
    assert "already a field" in out["result"]
    assert not any(c[0] == "PATCH" for c in calls)


def test_refuses_a_field_that_would_break_rendering():
    """THE guard. A select with no options makes DynamicModule replace the
    entire module — every row — with a red error panel."""
    out, calls = _run({"module": "bookings", "name": "status", "type": "select"}, _fresh())
    assert "stop the module displaying" in out["result"]
    assert not any(c[0] == "PATCH" for c in calls), "must not write a breaking field"


def test_a_valid_select_with_options_is_allowed():
    m = _fresh()
    out, _ = _run({"module": "bookings", "name": "status", "type": "select",
                   "options": ["new", "done"]}, m)
    assert "✅" in out["label"]
    assert m["schema"]["fields"][-1]["options"] == ["new", "done"]


def test_module_ref_needs_its_target_here_too():
    out, calls = _run({"module": "bookings", "name": "matter", "type": "module_ref"},
                      _fresh())
    assert "stop the module displaying" in out["result"]
    assert not any(c[0] == "PATCH" for c in calls)


def test_module_ref_with_a_target_is_allowed():
    m = _fresh()
    out, _ = _run({"module": "bookings", "name": "matter", "type": "module_ref",
                   "module_slug": "matters"}, m)
    assert "✅" in out["label"]


def test_unknown_module_fails_without_writing():
    out, calls = _run({"module": "nope", "name": "x", "type": "text"}, None)
    assert "no module called" in out["result"]
    assert not any(c[0] == "PATCH" for c in calls)


def test_a_rejected_patch_is_reported_not_swallowed():
    """sb PATCH returns None on a 4xx. Reporting success over a lost write
    is the failure module_inspect was built for."""
    out, _ = _run({"module": "bookings", "name": "phone", "type": "phone"},
                  _fresh(), patch_ok=False)
    assert "nothing was saved" in out["result"]


def test_a_lying_patch_is_caught_by_the_read_back():
    """A 200 is not evidence the column holds what we sent."""
    out, _ = _run({"module": "bookings", "name": "phone", "type": "phone"},
                  _fresh(), landed=[{"name": "title", "type": "text", "label": "T"}])
    assert "not there" in out["result"]


def test_the_verb_is_registered_and_classified():
    import action_registry

    assert "add_module_field" in cos.ACTION_HANDLERS
    assert action_registry.effect("add_module_field") == action_registry.WRITE
    assert action_registry.reversibility("add_module_field") == "A"


def test_it_is_not_on_the_agent_surface():
    """A write must never reach the read-only MCP surface."""
    import mcp_server

    assert "add_module_field" not in mcp_server.exposed_tools()


# ─── Is Chief actually told these exist? ──────────────────────────────

class _EmptyCtx(dict):
    def __missing__(self, key):
        return []


def _prompt():
    return cos._build_system_prompt(
        _EmptyCtx(business={"id": "b1", "name": "T", "type": "coach",
                            "settings": {}, "voice_profile": {}}), False)


@pytest.mark.parametrize("verb", ["add_module_field", "inspect_module"])
def test_chief_is_told_the_module_verbs_exist(verb):
    """THE lesson of this arc, applied to verbs instead of field types.

    inspect_module shipped in #515, was registered in ACTION_HANDLERS and
    exposed on the MCP surface — and was NEVER NAMED IN CHIEF'S OWN
    PROMPT. An outside agent could call it; Chief could not, because a
    verb the prompt never mentions is a verb the model never emits. It sat
    unreachable from the surface it was built for until this commit.

    Registering a handler is not shipping a capability.
    """
    assert verb in _prompt(), (
        f"{verb} is in ACTION_HANDLERS but Chief's system prompt never "
        f"names it — Chief cannot emit a verb it was not told about")
