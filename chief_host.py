"""
chief_host.py — how a split-out handler module reaches chief_of_staff.

chief_of_staff.py imports the handler modules (chief_strategy_actions,
chief_grow_actions, …) by name at import time, so those modules cannot
import chief_of_staff at the top of theirs: it is only half-built when
they load. Each of them needs the same four helpers and the registry.
These delegators resolve the real object at CALL time, which is one
attribute lookup per call and buys two things:

  * one definition. chief_time_actions carries its own copy of _fail,
    and that copy has drifted from chief_of_staff's (which genericises
    anything that looks technical before it reaches the practitioner).
    Nothing here is copied, so nothing here can drift.
  * the tests keep their reach. Dozens of tests monkeypatch `cos._sb`;
    because the delegator looks `_sb` up on chief_of_staff when the
    handler runs, that patch covers the moved handlers unchanged.

Import what you need: `from chief_host import _sb, _fail, _nav`.

The host's own addresses live here too (SELF_BASE, FALLBACK_BASE):
they are facts about the process, not about Chief, and a handler module
cannot read them off chief_of_staff at import time.
"""
from __future__ import annotations

import os
from typing import Any, Dict

# The server's own base URL, for calls that loop back into this process
# (SELF_BASE) and for links that must resolve from outside (FALLBACK_BASE).
SELF_BASE = f"http://localhost:{os.environ.get('PORT', '8000')}"
FALLBACK_BASE = os.environ.get(
    "RAILWAY_PUBLIC_URL", "https://kmj-intake-server-production.up.railway.app"
)


async def _sb(client, method, path, body=None):
    from chief_of_staff import _sb as _real
    return await _real(client, method, path, body)


def _fail(action_type: str, msg: str) -> Dict:
    from chief_of_staff import _fail as _real
    return _real(action_type, msg)


def _nav(*args, **kwargs):
    from chief_of_staff import _nav as _real
    return _real(*args, **kwargs)


async def _call_claude(*args, **kwargs):
    from chief_of_staff import _call_claude as _real
    return await _real(*args, **kwargs)


def _handlers() -> Dict[str, Any]:
    from chief_of_staff import ACTION_HANDLERS
    return ACTION_HANDLERS
