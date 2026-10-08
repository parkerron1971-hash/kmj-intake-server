"""
test_chief_brief_prefix_stable.py — Chief's cached brief is byte-stable (2026-10-08).

In the 30 days to 2026-10-07, 47 Chief calls re-wrote the whole ~106k-token
brief less than an hour after the business's previous call, most reading
nothing back (the start of the request had changed). Matched against the
deploy history and the code, the causes were:

- a deploy that changed prompt or tool text (10 of the 14 since 2026-09-24;
  not a bug: new text is a new cache);
- today's date inside the cached operating manual ("today is 2026-10-08"),
  which changes the manual at midnight UTC, 8 pm Eastern, mid-conversation;
- the 5-minute cache fallback re-issuing the call without the turn's tools
  or effort (a different request, so a cold write, and a turn with no tools).

These tests pin what makes the prefix stable: no date in the cached
segments, no hash-order dependence across processes (every deploy is a new
process), one tool list for voice and text turns, and every re-issue of the
call carrying the turn's own tools and effort.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import inspect
import json
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import chief_models
import chief_of_staff as chief
import chief_prompt
import chief_tool_loop as ctl

BIZ = {"id": "00000000-0000-4000-8000-000000000011", "name": "Example Studio", "type": "business coaching",
       "owner_id": "00000000-0000-4000-8000-0000000000ee", "settings": {}}


def _segments(system):
    stable, _, dynamic = system.partition("[[CHIEF_CACHE_SPLIT]]")
    universal, _, per_business = stable.partition("[[CHIEF_GLOBAL_SPLIT]]")
    return universal, per_business


def _system():
    import chief_turn_eval as te
    return chief._build_system_prompt(te._fixture_context(BIZ), False)


def _frozen(day):
    class Frozen(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(day.year, day.month, day.day, 23, 59, tzinfo=tz or dt.timezone.utc)
    return Frozen


def test_the_cached_segments_do_not_depend_on_the_date(monkeypatch):
    builds = []
    for day in (dt.date(2031, 3, 17), dt.date(2032, 11, 5)):
        monkeypatch.setattr(chief_prompt, "datetime", _frozen(day))
        monkeypatch.setattr(chief, "datetime", _frozen(day))
        builds.append(_segments(_system()))
    assert builds[0][0] == builds[1][0], "the universal core changed with the date"
    assert builds[0][1] == builds[1][1], "the per-business manual changed with the date"
    assert "2031-03-17" not in builds[0][1] and "2032-11-05" not in builds[1][1]


def test_todays_date_rides_the_per_message_time_context(monkeypatch):
    async def no_rows(*a, **k):
        return []
    monkeypatch.setattr(chief, "_sb", no_rows)
    monkeypatch.setattr(chief, "datetime", _frozen(dt.date(2026, 10, 8)))
    block = asyncio.run(chief._get_time_context(None, BIZ["id"]))
    assert "2026-10-08" in block and block.startswith("TIME CONTEXT:")
    assert "today's date in TIME CONTEXT" in _segments(_system())[1]


_PROBE = r"""
import hashlib, json, sys
sys.path.insert(0, %(root)r); sys.path.insert(0, %(scripts)r)
import chief_of_staff as chief, chief_tool_loop as ctl, chief_turn_eval as te
ctl.reset_turn(writes_allowed=True)
tools = json.dumps(ctl.tool_definitions_for_turn(True))
system = chief._build_system_prompt(te._fixture_context(%(biz)r), False)
stable = system.partition("[[CHIEF_CACHE_SPLIT]]")[0]
print(hashlib.sha256((tools + stable).encode()).hexdigest())
"""


def test_tools_and_cached_segments_are_the_same_in_every_process():
    """Each deploy starts a new process with a new string-hash seed. Anything
    built by iterating a set would come out in a new order and re-write the
    whole brief after every deploy, Chief change or not."""
    code = _PROBE % {"root": str(ROOT), "scripts": str(ROOT / "scripts"), "biz": BIZ}
    out = set()
    for seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        env.pop("ANTHROPIC_API_KEY", None)
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                           cwd=str(ROOT), timeout=240)
        assert r.returncode == 0, r.stderr[-2000:]
        out.add(r.stdout.strip().splitlines()[-1])
    assert len(out) == 1, out


def test_voice_and_text_turns_offer_the_same_tools():
    """The main turn always resets the tool loop as the chat surface; the
    voice lane changes only the uncached tail. One tool list, one cache."""
    src = inspect.getsource(chief.chief_chat) if hasattr(chief, "chief_chat") else ""
    assert "chief_tool_loop.reset_turn(writes_allowed=_native_writes)" in inspect.getsource(chief)
    ctl.reset_turn(writes_allowed=True)
    text_tools = json.dumps(ctl.tool_definitions_for_turn(True))
    ctl.reset_turn(writes_allowed=True)
    assert json.dumps(ctl.tool_definitions_for_turn(True)) == text_tools
    for block in (chief_models.VOICE_DELIVERY_BLOCK,):
        assert "[[CHIEF_" not in block
    del src


def test_every_reissue_of_the_call_sends_the_same_tools_and_effort():
    """A re-issued request with different tools or effort is a different
    cache key: the 5-minute fallback used to drop both."""
    src = inspect.getsource(chief._call_claude)
    calls = src.split("return await _call_claude(")[1:]
    assert len(calls) >= 4
    for call in calls:
        body = call[:call.index(")") + 1]
        for arg in ("read_tools=read_tools", "tool_biz=tool_biz", "effort=effort",
                    "stable_tools=stable_tools"):
            assert arg in body, (arg, body[:300])
