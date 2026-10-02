"""Lane buyer MCP transport. The probe never calls tools; purchase calls are allowlisted.

Lane: https://docs.getonlane.com/buy/mcp/quickstart
MCP: https://modelcontextprotocol.io/specification/2025-03-26/basic/transports
"""
from __future__ import annotations

import json
import re
import time
from uuid import uuid4

import httpx

ENDPOINT = "https://mcp.getonlane.com/mcp"
PROTOCOL = "2025-03-26"
MAX_BYTES = 512 * 1024
REQUIRED_TOOLS = frozenset({
    "intent_submit", "intent_get_status", "intent_get_terms",
    "find_products", "start_session", "get_session_status",
    "resume_session", "end_session",
})


class LaneError(Exception):
    """Only application-authored messages; never provider bodies or credentials."""


def valid_key(value):
    return isinstance(value, str) and bool(re.fullmatch(r"lane_[A-Za-z0-9_-]{8,512}", value)) and not value.startswith("lane_org_")


def _result(message, request_id):
    if not isinstance(message, dict) or message.get("id") != request_id:
        return None
    if message.get("jsonrpc") != "2.0" or "error" in message or not isinstance(message.get("result"), dict):
        raise LaneError("Lane could not complete the connection check.")
    return message["result"]


def _response(response, request_id, deadline):
    """Read bounded JSON or SSE. Stop at our response, not at stream closure."""
    kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if kind not in {"application/json", "text/event-stream"}:
        raise LaneError("Lane returned an unsupported response.")
    size = 0
    pending = b""
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > MAX_BYTES or time.monotonic() > deadline:
            raise LaneError("Lane's connection check exceeded its limit.")
        pending += chunk
        if kind == "text/event-stream":
            pending = pending.replace(b"\r\n", b"\n")
            while b"\n\n" in pending:
                event, pending = pending.split(b"\n\n", 1)
                data = b"\n".join(line[5:].lstrip(b" ") for line in event.split(b"\n") if line.startswith(b"data:"))
                if data:
                    result = _result(json.loads(data), request_id)
                    if result is not None:
                        return result
    if kind == "application/json":
        result = _result(json.loads(pending), request_id)
        if result is not None:
            return result
    raise LaneError("Lane did not return a complete connection check.")


def _exchange(api_key, *, tool=None, arguments=None, transport=None):
    """Initialize a bounded session; list tools or perform one allowlisted buyer call.

    Session and bearer remain local to this check, not in app-wide state.
    transport is injectable for offline tests.
    """
    if not valid_key(api_key):
        raise LaneError("A personal Lane wallet key is required.")
    headers = {"Authorization": "Bearer " + api_key,
               "Accept": "application/json, text/event-stream"}
    deadline = time.monotonic() + (75 if tool else 45)
    session_id = None
    try:
        with httpx.Client(timeout=httpx.Timeout(60 if tool else 10, connect=10), follow_redirects=False, trust_env=False, transport=transport) as client:
            def rpc(method, params=None):
                nonlocal session_id
                if method not in {"initialize", "notifications/initialized", "tools/list", "tools/call"} or (method == "tools/call" and tool is None):
                    raise LaneError("This connection check cannot call payment tools.")
                if time.monotonic() > deadline:
                    raise LaneError("Lane's connection check timed out.")
                request_id = str(uuid4()) if method != "notifications/initialized" else None
                body = {"jsonrpc": "2.0", "method": method}
                if request_id is not None:
                    body["id"] = request_id
                if params is not None:
                    body["params"] = params
                with client.stream("POST", ENDPOINT, headers=headers, json=body) as response:
                    if response.status_code in {401, 403}:
                        raise LaneError("Lane did not accept this wallet key. Check or rotate it in Lane.")
                    if request_id is None:
                        if response.status_code not in {202, 204}:
                            raise LaneError("Lane did not accept initialization.")
                        return {}
                    if response.status_code != 200:
                        raise LaneError("Lane is unavailable for a connection check.")
                    if method == "initialize":
                        session_id = response.headers.get("mcp-session-id")
                        if session_id:
                            if not re.fullmatch(r"[!-~]{1,1024}", session_id):
                                session_id = None
                                raise LaneError("Lane returned an invalid session.")
                            headers["Mcp-Session-Id"] = session_id
                    return _response(response, request_id, deadline)

            try:
                initialized = rpc("initialize", {
                    "protocolVersion": PROTOCOL, "capabilities": {},
                    "clientInfo": {"name": "solutionist-lane-connection-check", "version": "0.1.0"},
                })
                if initialized.get("protocolVersion") != PROTOCOL:
                    raise LaneError("Lane requires a different MCP protocol version.")
                capabilities = initialized.get("capabilities")
                if not isinstance(capabilities, dict) or not isinstance(capabilities.get("tools"), dict):
                    raise LaneError("Lane did not advertise buyer tools.")
                headers["MCP-Protocol-Version"] = PROTOCOL
                rpc("notifications/initialized")
                if tool is not None:
                    result = rpc("tools/call", {"name": tool, "arguments": arguments})
                    if result.get("isError"):
                        raise LaneError("Lane could not complete this purchase action. Refresh its status.")
                    data = result.get("structuredContent")
                    if data is None:
                        blocks = result.get("content", [])
                        if not isinstance(blocks, list) or len(blocks) != 1 or blocks[0].get("type") != "text":
                            raise LaneError("Lane returned an unsupported tool response.")
                        data = json.loads(blocks[0]["text"])
                    if not isinstance(data, dict):
                        raise LaneError("Lane returned incomplete purchase details.")
                    return data
                names, seen = set(), set()
                cursor = None
                for _ in range(5):
                    page = rpc("tools/list", {"cursor": cursor} if cursor else {})
                    tools = page.get("tools")
                    if not isinstance(tools, list) or any(not isinstance(t, dict) or not isinstance(t.get("name"), str) for t in tools):
                        raise LaneError("Lane returned an invalid tool list.")
                    names.update(t["name"] for t in tools if t["name"] in REQUIRED_TOOLS)
                    cursor = page.get("nextCursor")
                    if cursor is None:
                        return {"connection_verified": True,
                                "buyer_tools_available": REQUIRED_TOOLS <= names,
                                "available_tools": sorted(names),
                                "missing_tools": sorted(REQUIRED_TOOLS - names),
                                "live_spending_enabled": False}
                    if not isinstance(cursor, str) or not 1 <= len(cursor) <= 4096 or cursor in seen:
                        raise LaneError("Lane returned invalid tool pagination.")
                    seen.add(cursor)
                raise LaneError("Lane's tool list exceeded the connection-check limit.")
            finally:
                if session_id:
                    try:
                        with client.stream("DELETE", ENDPOINT, headers=headers):
                            pass
                    except Exception:
                        pass  # Best-effort MCP session closure. Never log the bearer.
    except LaneError:
        raise
    except Exception:
        raise LaneError("Lane could not finish the request. Refresh its status before taking further action.") from None


def probe(api_key, *, transport=None):
    """Read-only connectivity check; never invokes a Lane tool."""
    return _exchange(api_key, transport=transport)


def call(api_key, tool, arguments, *, transport=None):
    """Internal buyer transport; no arbitrary tools, approval, wallet funding or credentials."""
    if tool not in {"intent_submit", "intent_get_status", "intent_list", "find_products", "start_session", "get_session_status"}:
        raise LaneError("This Lane action is not supported.")
    return _exchange(api_key, tool=tool, arguments=arguments, transport=transport)
