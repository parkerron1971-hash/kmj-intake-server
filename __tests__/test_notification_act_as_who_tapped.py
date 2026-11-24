"""A tap on a notification's action runs as whoever tapped it
(notification_engine.execute_notification_action, _run_as).

Found in the review of the saved-conversations change (2026-11-24): the route
ran Chief's handler with no login in the turn, which every handler reads as
"the server, acting for the owner". A seat can write its own notification row,
so it could have had Chief read back the owner's conversations, or act outside
its lane.

Pins:
  * the owner's tap runs as it always has: no sign-in bound, no person in the turn
  * anyone else's runs under their own sign-in, with them as the person in the
    turn and their lane set, and all of it unbound afterwards, also when the
    handler raises
  * a verb outside the login's lane is refused before anything runs
  * with no sign-in to run under, or a lane that can't be read, nothing runs
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import chief_areas  # noqa: E402
import chief_of_staff as cos  # noqa: E402
import notification_engine as ne  # noqa: E402
import sb_clients  # noqa: E402

BIZ = {"id": "b1", "owner_id": "owner1", "name": "Love City Church", "type": "ministry", "settings": {}}
LANE = {"areas": ["people_care"], "role": "manager", "lane": "people_care"}
WHO = {"role": "manager", "name": "Jessica McCloud", "first_name": "Jessica"}


def _user(uid):
    return type("U", (), {"id": uid, "email": f"{uid}@x.com"})()


@pytest.fixture
def tap(monkeypatch):
    """Run one tap; returns what the handler saw while it ran."""
    seen, state = [], {"payload": {"type": "list_duties"}, "raise": False,
                       "lane": (LANE, WHO)}

    async def sb(client, method, path, body=None, **k):
        if method == "GET" and path.startswith("/chief_notifications"):
            return [{"id": "n1", "business_id": "b1", "title": "t", "action_payload": state["payload"]}]
        seen.append(("sb", method, path))
        return []
    monkeypatch.setattr(ne, "_sb", sb)
    monkeypatch.setattr(ne, "_require_access", lambda bid, user, min_role="member": dict(BIZ))

    def turn_for(bid, uid):
        if state["lane"] is None:
            raise RuntimeError("read failed")
        return state["lane"]
    monkeypatch.setattr(chief_areas, "turn_for", turn_for)

    async def handler(client, biz, action):
        seen.append({"jwt": sb_clients.get_current_user_jwt(), "uid": cos._TURN_USER_ID.get(),
                     "lane": chief_areas.TURN.get(), "who": chief_areas.WHO.get()})
        if state["raise"]:
            raise RuntimeError("boom")
        return {"result": "ok", "label": "ok"}
    for verb in ("list_duties", sorted(chief_areas.OWNERS)[0]):
        monkeypatch.setitem(ne.ACTION_HANDLERS, verb, handler)
    import audit_log
    monkeypatch.setattr(audit_log, "record", lambda *a, **k: seen.append(("audit", k.get("actor_id"), k.get("ok"))))

    def run(uid, authorization="Bearer the-seats-own-token"):
        return asyncio.run(ne.execute_notification_action("n1", _user(uid), authorization))
    return run, seen, state


def _unbound():
    return (sb_clients.get_current_user_jwt(), cos._TURN_USER_ID.get() or "", chief_areas.TURN.get(),
            chief_areas.WHO.get()) == (None, "", None, None)


def test_the_owners_tap_runs_as_it_always_has(tap):
    run, seen, _ = tap
    assert run("owner1")["executed"] is True
    assert seen[0] == {"jwt": None, "uid": cos._TURN_USER_ID.get(), "lane": None, "who": None}
    assert not seen[0]["uid"]


def test_anyone_elses_tap_runs_as_that_login_and_is_unbound_after(tap):
    run, seen, _ = tap
    assert run("jessica")["executed"] is True
    assert seen[0] == {"jwt": "the-seats-own-token", "uid": "jessica", "lane": LANE, "who": WHO}
    assert ("audit", "jessica", True) in seen
    assert _unbound()


def test_it_is_unbound_when_the_handler_raises(tap):
    run, seen, state = tap
    state["raise"] = True
    with pytest.raises(HTTPException) as e:
        run("jessica")
    assert e.value.status_code == 500 and ("audit", "jessica", False) in seen
    assert _unbound()


def test_a_verb_outside_the_lane_is_refused_before_anything_runs(tap):
    run, seen, state = tap
    owners_only = sorted(chief_areas.OWNERS)[0]
    state["payload"] = {"type": owners_only}
    import action_registry
    if not action_registry.classification(owners_only) or action_registry.is_bulk(owners_only):
        pytest.skip("the first owner-only verb isn't a plain classified one")
    with pytest.raises(HTTPException) as e:
        run("jessica")
    assert e.value.status_code == 403 and e.value.detail == chief_areas.refusal(owners_only, state["payload"], LANE)
    assert not any(isinstance(s, dict) for s in seen), "the handler never ran"
    assert _unbound()


@pytest.mark.parametrize("authorization", [None, "", "Basic abc", "Bearer ", object()])
def test_with_no_sign_in_to_run_under_nothing_runs(tap, authorization):
    run, seen, _ = tap
    with pytest.raises(HTTPException) as e:
        run("jessica", authorization)
    assert e.value.status_code == 401 and not any(isinstance(s, dict) for s in seen)
    # The owner needs none: the owner's tap never ran under a sign-in.
    assert run("owner1", authorization)["executed"] is True


def test_a_lane_that_cant_be_read_runs_nothing(tap):
    run, seen, state = tap
    state["lane"] = None
    with pytest.raises(HTTPException) as e:
        run("jessica")
    assert e.value.status_code == 503 and not any(isinstance(s, dict) for s in seen)


def test_a_login_no_lane_keeps_still_runs_as_itself(tap):
    """A business that isn't a church, or an Admin: no lane, and still their own sign-in."""
    run, seen, state = tap
    state["lane"] = (None, {"role": "admin", "name": "", "first_name": ""})
    assert run("m1")["executed"] is True
    assert seen[0]["jwt"] == "the-seats-own-token" and seen[0]["uid"] == "m1" and seen[0]["lane"] is None
