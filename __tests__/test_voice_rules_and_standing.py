"""
test_voice_rules_and_standing.py — the voice-rule defects and the standing
block that repeated the permissions (Layer Two step 0, 2026-10-11).

Voice rules: undo built inverses without `list`, so it always failed; removal
by position could drop the wrong rule; the MCP propose tool had no arguments,
so every call failed; the ledger kept "Added voice do" and not the rule; and
the chat add left the pending observations in place, so Chief proposed again
next turn.

Standing: `standing_lines` was reused for the standing PERMISSIONS, so the
STANDING INSTRUCTIONS block printed the permissions twice and never the
owner's instructions.
"""
from __future__ import annotations

import asyncio
import collections
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import action_inverse as ai
import chief_of_staff as cos
import mcp_server as mcp
import voice_depth_agent as vda


# ─── undo ────────────────────────────────────────────────────────────

def test_undoing_an_add_removes_that_text_from_that_list():
    inv = ai.build_inverse("add_voice_rule",
                           {"type": "add_voice_rule", "list": "voice_dos", "rule": "Use first names"},
                           {"type": "add_voice_rule", "list": "voice_dos", "rule": "Use first names"})
    assert inv == {"type": "remove_voice_rule", "list": "voice_dos", "rule": "Use first names"}


def test_undoing_a_duplicate_add_does_nothing():
    """The rule was there before this action; undo must not delete it."""
    inv = ai.build_inverse("add_voice_rule",
                           {"list": "voice_dos", "rule": "Use first names"},
                           {"list": "voice_dos", "rule": "Use first names", "duplicate": True})
    assert inv is None


def test_undoing_a_remove_puts_the_same_text_back():
    inv = ai.build_inverse("remove_voice_rule",
                           {"list": "voice_donts", "rule": "No exclamation points"},
                           {"list": "voice_donts", "removed_rule": "No exclamation points"})
    assert inv == {"type": "add_voice_rule", "list": "voice_donts", "rule": "No exclamation points"}


def test_undoing_an_index_only_remove_uses_the_removed_text():
    inv = ai.build_inverse("remove_voice_rule",
                           {"list": "voice_donts", "idx": 2},
                           {"list": "voice_donts", "removed_rule": "Never say 'Dear'"})
    assert inv == {"type": "add_voice_rule", "list": "voice_donts", "rule": "Never say 'Dear'"}


def test_no_inverse_without_a_list_or_text():
    assert ai.build_inverse("add_voice_rule", {"rule": "x"}, {}) is None
    assert ai.build_inverse("remove_voice_rule", {"list": "voice_dos", "idx": 0}, {}) is None
    assert ai.build_inverse("add_voice_rule", {"list": "nope", "rule": "x"}, {}) is None


# ─── removal names the rule by text ──────────────────────────────────

@pytest.fixture
def rules(monkeypatch):
    state = {"voice_dos": ["A", "B", "C", "B"]}
    saved = {}
    monkeypatch.setattr(vda, "get_voice_depth", lambda owner: dict(state))

    def patch(path, body):
        saved.update(body)
        return [body]
    monkeypatch.setattr(vda, "_sb_patch", patch)
    return saved


def test_text_wins_over_a_stale_index(rules):
    res = vda.remove_voice_rule("o1", "voice_dos", idx=0, rule="C")
    assert res["ok"] and res["removed"] == "C"
    assert rules["voice_dos"] == ["A", "B", "B"]


def test_index_is_used_when_its_text_matches(rules):
    res = vda.remove_voice_rule("o1", "voice_dos", idx=3, rule="B")
    assert res["ok"] and rules["voice_dos"] == ["A", "B", "C"]


def test_a_rule_that_is_gone_is_refused_not_guessed(rules):
    res = vda.remove_voice_rule("o1", "voice_dos", idx=1, rule="Z")
    assert not res["ok"] and "voice_dos" not in rules


def test_index_only_removal_still_works(rules):
    res = vda.remove_voice_rule("o1", "voice_dos", 1)
    assert res["ok"] and res["removed"] == "B"


# ─── the chat handlers ───────────────────────────────────────────────

def test_chat_add_keeps_the_text_and_clears_observations(monkeypatch):
    cleared = []
    monkeypatch.setattr(vda, "add_voice_rule",
                        lambda o, l, r: {"ok": True, "list": l, "count": 1})
    monkeypatch.setattr(vda, "clear_observations_after_rule",
                        lambda o: cleared.append(o) or {"ok": True})
    res = asyncio.run(cos.handle_add_voice_rule(
        None, {"id": "b1", "owner_id": "o1"},
        {"list": "voice_dos", "rule": "Open with their first name"}))
    assert "Open with their first name" in res["label"]
    assert "Open with their first name" in res["result"]
    assert res["list"] == "voice_dos" and res["rule"] == "Open with their first name"
    assert res["duplicate"] is False
    assert cleared == ["o1"]


def test_chat_remove_by_text(monkeypatch):
    seen = {}

    def remove(o, l, idx=None, rule=None):
        seen.update(owner=o, list=l, idx=idx, rule=rule)
        return {"ok": True, "removed": rule, "remaining": 0}
    monkeypatch.setattr(vda, "remove_voice_rule", remove)
    res = asyncio.run(cos.handle_remove_voice_rule(
        None, {"id": "b1", "owner_id": "o1"},
        {"list": "voice_donts", "rule": "Never use emojis"}))
    assert seen == {"owner": "o1", "list": "voice_donts", "idx": None, "rule": "Never use emojis"}
    assert "Never use emojis" in res["label"]
    assert res["removed_rule"] == "Never use emojis"
    assert not res.get("failed")


def test_chat_remove_needs_a_list_and_a_target():
    res = asyncio.run(cos.handle_remove_voice_rule(
        None, {"id": "b1", "owner_id": "o1"}, {"list": "voice_dos"}))
    assert res.get("failed") or str(res.get("result", "")).startswith("Failed")


def test_mcp_propose_voice_rule_takes_list_and_rule():
    _desc, schema = mcp.TOOL_SCHEMAS["propose_voice_rule"]
    assert set(schema["required"]) == {"list", "rule"}
    assert schema["properties"]["list"]["enum"] == ["voice_dos", "voice_donts"]


# ─── the settings screen writes a ledger row ─────────────────────────

def test_rest_add_and_remove_write_ledger_rows(monkeypatch):
    import audit_log
    import sb_clients
    import voice_depth_router as vdr
    from auth_supabase import AuthedUser

    rows = []
    monkeypatch.setattr(audit_log, "record", lambda bid, **kw: rows.append((bid, kw)) or True)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [{"id": "b1"}])
    monkeypatch.setattr(vda, "add_voice_rule", lambda o, l, r: {"ok": True, "list": l, "count": 1})
    monkeypatch.setattr(vda, "remove_voice_rule",
                        lambda o, l, idx=None, rule=None: {"ok": True, "removed": "Say thanks", "remaining": 0})
    user = AuthedUser(id="o1", email=None, role="authenticated")

    vdr.add_rule("o1", {"list": "voice_dos", "rule": "Say thanks"}, user)
    vdr.remove_rule("o1", {"list": "voice_dos", "idx": 0}, user)

    assert [r[1]["verb"] for r in rows] == ["add_voice_rule", "remove_voice_rule"]
    assert all(r[0] == "b1" for r in rows)
    assert all("Say thanks" in r[1]["summary"] for r in rows)


def test_rest_duplicate_add_writes_no_row(monkeypatch):
    import audit_log
    import sb_clients
    import voice_depth_router as vdr
    from auth_supabase import AuthedUser

    rows = []
    monkeypatch.setattr(audit_log, "record", lambda bid, **kw: rows.append(bid) or True)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [{"id": "b1"}])
    monkeypatch.setattr(vda, "add_voice_rule",
                        lambda o, l, r: {"ok": True, "duplicate": True, "list": l, "count": 1})
    vdr.add_rule("o1", {"list": "voice_dos", "rule": "Say thanks"},
                 AuthedUser(id="o1", email=None, role="authenticated"))
    assert rows == []


# ─── standing instructions vs standing permissions ───────────────────

def _ctx(**over):
    base = collections.defaultdict(lambda: [], {
        "business": {"id": "b1", "name": "Biz",
                     "settings": {"practitioner_name": "K",
                                  "autonomy": {"standing": {
                                      "send_sms": {"granted_at": "2026-09-05T10:00:00Z"}}}},
                     "voice_profile": {}}})
    base.update(over)
    return base


def _block(text, heading):
    after = text.split(heading, 1)[1]
    return after.split("\n\n", 1)[0]


def _snapshot(ctx):
    parts = cos._format_context_parts(ctx)
    return parts if isinstance(parts, str) else parts[0] + "\n" + parts[1]


def test_standing_instructions_show_the_owners_words_not_the_permissions():
    text = _snapshot(_ctx(memories=[
        {"id": "m1", "category": "standing_instruction", "source": "user_stated",
         "importance": 8, "content": "INSTR_TEXT_1", "created_at": "2026-10-01"}]))
    instructions = _block(text, "STANDING INSTRUCTIONS (execute when triggered):")
    permissions = _block(text, "STANDING PERMISSIONS:")
    assert "INSTR_TEXT_1" in instructions
    assert "revoke_standing_permission" not in instructions
    assert "revoke_standing_permission" in permissions
    assert "INSTR_TEXT_1" not in permissions
    # Rendered once, not again among the memories.
    assert text.count("INSTR_TEXT_1") == 1


def test_an_inferred_standing_instruction_is_not_an_order():
    text = _snapshot(_ctx(memories=[
        {"id": "m2", "category": "standing_instruction", "source": "ai_inferred",
         "importance": 8, "content": "INFERRED_TEXT_2", "created_at": "2026-10-01"}]))
    instructions = _block(text, "STANDING INSTRUCTIONS (execute when triggered):")
    assert "INFERRED_TEXT_2" not in instructions
    assert "(none set)" in instructions
    # It stays visible — as an assumption among the memories.
    assert "INFERRED_TEXT_2" in text and "inferred assumption" in text


def test_no_grants_reads_as_none_under_permissions():
    ctx = _ctx()
    ctx["business"]["settings"].pop("autonomy")
    text = _snapshot(ctx)
    assert "(none — every send" in _block(text, "STANDING PERMISSIONS:")
