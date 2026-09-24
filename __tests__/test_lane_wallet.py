"""Offline Lane connection checks; no purchases, provider calls, or real keys."""
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import lane_mcp as mcp
import lane_wallet as wallet

KEY = "lane_test_synthetic_only"
BID = "00000000-0000-4000-8000-000000000001"
UID = "00000000-0000-4000-8000-000000000002"
OTHER = "00000000-0000-4000-8000-000000000003"


class ConnectionTests(unittest.TestCase):
    def transport(self, *, sse=False, fail=None, missing=False, paginate=False):
        self.requests = []
        self.pages = 0

        def handle(request):
            self.assertEqual(str(request.url), mcp.ENDPOINT)
            self.assertEqual(request.headers["authorization"], "Bearer " + KEY)
            self.requests.append(request)
            if request.method == "DELETE":
                self.assertEqual(request.headers["mcp-session-id"], "session-test")
                return httpx.Response(204)
            body = json.loads(request.content)
            method = body["method"]
            self.assertIn(method, {"initialize", "notifications/initialized", "tools/list"})
            self.assertNotEqual(method, "tools/call")
            if fail:
                return fail(request, body)
            if method == "notifications/initialized":
                return httpx.Response(202)
            headers = {}
            if method == "initialize":
                result = {"protocolVersion": mcp.PROTOCOL, "capabilities": {"tools": {}}}
                headers["Mcp-Session-Id"] = "session-test"
            else:
                self.assertEqual(request.headers["mcp-session-id"], "session-test")
                self.assertEqual(request.headers["mcp-protocol-version"], mcp.PROTOCOL)
                self.pages += 1
                names = sorted(mcp.REQUIRED_TOOLS)
                if missing:
                    names.remove("start_session")
                if paginate and self.pages == 1:
                    result = {"tools": [{"name": names[0]}], "nextCursor": "next"}
                else:
                    if paginate:
                        self.assertEqual(body["params"], {"cursor": "next"})
                    result = {"tools": [{"name": n, "description": "PRIVATE PROVIDER TEXT"} for n in names]}
            message = {"jsonrpc": "2.0", "id": body["id"], "result": result}
            if sse:
                headers["Content-Type"] = "text/event-stream"
                return httpx.Response(200, headers=headers,
                    content=': heartbeat\r\n\r\ndata: {"jsonrpc":"2.0","method":"notifications/message"}\r\n\r\ndata: '
                    + json.dumps(message) + "\r\n\r\n")
            return httpx.Response(200, headers=headers, json=message)
        return httpx.MockTransport(handle)

    def test_json_and_sse_connect_without_calling_any_tool(self):
        for sse in (False, True):
            with self.subTest(sse=sse):
                result = mcp.probe(KEY, transport=self.transport(sse=sse))
                self.assertTrue(result["connection_verified"])
                self.assertTrue(result["buyer_tools_available"])
                self.assertFalse(result["live_spending_enabled"])
                self.assertNotIn("PRIVATE", json.dumps(result))
                self.assertNotIn(KEY, json.dumps(result))
                self.assertEqual(self.requests[-1].method, "DELETE")

    def test_pagination_and_missing_tool_do_not_claim_buyer_readiness(self):
        result = mcp.probe(KEY, transport=self.transport(paginate=True, missing=True))
        self.assertTrue(result["connection_verified"])
        self.assertFalse(result["buyer_tools_available"])
        self.assertEqual(result["missing_tools"], ["start_session"])

    def test_org_or_malformed_key_never_reaches_network(self):
        network = Mock(side_effect=AssertionError("must not connect"))
        for value in (None, "", "lane_org_sk_123456789", KEY + "\n", "secret"):
            with self.subTest(value=value), self.assertRaises(mcp.LaneError):
                mcp.probe(value, transport=httpx.MockTransport(network))
        network.assert_not_called()

    def test_auth_redirect_and_provider_errors_are_sanitized_without_retry(self):
        for status in (401, 403, 302, 500):
            with self.subTest(status=status), self.assertRaises(mcp.LaneError) as caught:
                mcp.probe(KEY, transport=self.transport(
                    fail=lambda req, body: httpx.Response(status,
                        headers={"Location": "https://example.com/steal"},
                        text=KEY + " PRIVATE ERROR")))
            self.assertNotIn(KEY, str(caught.exception))
            self.assertNotIn("PRIVATE", str(caught.exception))
            self.assertEqual(len(self.requests), 1)

    def test_malformed_mismatched_and_oversized_responses_fail_closed(self):
        bodies = [
            {"jsonrpc": "2.0", "id": "wrong", "result": {}},
            {"jsonrpc": "2.0", "id": None, "error": {"message": KEY}},
            {"padding": "x" * (mcp.MAX_BYTES + 1)},
        ]
        for data in bodies:
            with self.subTest(case=len(json.dumps(data))), self.assertRaises(mcp.LaneError) as caught:
                mcp.probe(KEY, transport=self.transport(fail=lambda req, body: httpx.Response(200, json=data)))
            self.assertNotIn(KEY, str(caught.exception))

    def test_timeout_does_not_echo_request_credentials(self):
        def fail(request, body):
            raise httpx.ReadTimeout(KEY, request=request)
        with self.assertRaises(mcp.LaneError) as caught:
            mcp.probe(KEY, transport=self.transport(fail=fail))
        self.assertNotIn(KEY, str(caught.exception))
        self.assertEqual(len(self.requests), 1)


class WalletTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "LANE_PILOT_ENABLED": "true", "LANE_PILOT_USER_ID": UID,
            "LANE_PILOT_BUSINESS_ID": BID, "LANE_PILOT_API_KEY": KEY})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.access = patch.object(wallet.business_access, "assert_access").start()
        self.probe = patch.object(wallet.lane_mcp, "probe", return_value={
            "connection_verified": True, "buyer_tools_available": True,
            "available_tools": sorted(mcp.REQUIRED_TOOLS), "missing_tools": [],
            "live_spending_enabled": False}).start()
        self.addCleanup(patch.stopall)
        app = FastAPI()
        app.include_router(wallet.router)
        self.identity = SimpleNamespace(user=SimpleNamespace(id=UID))
        app.dependency_overrides[wallet.sb_clients.authed_request] = lambda: self.identity
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.app = app
        self.base = "/lane/wallet/" + BID

    def test_status_does_not_call_lane_or_claim_connected(self):
        response = self.client.get(self.base)
        self.assertTrue(response.json()["configured"])
        self.assertFalse(response.json()["connection_verified"])
        self.assertFalse(response.json()["live_spending_enabled"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertNotIn(KEY, response.text)
        self.probe.assert_not_called()

    def test_only_bound_owner_can_verify(self):
        response = self.client.post(self.base + "/verify")
        self.assertEqual(response.status_code, 200)
        self.access.assert_called_with(BID, self.identity.user, "owner")
        self.probe.assert_called_once_with(KEY)
        self.assertNotIn(KEY, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_other_owner_business_and_disabled_pilot_cannot_use_key(self):
        for changes in ({"LANE_PILOT_USER_ID": OTHER},
                        {"LANE_PILOT_BUSINESS_ID": OTHER},
                        {"LANE_PILOT_ENABLED": "false"}):
            with self.subTest(changes=changes), patch.dict(os.environ, changes):
                self.assertEqual(self.client.post(self.base + "/verify").status_code, 403)
                self.assertFalse(self.client.get(self.base).json()["configured"])
        self.probe.assert_not_called()

    def test_jwt_and_business_access_are_enforced_before_provider_call(self):
        self.access.side_effect = HTTPException(403, "Forbidden")
        response = self.client.post(self.base + "/verify")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.headers["cache-control"], "no-store")
        def denied():
            raise HTTPException(401, "Authentication required")
        self.app.dependency_overrides[wallet.sb_clients.authed_request] = denied
        self.assertEqual(self.client.post(self.base + "/verify").status_code, 401)
        self.probe.assert_not_called()

    def test_missing_key_and_provider_failure_never_report_verified(self):
        with patch.dict(os.environ, {"LANE_PILOT_API_KEY": ""}):
            self.assertEqual(self.client.post(self.base + "/verify").status_code, 503)
        self.probe.assert_not_called()
        self.probe.side_effect = mcp.LaneError("Lane is unavailable.")
        response = self.client.post(self.base + "/verify")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_no_purchase_endpoint_is_exposed(self):
        for path in ("draft", "approve", "checkout", "load-credits"):
            self.assertEqual(self.client.post(self.base + "/" + path).status_code, 404)
        self.probe.assert_not_called()
