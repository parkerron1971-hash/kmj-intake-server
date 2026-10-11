"""turn_context.py — which Chief turn, which lane, which response.

Layer Two, step 1. The app sends a request id with every Chief message
(ChiefOfStaff.tsx, crypto.randomUUID()). Until now it reached only the
route log; nothing joined a turn's model calls to its archive row, its
ledger rows, the drafts it filed or what came of them. This module holds
the id for the life of the turn so every writer can stamp it without
being handed it.

Three things live here, all contextvars, so a turn's child tasks see
them and a different request never does:

  turn id   set once per chat turn by chief_chat (set_turn / reset).
  lane      the chief_models lane of the model call in progress. Set
            around a call by the code that chose the lane (set_lane /
            reset_lane); api_usage_logger reads it. Empty means the
            lane is not known, which is recorded as nothing, never a
            guess.
  turn info a small per-turn dict the main model call fills in (its
            model, lane and provider response id), read when the turn's
            ledger rows are written.

No imports beyond the standard library: api_usage_logger imports this.
"""
from __future__ import annotations

import contextvars
from typing import Any, Dict, Optional, Tuple

_TURN: contextvars.ContextVar[str] = contextvars.ContextVar("chief_turn_id", default="")
_LANE: contextvars.ContextVar[str] = contextvars.ContextVar("chief_call_lane", default="")
_INFO: contextvars.ContextVar[Optional[Dict[str, str]]] = contextvars.ContextVar(
    "chief_turn_info", default=None)

_MAX = 120


def _s(value: Any) -> str:
    return str(value or "").strip()[:_MAX]


def set_turn(turn_id: Optional[str]) -> Tuple[contextvars.Token, contextvars.Token]:
    """Start a turn. Returns the tokens reset() takes."""
    return _TURN.set(_s(turn_id)), _INFO.set({})


def reset(tokens: Tuple[contextvars.Token, contextvars.Token]) -> None:
    turn_token, info_token = tokens
    _TURN.reset(turn_token)
    _INFO.reset(info_token)


def turn_id() -> str:
    return _TURN.get()


def set_lane(lane: Optional[str]) -> contextvars.Token:
    return _LANE.set(_s(lane))


def reset_lane(token: contextvars.Token) -> None:
    _LANE.reset(token)


def lane() -> str:
    return _LANE.get()


def note_main_call(*, model: Optional[str] = None, lane: Optional[str] = None,
                   response_id: Optional[str] = None) -> None:
    """The turn's main model call says what it was. Last write wins: a
    tool round's final response is the one that produced the reply."""
    info = _INFO.get()
    if info is None:
        return
    for key, value in (("model", model), ("lane", lane), ("resp", response_id)):
        if _s(value):
            info[key] = _s(value)


def ai_context(model: Optional[str] = None, lane: Optional[str] = None,
               response_id: Optional[str] = None) -> Dict[str, str]:
    """The compact record of which AI acted, for a ledger row's payload.

    Explicit arguments win over what the turn's main call noted. Empty
    values are left out rather than written as blanks: a missing key
    means NOT RECORDED.
    """
    info = _INFO.get() or {}
    out = {
        "turn": turn_id(),
        "model": _s(model) or info.get("model", ""),
        "lane": _s(lane) or info.get("lane", "") or _LANE.get(),
        "resp": _s(response_id) or info.get("resp", ""),
    }
    return {k: v for k, v in out.items() if v}
