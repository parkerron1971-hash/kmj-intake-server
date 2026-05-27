"""RLS migration — sb_clients tests.

These tests are the SECURITY-MODEL contract. They verify:

  * sb_headers_user forwards the user's JWT (not the anon key) as Bearer
    so PostgREST sets auth.uid() to the practitioner's sub claim
  * sb_headers_service uses SUPABASE_SERVICE_ROLE_KEY and crashes
    visibly if it's missing (deploy-config bug, not a silent fallback)
  * sb_headers_anon stays the legacy anon path
  * sb_headers_user REFUSES empty / missing user_jwt — closes the
    "oops, I passed None and it silently went anonymous" footgun

Run via:
  python -m __tests__.test_sb_clients
"""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch, MagicMock

import sb_clients


ANON_KEY = "anon-eyJtest-anon-key"
SERVICE_ROLE_KEY = "service-role-eyJtest-service-role-key"
USER_JWT = "user-eyJtest-user-jwt-real-practitioner-token"
SUPABASE_URL = "https://test.supabase.co"


def _env(**overrides):
    base = {
        "SUPABASE_URL": SUPABASE_URL,
        "SUPABASE_ANON": ANON_KEY,
        "SUPABASE_SERVICE_ROLE_KEY": SERVICE_ROLE_KEY,
    }
    base.update(overrides)
    return base


class HeaderBuilderTests(unittest.TestCase):

    def test_user_headers_send_user_jwt_not_anon(self):
        with patch.dict(os.environ, _env(), clear=False):
            headers = sb_clients.sb_headers_user(USER_JWT)
        self.assertEqual(headers["apikey"], ANON_KEY)
        self.assertEqual(headers["Authorization"], f"Bearer {USER_JWT}")
        self.assertNotIn(ANON_KEY, headers["Authorization"])

    def test_user_headers_refuses_empty_jwt(self):
        with patch.dict(os.environ, _env(), clear=False):
            with self.assertRaises(ValueError):
                sb_clients.sb_headers_user("")
            with self.assertRaises(ValueError):
                sb_clients.sb_headers_user(None)  # type: ignore[arg-type]

    def test_service_headers_use_service_role_key(self):
        with patch.dict(os.environ, _env(), clear=False):
            headers = sb_clients.sb_headers_service()
        self.assertEqual(headers["apikey"], SERVICE_ROLE_KEY)
        self.assertEqual(headers["Authorization"], f"Bearer {SERVICE_ROLE_KEY}")

    def test_service_headers_crashes_if_missing(self):
        env_without_service = _env()
        env_without_service.pop("SUPABASE_SERVICE_ROLE_KEY", None)
        with patch.dict(os.environ, env_without_service, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                sb_clients.sb_headers_service()
            self.assertIn("SUPABASE_SERVICE_ROLE_KEY", str(ctx.exception))

    def test_anon_headers_legacy_path(self):
        with patch.dict(os.environ, _env(), clear=False):
            headers = sb_clients.sb_headers_anon()
        self.assertEqual(headers["apikey"], ANON_KEY)
        self.assertEqual(headers["Authorization"], f"Bearer {ANON_KEY}")

    def test_all_variants_set_content_type_json(self):
        with patch.dict(os.environ, _env(), clear=False):
            for h in (
                sb_clients.sb_headers_user(USER_JWT),
                sb_clients.sb_headers_service(),
                sb_clients.sb_headers_anon(),
            ):
                self.assertEqual(h["Content-Type"], "application/json")

    def test_prefer_passes_through(self):
        with patch.dict(os.environ, _env(), clear=False):
            h = sb_clients.sb_headers_user(USER_JWT, prefer="count=exact")
            self.assertEqual(h["Prefer"], "count=exact")
            h2 = sb_clients.sb_headers_user(USER_JWT, prefer=None)
            self.assertNotIn("Prefer", h2)


class SyncRequestTests(unittest.TestCase):

    @patch("sb_clients.httpx.Client")
    def test_get_as_user_url_and_headers(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '[{"id":"biz-1","name":"Test"}]'
        mock_client_cls.return_value.__enter__.return_value.request.return_value = mock_resp

        with patch.dict(os.environ, _env(), clear=False):
            result = sb_clients.sb_get_as_user("/businesses?id=eq.biz-1", USER_JWT)
        self.assertEqual(result, [{"id": "biz-1", "name": "Test"}])

        request_call = mock_client_cls.return_value.__enter__.return_value.request.call_args
        method, url = request_call.args
        headers = request_call.kwargs["headers"]
        self.assertEqual(method, "GET")
        self.assertEqual(url, f"{SUPABASE_URL}/rest/v1/businesses?id=eq.biz-1")
        self.assertEqual(headers["Authorization"], f"Bearer {USER_JWT}")

    @patch("sb_clients.httpx.Client")
    def test_get_as_service_uses_service_role(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "[]"
        mock_client_cls.return_value.__enter__.return_value.request.return_value = mock_resp
        with patch.dict(os.environ, _env(), clear=False):
            sb_clients.sb_get_as_service("/businesses")
        headers = mock_client_cls.return_value.__enter__.return_value.request.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], f"Bearer {SERVICE_ROLE_KEY}")

    @patch("sb_clients.httpx.Client")
    def test_patch_as_user_body_serialized(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"id":"biz-1"}'
        mock_client_cls.return_value.__enter__.return_value.request.return_value = mock_resp
        with patch.dict(os.environ, _env(), clear=False):
            sb_clients.sb_patch_as_user(
                "/businesses?id=eq.biz-1",
                {"settings": {"updated": True}},
                USER_JWT,
            )
        call = mock_client_cls.return_value.__enter__.return_value.request.call_args
        self.assertEqual(call.args[0], "PATCH")
        body_content = call.kwargs["content"]
        self.assertEqual(json.loads(body_content), {"settings": {"updated": True}})

    @patch("sb_clients.httpx.Client")
    def test_4xx_returns_none(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = '{"message":"JWT expired"}'
        mock_client_cls.return_value.__enter__.return_value.request.return_value = mock_resp
        with patch.dict(os.environ, _env(), clear=False):
            result = sb_clients.sb_get_as_user("/businesses", USER_JWT)
        self.assertIsNone(result)


class AsyncRequestTests(unittest.IsolatedAsyncioTestCase):

    async def test_sb_as_user_forwards_jwt(self):
        captured = {}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '[{"id":"biz-1"}]'

        mock_client = MagicMock()
        async def fake_request(method, url, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = kwargs["headers"]
            return mock_resp
        mock_client.request = fake_request

        with patch.dict(os.environ, _env(), clear=False):
            result = await sb_clients.sb_as_user(
                mock_client, "POST", "/businesses", USER_JWT, body={"name": "X"},
            )
        self.assertEqual(result, [{"id": "biz-1"}])
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["url"], f"{SUPABASE_URL}/rest/v1/businesses")
        self.assertEqual(captured["headers"]["Authorization"], f"Bearer {USER_JWT}")

    async def test_sb_as_service_uses_service_role(self):
        captured = {}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '[]'
        mock_client = MagicMock()
        async def fake_request(method, url, **kwargs):
            captured["headers"] = kwargs["headers"]
            return mock_resp
        mock_client.request = fake_request

        with patch.dict(os.environ, _env(), clear=False):
            await sb_clients.sb_as_service(mock_client, "GET", "/businesses")
        self.assertEqual(captured["headers"]["Authorization"], f"Bearer {SERVICE_ROLE_KEY}")

    async def test_sb_as_user_refuses_empty_jwt(self):
        mock_client = MagicMock()
        with patch.dict(os.environ, _env(), clear=False):
            with self.assertRaises(ValueError):
                await sb_clients.sb_as_user(mock_client, "GET", "/businesses", "")


class AntiRegressionTests(unittest.TestCase):

    def test_anon_and_user_authorization_differ(self):
        with patch.dict(os.environ, _env(), clear=False):
            anon_headers = sb_clients.sb_headers_anon()
            user_headers = sb_clients.sb_headers_user(USER_JWT)
        self.assertNotEqual(
            anon_headers["Authorization"], user_headers["Authorization"],
            "anon and user headers MUST differ — silent degrade to anon "
            "would defeat the RLS migration",
        )

    def test_fixture_sanity_distinct_keys(self):
        self.assertNotEqual(USER_JWT, ANON_KEY)
        self.assertNotEqual(USER_JWT, SERVICE_ROLE_KEY)
        self.assertNotEqual(ANON_KEY, SERVICE_ROLE_KEY)


if __name__ == "__main__":
    unittest.main()
