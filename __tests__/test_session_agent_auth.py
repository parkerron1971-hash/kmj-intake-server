"""Session agent — the door.

These three endpoints took a bare `business_id` and no credential.
Anyone who knew a uuid could make that business draft messages to its
clients, spend its model budget and decay its contact health scores.

They could not simply be locked, because chief_of_staff reached them
over the loopback with no credential — the BE#210 regression, where
adding auth to /sms/send and /stripe/product-link 401'd the backend
against itself. So Chief now calls the core functions in-process and
the doors are shut.

Both halves are tested here, because fixing one and breaking the other
is the failure mode: a locked endpoint Chief can no longer use, or an
open endpoint nobody noticed was still open.

Run via:
  pytest -q __tests__/test_session_agent_auth.py
"""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import chief_of_staff
import session_agent
from auth_supabase import require_user


OWNER_ID = "user-owner-1"
OTHER_ID = "user-someone-else"
BIZ_ID = "biz-1"


class _User:
    def __init__(self, uid):
        self.id = uid


def _client(user_id=None) -> TestClient:
    app = FastAPI()
    app.include_router(session_agent.router)
    if user_id is not None:
        app.dependency_overrides[require_user] = lambda: _User(user_id)
    return TestClient(app, raise_server_exceptions=False)


class EndpointAuthTests(unittest.TestCase):
    def test_no_credential_is_rejected(self):
        # The whole point. Before this fix these returned 200.
        for path in ("/agents/session/prep",
                     "/agents/session/follow-up",
                     "/agents/session/no-show"):
            r = _client().post(path, json={"business_id": BIZ_ID})
            self.assertNotEqual(r.status_code, 200, path)
            self.assertIn(r.status_code, (401, 403, 422), f"{path} -> {r.status_code}")

    def test_non_owner_is_rejected(self):
        rows = [{"id": BIZ_ID, "owner_id": OWNER_ID}]
        with patch.object(session_agent.sb_clients, "sb_get_as_service",
                          return_value=rows):
            r = _client(OTHER_ID).post("/agents/session/prep",
                                       json={"business_id": BIZ_ID})
        self.assertEqual(r.status_code, 403)

    def test_unknown_business_is_404(self):
        with patch.object(session_agent.sb_clients, "sb_get_as_service",
                          return_value=[]):
            r = _client(OWNER_ID).post("/agents/session/prep",
                                       json={"business_id": BIZ_ID})
        self.assertEqual(r.status_code, 404)

    def test_owner_reaches_the_work(self):
        # The gate must not lock out the person it exists to protect.
        rows = [{"id": BIZ_ID, "owner_id": OWNER_ID}]
        with patch.object(session_agent.sb_clients, "sb_get_as_service",
                          return_value=rows), \
             patch.object(session_agent, "run_prep",
                          new=AsyncMock(return_value={"briefs_created": 2})) as run:
            r = _client(OWNER_ID).post("/agents/session/prep",
                                       json={"business_id": BIZ_ID})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["briefs_created"], 2)
        run.assert_awaited_once_with(BIZ_ID)


class ChiefDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_agents_run_in_process_not_over_http(self):
        # If this regresses to a loopback POST, Chief starts 401ing
        # against our own newly-locked endpoints.
        loopback = AsyncMock(return_value={"should": "not be used"})
        with patch.object(session_agent, "run_noshow",
                          new=AsyncMock(return_value={"drafts_created": 1})) as run, \
             patch.object(chief_of_staff, "_loopback_post", new=loopback):
            out = await chief_of_staff._dispatch_agent(
                "/agents/session/no-show", {"business_id": BIZ_ID})
        run.assert_awaited_once_with(BIZ_ID)
        loopback.assert_not_awaited()
        self.assertEqual(out, {"drafts_created": 1})

    async def test_other_agents_still_use_the_loopback(self):
        # The change must be narrow — nurture, contract, payment and the
        # rest are unchanged and must keep working.
        loopback = AsyncMock(return_value={"drafts_created": 3})
        with patch.object(chief_of_staff, "_loopback_post", new=loopback):
            out = await chief_of_staff._dispatch_agent(
                "/agents/nurture/run", {"business_id": BIZ_ID})
        loopback.assert_awaited_once()
        self.assertEqual(out, {"drafts_created": 3})

    async def test_failure_returns_none_rather_than_raising(self):
        # Chief's callers check `if not data` and report the agent as
        # unreachable; an exception here would surface as a 500 in chat.
        with patch.object(session_agent, "run_prep",
                          new=AsyncMock(side_effect=RuntimeError("boom"))):
            out = await chief_of_staff._dispatch_agent(
                "/agents/session/prep", {"business_id": BIZ_ID})
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
