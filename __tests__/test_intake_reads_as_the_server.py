"""The public intake door reads and writes as the server, not as anon.

2026-09-18: the form page Chief links to (GET /public/widget/form/{id})
went live and still answered "Form not found" on both hosts. The intake
router's supabase_request used the ANON key; every policy on intake_forms
and businesses is member-scoped, so an anonymous read returns nothing.
The same helper serves POST /intake/submit — no contact had come through
that door since 2026-04-15.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import intake_endpoint
import sb_clients


class _Resp:
    status_code = 200
    text = json.dumps([{"id": "f1"}])


def test_supabase_request_sends_the_service_key_when_configured():
    seen = {}

    class _Client:
        async def request(self, method, url, headers=None, content=None, timeout=None):
            seen.update({"headers": headers, "url": url})
            return _Resp()

    with mock.patch.object(sb_clients, "sb_service_role", return_value="service-key"), \
         mock.patch.object(intake_endpoint, "get_supabase_url", return_value="https://x.supabase.co"), \
         mock.patch.object(intake_endpoint, "get_supabase_anon", return_value="anon-key"):
        out = asyncio.run(intake_endpoint.supabase_request(_Client(), "GET", "/intake_forms?id=eq.f1"))
    assert out == [{"id": "f1"}]
    assert seen["headers"]["apikey"] == "service-key"
    assert seen["headers"]["Authorization"] == "Bearer service-key"
    assert seen["headers"]["Prefer"] == "return=representation"


def test_supabase_request_falls_back_to_anon_without_a_service_key():
    seen = {}

    class _Client:
        async def request(self, method, url, headers=None, content=None, timeout=None):
            seen.update({"headers": headers})
            return _Resp()

    with mock.patch.object(sb_clients, "sb_service_role", return_value=""), \
         mock.patch.object(intake_endpoint, "get_supabase_url", return_value="https://x.supabase.co"), \
         mock.patch.object(intake_endpoint, "get_supabase_anon", return_value="anon-key"):
        asyncio.run(intake_endpoint.supabase_request(_Client(), "GET", "/intake_forms?id=eq.f1"))
    assert seen["headers"]["apikey"] == "anon-key"
