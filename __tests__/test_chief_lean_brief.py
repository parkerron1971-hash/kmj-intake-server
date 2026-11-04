"""
test_chief_lean_brief.py — Chief's short brief (CHIEF_BRIEF=lean), 2026-11-03.

The short brief keeps every rule and the full how-to of the verbs that do
~90% of Chief's work; every other verb keeps one line and its full how-to
comes back from the action_guide lookup; rarely used tools are deferred;
the snapshot is a digest the answer check also reviews. These tests pin:

- off (the default) is today's brief: the lean code never runs;
- nothing is lost: every line of the full manual is in the short one or
  comes back from the lookup, every handler is still dispatchable, every
  tool is still sent, every deferred tool can be loaded;
- the universal block is identical across businesses and every cached
  segment stays far above the model's 1,024-token minimum;
- the digest is what the answer check reviews.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import chief_lean_brief as lean
import chief_of_staff as chief
import chief_tool_loop as ctl

BIZ = {"id": "00000000-0000-4000-8000-000000000011", "name": "Example Studio",
       "type": "business coaching", "owner_id": "00000000-0000-4000-8000-0000000000ee",
       "settings": {}}
CHURCH = {"id": "00000000-0000-4000-8000-000000000012", "name": "Grace Street Fellowship",
          "type": "ministry", "owner_id": "00000000-0000-4000-8000-0000000000ee",
          "settings": {"practitioner_name": "Ann Lee"}}


def _system(biz=BIZ, greeting=False, ctx=None):
    import chief_turn_eval as te
    return chief._build_system_prompt(ctx or te._fixture_context(biz), greeting)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("CHIEF_BRIEF", "lean")
    yield
    monkeypatch.delenv("CHIEF_BRIEF", raising=False)


@pytest.fixture
def off(monkeypatch):
    monkeypatch.delenv("CHIEF_BRIEF", raising=False)


def _full_manual():
    """The FULL manual this process builds (the short one is cut from it)."""
    system = _system()
    full = lean.full_manual() if lean.LEAN_MARK in system else lean.segments(system)["universal"]
    assert full and lean.LEAN_MARK not in full
    return full


# ── the switch ───────────────────────────────────────────────────────────

def test_off_is_todays_brief_the_lean_code_never_runs(off, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("lean code ran with the switch off")
    for name in ("lean_manual", "digest_for_prompt", "with_digest_note", "digest_context"):
        monkeypatch.setattr(lean, name, boom)
    system = _system()
    assert lean.LEAN_MARK not in system
    assert not lean.active_for(system)
    import chief_truth
    import chief_turn_eval as te
    ctx = te._fixture_context(BIZ)
    assert lean.digest_for(ctx) is ctx
    chief_truth.evidence_for_review(ctx, "", [])


def test_on_changes_only_the_manual_and_the_snapshot(off, monkeypatch):
    import chief_turn_eval as te
    ctx = te._fixture_context(BIZ)
    full = lean.segments(_system(ctx=ctx))
    monkeypatch.setenv("CHIEF_BRIEF", "lean")
    short = lean.segments(_system(ctx=ctx))
    assert short["per_business"] == full["per_business"]
    assert short["tail"] == full["tail"]
    assert lean.LEAN_MARK in short["universal"] and lean.LEAN_MARK not in full["universal"]
    assert len(short["universal"]) < 0.65 * len(full["universal"])


def test_the_lean_tools_travel_only_with_the_lean_manual(on):
    assert not lean.active_for("You are Chief. A prompt without the short manual.")
    assert lean.active_for(_system())
    assert lean.active_for([{"type": "text", "text": _system()}])


# ── nothing is lost ──────────────────────────────────────────────────────

def test_every_line_of_the_full_manual_is_kept_or_comes_back_from_the_lookup(on):
    full = _full_manual()
    short = lean.lean_manual(full)
    for section in lean._parsed(full):
        area = lean._area_name(section.header)
        whole = lean.guide(area, full) if area else ""
        for line, own in zip(section.lines, section.owners):
            if not line.strip() or line in short:
                continue
            found = whole and line in whole
            for verb in sorted(own or ()):
                found = found or line in (lean.guide(verb, full) or "")
            assert found, ("lost from the short manual and the lookup", section.header[:60], line[:120])


def test_every_handler_is_still_dispatchable_and_its_how_to_retrievable(on):
    import chief_turn_eval  # noqa: F401  (the fixture context)
    handlers_before = dict(chief.ACTION_HANDLERS)
    full = _full_manual()
    short = lean.lean_manual(full)
    assert chief.ACTION_HANDLERS == handlers_before, "the short brief must not touch dispatch"
    for verb in sorted(chief.ACTION_HANDLERS):
        lines = [line for s in lean._parsed(full) if not s.rule
                 for line, own in zip(s.lines, s.owners) if own and verb in own and line.strip()]
        if not lines:
            continue
        how = lean.guide(verb, full) or ""
        for line in lines:
            assert line in short or line in how, (verb, line[:120])
        if verb not in lean.KEEP_VERBS:
            assert f"· {verb}" in short or verb in short, f"{verb} has no line in the short manual"


def test_every_tool_is_still_sent_and_every_deferred_one_can_be_loaded(on):
    _system()  # the manual this process uses
    ctl.reset_turn(writes_allowed=True)
    tools = ctl.tool_definitions_for_turn(True)
    out = lean.tools_for_request(tools)
    names = [t["name"] for t in out]
    assert names[:len(tools)] == [t["name"] for t in tools], "a tool was dropped or moved"
    assert names[-1] == lean.TOOL_NAME
    deferred = [t for t in out if t.get("defer_loading")]
    loaded = [t for t in out if not t.get("defer_loading")]
    assert deferred and loaded
    assert not any("cache_control" in t for t in deferred)
    for t in loaded:
        assert t["name"] in lean.LOADED_TOOLS or t["name"] == lean.TOOL_NAME or t.get("type")
    listing = out[-1]["description"]
    for t in deferred:
        assert t["name"] in listing
        is_error, content = lean.tool_result({"name": t["name"]})
        assert not is_error and content == [{"type": "tool_reference", "tool_name": t["name"]}]
    # A tool the manual explains carries that how-to when it is loaded.
    with_how = [t for t in deferred if "How-to, from Chief's manual" in t["description"]]
    assert with_how


def test_the_lookup_answers_a_verb_an_area_and_a_typo(on):
    _system()
    lean._DEFERRED.set(())  # no request in flight: every name answers in words
    is_error, text = lean.tool_result({"name": "plan_content"})
    assert not is_error and "plan_content" in text and "[ACTION:" in text
    is_error, text = lean.tool_result({"name": "store"})
    assert not is_error and "STORE" in text
    is_error, text = lean.tool_result({"name": "plan_contnet"})
    assert is_error and "plan_content" in text
    assert lean.tool_result({})[0] is True


def test_the_kept_verbs_and_every_rule_section_are_written_out_in_full(on):
    full = _full_manual()
    short = lean.lean_manual(full)
    for s in lean._parsed(full):
        if s.rule:
            assert "\n".join(s.lines).strip() in short, s.header[:60]
        else:
            for line, own in zip(s.lines, s.owners):
                if own and own & lean.KEEP_VERBS:
                    assert line in short, line[:120]
    for rule in ("TRUST BOUNDARY", "ACTIONS — BUILDER BRIDGE", "STANDING PERMISSIONS",
                 "ADAPTIVE EXECUTION", "SMS & consent", "Autonomy:", "Deflection"):
        assert rule in short, rule


def test_which_areas_send_their_prose_to_the_lookup_is_a_decision(on):
    """An area none of whose verbs is kept keeps only its header line and
    its one-line entries. A new section that would join this list may be
    a rule in an area's clothes: decide, then pin it here (or add it to
    RULE_SECTIONS / PROSE_KEPT)."""
    assert lean.prose_to_lookup(_full_manual()) == [
        "ACTIONS — THE WORKSPACE ITSELF (what their home ",
        "ACTIONS — TIMERS & ALARMS:",
        "REVENUE & TAX:",
    ]


def test_the_rare_actions_eval_asks_only_for_verbs_outside_the_kept_set():
    import chief_rare_actions_eval as rare
    for case in rare.CASES:
        assert case["expect_any"]
        for verb in case["expect_any"]:
            assert verb in chief.ACTION_HANDLERS, verb
        assert not set(case["expect_any"]) & lean.KEEP_VERBS, case["id"]


# ── the universal block and the cache ────────────────────────────────────

def test_the_short_manual_is_the_same_for_every_business(on):
    a = lean.segments(_system(BIZ, greeting=False))["universal"]
    b = lean.segments(_system(CHURCH, greeting=True))["universal"]
    assert a == b


def test_every_cached_segment_stays_above_the_cache_minimum(on):
    segs = lean.segments(_system())
    # ~3.6 characters a token in this text; 4 is the safe side.
    running = 0
    for name in ("universal", "per_business", "state"):
        running += len(segs[name])
        assert running // 4 > 1024 * 4, (name, running)
    assert len(segs["universal"]) // 4 > 1024 * 10


# ── the tool round ───────────────────────────────────────────────────────

def test_a_lookup_in_the_tool_round_loads_a_tool_and_spends_no_lookup(on):
    _system()
    ctl.reset_turn(writes_allowed=True)
    out = lean.tools_for_request(ctl.tool_definitions_for_turn(True))
    deferred = next(t["name"] for t in out if t.get("defer_loading"))
    content = [{"type": "tool_use", "id": "toolu_1", "name": lean.TOOL_NAME,
                "input": {"name": deferred}},
               {"type": "tool_use", "id": "toolu_2", "name": lean.TOOL_NAME,
                "input": {"name": "make_offer"}}]
    async def turn():
        step = await ctl.run_tool_round(None, BIZ, content, 0)
        return step, lean.looked_up()  # the same task: what the door sees later

    step, looked = asyncio.run(turn())
    assistant, results, n_calls = step
    assert n_calls == 0
    first, second = results["content"]
    assert first["content"] == [{"type": "tool_reference", "tool_name": deferred}]
    assert isinstance(second["content"], str) and "make_offer" in second["content"]
    assert set(looked) >= {deferred, "make_offer"}


def test_call_claude_sends_the_lean_tools_only_with_the_lean_manual(on, monkeypatch):
    import llm_call
    sent = []

    class _Resp:
        status_code = 200
        text = ""

        def __init__(self, body):
            self._body = body

        def json(self):
            return self._body

    async def fake_post(client, payload, **kw):
        sent.append(json.loads(json.dumps(payload)))
        return _Resp({"content": [{"type": "text", "text": "Done."}], "stop_reason": "end_turn",
                      "usage": {"input_tokens": 1, "output_tokens": 1}})

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(llm_call, "apost", fake_post)
    import spend_guard
    monkeypatch.setattr(spend_guard, "over_budget", lambda *a, **k: False)
    ctl.reset_turn(writes_allowed=True)
    tools = ctl.tool_definitions_for_turn(True)
    system = _system()
    asyncio.run(chief._call_claude(None, system, [{"role": "user", "content": "hi"}],
                                   enable_web_search=False, read_tools=tools, tool_biz=BIZ))
    names = [t["name"] for t in sent[-1]["tools"]]
    assert lean.TOOL_NAME in names and any(t.get("defer_loading") for t in sent[-1]["tools"])
    asyncio.run(chief._call_claude(None, "A prompt without the short manual.",
                                   [{"role": "user", "content": "hi"}],
                                   enable_web_search=False, read_tools=tools, tool_biz=BIZ))
    assert lean.TOOL_NAME not in [t["name"] for t in sent[-1]["tools"]]
    assert not any(t.get("defer_loading") for t in sent[-1]["tools"])


# ── the snapshot digest ──────────────────────────────────────────────────

def _memories(n, category="fact", pad=400):
    return [{"id": f"m{i}", "category": category, "content": f"memory number {i} " + "x" * pad,
             "importance": 5, "source": "owner"} for i in range(n)]


def test_the_digest_cuts_long_lists_and_keeps_standing_orders(on):
    import chief_turn_eval as te
    ctx = te._fixture_context(BIZ)
    standing = [{"id": "s1", "category": "standing_instruction", "content": "Always cc me.",
                 "importance": 8, "source": "owner"}]
    ctx = {**ctx, "memories": _memories(40) + standing,
           "contacts_lookup": [{"id": f"c{i}", "name": f"P{i}", "status": "active",
                                "health_score": 50} for i in range(80)],
           "sms_messages": [{"id": f"t{i}"} for i in range(15)]}
    d = lean.digest_context(ctx)
    assert len(d["contacts_lookup"]) == lean.CONTACTS_SHOWN and len(ctx["contacts_lookup"]) == 80
    assert len(d["sms_messages"]) == lean.TEXTS_KEPT
    kept = [m["id"] for m in d["memories"]]
    if chief._is_owner_standing_instruction(standing[0]):
        assert "s1" in kept
    assert len([k for k in kept if k.startswith("m")]) == lean.MEMORIES_KEPT
    assert all(len(m["content"]) <= lean.MEMORY_CHARS + 40 for m in d["memories"])
    assert d["_lean_digest_notes"]


def test_the_answer_check_reviews_the_digest_chief_was_shown(on):
    import chief_truth
    import chief_turn_eval as te
    ctx = te._fixture_context(BIZ)
    ctx = {**ctx, "memories": _memories(30, pad=10)}
    system = _system(ctx=ctx)
    assert "SHORTENED IN THIS SNAPSHOT" in system
    shown = chief_truth.evidence_for_review(ctx, "", [])
    text = json.dumps(shown)
    assert "memory number 3 " in text and "memory number 29 " not in text


def test_off_the_answer_check_reviews_the_whole_snapshot(off):
    import chief_truth
    import chief_turn_eval as te
    ctx = te._fixture_context(BIZ)
    ctx = {**ctx, "memories": _memories(30, pad=10)}
    _system(ctx=ctx)
    assert "memory number 29 " in json.dumps(chief_truth.evidence_for_review(ctx, "", []))
