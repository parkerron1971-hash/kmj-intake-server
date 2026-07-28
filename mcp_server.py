"""
mcp_server.py — the agent-facing surface. Stage 1: read-only, owner-only.

An MCP (Model Context Protocol) endpoint exposing a narrow READ-ONLY slice
of Chief's verbs, so an external client (Claude Desktop, a self-hosted ops
agent) can read Mission Control state. Blast radius is one account — the
platform owner's — by design.

Strategy: solutionist-studio/docs/PERSONAL_AGENT_ARCHITECTURE.md §4 (open on
read, closed on write), §7 (trust/egress), §10 Stage 1. Gateway shape:
docs/extensibility_and_autonomy.md §2.3. Permission model:
docs/future_architecture.md §3 — the Trust Track, not a parallel invention.

═══════════════════════════════════════════════════════════════════════
WHY THE TRANSPORT IS HAND-WRITTEN
═══════════════════════════════════════════════════════════════════════
The official `mcp` SDK's Streamable HTTP transport needs its session
manager running in an ASGI **lifespan**. This app uses the deprecated
`@app.on_event("startup")` and starts the APScheduler there — and Starlette
ignores `on_event` the moment a `lifespan=` is supplied. Adopting the SDK
therefore means rewriting the startup path of a live service that mounts
~70 routers and owns the scheduler. That is a disproportionate risk for a
surface with one user. (Mounting it as a sub-app does not help: Starlette
does not run mounted sub-app lifespans without manual wiring.)

Against that, the compliant surface is small — `initialize`,
`notifications/initialized`, `tools/list`, `tools/call`, `ping` over
JSON-RPC 2.0, answered with plain JSON, which Streamable HTTP permits for
non-streaming responses. And every control that matters here is bespoke:
scoped tokens, a fail-CLOSED limiter, an audit row per call, the remapper
bypass, tenancy. Owning the request path is the point, not the cost.

The trade is that protocol compliance is ours to prove rather than
inherit. See __tests__/test_mcp_server.py.

═══════════════════════════════════════════════════════════════════════
THE AUTHORIZATION DECISION IS NOT MADE HERE
═══════════════════════════════════════════════════════════════════════
`action_registry.may_expose_to_agent()` decides what an agent may call.
This module ASKS it and never second-guesses it. There is deliberately no
hand-maintained tool list: a second list would drift from the registry,
and that drift is a security bug rather than a tidiness one.

Today that yields exactly 16 read verbs. The 5 `ui` verbs are excluded
(an off-app caller has no UI to drive) and the 22 class-C verbs can never
appear at any scope.

═══════════════════════════════════════════════════════════════════════
WHAT THIS DELIBERATELY DOES NOT DO
═══════════════════════════════════════════════════════════════════════
It never calls `chief_of_staff._execute_actions`. That function routes an
unrecognised verb to `chief_action_reasoner`, which reinterprets it into
known-safe primitives — correct inside Chief, where a practitioner asked
for something the system was never coded for, and WRONG here. An agent
asking for an unknown tool is either mistaken or probing; either way it
gets an error, not a helpful reinterpretation. Dispatch goes straight to
`ACTION_HANDLERS`, so the remapper is not bypassed by a flag — it is
simply not on the path.

Kill switch: MCP_ENABLED=off (default on).
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

import action_registry
import rate_limit
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("mcp_server")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] mcp: %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

router = APIRouter(prefix="/mcp", tags=["mcp"])

# The spec revision this server implements. Clients send their own in
# `initialize`; we echo ours back and let them decide about compatibility.
PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "solutionist-admin"
SERVER_VERSION = "0.1.0"

HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=45.0, write=15.0, pool=10.0)

PLATFORM_OWNER_EMAIL = os.environ.get(
    "PLATFORM_OWNER_EMAIL", "kmjcreativesolution@gmail.com").lower()


def enabled() -> bool:
    return (os.environ.get("MCP_ENABLED") or "on").strip().lower() != "off"


# ─── JSON-RPC 2.0 ────────────────────────────────────────────────────
# Error codes: the three below -32000 are ours (the spec reserves
# -32000..-32099 for implementation-defined server errors).
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
UNAUTHORIZED = -32001
RATE_LIMITED = -32002
TOOL_FORBIDDEN = -32003


def _result(req_id: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str,
           data: Optional[Dict] = None) -> Dict[str, Any]:
    err: Dict[str, Any] = {"code": code, "message": message}
    if data:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


# ─── Tool schemas ────────────────────────────────────────────────────
# MCP requires machine-readable JSON Schema per tool. Chief's parameter
# documentation is PROSE in the system prompt, so these are written by
# hand — but only for verbs the registry already exposes, and a test
# asserts this dict covers exactly that set. A verb becoming exposable
# without a schema fails CI rather than shipping as a broken tool.
#
# Descriptions are written for a MODEL choosing between tools, not for a
# human reading docs: what it answers, and when to reach for it.

_NO_ARGS: Dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}


def _obj(props: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
    schema: Dict[str, Any] = {
        "type": "object", "properties": props, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


TOOL_SCHEMAS: Dict[str, Tuple[str, Dict[str, Any]]] = {
    "catch_up": (
        "What has happened in this business recently — new activity, drafts "
        "waiting, anything that moved since last time. Start here when you "
        "need orientation rather than one specific number.",
        _NO_ARGS),
    "check_goals": (
        "Progress against every active goal, computed from live data.",
        _NO_ARGS),
    "contact_deep_dive": (
        "Everything on file for ONE person: history, sessions, invoices, "
        "notes. Requires the contact's id.",
        _obj({"contact_id": {"type": "string",
                             "description": "The contact's uuid."}},
             ["contact_id"])),
    "list_availability": (
        "The booking availability configuration — weekly hours, overrides, "
        "lead time, slot size.",
        _NO_ARGS),
    "list_module_entries": (
        "Rows of one custom module. Modules are the practitioner's own data "
        "structures; name the module by slug or id.",
        _obj({"module": {"type": "string",
                         "description": "Module slug or uuid."},
              "limit": {"type": "integer", "minimum": 1, "maximum": 100,
                        "description": "Max rows to return. Default 20."}},
             ["module"])),
    "list_offerings": (
        "The services or packages this business sells, with prices.",
        _NO_ARGS),
    "list_products": (
        "Physical or digital products in the catalogue, with prices.",
        _NO_ARGS),
    "list_projects": (
        "Active projects and their status.",
        _NO_ARGS),
    "list_scheduled": (
        "Actions Chief has queued to run later, with their run times.",
        _NO_ARGS),
    "offering_readiness": (
        "Per-offering readiness report: which offerings are actually "
        "sellable and what is blocking the ones that are not.",
        _NO_ARGS),
    "recall_conversation": (
        "Search earlier conversation with Chief by meaning, not keyword.",
        _obj({"query": {"type": "string",
                        "description": "What to look for."}},
             ["query"])),
    "show_revenue": (
        "Revenue figures for this business.",
        _NO_ARGS),
    "site_health": (
        "Whether the public website and booking page are live and wired "
        "up, and what is broken if not.",
        _NO_ARGS),
    "list_bookkeeping_proposals": (
        "Bookkeeping changes Chief has proposed and is waiting on. Read-only: "
        "approving one is a class-C action and is not available here.",
        _NO_ARGS),
    "propose_brand_kit_from_context": (
        "Generate a brand-kit proposal from everything known about the "
        "business. Returns the proposal and saves NOTHING. Costs model "
        "tokens, so do not call it speculatively.",
        _NO_ARGS),
    "propose_voice_rule": (
        "Suggest a writing-voice rule from observed edits. Returns the "
        "suggestion and stores nothing.",
        _NO_ARGS),
}


def exposed_tools() -> List[str]:
    """The verb list, DERIVED. `may_expose_to_agent` is the authorization
    decision; this module only asks it."""
    return sorted(v for v in action_registry.REGISTRY
                  if action_registry.may_expose_to_agent(v))


def tool_definitions() -> List[Dict[str, Any]]:
    """MCP tool descriptors. A verb the registry exposes but that has no
    schema here is OMITTED rather than guessed at — better a missing tool
    than one whose arguments we invented. The test suite makes that state
    loud so it cannot persist unnoticed."""
    out: List[Dict[str, Any]] = []
    for verb in exposed_tools():
        entry = TOOL_SCHEMAS.get(verb)
        if not entry:
            logger.error(
                "verb %r is agent-exposable but has no inputSchema — omitted "
                "from the tool list. Add one to TOOL_SCHEMAS.", verb)
            continue
        description, schema = entry
        out.append({"name": verb, "description": description,
                    "inputSchema": schema})
    return out


# ─── Audit ───────────────────────────────────────────────────────────

def _audit(*, actor: str, tool: str, ok: bool, duration_ms: int,
           business_id: Optional[str] = None, error: Optional[str] = None,
           arg_keys: Optional[List[str]] = None, allowed: bool = True,
           actor_user_id: Optional[str] = None) -> None:
    """Record one MCP call — to the log AND to `agent_runs`.

    Argument NAMES are recorded, never values. An argument can carry a
    customer's name, an email, a search phrase; an audit trail that
    records values becomes a second copy of the data it audits, held
    longer, under weaker scrutiny, and outside every deletion path.

    `allowed` and `ok` are different questions and both are kept. A
    refused call is not an error — it is this table doing its job, and
    the refusals are the rows worth reading.

    Never fatal. An audit write that could take down the surface it
    audits would be a worse bug than the one it is guarding against; the
    log line above always lands, so a DB failure loses the row, not the
    record.
    """
    logger.info(
        "[audit] actor=%s tool=%s allowed=%s ok=%s biz=%s dur=%dms args=%s%s",
        actor, tool, allowed, ok, business_id or "-", duration_ms,
        ",".join(arg_keys or []) or "-",
        f" error={error}" if error else "")
    try:
        import sb_clients
        sb_clients.sb_post_as_service("/agent_runs", {
            "business_id": business_id,
            "surface": "mcp",
            "tool": tool[:200],
            "actor_user_id": actor_user_id,
            "actor_email": actor,
            "allowed": bool(allowed),
            "ok": bool(ok),
            "duration_ms": int(duration_ms),
            # A reason, not a traceback. Exception text in this service
            # routinely carries table names, ids and query fragments.
            "error": (error or None) and str(error)[:300],
            "arg_keys": sorted(arg_keys or []),
        }, prefer="return=minimal")
    except Exception as e:
        logger.warning("[audit] agent_runs write failed (non-fatal): %s", e)


# ─── Tenancy ─────────────────────────────────────────────────────────

async def _resolve_business(client: httpx.AsyncClient,
                            user: AuthedUser) -> Optional[Dict[str, Any]]:
    """THE business for this caller. Singular on purpose.

    Build 3 replaces this with a scoped token whose claims name one
    business. Until then the owner's own business is resolved from their
    verified JWT — same guarantee, narrower source: the caller never names
    a business, so a cross-business request is not blocked, it is
    unrepresentable.
    """
    import sb_clients
    rows = await client.get(
        f"{sb_clients.sb_url()}/rest/v1/businesses",
        headers=sb_clients.sb_headers_service(),
        params={"owner_id": f"eq.{user.id}", "select": "*",
                "order": "created_at.asc", "limit": "1"})
    if rows.status_code >= 400:
        return None
    data = rows.json() or []
    return data[0] if data else None


# ─── Dispatch ────────────────────────────────────────────────────────

async def _call_tool(name: str, arguments: Dict[str, Any],
                     user: AuthedUser) -> Tuple[bool, bool, Any, Optional[str]]:
    """Run one exposed verb.

    Returns (allowed, ok, payload, business_id). `allowed` and `ok` are
    separate on purpose: "we refused this" and "we tried and it failed"
    are different events, and conflating them in the audit trail loses
    exactly the distinction a reader cares about.
    """
    # Authorization, from the registry. Not a list kept here.
    if not action_registry.may_expose_to_agent(name):
        # Covers unknown verbs, ui verbs, every write, and anything
        # unclassified — all of which the registry answers False for.
        # Note the deliberate absence of a remapper: an unknown tool is an
        # error, never a reinterpretation.
        return False, False, f"tool {name!r} is not available on this surface", None

    handler = None
    try:
        import chief_of_staff
        handler = chief_of_staff.ACTION_HANDLERS.get(name)
    except Exception as e:
        logger.warning("handler lookup failed for %s: %s", name, e)
    if handler is None:
        # The registry says exposable but Chief has no handler: a drift the
        # test suite is supposed to catch before it ships.
        return False, False, f"tool {name!r} has no handler", None

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        biz = await _resolve_business(client, user)
        if not biz:
            return True, False, "no business resolved for this account", None
        action = dict(arguments or {})
        action["type"] = name
        result = await handler(client, biz, action)
    return True, True, result, str(biz.get("id") or "") or None


# ─── JSON-RPC methods ────────────────────────────────────────────────

async def _handle_rpc(message: Dict[str, Any], user: AuthedUser,
                      actor: str) -> Optional[Dict[str, Any]]:
    """One JSON-RPC message. Returns the response, or None for a
    notification (which by spec gets no reply)."""
    req_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}
    is_notification = "id" not in message

    if method == "initialize":
        return _result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": (
                "Read-only view of one Solutionist business. Every tool here "
                "reads; nothing writes, sends, or spends money. If you need an "
                "action taken, tell the practitioner — you cannot do it here."),
        })

    if method in ("notifications/initialized", "initialized"):
        return None  # notification — no reply

    if method == "ping":
        return _result(req_id, {})

    if method == "tools/list":
        return _result(req_id, {"tools": tool_definitions()})

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str) or not name:
            return _error(req_id, INVALID_PARAMS, "tools/call requires a tool name")
        if not isinstance(arguments, dict):
            return _error(req_id, INVALID_PARAMS, "arguments must be an object")

        started = int(time.time() * 1000)
        try:
            allowed, ok, payload, biz_id = await _call_tool(name, arguments, user)
        except Exception as e:
            logger.warning("tool %s raised: %s", name, e)
            _audit(actor=actor, actor_user_id=getattr(user, "id", None),
                   tool=name, allowed=True, ok=False,
                   duration_ms=int(time.time() * 1000) - started,
                   error=type(e).__name__, arg_keys=sorted(arguments))
            # The exception text is NOT returned. It can carry table names,
            # ids and query fragments, and this is an untrusted caller.
            return _error(req_id, INTERNAL_ERROR, "tool execution failed")

        _audit(actor=actor, actor_user_id=getattr(user, "id", None),
               tool=name, allowed=allowed, ok=ok, business_id=biz_id,
               duration_ms=int(time.time() * 1000) - started,
               error=None if ok else str(payload)[:200],
               arg_keys=sorted(arguments))

        if not ok:
            return _error(req_id,
                          TOOL_FORBIDDEN if not allowed else INTERNAL_ERROR,
                          str(payload))
        # MCP returns tool output as content blocks. Chief handlers return
        # a dict with result + label; both are useful to a reading agent,
        # so the whole payload is serialised rather than flattened to prose.
        return _result(req_id, {
            "content": [{"type": "text",
                         "text": json.dumps(payload, default=str)}],
            "isError": False,
        })

    if is_notification:
        return None
    return _error(req_id, METHOD_NOT_FOUND, f"unknown method {method!r}")


# ─── Transport ───────────────────────────────────────────────────────

@router.post("")
@router.post("/")
async def mcp_endpoint(request: Request,
                       user: AuthedUser = Depends(require_user)):
    """Streamable HTTP endpoint. JSON-RPC 2.0 in, JSON out.

    Auth in Build 1 is the owner's own Supabase JWT — the surface is
    explicitly single-tenant, so the narrowest credential that already
    exists is the right one. Build 3 adds scoped tokens; this dependency
    is the seam that swaps.
    """
    if not enabled():
        return JSONResponse(status_code=503, content=_error(
            None, INTERNAL_ERROR, "MCP surface is disabled"))

    actor = (user.email or user.id or "unknown").lower()
    # The two refusals below happen BEFORE any tool is named, so they used
    # to leave no trace at all. They are also the two most worth having:
    # an authenticated non-owner reaching this endpoint, and a caller
    # hitting the limiter, are the shapes an attempt looks like.
    if actor != PLATFORM_OWNER_EMAIL:
        # 403 rather than 401: the caller IS authenticated, just not
        # permitted. Stage 1 is owner-only by design.
        logger.warning("[mcp] refused non-owner caller %s", actor)
        _audit(actor=actor, actor_user_id=getattr(user, "id", None),
               tool="(endpoint)", allowed=False, ok=False, duration_ms=0,
               error="non-owner caller")
        return JSONResponse(status_code=403, content=_error(
            None, UNAUTHORIZED, "this surface is restricted to the platform owner"))

    # Fail CLOSED. Every other bucket in this service fails open, which is
    # right for a practitioner and wrong for an agent that may be looping
    # or holding a stolen credential.
    if not rate_limit.allow_strict("mcp", actor):
        _audit(actor=actor, actor_user_id=getattr(user, "id", None),
               tool="(endpoint)", allowed=False, ok=False, duration_ms=0,
               error="rate limited")
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(rate_limit.retry_after("mcp"))},
            content=_error(None, RATE_LIMITED, "rate limit exceeded"))

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content=_error(
            None, PARSE_ERROR, "invalid JSON"))

    # A batch is a JSON array; a single call is an object. Both are valid
    # JSON-RPC 2.0 and clients use both.
    if isinstance(body, list):
        if not body:
            return JSONResponse(status_code=400, content=_error(
                None, INVALID_REQUEST, "empty batch"))
        responses = []
        for msg in body:
            if not isinstance(msg, dict):
                responses.append(_error(None, INVALID_REQUEST, "malformed message"))
                continue
            r = await _handle_rpc(msg, user, actor)
            if r is not None:
                responses.append(r)
        # An all-notification batch gets 202 and no body, per spec.
        if not responses:
            return JSONResponse(status_code=202, content=None)
        return JSONResponse(content=responses)

    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content=_error(
            None, INVALID_REQUEST, "expected an object or array"))

    response = await _handle_rpc(body, user, actor)
    if response is None:
        return JSONResponse(status_code=202, content=None)
    return JSONResponse(content=response)


@router.get("/health")
async def mcp_health():
    """Unauthenticated liveness + shape check. Deliberately says what is
    EXPOSED and nothing about the business — it is a public endpoint."""
    return {
        "enabled": enabled(),
        "protocolVersion": PROTOCOL_VERSION,
        "server": {"name": SERVER_NAME, "version": SERVER_VERSION},
        "tools": len(tool_definitions()),
    }
