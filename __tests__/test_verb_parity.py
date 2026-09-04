"""
test_verb_parity.py — every verb Chief has is a verb Chief can be asked
to use.

The Jarvis arc, step 2 (Kevin, 8/14: "anything that is requested in the
system, I want Chief to be able to do with no problem"). The audit that
opened this step found 16 verbs with handlers, registry entries, and in
several cases their own tested modules — that the system prompt never
mentioned. The prompt is the capability surface: a verb the prompt never
names is a verb Chief doesn't have, no matter how much code stands
behind it. Ten of them were WRITES — time tracking, prepaid balances,
recurring bookings, giving statements, undo — wired long ago and mute
ever since. "Undo that" did nothing, silently, for months.

The ratchet: a verb in ACTION_HANDLERS must be either

  (a) NAMED IN THE PROMPT REGION — the practitioner can invoke it in
      conversation, or
  (b) ON THE TOOL-LOOP SURFACE (the MCP read set) — Chief reaches it
      mid-thought without needing a tag.

No third bucket, no hand-kept exception list to rot. A future PR that
registers a handler without giving Chief the words fails here with the
verb's name in the message.
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from __tests__._chief_source import chief_source  # noqa: E402
import chief_of_staff as cos
import mcp_server


def _prompt_region() -> str:
    src = chief_source()
    i = src.index("def _build_system_prompt")
    # to the next async def, or the end: chief_prompt (2026-09-04) ends
    # with the two synchronous assemblers, so there may be none after.
    j = src.find(chr(10) + "async def ", i)
    return src[i:] if j == -1 else src[i:j]


def test_the_region_extraction_actually_sees_the_prompt():
    """Guarding the guard: a region that missed the prompt entirely
    would pass the ratchet by matching nothing."""
    region = _prompt_region()
    for known in ("show_view", "create_contact", "draft_email", "navigate"):
        assert known in region, f"region extraction lost {known}"
    assert len(region) > 50_000, "the prompt region is far bigger than this"


def _prompt_bearing_sources() -> str:
    """Every module that documents action tags — auto-discovered by the
    doc marker itself, so a future coach module joins the search surface
    the day it starts documenting verbs."""
    root = pathlib.Path(cos.__file__).parent
    out = []
    for f in root.glob("*.py"):
        try:
            t = f.read_text(encoding="utf-8")
        except OSError:
            continue
        if "[ACTION:{" in t or "[ACTION:{{" in t:
            out.append(t)
    return chr(10).join(out)


def _documented_verbs() -> set:
    """Verbs that appear in an actual tag-documentation form — either
    [ACTION:{"type":"verb"...}] (with any brace doubling) or the bare
    prose form [ACTION:verb]. A verb's own implementation mentioning its
    name does NOT count as words; only teaching the model the tag does.
    The first rehearsal of this ratchet proved that distinction matters:
    with the docs stripped, plain name-counting still passed, because a
    handler module quotes its own verb constantly."""
    src = _prompt_bearing_sources().replace("{{", "{").replace(" ", "")
    out = set(re.findall(r'\[ACTION:\{"type":"([a-z_0-9]+)"', src))
    out |= set(re.findall(r'\[ACTION:([a-z_0-9]+)\]', src))
    return out


def test_every_verb_has_words_or_a_tool_path():
    documented = _documented_verbs()
    tool_surface = set(mcp_server.exposed_tools())
    wordless = sorted(
        v for v in cos.ACTION_HANDLERS
        if v not in documented and v not in tool_surface
    )
    assert not wordless, (
        f"verbs with handlers but NO way to be invoked: {wordless}. "
        "Either document them in the system prompt (the prompt is the "
        "capability surface) or, if they are reads an agent may see, give "
        "them a TOOL_SCHEMAS entry. A handler without words is dead weight "
        "wearing a registry entry."
    )


def test_the_twelve_resurrected_verbs_are_documented():
    """The specific findings of the 8/14 audit, pinned so a prompt
    refactor cannot silently drop them again."""
    region = _prompt_region()
    for verb in ("log_time", "bill_time_to_retainer", "write_off_time",
                 "grant_balance", "consume_balance",
                 "create_recurring_booking", "cancel_recurring_booking",
                 "giving_statement", "giving_statements_run",
                 "undo_last", "add_testimonial", "analyze_trends"):
        assert f'"type":"{verb}"' in region.replace("{{", "{").replace(" ", ""), (
            f"{verb} lost its prompt documentation"
        )


def test_undo_is_framed_as_the_safety_net():
    """'Undo that' is a trust feature. The doc must route the phrase."""
    region = _prompt_region()
    assert "undo that" in region
    assert "Never claim something cannot be undone without checking" in region


def test_giving_docs_carry_the_confidentiality_line():
    """Giving data is the most sensitive thing a church holds — the same
    reasoning that keeps it off the agent surface belongs in the words
    that expose it to the practitioner surface."""
    region = _prompt_region()
    assert "never volunteer another donor's numbers" in region


def test_documented_tags_reference_real_verbs():
    """The reverse direction: a tag documented in the prompt must have a
    handler — words without a handler are a promise Chief cannot keep
    (the dead-weight rule, applied to the prompt itself)."""
    region = _prompt_region()
    # Only tags in [ACTION: position — chart-spec examples ({{"type":"bar"}})
    # are data formats, not verbs.
    documented = set(re.findall(r'\[ACTION:\{\{"type":"([a-z_0-9]+)"', region))
    ghosts = sorted(v for v in documented if v not in cos.ACTION_HANDLERS)
    assert not ghosts, f"prompt documents verbs with no handler: {ghosts}"
