"""RLS migration P5 regression: `authed_request` dep must survive
FastAPI's sync-handler dispatch path.

Bug context (caught by preview-rls smoke #5b):

  When a *sync* route handler uses `Depends(sb_clients.authed_request)`,
  FastAPI runs the dep generator body inside `anyio.to_thread.run_sync`,
  which forks a worker-thread copy of the asyncio context. The generator's
  `set_user_jwt(...)` binds the contextvar in that worker-thread context.
  After the response renders, FastAPI runs the generator's `finally`
  block via `contextmanager_in_threadpool` — but the cleanup runs back
  on the *asyncio* context, which never saw the original `set()`.
  `contextvars.ContextVar.reset(token)` requires the token to be reset
  in the same context where it was created, so it raises
  `ValueError: Token ... was created in a different Context` and the
  response 500s on every authenticated request to a sync route.

  Unit tests that exercise `set_user_jwt` + `reset_user_jwt` in a
  single Python thread context don't reproduce this — the bug needs
  the actual FastAPI worker-thread dispatch boundary.

This test exercises that boundary using `fastapi.testclient.TestClient`
with a tiny app that defines:
  • a SYNC route that depends on `authed_request`
  • an ASYNC route that depends on `authed_request`
  • a route that reads the bound JWT inside the handler so we can
    assert that the contextvar plumbing actually delivers the token

Both should return 200, not 500. The async path was always working;
the sync path is what the smoke test caught.
"""
from __future__ import annotations

import os
import time
import unittest
from typing import Optional
from unittest.mock import patch

import jwt as pyjwt
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import sb_clients
import auth_supabase
from auth_supabase import UserSession


JWT_SECRET = "test-jwt-secret-32-chars-padded-for-hs256"
SUPABASE_URL = "https://test.supabase.co"
ANON_KEY = "test-anon"
SERVICE_KEY = "test-service-role"
USER_SUB = "11111111-2222-3333-4444-555555555555"


def _mint_test_jwt() -> str:
    """Sign a JWT with the test secret the way Supabase would."""
    payload = {
        "sub": USER_SUB,
        "aud": "authenticated",
        "role": "authenticated",
        "iss": f"{SUPABASE_URL}/auth/v1",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "email": "regression-test@example.com",
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _env():
    return {
        "SUPABASE_URL": SUPABASE_URL,
        "SUPABASE_ANON": ANON_KEY,
        "SUPABASE_SERVICE_ROLE_KEY": SERVICE_KEY,
        "SUPABASE_JWT_SECRET": JWT_SECRET,
    }


class _PatchAuthEnv:
    """auth_supabase reads the JWT secret at module import time, not
    per-call. Patch the module-level constants directly so the
    verifier in `_verify_token` picks up our test fixtures."""

    def __enter__(self):
        self._patches = [
            patch.object(auth_supabase, "SUPABASE_JWT_SECRET", JWT_SECRET),
            patch.object(auth_supabase, "SUPABASE_URL", SUPABASE_URL),
            patch.object(auth_supabase, "SUPABASE_JWT_AUDIENCE", "authenticated"),
            patch.dict(os.environ, _env(), clear=False),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *args):
        for p in reversed(self._patches):
            p.stop()


def _make_app() -> FastAPI:
    """Build a tiny FastAPI app with a sync and async route that both
    depend on authed_request. The handlers return whatever the
    contextvar holds so we can assert end-to-end propagation."""
    app = FastAPI()

    @app.get("/sync-route")
    def sync_route(session: UserSession = Depends(sb_clients.authed_request)):
        # Read the contextvar inside the handler. If propagation works,
        # this returns the same token the handler authenticated with.
        ctx_token = sb_clients.get_current_user_jwt()
        return {
            "handler_kind": "sync",
            "session_token_first8": session.token[:8],
            "ctx_token_first8": (ctx_token or "")[:8],
            "user_id": session.user.id,
        }

    @app.get("/async-route")
    async def async_route(session: UserSession = Depends(sb_clients.authed_request)):
        ctx_token = sb_clients.get_current_user_jwt()
        return {
            "handler_kind": "async",
            "session_token_first8": session.token[:8],
            "ctx_token_first8": (ctx_token or "")[:8],
            "user_id": session.user.id,
        }

    return app


class AuthedRequestSyncDispatchTests(unittest.TestCase):
    """The bug: sync route + authed_request crashed on cleanup with
    ValueError ("Token was created in a different Context")."""

    def test_sync_route_returns_200_not_500(self):
        with _PatchAuthEnv():
            client = TestClient(_make_app())
            resp = client.get(
                "/sync-route",
                headers={"Authorization": f"Bearer {_mint_test_jwt()}"},
            )
        self.assertEqual(
            resp.status_code, 200,
            f"sync route + authed_request must return 200, got {resp.status_code}. "
            f"Body: {resp.text[:300]}",
        )
        data = resp.json()
        self.assertEqual(data["handler_kind"], "sync")
        self.assertEqual(data["user_id"], USER_SUB)
        # End-to-end propagation: the contextvar inside the handler
        # must carry the JWT the handler was authenticated with.
        self.assertEqual(
            data["session_token_first8"], data["ctx_token_first8"],
            "Contextvar didn't deliver the bound JWT to handler-side reads — "
            "the whole RLS pattern depends on this propagation working.",
        )

    def test_async_route_still_works(self):
        """Regression guard: the fix to reset_user_jwt should not break
        the async-handler path that was already working."""
        with _PatchAuthEnv():
            client = TestClient(_make_app())
            resp = client.get(
                "/async-route",
                headers={"Authorization": f"Bearer {_mint_test_jwt()}"},
            )
        self.assertEqual(resp.status_code, 200, resp.text[:300])
        data = resp.json()
        self.assertEqual(data["handler_kind"], "async")
        self.assertEqual(data["session_token_first8"], data["ctx_token_first8"])

    def test_missing_auth_still_401_after_fix(self):
        """Regression guard: deny-without-token must still fire."""
        with _PatchAuthEnv():
            client = TestClient(_make_app())
            resp = client.get("/sync-route")  # no Authorization header
        self.assertEqual(resp.status_code, 401, resp.text[:300])

    def test_invalid_jwt_still_401_after_fix(self):
        """Regression guard: a bogus signature must still 401, not 500."""
        with _PatchAuthEnv():
            client = TestClient(_make_app())
            resp = client.get(
                "/sync-route",
                headers={"Authorization": "Bearer not-a-real-jwt"},
            )
        self.assertEqual(resp.status_code, 401, resp.text[:300])

    def test_sequential_sync_requests_dont_leak_token(self):
        """Per-Task contextvar isolation must hold across consecutive
        requests on the same TestClient — would surface a missing reset."""
        with _PatchAuthEnv():
            client = TestClient(_make_app())
            # Request 1: authenticated, token X.
            t1 = _mint_test_jwt()
            r1 = client.get("/sync-route", headers={"Authorization": f"Bearer {t1}"})
            self.assertEqual(r1.status_code, 200)
            self.assertEqual(r1.json()["ctx_token_first8"], t1[:8])

            # Request 2: no auth. If reset failed silently and the
            # contextvar leaked, the handler would still see t1.
            # But because the route requires auth, it should be 401
            # before the handler runs — and even if the handler somehow
            # ran, the contextvar should be cleared.
            r2 = client.get("/sync-route")
            self.assertEqual(r2.status_code, 401)


class ResetUserJwtRobustnessTests(unittest.TestCase):
    """Direct exercise of the patched reset_user_jwt — proves the
    ValueError-swallow path works without breaking the happy path."""

    def test_happy_path_reset_unchanged(self):
        sb_clients._user_jwt_ctx.set(None)  # baseline
        token = sb_clients.set_user_jwt("test-jwt-abc")
        self.assertEqual(sb_clients.get_current_user_jwt(), "test-jwt-abc")
        sb_clients.reset_user_jwt(token)
        self.assertIsNone(sb_clients.get_current_user_jwt())

    def test_cross_context_reset_falls_back_to_clear(self):
        """Simulate the FastAPI sync-handler-cleanup race: token created
        in one context, reset attempted in another. Must NOT raise."""
        import contextvars

        # Capture a token from context A.
        captured = {}
        ctx_a = contextvars.copy_context()
        def in_ctx_a():
            captured["token"] = sb_clients.set_user_jwt("ctx-a-jwt")
        ctx_a.run(in_ctx_a)

        # Now try to reset that token from context B (the current one).
        # Before the fix this raised ValueError; after the fix it must
        # silently fall through to _user_jwt_ctx.set(None).
        try:
            sb_clients.reset_user_jwt(captured["token"])
        except ValueError:
            self.fail(
                "reset_user_jwt must NOT raise ValueError on cross-context "
                "reset — the patch is supposed to swallow this exact case. "
                "If you see this, the bug is back."
            )
        # And it should leave the current context with the contextvar
        # unset, not in some half-resetted state.
        self.assertIsNone(sb_clients.get_current_user_jwt())


if __name__ == "__main__":
    unittest.main()
