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

Writes are deliberately absent. Operations still travel as [ACTION:]
tags after the reply, through the action registry, the policy engine,
step-up auth and the ledger. The loop makes Chief better informed, not
more powerful.
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

# How many tools the current turn actually called — read by the
# [Chief timing] line so production can see the loop working.
_calls_this_turn: contextvars.ContextVar[int] = contextvars.ContextVar(
    "chief_tool_loop.calls", default=0)


def reset_turn() -> None:
    _calls_this_turn.set(0)


def calls_this_turn() -> int:
    return _calls_this_turn.get()


def read_tool_definitions() -> List[Dict[str, Any]]:
    """The MCP read surface in Anthropic tools shape. Derived per call —
    a verb that loses its registry entry disappears from here the same
    moment it disappears from the agent surface."""
    out: List[Dict[str, Any]] = []
    for t in mcp_server.tool_definitions():
        name = t.get("name")
        if not name or name in _EXCLUDED:
            continue
        out.append({
            "name": name,
            "description": t.get("description") or "",
            "input_schema": t.get("inputSchema") or {"type": "object", "properties": {}},
        })
    return out


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

    if name in _EXCLUDED or not action_registry.may_expose_to_agent(name):
        return True, (f"'{name}' is not a mid-turn lookup. Reads only here; "
                      f"operations go through [ACTION:] tags in your reply.")
    if action_registry.effect(name) != action_registry.READ:
        # Belt over may_expose_to_agent's braces: even if exposure rules
        # ever widen, this loop stays reads-only.
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
