"""
chief_tool_loop.py — Chief reads mid-thought.

Kevin's goal, 2026-08-14: "make Chief a Jarvis of the Solutionist
system … anything that is requested in the system, I want Chief to be
able to do with no problem."

The ceiling on that goal was architectural. A Chief turn wrote its whole
reply FIRST, actions ran after, and a second pass patched the words.
Chief could not look anything up while it thought — so every answer was
limited to what had been pre-stuffed into its context, and every gap
surfaced as "I don't have that loaded" (the invoices transcript), or
worse, a web search over the practitioner's own books. Each incident got
fixed by stuffing one more table into the prompt. That does not scale to
"anything in the system".

This module gives the model TOOLS for the duration of a turn: when it
needs data it does not see, it pauses, calls a read, gets the rows, and
keeps thinking. The loop lives in _call_claude (both branches); this
module owns the two decisions that make it safe:

WHICH TOOLS — the MCP read surface, verbatim. mcp_server.TOOL_SCHEMAS
  is already the audited answer to "which verbs may an agent call, with
  what arguments": every entry is registry-classified `read`, sensitive
  reads never reach it, and its tripwire tests force a human decision
  per verb. Chief's inner loop reuses that surface rather than growing
  a second, driftable list. (show_view is excluded — it is a DISPLAY
  action with a UI side effect, and the one way to put data on the
  practitioner's screen stays the action tag.)

WHAT EXECUTION MEANS — reads only, enforced at dispatch and not by
  trust in the model. A tool_use naming a write verb, a ui verb, or
  anything unregistered is refused with an error result the model can
  read. Handlers run under the practitioner's own JWT (bound to the
  async context by chief_chat), so RLS stays the authority — this loop
  adds reach to the MODEL, never to the ACCOUNT.

WRITES, THE SAME DOOR (2026-09-04). Until now every operation travelled
as an [ACTION:] tag parsed out of prose after the reply — and three
patches existed only because of that: a tolerant JSON repairer for
truncated tags, a second model call to rewrite the reply around real
outcomes (the words were written before anything ran), and a retry with
a SYSTEM CORRECTION when prose claimed an action no tag was emitted
for. The comments on those say the prompt rules are "empirically
ignored". That is the model saying the mechanism is wrong, not the
prompt.

So the reversible verbs an outside agent may already call
(mcp_server.WRITE_TOOL_SCHEMAS — class A, reviewed, never bulk) are
tools on the practitioner's own turn too. What does NOT change is the
door: a write tool call is dispatched through chief_of_staff.
_execute_actions, one action at a time, so reference resolution, the
class-C gate, the policy engine, the undo log and `_authorized_by`
all run exactly as they do for a tag. This module never calls a write
handler directly.

Bounded on purpose: MAX_WRITE_CALLS per turn, separate from the read
budget, and a held verdict (a spoken-confirmation hold, a tainted
turn) spends the whole budget — the model gets one HELD and must ask,
not retry. Class C has no tool today (no schema exists for it) and
still travels as a tag, single-shot, exactly as before.

A turn that acted through tools skips the recompose call and the
correction retry: the model already saw every result before it wrote
its last sentence, and a tool_use block is unambiguous.
"""
from __future__ import annotations

import contextvars
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import action_registry
import mcp_server

logger = logging.getLogger("chief")

# Rounds = model requests per turn (1 means no tool use). Calls = total
# tool executions across the turn. Both exist so a model that loops on
# a read cannot spend the practitioner's money doing it.
MAX_TOOL_ROUNDS = 4
MAX_TOOL_CALLS = 8

# One tool result larger than this is truncated, not trusted: the model
# needs the shape of an answer, and 6000 chars of JSON is a shape.
MAX_RESULT_CHARS = 6000

# Display actions stay actions — one way to put data on the screen.
_EXCLUDED = {"show_view"}

# Writes per turn. Three is a task — "add Ada, put Thursday on the
# calendar, remind me" — and not a loop. Separate from MAX_TOOL_CALLS so
# a model that reads five things can still act.
MAX_WRITE_CALLS = 3

# How many tools the current turn actually called — read by the
# [Chief timing] line so production can see the loop working.
_calls_this_turn: contextvars.ContextVar[int] = contextvars.ContextVar(
    "chief_tool_loop.calls", default=0)
# Whether THIS turn may write through tools. Off by default so every
# caller that never asked (drafts, the fallback brain, tests) keeps
# the read-only loop it had.
_writes_allowed: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "chief_tool_loop.writes_allowed", default=False)
# The full handler results of every write this turn — nav,
# frontend_event and all — so chief_chat can put them in actions_taken
# exactly as a tag action would be. The model only ever sees _shrink().
_writes_this_turn: contextvars.ContextVar[List[Dict[str, Any]]] = contextvars.ContextVar(
    "chief_tool_loop.writes", default=[])
_write_calls: contextvars.ContextVar[int] = contextvars.ContextVar(
    "chief_tool_loop.write_calls", default=0)
# Set when the budget is spent OR a write came back held: one HELD per
# turn, then the model asks instead of retrying.
_writes_closed: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "chief_tool_loop.writes_closed", default=False)


# WHO IS ACTING (2026-09-04). A chat turn is a practitioner asking, so a
# write through this loop reaches the door as surface="chat",
# prompted=True. The standing agent (chief_agent) runs the same loop on
# nobody's prompt, and must say so, or the policy engine would hand it
# the one exemption it grants a human. Set per turn by reset_turn().
_turn_surface: contextvars.ContextVar[str] = contextvars.ContextVar(
    "chief_tool_loop.surface", default="chat")
_turn_prompted: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "chief_tool_loop.prompted", default=True)


def reset_turn(writes_allowed: bool = False, *, surface: str = "chat",
               prompted: bool = True) -> None:
    _calls_this_turn.set(0)
    _writes_allowed.set(bool(writes_allowed))
    _writes_this_turn.set([])
    _write_calls.set(0)
    _writes_closed.set(False)
    _turn_surface.set(surface or "chat")
    _turn_prompted.set(bool(prompted))


def calls_this_turn() -> int:
    return _calls_this_turn.get()


def writes_this_turn() -> List[Dict[str, Any]]:
    """The write results of this turn, in order, as chief_chat's
    `taken` list expects them."""
    return list(_writes_this_turn.get())


def writes_allowed() -> bool:
    return bool(_writes_allowed.get())


def _anthropic_shape(t: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": t.get("name"),
        "description": t.get("description") or "",
        "input_schema": t.get("inputSchema") or {"type": "object", "properties": {}},
    }


def read_tool_definitions() -> List[Dict[str, Any]]:
    """The MCP read surface in Anthropic tools shape. Derived per call —
    a verb that loses its registry entry disappears from here the same
    moment it disappears from the agent surface."""
    out: List[Dict[str, Any]] = []
    for t in mcp_server.tool_definitions():
        name = t.get("name")
        if not name or name in _EXCLUDED:
            continue
        out.append(_anthropic_shape(t))
    return out


def _write_verb_offered(name: str) -> bool:
    """May THIS verb be a write tool? The same two gates the agent
    surface applies — the registry is the ceiling (class A, not
    sensitive, not bulk), the reviewed schema table is the floor."""
    return (name in mcp_server.WRITE_TOOL_SCHEMAS
            and action_registry.may_expose_to_agent(name, allow_writes=True)
            and action_registry.effect(name) == action_registry.WRITE
            and not action_registry.is_bulk(name))


def write_tool_definitions() -> List[Dict[str, Any]]:
    """The reviewed class-A write verbs, Anthropic-shaped. Derived from
    the agent surface's own schema table, not a second list."""
    out: List[Dict[str, Any]] = []
    for name in sorted(mcp_server.WRITE_TOOL_SCHEMAS):
        if not _write_verb_offered(name):
            continue
        description, schema = mcp_server.WRITE_TOOL_SCHEMAS[name]
        out.append(_anthropic_shape(
            {"name": name, "description": description, "inputSchema": schema}))
    return out


def tool_definitions_for_turn(writes: bool) -> List[Dict[str, Any]]:
    """Reads always; writes when the turn allows them."""
    tools = read_tool_definitions()
    if writes:
        tools += write_tool_definitions()
    return tools


def _shrink(result: Any) -> str:
    """A handler result as tool_result text: UI plumbing stripped (the
    model has no screen), JSON capped."""
    if isinstance(result, dict):
        result = {k: v for k, v in result.items()
                  if k not in ("frontend_event", "nav", "toast")}
    try:
        text = json.dumps(result, default=str)
    except (TypeError, ValueError):
        text = str(result)
    # A lookup result can carry an email body, a contact's notes, a
    # form answer — third-party text arriving mid-turn, after the
    # prompt-time neutraliser ran. Same two layers, same taint.
    import untrusted_text
    text = untrusted_text.defuse(text)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + '… [truncated — ask a narrower question]"}'
    return text


async def execute_tool_use(client, biz: Dict[str, Any],
                           name: str, args: Dict[str, Any]) -> Tuple[bool, str]:
    """One mid-turn tool call. Returns (is_error, result_text).

    The read-only guard lives HERE, at dispatch — not in the tool list
    the model was shown. A model that hallucinates a write verb into a
    tool_use block gets a refusal it can read, never an execution.
    """
    import chief_of_staff  # runtime import — this module loads first

    effect = action_registry.effect(name)
    if effect == action_registry.WRITE and name not in _EXCLUDED:
        return await _execute_write(client, biz, name, args)

    if name in _EXCLUDED or not action_registry.may_expose_to_agent(name):
        return True, (f"'{name}' is not a mid-turn lookup. Reads only here; "
                      f"operations go through [ACTION:] tags in your reply.")
    if effect != action_registry.READ:
        # Belt over may_expose_to_agent's braces: even if exposure rules
        # ever widen, the READ path stays reads-only.
        return True, f"'{name}' is not a read — not available mid-turn."
    handler = chief_of_staff.ACTION_HANDLERS.get(name)
    if handler is None:
        return True, f"'{name}' has no handler."

    _calls_this_turn.set(_calls_this_turn.get() + 1)
    action = dict(args or {})
    action["type"] = name
    try:
        result = await handler(client, biz, action)
    except Exception as e:
        logger.warning(f"[tool-loop] {name} raised: {e}")
        return True, f"'{name}' failed: {type(e).__name__}. Answer from what you have."
    if isinstance(result, dict) and chief_of_staff._action_failed(result):
        return True, _shrink(result)
    return False, _shrink(result)


def _looks_held(result: Any) -> bool:
    """A gate verdict rather than a handler outcome: the class-C hold for
    a spoken yes, the taint hold, a safety check that could not run.
    All of them come back `failed` with a sentence that says held."""
    if not isinstance(result, dict) or not result.get("failed"):
        return False
    blob = f"{result.get('result') or ''} {result.get('label') or ''}".lower()
    return "held" in blob


async def _execute_write(client, biz: Dict[str, Any],
                         name: str, args: Dict[str, Any]) -> Tuple[bool, str]:
    """One write, THROUGH THE DOOR.

    Never a handler call. `_execute_actions` with a list of one gives
    the write everything a tag gets: `_resolve_action_references`,
    `_gate_class_c`, the policy engine, `_record_undoable`, the
    `_authorized_by` stamp. The full result is kept for chief_chat's
    `actions_taken`; the model sees the shrunk form, same as a read.
    """
    import chief_of_staff

    if not _writes_allowed.get():
        return True, (f"'{name}' changes records and is not a mid-turn tool on "
                      f"this turn. Operations go through [ACTION:] tags in your reply.")
    if not _write_verb_offered(name):
        # Class C, bulk, unreviewed, or sensitive. The same flat sentence
        # the agent surface uses, so a refusal is never a hint that a
        # scope or a retry would help.
        return True, (f"'{name}' is not a tool. If it is an operation, emit its "
                      f"[ACTION:] tag in your reply; the usual rules apply.")
    if _writes_closed.get():
        return True, ("The write budget for this turn is spent (or an earlier write "
                      "is HELD). Say what happened so far and what is still to do; "
                      "do not retry.")
    handler = chief_of_staff.ACTION_HANDLERS.get(name)
    if handler is None:
        return True, f"'{name}' has no handler."

    _calls_this_turn.set(_calls_this_turn.get() + 1)
    _write_calls.set(_write_calls.get() + 1)
    if _write_calls.get() >= MAX_WRITE_CALLS:
        _writes_closed.set(True)

    action = dict(args or {})
    action["type"] = name
    user_id = None
    try:
        user_id = chief_of_staff._TURN_USER_ID.get() or None
    except Exception:
        user_id = None
    # The surface is named only when it is not the chat turn, so every
    # caller and every test double that knows the door's older signature
    # keeps working unchanged; the agent's turn is the one that says so.
    door_kwargs: Dict[str, Any] = {}
    if _turn_surface.get() != "chat" or not _turn_prompted.get():
        door_kwargs = {"surface": _turn_surface.get(), "prompted": _turn_prompted.get()}
    try:
        results = await chief_of_staff._execute_actions(
            client, biz, [action], user_id=user_id, **door_kwargs)
    except Exception as e:
        logger.warning(f"[tool-loop] write {name} raised: {e}")
        return True, f"'{name}' failed: {type(e).__name__}. Tell the practitioner it did not go through."
    result = results[0] if results else chief_of_staff._fail(name, "nothing was returned")
    if not isinstance(result, dict):
        result = {"type": name, "result": str(result), "label": name}

    # Kept in full — nav and frontend_event are how the app reacts to
    # what just happened, and they must reach actions_taken.
    _writes_this_turn.set(_writes_this_turn.get() + [result])

    if _looks_held(result):
        # One HELD per turn. The model reads why, asks the practitioner,
        # and the NEXT turn re-issues the same action. Retrying inside
        # this turn would be exactly the door the hold exists to close.
        _writes_closed.set(True)
        return True, _shrink(result)
    if chief_of_staff._action_failed(result):
        return True, _shrink(result)
    return False, _shrink(result)


async def run_tool_round(client, biz: Dict[str, Any],
                         assistant_content: List[Dict[str, Any]],
                         calls_so_far: int) -> Optional[Tuple[Dict, Dict, int]]:
    """Execute every tool_use block in one assistant message.

    Returns (assistant_msg, tool_results_msg, n_calls) to append to the
    conversation for the next round — or None when the message contains
    no tool_use blocks (the turn is done).

    Only text and tool_use blocks are replayed into the assistant
    message: server-tool blocks (web_search) belong to the API's own
    bookkeeping and must not be echoed back.
    """
    tool_uses = [b for b in assistant_content
                 if isinstance(b, dict) and b.get("type") == "tool_use"]
    if not tool_uses:
        return None

    results: List[Dict[str, Any]] = []
    for b in tool_uses:
        if calls_so_far + len(results) >= MAX_TOOL_CALLS:
            results.append({
                "type": "tool_result", "tool_use_id": b.get("id"),
                "is_error": True,
                "content": "Lookup budget for this turn is spent — answer from what you have.",
            })
            continue
        is_error, text = await execute_tool_use(
            client, biz, b.get("name") or "", b.get("input") or {})
        entry: Dict[str, Any] = {
            "type": "tool_result", "tool_use_id": b.get("id"), "content": text,
        }
        if is_error:
            entry["is_error"] = True
        results.append(entry)

    replay = [b for b in assistant_content
              if isinstance(b, dict) and b.get("type") in ("text", "tool_use")]
    return ({"role": "assistant", "content": replay},
            {"role": "user", "content": results},
            len(tool_uses))
