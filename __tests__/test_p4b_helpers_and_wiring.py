"""RLS migration P5 — additional safety tests for the helpers + wiring
added in P3c (sb_post_current_context with `prefer`, sb_delete_*,
override_storage._sb_post + _sb_delete, refine._sb_delete, foundation
_sb_headers switch).

These complement the foundational sb_clients header tests by proving
the per-file integration shape — i.e. that the migrated helpers in
the agent files actually delegate to the sb_clients context-aware
dispatchers and don't quietly bypass them.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch, MagicMock

import sb_clients


ANON_KEY = "anon-eyJtest-anon-key"
SERVICE_ROLE_KEY = "service-role-eyJtest-service-role-key"
USER_JWT = "user-eyJtest-user-jwt-real-practitioner-token"
SUPABASE_URL = "https://test.supabase.co"


def _env():
    return {
        "SUPABASE_URL": SUPABASE_URL,
        "SUPABASE_ANON": ANON_KEY,
        "SUPABASE_SERVICE_ROLE_KEY": SERVICE_ROLE_KEY,
    }


class PostWithPreferTests(unittest.TestCase):
    """sb_post_current_context grew a `prefer` kwarg so upsert callers
    (override_storage) can pass resolution=merge-duplicates. The bug
    we're guarding against: prefer dropped on the floor → upserts
    behave like plain inserts and 409 on the UNIQUE constraint."""

    @patch("sb_clients.httpx.Client")
    def test_user_path_forwards_prefer(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.text = '[{"id":"ov-1"}]'
        mock_client_cls.return_value.__enter__.return_value.request.return_value = mock_resp
        try:
            jwt_token = sb_clients.set_user_jwt(USER_JWT)
            with patch.dict(os.environ, _env(), clear=False):
                sb_clients.sb_post_current_context(
                    "/site_content_overrides",
                    {"business_id": "biz-1", "target_path": "hero/cta"},
                    prefer="resolution=merge-duplicates,return=representation",
                )
        finally:
            sb_clients.reset_user_jwt(jwt_token)
        call = mock_client_cls.return_value.__enter__.return_value.request.call_args
        headers = call.kwargs["headers"]
        self.assertEqual(headers["Authorization"], f"Bearer {USER_JWT}")
        self.assertIn("resolution=merge-duplicates", headers["Prefer"])

    @patch("sb_clients.httpx.Client")
    def test_service_fallback_also_forwards_prefer(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.text = "[]"
        mock_client_cls.return_value.__enter__.return_value.request.return_value = mock_resp
        # No user JWT in context — service-role fallback path.
        with patch.dict(os.environ, _env(), clear=False):
            sb_clients.sb_post_current_context(
                "/site_chat_history",
                {"business_id": "biz-1", "message_type": "system"},
                prefer="return=minimal",
                allow_service_fallback=True,
            )
        call = mock_client_cls.return_value.__enter__.return_value.request.call_args
        headers = call.kwargs["headers"]
        self.assertEqual(headers["Authorization"], f"Bearer {SERVICE_ROLE_KEY}")
        self.assertEqual(headers["Prefer"], "return=minimal")


class DeleteCurrentContextTests(unittest.TestCase):
    """sb_delete_current_context is new. Confirm RLS scoping (user JWT
    when context bound) + service fallback + the "deny by default if
    nothing in context" contract."""

    @patch("sb_clients.httpx.Client")
    def test_user_context_path(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_resp.text = ""
        mock_client_cls.return_value.__enter__.return_value.request.return_value = mock_resp
        try:
            jwt_token = sb_clients.set_user_jwt(USER_JWT)
            with patch.dict(os.environ, _env(), clear=False):
                ok = sb_clients.sb_delete_current_context(
                    "/site_content_overrides?id=eq.ov-1",
                )
        finally:
            sb_clients.reset_user_jwt(jwt_token)
        self.assertTrue(ok)
        call = mock_client_cls.return_value.__enter__.return_value.request.call_args
        self.assertEqual(call.args[0], "DELETE")
        self.assertEqual(call.kwargs["headers"]["Authorization"], f"Bearer {USER_JWT}")

    @patch("sb_clients.httpx.Client")
    def test_service_fallback_when_allowed(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_resp.text = ""
        mock_client_cls.return_value.__enter__.return_value.request.return_value = mock_resp
        with patch.dict(os.environ, _env(), clear=False):
            ok = sb_clients.sb_delete_current_context(
                "/site_chat_history?business_id=eq.biz-1",
                allow_service_fallback=True,
            )
        self.assertTrue(ok)
        call = mock_client_cls.return_value.__enter__.return_value.request.call_args
        self.assertEqual(call.kwargs["headers"]["Authorization"], f"Bearer {SERVICE_ROLE_KEY}")

    def test_no_context_no_fallback_refuses(self):
        # No user JWT, no fallback → returns False without making a request.
        # This is the deny-by-default contract — the migration must NEVER
        # quietly drop authentication.
        with patch.dict(os.environ, _env(), clear=False):
            ok = sb_clients.sb_delete_current_context(
                "/site_content_overrides?id=eq.ov-1",
                allow_service_fallback=False,
            )
        self.assertFalse(ok)

    @patch("sb_clients.httpx.Client")
    def test_5xx_returns_false(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "internal error"
        mock_client_cls.return_value.__enter__.return_value.request.return_value = mock_resp
        try:
            jwt_token = sb_clients.set_user_jwt(USER_JWT)
            with patch.dict(os.environ, _env(), clear=False):
                ok = sb_clients.sb_delete_current_context(
                    "/site_content_overrides?id=eq.ov-1",
                )
        finally:
            sb_clients.reset_user_jwt(jwt_token)
        self.assertFalse(ok)


class OverrideStorageWiringTests(unittest.TestCase):
    """override_storage._sb_post + _sb_delete are migrated to delegate
    to sb_clients context-aware dispatchers. Prove the integration by
    setting a user JWT in context and confirming the storage helpers
    end up calling httpx with the practitioner's Authorization."""

    @patch("sb_clients.httpx.Client")
    def test_post_routes_through_current_context(self, mock_client_cls):
        from agents.override_system import override_storage

        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.text = '[{"id":"ov-1"}]'
        mock_client_cls.return_value.__enter__.return_value.request.return_value = mock_resp
        try:
            jwt_token = sb_clients.set_user_jwt(USER_JWT)
            with patch.dict(os.environ, _env(), clear=False):
                override_storage._sb_post(
                    "/site_content_overrides",
                    {"business_id": "biz-1", "target_path": "hero/cta"},
                    prefer="resolution=merge-duplicates,return=representation",
                )
        finally:
            sb_clients.reset_user_jwt(jwt_token)
        call = mock_client_cls.return_value.__enter__.return_value.request.call_args
        self.assertEqual(call.kwargs["headers"]["Authorization"], f"Bearer {USER_JWT}")
        self.assertIn("resolution=merge-duplicates", call.kwargs["headers"]["Prefer"])

    @patch("sb_clients.httpx.Client")
    def test_delete_routes_through_current_context(self, mock_client_cls):
        from agents.override_system import override_storage

        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_resp.text = ""
        mock_client_cls.return_value.__enter__.return_value.request.return_value = mock_resp
        try:
            jwt_token = sb_clients.set_user_jwt(USER_JWT)
            with patch.dict(os.environ, _env(), clear=False):
                ok = override_storage._sb_delete(
                    "/site_content_overrides?id=eq.ov-1",
                )
        finally:
            sb_clients.reset_user_jwt(jwt_token)
        self.assertTrue(ok)
        call = mock_client_cls.return_value.__enter__.return_value.request.call_args
        self.assertEqual(call.kwargs["headers"]["Authorization"], f"Bearer {USER_JWT}")


class RefineWiringTests(unittest.TestCase):
    """Director refine — chat history delete is the user-action path."""

    @patch("sb_clients.httpx.Client")
    def test_chat_history_delete_routes_through_current_context(self, mock_client_cls):
        from agents.director_agent import refine

        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_resp.text = ""
        mock_client_cls.return_value.__enter__.return_value.request.return_value = mock_resp
        try:
            jwt_token = sb_clients.set_user_jwt(USER_JWT)
            with patch.dict(os.environ, _env(), clear=False):
                ok = refine._sb_delete(
                    "/site_chat_history?business_id=eq.biz-1",
                )
        finally:
            sb_clients.reset_user_jwt(jwt_token)
        self.assertTrue(ok)
        call = mock_client_cls.return_value.__enter__.return_value.request.call_args
        self.assertEqual(call.kwargs["headers"]["Authorization"], f"Bearer {USER_JWT}")


class FoundationHeadersSwitchTests(unittest.TestCase):
    """foundation_agent._sb_headers() is the single swap point — returns
    user-JWT headers when bound, service-role when not. All three async
    helpers in that file (_sb_get/_sb_post/_sb_patch) inherit from it."""

    def test_returns_user_headers_when_context_bound(self):
        import foundation_agent

        try:
            jwt_token = sb_clients.set_user_jwt(USER_JWT)
            with patch.dict(os.environ, _env(), clear=False):
                headers = foundation_agent._sb_headers()
        finally:
            sb_clients.reset_user_jwt(jwt_token)
        self.assertEqual(headers["Authorization"], f"Bearer {USER_JWT}")
        self.assertEqual(headers["apikey"], ANON_KEY)

    def test_falls_back_to_service_role_without_context(self):
        import foundation_agent

        with patch.dict(os.environ, _env(), clear=False):
            headers = foundation_agent._sb_headers()
        self.assertEqual(headers["Authorization"], f"Bearer {SERVICE_ROLE_KEY}")
        self.assertEqual(headers["apikey"], SERVICE_ROLE_KEY)


class ComposerPostProcessorWiringTests(unittest.IsolatedAsyncioTestCase):
    """post_processor._read_use_composer was the silent-failure root
    cause — anon-keyed business read returned 0 rows under RLS and every
    site fell back to the Builder-only path. Now routes through
    sb_as_current_context so the build_with_loop handler's bound user
    JWT forwards correctly."""

    async def test_uses_user_context_when_bound(self):
        from agents.composer import post_processor

        captured = {}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '[{"use_composer":true}]'
        mock_client = MagicMock()
        async def fake_request(method, url, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = kwargs["headers"]
            return mock_resp
        mock_client.request = fake_request

        try:
            jwt_token = sb_clients.set_user_jwt(USER_JWT)
            with patch.dict(os.environ, _env(), clear=False):
                result = await post_processor._read_use_composer(mock_client, "biz-1")
        finally:
            sb_clients.reset_user_jwt(jwt_token)
        self.assertTrue(result)
        self.assertEqual(captured["headers"]["Authorization"], f"Bearer {USER_JWT}")
        self.assertIn("use_composer", captured["url"])


if __name__ == "__main__":
    unittest.main()
