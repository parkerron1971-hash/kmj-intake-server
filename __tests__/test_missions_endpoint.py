"""GET /agents/chief/missions — the door the mission engine never had.

chief_missions has run headless since BE#615: it plans, executes,
pauses for approval and resumes across days, and the only way to see
any of it was to ask Chief in words. A practitioner cannot supervise
work they cannot see, so autonomy without a face is a promise nobody
can check.

What these pin:

  1. IT IS A DOOR, NOT A SECOND QUERY. The route delegates to
     handle_mission_status — the same verb the practitioner hears — so
     the panel and the spoken answer cannot drift apart.
  2. IT CANNOT MOVE A MISSION. Read-only. Starting, advancing and
     abandoning stay actions behind their own class-C gates.
  3. "NO MISSIONS" AND "I COULD NOT CHECK" STAY DIFFERENT FACTS. An
     unreachable store must not render as an empty panel.
"""
from __future__ import annotations

import asyncio
import inspect
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from __tests__._chief_source import chief_source  # noqa: E402
import pytest
from fastapi import HTTPException

import chief_of_staff as cos
import chief_missions


_BIZ = {"id": "biz-1", "name": "KMJ", "type": "coach",
        "owner_id": "user-1", "settings": {}}


class _Session:
    token = "jwt-abc"
    user = type("U", (), {"id": "user-1"})()


def _call(business_id="biz-1"):
    return asyncio.run(cos.chief_missions_endpoint(
        business_id=business_id, user_session=_Session()))


@pytest.fixture
def store(monkeypatch):
    """Stub the business lookup; mission reads go through handle_mission_status."""
    async def fake_sb(client, method, path, body=None):
        if path.startswith("/businesses"):
            return [_BIZ]
        return []
    monkeypatch.setattr(cos, "_sb", fake_sb)
    return fake_sb


def test_it_delegates_to_the_verb_the_practitioner_hears(monkeypatch, store):
    """Not a second query. If the panel read the table itself it would
    start disagreeing with mission_status the day either changed."""
    seen = {}

    async def fake_status(client, biz, action):
        seen["biz"] = biz["id"]
        return {"type": "mission_status", "result": "1 open",
                "label": "x", "missions": [{"id": "m1", "title": "Chase invoices",
                                            "status": "active", "progress": "2/5",
                                            "steps": []}],
                "signal": {"open": 1, "awaiting": 0}}

    monkeypatch.setattr(chief_missions, "handle_mission_status", fake_status)
    out = _call()
    assert seen["biz"] == "biz-1"
    assert out["missions"][0]["title"] == "Chase invoices"
    assert out["open"] == 1 and out["awaiting"] == 0


def test_a_mission_waiting_on_the_practitioner_is_counted(monkeypatch, store):
    async def fake_status(client, biz, action):
        return {"missions": [{"id": "m1", "title": "t", "status": "awaiting_approval",
                              "progress": "3/5", "steps": []}],
                "signal": {"open": 1, "awaiting": 1}}
    monkeypatch.setattr(chief_missions, "handle_mission_status", fake_status)
    assert _call()["awaiting"] == 1


def test_nothing_in_flight_is_an_empty_list_not_an_error(monkeypatch, store):
    async def fake_status(client, biz, action):
        return {"missions": [], "signal": {"open": 0, "awaiting": 0}}
    monkeypatch.setattr(chief_missions, "handle_mission_status", fake_status)
    out = _call()
    assert out == {"missions": [], "open": 0, "awaiting": 0}


def test_a_failed_read_is_a_503_not_an_empty_panel(monkeypatch, store):
    """The distinction this whole codebase keeps having to relearn: "no
    missions" is a fact about the business, "I could not check" is a
    fact about the system, and the second must never wear the first."""
    async def fake_status(client, biz, action):
        return {"failed": True, "result": "couldn't load missions just now"}
    monkeypatch.setattr(chief_missions, "handle_mission_status", fake_status)
    with pytest.raises(HTTPException) as e:
        _call()
    assert e.value.status_code == 503


def test_an_unreadable_business_draws_nothing_rather_than_erroring(monkeypatch):
    """RLS filtering a business out and it not existing are the same
    answer, and neither is worth an error the practitioner sees."""
    async def fake_sb(client, method, path, body=None):
        return []
    monkeypatch.setattr(cos, "_sb", fake_sb)
    assert _call("someone-elses-biz") == {"missions": [], "open": 0, "awaiting": 0}


def test_the_route_is_read_only():
    """It must not be able to move a mission. Advancing is class C and
    stays an action with its own gate."""
    src = inspect.getsource(cos.chief_missions_endpoint)
    for mover in ("handle_start_mission", "handle_advance_mission",
                  "handle_abandon_mission", "handle_propose_mission"):
        assert mover not in src
    assert '@router.get("/agents/chief/missions")' in chief_source()


def test_it_runs_under_the_callers_own_jwt():
    """RLS is the gate. A missions panel that read with the service role
    would show every business's work to whoever asked."""
    src = inspect.getsource(cos.chief_missions_endpoint)
    assert "sb_clients.set_user_jwt(user_session.token)" in src
    assert "reset_user_jwt" in src
