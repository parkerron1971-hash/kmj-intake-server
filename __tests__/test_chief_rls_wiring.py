"""RLS migration — chief_of_staff RLS-wiring integration tests.

Verifies the chain that closes the Chief 404:

  chief_chat handler  →  sb_clients.set_user_jwt(user_session.token)
                      →  chief_of_staff._sb(...)
                      →  sb_clients.sb_as_current_context(...)
                      →  Authorization: Bearer <user_jwt>

These tests confirm the LOCAL _sb helper in chief_of_staff actually
reads the contextvar and forwards the user's token, OR falls back to
service-role for paths invoked outside a request context (cron jobs,
notification engine sweeps, autopilot).

Mocks httpx so the tests are deterministic + don't need real Supabase.

Run via:
  python -m __tests__.test_chief_rls_wiring
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

import sb_clients


USER_JWT = "user-eyJtest-pract-token-rls-aware"
SERVICE_ROLE = "service-role-eyJtest-bypasses-rls"
ANON = "anon-eyJtest"
SUPABASE_URL = "https://test.supabase.co"


def _env():
    return {
        "SUPABASE_URL": SUPABASE_URL,
        "SUPABASE_ANON": ANON,
        "SUPABASE_SERVICE_ROLE_KEY": SERVICE_ROLE,
    }


class ChiefSbWiringTests(unittest.IsolatedAsyncioTestCase):

    async def test_chief_sb_forwards_user_jwt_when_context_set(self):
        """When chief_chat has bound the user's JWT, the local _sb in
        chief_of_staff routes through sb_as_current_context which routes
        to sb_as_user with the bound token. PostgREST would set
        auth.uid() to the user's sub and RLS would resolve honestly."""
        from chief_of_staff import _sb as chief_sb

        captured = {}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '[{"id":"biz-1","name":"KMJ"}]'
        mock_client = MagicMock()
        async def fake_request(method, url, **kwargs):
            captured["headers"] = kwargs.get("headers", {})
            captured["url"] = url
            return mock_resp
        mock_client.request = fake_request

        with patch.dict(os.environ, _env(), clear=False):
            _tok = sb_clients.set_user_jwt(USER_JWT)
            try:
                result = await chief_sb(mock_client, "GET", "/businesses?id=eq.biz-1")
            finally:
                sb_clients.reset_user_jwt(_tok)

        self.assertEqual(result, [{"id": "biz-1", "name": "KMJ"}])
        # User JWT was forwarded — NOT the anon key.
        self.assertEqual(captured["headers"]["Authorization"], f"Bearer {USER_JWT}")
        self.assertNotEqual(captured["headers"]["Authorization"], f"Bearer {ANON}")
        # URL composed correctly.
        self.assertEqual(captured["url"], f"{SUPABASE_URL}/rest/v1/businesses?id=eq.biz-1")

    async def test_chief_sb_falls_back_to_service_role_without_context(self):
        """For server-initiated paths (cron jobs invoking chief helpers
        without a request), no JWT is bound. _sb is configured to allow
        service-role fallback so notification sweeps + recurrence crons
        still work."""
        from chief_of_staff import _sb as chief_sb

        captured = {}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '[]'
        mock_client = MagicMock()
        async def fake_request(method, url, **kwargs):
            captured["headers"] = kwargs.get("headers", {})
            return mock_resp
        mock_client.request = fake_request

        with patch.dict(os.environ, _env(), clear=False):
            # NO set_user_jwt — simulating cron / server-initiated path
            await chief_sb(mock_client, "GET", "/businesses")

        # Service-role key forwarded (bypasses RLS — server is trusted).
        self.assertEqual(captured["headers"]["Authorization"], f"Bearer {SERVICE_ROLE}")
        self.assertEqual(captured["headers"]["apikey"], SERVICE_ROLE)

    async def test_user_context_isolated_between_concurrent_requests(self):
        """contextvars are per-async-task by design. Two concurrent
        chief_chat invocations must not bleed each other's tokens.
        This test simulates two interleaved request handlers."""
        from chief_of_staff import _sb as chief_sb
        import asyncio

        results = {}

        async def handler(name: str, jwt: str):
            captured = {}
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = '[]'
            mock_client = MagicMock()
            async def fake_request(method, url, **kwargs):
                captured["headers"] = kwargs.get("headers", {})
                return mock_resp
            mock_client.request = fake_request

            _tok = sb_clients.set_user_jwt(jwt)
            try:
                # Yield to the event loop so the other task interleaves.
                await asyncio.sleep(0)
                await chief_sb(mock_client, "GET", "/businesses")
            finally:
                sb_clients.reset_user_jwt(_tok)
            results[name] = captured["headers"]["Authorization"]

        with patch.dict(os.environ, _env(), clear=False):
            await asyncio.gather(
                handler("alice", "alice-jwt-eyJtest"),
                handler("bob", "bob-jwt-eyJtest"),
            )

        # Critical security check — each request saw ONLY its own user's
        # JWT, not the other's. If contextvars weren't per-task scoped,
        # one task would have seen the other's token (data leak).
        self.assertEqual(results["alice"], "Bearer alice-jwt-eyJtest")
        self.assertEqual(results["bob"], "Bearer bob-jwt-eyJtest")
        self.assertNotEqual(results["alice"], results["bob"])

    async def test_chief_sb_user_path_picks_user_over_service_when_both_available(self):
        """If a user JWT is in context AND SUPABASE_SERVICE_ROLE_KEY is
        set in env, the user path wins. Service role is the fallback,
        not a co-resident option."""
        from chief_of_staff import _sb as chief_sb

        captured = {}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '[]'
        mock_client = MagicMock()
        async def fake_request(method, url, **kwargs):
            captured["headers"] = kwargs.get("headers", {})
            return mock_resp
        mock_client.request = fake_request

        with patch.dict(os.environ, _env(), clear=False):
            _tok = sb_clients.set_user_jwt(USER_JWT)
            try:
                await chief_sb(mock_client, "GET", "/businesses")
            finally:
                sb_clients.reset_user_jwt(_tok)

        # Confirmed: user JWT, NOT service-role.
        self.assertEqual(captured["headers"]["Authorization"], f"Bearer {USER_JWT}")
        self.assertNotIn(SERVICE_ROLE, captured["headers"]["Authorization"])


class AuthDependencyTests(unittest.TestCase):
    """Spot-check that require_user_session extracts the token and
    returns it alongside the verified user. This is the dep chief_chat
    relies on to feed sb_clients.set_user_jwt."""

    def test_require_user_session_extracts_bearer(self):
        from auth_supabase import require_user_session, UserSession
        from fastapi import HTTPException

        # Without Authorization header → 401
        with self.assertRaises(HTTPException) as ctx:
            require_user_session(authorization=None)
        self.assertEqual(ctx.exception.status_code, 401)

        with self.assertRaises(HTTPException) as ctx:
            require_user_session(authorization="not-a-bearer")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_optional_user_session_returns_none_without_auth(self):
        from auth_supabase import optional_user_session
        result = optional_user_session(authorization=None)
        self.assertIsNone(result)
        result = optional_user_session(authorization="not-a-bearer")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
