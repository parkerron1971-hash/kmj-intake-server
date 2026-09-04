"""
mcp_server.py — the agent-facing surface. Stage 4: every practitioner's
business is reachable by the agent they already use, and a granted scope
lets that agent act.

An MCP (Model Context Protocol) endpoint exposing a slice of Chief's verbs
to an external client — Claude.ai, ChatGPT, Claude Desktop, a self-hosted
agent. Reads are the default posture. Reversible writes (the registry's
class A) are reachable only by a token minted with the `write` scope; class
C is unreachable at any scope, which is the whole point of having a
registry rather than a list.

Stage 1 (2026-07-28) was read-only and owner-only: one tenant, us, as free
tuition. Stage 4 (2026-09-03) opens the door the July strategy reserved —
docs/future_architecture.md §3, "when the assistant wars settle, Solutionist
wins regardless of which assistant won, because they all operate the
practitioner's business through us". The day a general computer-using
agent shipped to every paid ChatGPT tier was the review trigger that doc
named for itself. This is the response.

Strategy: solutionist-studio/docs/PERSONAL_AGENT_ARCHITECTURE.md §4 (open on
read, closed on write), §7 (trust/egress), §10 Stage 4. Gateway shape:
docs/extensibility_and_autonomy.md §2.3. Permission model:
docs/future_architecture.md §3 — the Trust Track, not a parallel invention.

═══════════════════════════════════════════════════════════════════════
WHAT A WRITE SCOPE CAN AND CANNOT REACH
═══════════════════════════════════════════════════════════════════════
Two gates, both required, neither hand-maintained as a list of verbs:

  action_registry.may_expose_to_agent(verb, allow_writes=True)
      the CEILING. Class A only, never sensitive, never unclassified.
      Bulk verbs are refused here too — forty rows is not one undo.
  WRITE_TOOL_SCHEMAS
      the FLOOR. A class A verb is offered only once somebody has read
      its handler and written the schema an outside model will fill in.
      A verb missing from here is not a tool, whatever the registry says.

The registry can only ever narrow what this dict offers; the dict can only
ever narrow what the registry allows. Drift in the dangerous direction —
something exposed that should not be — needs both to be wrong at once.

policy_engine.evaluate() runs on every call with prompted=False, because
nobody is sitting in front of an MCP call: a token is. So a practitioner
who paused their automations pauses their agent too, and a regulated
practice's client-facing switch is honoured — the same rules the scheduler
and the autopilot sweep answer to.

Every successful write is recorded in chief_undo_log exactly as a chat
action is, so `undo_last` (itself on this surface) can take it back, and
the practitioner's own "what would undo do?" sees the agent's work.

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

The `ui` verbs are excluded (an off-app caller has no UI to drive) and the
class-C verbs can never appear at any scope.

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
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple, Union

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import action_registry
import rate_limit
from mcp_tokens import SCOPE_READ, SCOPE_WRITE
from auth_supabase import AuthedUser, optional_user, require_user

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
# Was "solutionist-admin" while the surface was one tenant's. It is every
# practitioner's now, and the name a connector shows is the name they see.
SERVER_NAME = "solutionist"
SERVER_VERSION = "0.2.0"

HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=45.0, write=15.0, pool=10.0)

PLATFORM_OWNER_EMAIL = os.environ.get(
    "PLATFORM_OWNER_EMAIL", "kmjcreativesolution@gmail.com").lower()


def enabled() -> bool:
    return (os.environ.get("MCP_ENABLED") or "on").strip().lower() != "off"


class Caller:
    """Who is on the other end, normalised across both credential kinds.

    A scoped token carries its business in a signed claim. An owner JWT
    does not, and resolves to the owner's own business instead. Everything
    downstream reads this object rather than branching on which kind
    arrived — the branch happens once, at the door.
    """

    __slots__ = ("kind", "actor", "user_id", "business_id", "scopes", "jti")

    def __init__(self, kind: str, actor: str, *, user_id: Optional[str] = None,
                 business_id: Optional[str] = None,
                 scopes: Optional[List[str]] = None,
                 jti: Optional[str] = None):
        self.kind = kind                  # 'token' | 'owner_jwt'
        self.actor = actor
        self.user_id = user_id
        self.business_id = business_id    # set ONLY by a signed claim
        self.scopes = scopes or []
        self.jti = jti

    @property
    def may_write(self) -> bool:
        """Only a scoped token can carry `write`. A browser session is a
        person, and a person acts through Chief, where the action gets
        the prompted path and the practitioner's own confirmation UX —
        not through a JSON-RPC endpoint built for their agent."""
        return self.kind == "token" and SCOPE_WRITE in self.scopes


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
    # Deliberately exposed. This is strictly LESS revealing than
    # contact_deep_dive, which already ships the same person's full history,
    # sessions, invoices and notes — a prepaid balance is a subset of that.
    # "How many sessions does Marcus have left" is also one of the questions
    # an outside agent is most usefully asked.
    # Exposed: this reports what the LAST change was, which is app-state
    # metadata of the same class as list_scheduled and catch_up — both
    # already on the surface. Note undo_last itself is a WRITE and stays off.
    "what_undo": (
        "What the most recent reversible action was, and what undoing it "
        "would do. Reports only — it does not undo anything.",
        _NO_ARGS),
    "check_balance": (
        "What ONE person has prepaid and not yet used — package sessions, "
        "retainer hours or money, a deposit, or gift-card value. Requires "
        "the contact's id.",
        _obj({"contact_id": {"type": "string",
                             "description": "The contact's uuid."}},
             ["contact_id"])),
    # Exposed on the same reasoning as show_revenue, which already ships
    # business financials: this is work done and not yet charged. Contact
    # id is OPTIONAL here — firm-wide "what am I owed" is the more common
    # question than any single client's.
    "unbilled_time": (
        "Hours worked and not yet billed — for the whole business, or for "
        "one person if you pass a contact id. Returns entry count, total "
        "hours, and the amount where rates are set.",
        _obj({"contact_id": {"type": "string",
                             "description": "Optional. Narrow to one "
                                            "contact's unbilled time."}})),
    "contact_deep_dive": (
        "Everything on file for ONE person as one dated timeline: bookings, "
        "forms, invoices and payments, contracts, email and SMS, notes, "
        "time, balances, records — plus a summary (last touch, next "
        "booking, open invoices, unbilled time). Requires the contact's id.",
        _obj({"contact_id": {"type": "string",
                             "description": "The contact's uuid."}},
             ["contact_id"])),
    "list_availability": (
        "The booking availability configuration — weekly hours, overrides, "
        "lead time, slot size.",
        _NO_ARGS),
    "inspect_module": (
        "Health check on the practitioner's custom modules: does each one "
        "actually display, and will its automations fire? Names the specific "
        "problems. Omit both arguments to check every module.",
        _obj({"module_id": {"type": "string",
                            "description": "Module uuid. Optional."},
              "slug": {"type": "string",
                       "description": "Module slug. Optional."}},
             [])),
    "summarize_module": (
        "Counts and totals the rows of one custom module — how many in each "
        "state, and the money total if it has an amount field. Use for "
        "'how many', 'what am I owed', 'what did I do last month'.",
        _obj({"module": {"type": "string",
                         "description": "Module slug or uuid."},
              "group_by": {"type": "string",
                           "description": "A choice field to break the counts down by. "
                                          "Defaults to the module's first choice field."},
              "sum": {"type": "string",
                      "description": "A money or number field to total. Defaults to the "
                                     "module's first money field."},
              "since": {"type": "string", "description": "YYYY-MM-DD, inclusive."},
              "until": {"type": "string", "description": "YYYY-MM-DD, inclusive."}},
             ["module"])),
    "list_module_entries": (
        "Rows of one custom module. Modules are the practitioner's own data "
        "structures; name the module by slug or id.",
        _obj({"module": {"type": "string",
                         "description": "Module slug or uuid."},
              "limit": {"type": "integer", "minimum": 1, "maximum": 100,
                        "description": "Max rows to return. Default 20."}},
             ["module"])),
    "list_client_forms": (
        "The public forms a new client fills in on this business's site or "
        "links, with how many submissions each has actually taken. Answers "
        "\"is my intake form working?\" — a form with zero submissions is "
        "either unembedded or asking the wrong thing.",
        _obj({"include_inactive": {
            "type": "boolean",
            "description": "Include forms that have been switched off. "
                           "Default false."}})),
    "sms_status": (
        "Whether texting is actually working for this business: the keyword "
        "clients text to reach it, whether the provider is switched on, "
        "whether the automated booking confirmations and appointment "
        "reminders are on, and how many contacts have replied STOP. No "
        "message contents.",
        _NO_ARGS),
    "email_setup_status": (
        "Whether email is actually set up for this business: what address it "
        "sends from (its own verified domain or the platform address), whether "
        "the domain is waiting on DNS or has stopped verifying, whether a Gmail "
        "or Google Workspace inbox is connected and still syncing, whether a "
        "test email has landed, and the next setup step. Configuration and "
        "counts only - never a message body.",
        _NO_ARGS),
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
    # Deliberately exposed (tripwire bump 24 -> 25, 8/14). show_view is a
    # bounded read over tables whose data is ALREADY on this surface —
    # invoices are the same financial class as list_expenses /
    # unbilled_time / show_revenue, contacts are already readable through
    # contact_deep_dive, sessions through list_scheduled, products
    # through list_products. It returns typed rows for display; the nav /
    # frontend_event fields it carries are meaningless off the app
    # surface and inert in an agent's hands. Filters are advisory: an
    # unknown filter falls back to the view's default server-side.
    # Deliberately exposed (tripwire bump 25 -> 26, 8/15). mission_status
    # is operational plan state — the same class as list_scheduled and
    # campaign_status, both already here. Reads per-step status only;
    # starting/advancing/abandoning are writes and stay OFF this surface.
    "mission_status": (
        "Chief's open multi-step missions and their per-step progress. "
        "Read-only; a mission waiting on approval can only be advanced by "
        "the practitioner in the app.",
        _NO_ARGS),
    "show_view": (
        "A bounded list (max 25 rows) of one view of this business's "
        "records, as typed columns and rows. Read-only.",
        _obj({"view": {"type": "string",
                       "enum": ["invoices", "contacts", "sessions", "products"],
                       "description": "Which list to fetch."},
              "filter": {"type": "string",
                         "description": "Optional. invoices: open|overdue|"
                                        "draft|paid|all. contacts: all|leads|"
                                        "active. sessions: upcoming|all."}},
             ["view"])),
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
    # Deliberately exposed (tripwire bump 19 → 21). campaign_status is
    # operational marketing state — the same class as list_scheduled and
    # site_health, both already here; audience members are counted, never
    # named. list_expenses is business financials of the same class as
    # show_revenue and unbilled_time, both already here. Launching,
    # pausing, logging and deleting stay writes and stay OFF this surface.
    "campaign_status": (
        "Marketing campaigns and their honest send progress — drafts, "
        "running, paused, completed, with sends/replies/bookings counts. "
        "Pass a name for one campaign's full results.",
        _obj({"name": {"type": "string",
                       "description": "Optional. A campaign name (partial "
                                      "match) for detailed results."}})),
    "list_expenses": (
        "Recent manually-logged business expenses with a total. Optional "
        "month (YYYY-MM) and category (tax | owner_pay | operating | "
        "savings | other) filters.",
        _obj({"month": {"type": "string",
                        "description": "Optional. YYYY-MM month filter."},
              "category": {"type": "string",
                           "description": "Optional. One of the five "
                                          "expense buckets."}})),
    # Deliberately exposed (tripwire bump 21 → 22). check_inventory is
    # operational store state — stock counts and low-stock flags for the
    # business's own products, the same class as list_offerings and
    # list_products, both already here. No customer data, no money
    # figures. adjust_stock stays a write (class C) and stays OFF this
    # surface.
    "check_inventory": (
        "Stock levels for the store's products: tracked quantities, "
        "low-stock and out-of-stock lists. Read-only — adjusting stock "
        "is not available here.",
        _NO_ARGS),
    # Deliberately exposed (tripwire bump 26 → 27). draft_purchase_order
    # COMPOSES a reorder email preview and writes nothing — the supplier
    # name/email it reveals is the business's own reorder plan, the same
    # operational class as check_inventory's stock counts. SENDING the PO
    # (send_purchase_order, class C, client-facing) stays OFF this
    # surface: an outside agent may see what would go out, never send it.
    "draft_purchase_order": (
        "Preview the purchase-order email Chief would send to a "
        "product's supplier (quantity defaults to the product's reorder "
        "plan). Pure preview — nothing is sent, and sending is not "
        "available here; the practitioner approves sends in the app.",
        _obj({"offering_id": {"type": "string",
                              "description": "The offering (product) id."},
              "name": {"type": "string",
                       "description": "Product name, if the id is unknown."},
              "qty": {"type": "integer",
                      "description": "Optional. Override the plan's "
                                     "reorder quantity."}})),
}


# ─── Write tools ─────────────────────────────────────────────────────
#
# The verbs a `write`-scoped token may call, each with the schema an
# outside model fills in. Every entry was written against its handler's
# source on 2026-09-03 — the argument names below are the ones the handler
# reads, the enums are the ones it validates, and a description says what
# the practitioner will find changed.
#
# WHAT IS DELIBERATELY NOT HERE, and why, so the next reader does not add
# it by accident:
#
#   Anything that spends model tokens on the practitioner's account from
#   an outside caller — draft_nurture, rewrite_draft, run_agent,
#   analyze_trends, run_market_research, propose_module_from_intake,
#   plan_campaign, generate_document. An agent that can burn the metered
#   allotment in a loop is a billing incident. draft_email is here ONLY
#   because the body is required (the handler drafts with the model when
#   the body is short, and the schema forbids a short one).
#
#   cancel_booking and reschedule_booking. Class A, and the registry
#   itself flags that a silently-cancelled client appointment is a
#   product question. That question is answered in the app, not here.
#
#   edit_draft. Its registry entry was corrected to say it APPROVES AND
#   SENDS. save_draft, which does not, is the one a future entry gets.
#
#   Site, voice, brand, workspace and strategy-track writes. Reversible,
#   but they shape what the public and Chief itself say; a practitioner
#   changes those looking at the result, in the app.
#
# Descriptions are written for a MODEL choosing between tools. Each names
# what changes and what does NOT happen (no email, nothing sent), because
# the model's user will ask exactly that.

_CONTACT_ID = {"type": "string", "description": "The contact's uuid."}
_DATE = {"type": "string",
         "description": "YYYY-MM-DD.", "pattern": r"^\d{4}-\d{2}-\d{2}$"}
_WHEN = {"type": "string",
         "description": "ISO 8601 date-time, UTC (e.g. 2026-09-10T14:00:00Z). "
                        "A bare YYYY-MM-DD means 09:00 UTC that day."}
_HOURS = {"type": "array",
          "description": "Open intervals for that date. An EMPTY list means "
                         "closed all day.",
          "items": {"type": "object", "additionalProperties": False,
                    "required": ["start", "end"],
                    "properties": {"start": {"type": "string",
                                             "description": "HH:MM, 24-hour"},
                                   "end": {"type": "string",
                                           "description": "HH:MM, 24-hour"}}}}

WRITE_TOOL_SCHEMAS: Dict[str, Tuple[str, Dict[str, Any]]] = {
    # ── people ───────────────────────────────────────────────────────
    "create_contact": (
        "Add a person to this business's contacts. Nothing is sent to "
        "them. Returns the new contact_id.",
        _obj({"name": {"type": "string"},
              "email": {"type": "string"},
              "phone": {"type": "string"},
              "role": {"type": "string",
                       "description": "Their role or relationship, free text."},
              "status": {"type": "string",
                         "enum": ["lead", "active", "vip", "inactive", "churned"],
                         "description": "Default lead."},
              "tags": {"type": "array", "items": {"type": "string"}}},
             ["name"])),
    "update_contact": (
        "Change fields on ONE existing contact. Pass contact_id when you "
        "have it; otherwise contact_name finds a unique match and fails if "
        "several match. Only the fields you pass change.",
        _obj({"contact_id": _CONTACT_ID,
              "contact_name": {"type": "string",
                               "description": "Lookup by name when no id."},
              "name": {"type": "string", "description": "A NEW name for them."},
              "email": {"type": "string"},
              "phone": {"type": "string"},
              "role": {"type": "string"},
              "notes": {"type": "string"},
              "status": {"type": "string",
                         "enum": ["lead", "active", "vip", "inactive", "churned"]},
              "tags": {"type": "array", "items": {"type": "string"}}})),
    "update_contact_status": (
        "Move one contact to a new status. Records the change on their "
        "timeline.",
        _obj({"contact_id": _CONTACT_ID,
              "new_status": {"type": "string",
                             "enum": ["lead", "active", "vip", "inactive", "churned"]}},
             ["contact_id", "new_status"])),
    "create_note": (
        "Attach a note to one contact's record. Private to the "
        "practitioner; the contact never sees it.",
        _obj({"contact_id": _CONTACT_ID,
              "note": {"type": "string"}},
             ["contact_id", "note"])),
    "log_activity": (
        "Record that an interaction with a contact happened — a call, a "
        "text, a meeting. Updates their last-contact date. Sends nothing.",
        _obj({"contact_id": _CONTACT_ID,
              "activity_type": {"type": "string",
                                "enum": ["call", "text", "meeting", "email", "other"]},
              "notes": {"type": "string", "description": "What happened."},
              "occurred_at": {**_DATE, "description": "YYYY-MM-DD. Default today."}},
             ["contact_id", "activity_type"])),

    # ── work ─────────────────────────────────────────────────────────
    "create_task": (
        "Add a to-do for the practitioner. Returns task_id.",
        _obj({"title": {"type": "string"},
              "description": {"type": "string"},
              "due_date": _DATE,
              "priority": {"type": "string",
                           "enum": ["urgent", "high", "medium", "low"],
                           "description": "Default medium."},
              "contact_id": {**_CONTACT_ID,
                             "description": "Optional. Link the task to a contact."}},
             ["title"])),
    "complete_task": (
        "Mark a task done. Pass task_id, or a title fragment that matches "
        "one open task.",
        _obj({"task_id": {"type": "string"},
              "title": {"type": "string",
                        "description": "Fragment of the task's title, when no id."}})),
    "create_project": (
        "Open a project, optionally for a client. Returns project_id.",
        _obj({"title": {"type": "string"},
              "description": {"type": "string"},
              "contact_name": {"type": "string",
                               "description": "The client, by name. Optional."},
              "status": {"type": "string",
                         "enum": ["planning", "active", "on_hold", "completed", "cancelled"],
                         "description": "Default planning."},
              "value": {"type": "number", "description": "Expected value, in the "
                                                          "business's currency."},
              "start_date": _DATE,
              "target_date": _DATE},
             ["title"])),
    "log_time": (
        "Record work done for a client — hours worked, not yet billed. "
        "Charges nobody; the practitioner invoices it later in the app.",
        _obj({"contact_id": _CONTACT_ID,
              "hours": {"type": "number", "description": "e.g. 1.5"},
              "description": {"type": "string",
                              "description": "What the work was. Required — "
                                             "a bill line needs a narrative."},
              "matter": {"type": "string",
                         "description": "Optional matter or engagement name."},
              "billable": {"type": "boolean", "description": "Default true."},
              "rate": {"type": "number",
                       "description": "Optional hourly rate; otherwise the "
                                      "client's or offering's rate applies."},
              "date": {**_DATE, "description": "YYYY-MM-DD. Default today."}},
             ["contact_id", "hours", "description"])),
    "log_expense": (
        "Record a business expense already paid — bookkeeping about money, "
        "not movement of it. Flows to the P&L. Refuses dates in a closed "
        "accounting period.",
        _obj({"amount": {"type": "number", "exclusiveMinimum": 0},
              "category": {"type": "string",
                           "enum": ["operating", "tax", "owner_pay", "savings", "other"],
                           "description": "Default operating (day-to-day costs)."},
              "vendor": {"type": "string"},
              "note": {"type": "string", "description": "What it was for."},
              "date": {**_DATE, "description": "YYYY-MM-DD. Default today."}},
             ["amount"])),

    # ── calendar ─────────────────────────────────────────────────────
    "create_session": (
        "Put a session or appointment on the practitioner's calendar. "
        "Sends NO confirmation to the client — this is the practitioner's "
        "own record. Returns session_id.",
        _obj({"title": {"type": "string"},
              "scheduled_for": _WHEN,
              "duration_minutes": {"type": "integer", "minimum": 5,
                                   "description": "Default 60."},
              "contact_id": {**_CONTACT_ID, "description": "Optional. Who it is with."},
              "contact_name": {"type": "string",
                               "description": "Lookup by name when no id."},
              "session_type": {"type": "string",
                               "description": "e.g. consultation, coaching_session, "
                                              "discovery_call, follow_up, meeting."},
              "notes": {"type": "string"}},
             ["scheduled_for"])),
    "update_session": (
        "Change one session: move it, mark it completed or a no-show, add "
        "notes. Pass session_id, or contact_name to mean that person's "
        "most recent session. Sends nothing to the client.",
        _obj({"session_id": {"type": "string"},
              "contact_name": {"type": "string"},
              "scheduled_for": _WHEN,
              "status": {"type": "string",
                         "enum": ["scheduled", "in_progress", "completed",
                                  "no_show", "cancelled"]},
              "duration_minutes": {"type": "integer", "minimum": 5},
              "title": {"type": "string"},
              "notes": {"type": "string"}})),
    "set_availability_override": (
        "Make ONE date an exception to the weekly booking hours — closed, "
        "or open only at these times. Replaces any existing override for "
        "that date.",
        _obj({"date": _DATE, "hours": _HOURS}, ["date"])),
    "add_block_range": (
        "Block a run of dates from online booking (vacation, a holiday "
        "week). Inclusive of both ends. remove_block_range undoes it.",
        _obj({"start": _DATE,
              "end": {**_DATE, "description": "YYYY-MM-DD. Default same as start."},
              "reason": {"type": "string"}},
             ["start"])),
    "remove_block_range": (
        "Remove a booking block, identified by its start date.",
        _obj({"start": _DATE}, ["start"])),

    # ── records the practitioner defined ─────────────────────────────
    "create_module_entry": (
        "Add a row to one of the practitioner's own custom modules. Read "
        "the module first (list_module_entries) to learn its fields. "
        "Refused for access-restricted modules.",
        _obj({"module_id": {"type": "string", "description": "The module's uuid."},
              "data": {"type": "object",
                       "description": "Field values, keyed by the module's "
                                      "field names.",
                       "additionalProperties": True}},
             ["module_id", "data"])),
    "update_module_entry": (
        "Patch fields on one custom-module row. Fields you do not pass are "
        "kept.",
        _obj({"entry_id": {"type": "string"},
              "data": {"type": "object", "additionalProperties": True,
                       "description": "Only the fields to change."}},
             ["entry_id", "data"])),
    "delete_module_entry": (
        "Remove one custom-module row. A soft delete — the row is hidden, "
        "not destroyed.",
        _obj({"entry_id": {"type": "string"}}, ["entry_id"])),

    # ── offerings ────────────────────────────────────────────────────
    "create_offering": (
        "Add a service, session type, package, course or product the "
        "business sells. Products and packages with a price appear in the "
        "hosted store. Refuses a duplicate name.",
        _obj({"name": {"type": "string"},
              "category": {"type": "string",
                           "enum": ["service", "session", "event", "package",
                                    "course", "product"],
                           "description": "Default service."},
              "current_price": {"type": "number"},
              "duration_min": {"type": "integer", "minimum": 1,
                               "description": "For bookable services."},
              "description": {"type": "string"},
              "show_price_to_customer": {"type": "boolean"}},
             ["name"])),
    "update_offering": (
        "Change price, duration, description or visibility of one "
        "offering, by offering_id or by its exact name.",
        _obj({"offering_id": {"type": "string"},
              "name": {"type": "string",
                       "description": "The offering's current name, when no id."},
              "current_price": {"type": "number"},
              "duration_min": {"type": "integer", "minimum": 1},
              "description": {"type": "string"},
              "show_price_to_customer": {"type": "boolean"}})),

    # ── drafts, memory, notes, content ───────────────────────────────
    "draft_email": (
        "Queue an email DRAFT for the practitioner to approve. Nothing is "
        "sent by this tool — they review it in the app and send or dismiss "
        "it. Write the full body yourself.",
        _obj({"contact_id": {**_CONTACT_ID, "description": "The recipient."},
              "subject": {"type": "string"},
              "body": {"type": "string", "minLength": 21,
                       "description": "The complete email text, in the "
                                      "practitioner's voice."},
              "reason": {"type": "string",
                         "description": "One line on why — shown next to "
                                        "the draft."}},
             ["contact_id", "subject", "body"])),
    "remember": (
        "Store a durable fact about this business or practitioner that "
        "Chief should carry into future conversations. Not for to-dos "
        "(create_task) or notes-to-self (save_note).",
        _obj({"content": {"type": "string"},
              "category": {"type": "string",
                           "enum": ["preference", "pattern", "context", "decision",
                                    "boundary", "goal", "standing_instruction", "other"]},
              "importance": {"type": "integer", "minimum": 1, "maximum": 10,
                             "description": "Default 5."}},
             ["content"])),
    "forget": (
        "Deactivate a stored memory whose content matches this phrase.",
        _obj({"memory_content": {"type": "string",
                                 "description": "A distinctive phrase from the memory."}},
             ["memory_content"])),
    "save_note": (
        "File something on the practitioner's Notes pad for later — an "
        "idea, a question, a quote. Verbatim.",
        _obj({"content": {"type": "string"},
              "kind": {"type": "string",
                       "enum": ["idea", "task", "question", "quote", "note"]}},
             ["content"])),
    "capture_idea": (
        "Drop a content idea into the Idea Inbox. No date, no platform — "
        "just the idea.",
        _obj({"title": {"type": "string"},
              "notes": {"type": "string"},
              "pillar_name": {"type": "string",
                              "description": "Optional content pillar, by name."}},
             ["title"])),
    "plan_content": (
        "Put a post on the content calendar for a date. Publishes "
        "nothing — the practitioner posts it. Same title, platform and "
        "date updates the existing plan instead of duplicating it.",
        _obj({"title": {"type": "string"},
              "platform": {"type": "string",
                           "enum": ["instagram", "linkedin", "twitter", "facebook",
                                    "tiktok", "youtube", "blog", "other"]},
              "scheduled_date": _DATE,
              "body": {"type": "string", "description": "The drafted post, if written."},
              "pillar_name": {"type": "string"}},
             ["title", "platform", "scheduled_date"])),
    "add_faq": (
        "Add or replace one question-and-answer on the business's public "
        "FAQ. Live on the website at once, and Chief uses it when clients "
        "ask.",
        _obj({"question": {"type": "string"},
              "answer": {"type": "string"}},
             ["question", "answer"])),

    # ── the safety net ───────────────────────────────────────────────
    "undo_last": (
        "Reverse the most recent reversible action on this business — "
        "including one this agent just took. Call what_undo first to see "
        "what it would reverse.",
        _NO_ARGS),

    # ── batch 2 (2026-09-04): goals, projects, hours, drafts, balances ─
    # Same rules as the first 28: every argument name below is one the
    # handler reads, every enum is one it validates, and nothing here
    # sends, spends model tokens from outside, reaches a client, or
    # deletes for good. Site copy, voice, brand, workspace and the
    # strategy-track deliverables stay tags on purpose (see the header).
    "create_goal": (
        "Set a goal the practitioner will track — a number to reach by a "
        "date. Auto-tracked from live data for the built-in metrics.",
        _obj({"title": {"type": "string"},
              "category": {"type": "string",
                           "enum": ["contacts", "revenue", "sessions", "engagement",
                                    "marketing", "growth", "learning", "wellness", "custom"],
                           "description": "Default custom."},
              "target": {"type": "number", "exclusiveMinimum": 0},
              "metric": {"type": "string",
                         "enum": ["total_contacts", "new_contacts", "revenue_collected",
                                  "revenue_invoiced", "sessions_completed",
                                  "sessions_scheduled", "engagement_rate", "custom"],
                         "description": "Defaults to the category's usual metric."},
              "period": {"type": "string",
                         "enum": ["weekly", "monthly", "quarterly", "yearly"],
                         "description": "Default quarterly."},
              "start": _DATE, "end": _DATE,
              "description": {"type": "string"}},
             ["title", "target"])),
    "add_reminder": (
        "Attach a dated reminder to an existing goal. Pass goal_id, or "
        "goal_title to match one.",
        _obj({"goal_id": {"type": "string"},
              "goal_title": {"type": "string"},
              "date": _DATE,
              "message": {"type": "string"}},
             ["date"])),
    "update_project": (
        "Change one project's status, dates, description, value or client. "
        "Pass project_id, or title_query to match one project by name.",
        _obj({"project_id": {"type": "string"},
              "title_query": {"type": "string",
                              "description": "Part of the title, when no id."},
              "status": {"type": "string",
                         "enum": ["planning", "active", "on_hold", "completed", "cancelled"]},
              "start_date": _DATE, "target_date": _DATE,
              "description": {"type": "string"},
              "notes": {"type": "string"},
              "value": {"type": "number"},
              "contact_id": _CONTACT_ID,
              "contact_name": {"type": "string"}})),
    "set_availability_day": (
        "Set the weekly booking hours for ONE weekday. An empty hours list "
        "closes that day every week.",
        _obj({"day": {"type": "string",
                      "enum": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
              "hours": _HOURS},
             ["day", "hours"])),
    "set_lead_time": (
        "How far ahead a client must book — nothing inside this many "
        "minutes of now is offered.",
        _obj({"minutes": {"type": "integer", "minimum": 0}}, ["minutes"])),
    "set_slot_granularity": (
        "The booking grid: slots start every N minutes.",
        _obj({"minutes": {"type": "integer", "minimum": 5, "maximum": 240}}, ["minutes"])),
    "set_business_timezone": (
        "The business's timezone, used for hours, slots and reminders.",
        _obj({"timezone": {"type": "string",
                           "description": "IANA name, e.g. America/New_York."}},
             ["timezone"])),
    "add_testimonial": (
        "Add a client's testimonial, stored exactly as given. Shows on "
        "the website unless show_on_website is false.",
        _obj({"quote": {"type": "string"},
              "name": {"type": "string"},
              "role": {"type": "string"},
              "show_on_website": {"type": "boolean", "description": "Default true."}},
             ["quote", "name"])),
    "remove_testimonial": (
        "Remove one testimonial, by id, by the person's name, or by a "
        "fragment of the quote.",
        _obj({"testimonial_id": {"type": "string"},
              "name": {"type": "string"},
              "quote": {"type": "string", "description": "A fragment of the quote."}})),
    "set_business_policy": (
        "Record one policy in the practitioner's words: cancellation, "
        "deposit, lateness, refunds or no-show. Goes on the website FAQ "
        "and Chief answers clients with it.",
        _obj({"policy": {"type": "string",
                         "enum": ["cancellation", "deposit", "lateness", "refunds", "no_show"]},
              "text": {"type": "string"}},
             ["policy", "text"])),
    "save_email_template": (
        "Save or update a reusable email template by name. {name}, "
        "{service}, {date} style placeholders are kept as variables. "
        "Sends nothing.",
        _obj({"name": {"type": "string"},
              "subject": {"type": "string"},
              "body": {"type": "string"},
              "category": {"type": "string",
                           "enum": ["welcome", "follow_up", "reminder", "nurture", "custom"]}},
             ["name"])),
    "mark_reply_read": (
        "Mark an email reply as read — one by reply_id, or every unread "
        "reply from one contact.",
        _obj({"reply_id": {"type": "string"},
              "contact_id": _CONTACT_ID,
              "contact_name": {"type": "string"}})),
    "mark_sms_read": (
        "Mark texts as read — one by sms_id, every unread text from one "
        "contact, or, with no arguments, all unread texts.",
        _obj({"sms_id": {"type": "string"},
              "contact_id": _CONTACT_ID,
              "contact_name": {"type": "string"}})),
    "cancel_scheduled": (
        "Cancel something Chief has queued to run later, by schedule_id "
        "or by matching its label. See list_scheduled.",
        _obj({"schedule_id": {"type": "string"},
              "label": {"type": "string", "description": "Part of the label."}})),
    "dismiss_draft": (
        "Dismiss a queued draft without sending it. The row survives.",
        _obj({"queue_id": {"type": "string"}}, ["queue_id"])),
    "save_draft": (
        "Replace a queued draft's body and LEAVE it a draft — nothing is "
        "approved or sent.",
        _obj({"queue_id": {"type": "string"},
              "new_body": {"type": "string", "minLength": 1}},
             ["queue_id", "new_body"])),
    "archive_offering": (
        "Retire an offering. Soft: past bookings and invoices keep its "
        "name and price. By offering_id or exact name.",
        _obj({"offering_id": {"type": "string"},
              "name": {"type": "string"}})),
    "update_contact_health": (
        "Set a contact's health score, 0 to 100.",
        _obj({"contact_id": _CONTACT_ID,
              "health_score": {"type": "integer", "minimum": 0, "maximum": 100}},
             ["contact_id", "health_score"])),
    "notify_practitioner": (
        "Leave the practitioner an in-app notification (and a push). "
        "Reaches the OWNER only — never a client.",
        _obj({"title": {"type": "string"},
              "body": {"type": "string"}},
             ["title"])),
    "write_off_time": (
        "Mark a logged time entry as never-to-be-billed. The row survives.",
        _obj({"entry_id": {"type": "string"}}, ["entry_id"])),
    "grant_balance": (
        "Record that a client prepaid for something not yet delivered — "
        "package sessions, retainer hours, a deposit. Bookkeeping about "
        "money already received; charges nobody.",
        _obj({"contact_id": _CONTACT_ID,
              "amount": {"type": "number", "exclusiveMinimum": 0},
              "kind": {"type": "string",
                       "description": "What was bought (e.g. package, retainer, "
                                      "deposit). Defaults to the business's usual."},
              "unit": {"type": "string",
                       "description": "sessions, hours or money. Defaults to the "
                                      "business's usual."},
              "reason": {"type": "string"},
              "offering_id": {"type": "string"},
              "expires_at": {**_DATE, "description": "Optional expiry, YYYY-MM-DD."}},
             ["contact_id", "amount"])),
    "consume_balance": (
        "Draw a prepaid balance down — a session delivered, an hour used. "
        "Refuses to overdraw unless allow_overdraw is true.",
        _obj({"contact_id": _CONTACT_ID,
              "amount": {"type": "number", "exclusiveMinimum": 0,
                         "description": "Default 1."},
              "reason": {"type": "string"},
              "session_id": {"type": "string"},
              "allow_overdraw": {"type": "boolean"}},
             ["contact_id"])),
    "bill_time_to_retainer": (
        "Bill one logged time entry against the client's prepaid retainer "
        "hours. Moves prepaid balance; reaches no card and posts no GL "
        "entry.",
        _obj({"contact_id": _CONTACT_ID,
              "entry_id": {"type": "string"}},
             ["contact_id", "entry_id"])),
    "set_sms_alerts": (
        "Turn the automated booking confirmation texts and the 24-hour "
        "reminder texts on or off.",
        _obj({"kinds": {"type": "array",
                        "items": {"type": "string", "enum": ["confirmations", "reminders"]},
                        "description": "Which switches. Default both."},
              "on": {"type": "boolean"}},
             ["on"])),
    "set_sms_keyword": (
        "Claim or change the word a client texts to reach this business.",
        _obj({"keyword": {"type": "string", "minLength": 2}}, ["keyword"])),
    "adjust_template": (
        "Add, remove or reword ONE clause of an agreement template the "
        "business owns. No document is created; existing documents are "
        "untouched.",
        _obj({"template_id": {"type": "string"},
              "operation": {"type": "string", "enum": ["add", "remove", "replace"]},
              "heading": {"type": "string", "description": "The clause heading."},
              "text": {"type": "string", "description": "The clause text, for add/replace."}},
             ["template_id", "operation", "heading"])),
    "reject_bookkeeping_proposal": (
        "Decline one bookkeeping proposal Chief made. Inert — nothing is "
        "posted; the proposal is marked rejected and Chief learns from it.",
        _obj({"proposal_id": {"type": "string"},
              "reason": {"type": "string"}},
             ["proposal_id"])),
}


def exposed_tools(allow_writes: bool = False) -> List[str]:
    """The verb list, DERIVED. `may_expose_to_agent` is the authorization
    decision; this module only asks it.

    With `allow_writes`, the registry's class A verbs join the list — but
    only those with a reviewed schema (see WRITE_TOOL_SCHEMAS), and never
    a bulk verb. The registry is the ceiling; the schema table is the
    floor; both must agree before a write is offered.
    """
    reads = [v for v in action_registry.REGISTRY
             if action_registry.may_expose_to_agent(v)]
    if not allow_writes:
        return sorted(reads)
    writes = [v for v in WRITE_TOOL_SCHEMAS
              if action_registry.may_expose_to_agent(v, allow_writes=True)
              and not action_registry.is_bulk(v)]
    return sorted(set(reads) | set(writes))


def is_write_tool(verb: str) -> bool:
    return action_registry.effect(verb) == action_registry.WRITE


def tool_definitions(caller: Optional["Caller"] = None) -> List[Dict[str, Any]]:
    """MCP tool descriptors for THIS caller. A verb the registry exposes
    but that has no schema here is OMITTED rather than guessed at — better
    a missing tool than one whose arguments we invented. The test suite
    makes that state loud so it cannot persist unnoticed.

    Write tools appear only for a caller whose token carries the `write`
    scope. A read-only client is not shown tools it will be refused —
    a list that advertises what it then denies teaches the model to
    stop trusting the list.
    """
    allow_writes = bool(caller and caller.may_write)
    out: List[Dict[str, Any]] = []
    for verb in exposed_tools(allow_writes=allow_writes):
        entry = TOOL_SCHEMAS.get(verb) or WRITE_TOOL_SCHEMAS.get(verb)
        if not entry:
            logger.error(
                "verb %r is agent-exposable but has no inputSchema — omitted "
                "from the tool list. Add one to TOOL_SCHEMAS.", verb)
            continue
        description, schema = entry
        out.append({"name": verb, "description": description,
                    "inputSchema": schema})
    return out


# ─── Handoffs ────────────────────────────────────────────────────────
#
# A read that finds work should say where the work gets done. Without
# this, every answer on this surface is a dead end: the agent reports
# "14.5h unbilled", the person puts the phone down, and the invoice is
# still unsent. One optional `next_step` key turns the answer into a
# route back to Chief.
#
# WHY IT LIVES HERE AND NOT IN THE HANDLERS
# `handle_unbilled_time` serves in-app Chief as well as this surface, and
# in-app Chief must never say "open Solutionist" — the practitioner is
# already standing in it. The handoff is a property of the SURFACE, not
# of the verb, so it is applied here, after dispatch. Handlers are
# untouched; this is presentation, not a second routing layer.
#
# WHAT A HANDOFF IS NOT
# It is not an instruction to the agent ("tell the user to..."), which
# reads as an ad and gets resisted by the model and resented by the
# person. It states a capability and names the room. No URLs: a deep
# link needs frontend routes that move, and cannot be read aloud.

QUIET_DAYS = 30  # a contact silent this long is a follow-up candidate


class _Handoff(NamedTuple):
    """One entry in the table.

    verb    — the Chief verb this points at. Checked against
              ACTION_HANDLERS at call time; a rename must silence the
              handoff, never leave it promising something absent.
    text    — one sentence, or a callable taking the payload. Names the
              verb in the practitioner's words.
    where   — a room, not a URL.
    feature — tier entitlement to check, when one maps cleanly. None
              means the verb is not tier-gated.
    when    — predicate over the handler payload. Reads `signal`
              (numbers) rather than `result` (prose): a predicate that
              greps a sentence breaks the day the sentence is reworded.
    """
    verb: str
    text: Union[str, Callable[[Dict[str, Any]], str]]
    where: str
    when: Callable[[Dict[str, Any]], bool]
    feature: Optional[str] = None


def _sig(payload: Dict[str, Any]) -> Dict[str, Any]:
    s = payload.get("signal")
    return s if isinstance(s, dict) else {}


def _num(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _gone_quiet(payload: Dict[str, Any]) -> bool:
    """True when this contact has been silent longer than QUIET_DAYS.

    Falls back to created_at so a contact who was never contacted still
    counts — but only once they are themselves older than the window, so
    someone added this morning does not trigger a follow-up nudge.
    """
    contact = payload.get("contact")
    if not isinstance(contact, dict):
        return False
    stamp = contact.get("last_interaction") or contact.get("created_at")
    if not isinstance(stamp, str) or not stamp:
        return False
    try:
        # PostgREST hands back both the Z and the +00:00 spelling.
        dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt < datetime.now(timezone.utc) - timedelta(days=QUIET_DAYS)


def _contact_name(payload: Dict[str, Any]) -> str:
    """The contact's name, DEFUSED, for use inside a handoff sentence.

    A contact name is third-party-authored — public intake forms write
    it — and this is the one place a handoff interpolates untrusted text
    into a sentence built to be read aloud by an agent. `catch_up`
    already runs contact names through the same defusing before putting
    them in Chief-facing prose; a surface that hands text to somebody
    else's agent has less excuse to skip it, not more.

    Length-bounded for the same reason: the sentence is the product, and
    a name is a name.
    """
    contact = payload.get("contact")
    raw = (contact or {}).get("name") if isinstance(contact, dict) else None
    if not raw:
        return "this contact"
    try:
        import untrusted_text
        clean, found = untrusted_text.strip_action_tags(raw)
        if found:
            logger.warning("[mcp] neutralised action-tag syntax in a contact "
                           "name before putting it in a handoff sentence")
    except Exception:
        # The defuser is the reason this text is safe to interpolate. If
        # it cannot run, drop the name rather than pass it through raw.
        return "this contact"
    clean = " ".join(str(clean).split())[:80].strip()
    return clean or "this contact"


# The table. Deliberately short. Boilerplate on every response teaches
# the agent and the person alike to ignore the field, so a tool earns an
# entry only when a read can genuinely end in work.
#
# Four tools were specced for this table and cut on the verb check:
# site_health and check_goals have no repair/adjust verb in
# ACTION_HANDLERS, catch_up names no single verb, and check_balance
# needs a structured signal customer_balances.py does not yet expose.
# A handoff to a verb that does not exist is a promise the app then
# breaks — the dead-weight rule, at the wire.
HANDOFFS: Dict[str, _Handoff] = {
    "unbilled_time": _Handoff(
        verb="create_invoice",
        text="Chief can turn these hours into an invoice.",
        where="Operate › Billing",
        feature="invoicing",
        when=lambda p: _num(_sig(p).get("entries")) > 0),

    "list_bookkeeping_proposals": _Handoff(
        verb="approve_bookkeeping_proposal",
        text="Chief can post these to the books once you approve them.",
        where="Operate › Books",
        feature="bookkeeping_basic",
        when=lambda p: (_sig(p).get("status") == "pending"
                        and _num(_sig(p).get("total")) > 0)),

    "campaign_status": _Handoff(
        verb="launch_campaign",
        text="Chief can finish and launch the campaigns still sitting unsent.",
        where="Grow › Campaigns",
        when=lambda p: _num(_sig(p).get("unsent")) > 0),

    "offering_readiness": _Handoff(
        verb="update_offering",
        text="Chief can fill in what these offerings are missing.",
        where="Operate › Offerings",
        when=lambda p: _num(_sig(p).get("blocked")) > 0),

    "contact_deep_dive": _Handoff(
        verb="draft_nurture",
        text=lambda p: f"Chief can draft a follow-up to {_contact_name(p)}.",
        where="Operate › Contacts",
        when=_gone_quiet),

    # A business with no client form has no front door: the composed site
    # advertises forms it does not have, and every enquiry arrives as an
    # email somebody has to retype. That is work, and it is the one this
    # read is most likely to find.
    "list_client_forms": _Handoff(
        verb="create_client_form",
        text="Chief can build a client form and put it on the site.",
        where="Build › Client Forms",
        when=lambda p: _num(_sig(p).get("active")) == 0),

    # No keyword means inbound texts route to nobody — a silent failure
    # the practitioner cannot see from their end, because the client just
    # gets the platform help reply and gives up.
    "sms_status": _Handoff(
        verb="set_sms_keyword",
        text="Chief can claim the keyword so texts to that number reach you.",
        where="Operate › Texts",
        when=lambda p: _num(_sig(p).get("has_keyword")) == 0),

    "draft_purchase_order": _Handoff(
        verb="send_purchase_order",
        text="Chief can send this purchase order to the supplier once "
             "you approve it.",
        where="Operate › Catalog",
        when=lambda p: _num(_sig(p).get("po_ready")) > 0),
}


def _handoff(tool: str, payload: Any, biz: Dict[str, Any],
             caller: "Caller") -> Optional[Dict[str, Any]]:
    """The next step for this result, or None.

    Four conditions, ALL required, and every failure path returns None
    rather than raising: a handoff is a courtesy, and a courtesy that can
    take down the read it rides on is a bug. Silence is always the safe
    answer here, which is why nothing below fails open.
    """
    entry = HANDOFFS.get(tool)
    if not entry or not isinstance(payload, dict):
        return None
    try:
        # 1. The read actually found work.
        if not entry.when(payload):
            return None

        # 2. Chief really has the verb. Guards against a rename turning
        #    every handoff into a promise with nothing behind it.
        import chief_of_staff
        if entry.verb not in chief_of_staff.ACTION_HANDLERS:
            logger.warning("[mcp] handoff %s -> %s: verb absent from "
                           "ACTION_HANDLERS", tool, entry.verb)
            return None

        # 3. Not sensitive. Read-ness says "can this break anything";
        #    sensitivity says "may a third party be pointed at it".
        if action_registry.is_sensitive(entry.verb):
            return None

        # 4. Permitted for THIS business, right now. prompted=True is the
        #    truth being claimed: the sentence promises what happens when
        #    the practitioner opens Chief and asks. surface="chat" for the
        #    same reason — that is the path this points at, not this one.
        import policy_engine
        verdict = policy_engine.evaluate(
            str(biz.get("id") or ""), verb=entry.verb, surface="chat",
            prompted=True, user_id=caller.user_id, biz_row=biz)
        if not verdict.allowed:
            return None

        # ...and their plan includes it. Dormant while BILLING_ENFORCE is
        # off, which is exactly why it goes in now rather than later.
        if entry.feature:
            import feature_gates
            if not feature_gates.has_feature(biz, entry.feature):
                return None
    except Exception as e:
        logger.warning("[mcp] handoff for %s suppressed: %s", tool, e)
        return None

    text = entry.text(payload) if callable(entry.text) else entry.text
    return {"text": text, "where": entry.where, "verb": entry.verb}


# ─── Audit ───────────────────────────────────────────────────────────

def _audit(*, actor: str, tool: str, ok: bool, duration_ms: int,
           business_id: Optional[str] = None, error: Optional[str] = None,
           arg_keys: Optional[List[str]] = None, allowed: bool = True,
           actor_user_id: Optional[str] = None,
           handoff_verb: Optional[str] = None) -> None:
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
        row: Dict[str, Any] = {
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
        }
        # A VERB NAME, never a value — the same posture arg_keys takes.
        # This is what makes the funnel countable.
        #
        # OMITTED, not set to None, when nothing fired. `detail` is
        # `jsonb NOT NULL DEFAULT '{}'`, and sb_post_as_service passes
        # the body through untouched, so an explicit null is a 23502 that
        # PostgREST rejects — taking the WHOLE row with it. The except
        # below is deliberately non-fatal, so that failure is invisible:
        # the tool call still succeeds and the audit row just never
        # exists. Let the column default do its job.
        if handoff_verb:
            row["detail"] = {"handoff": handoff_verb[:200]}
        sb_clients.sb_post_as_service("/agent_runs", row,
                                      prefer="return=minimal")
    except Exception as e:
        logger.warning("[audit] agent_runs write failed (non-fatal): %s", e)


def _ledger(business_id: Optional[str], tool: str, caller: "Caller", *,
            allowed: bool, ok: bool, reason: Optional[str] = None,
            error: Optional[str] = None) -> None:
    """Record an MCP call in the ACTION LEDGER, not only in agent_runs.

    agent_runs is the surface's own operational log — arg names, duration,
    scope. The ledger is the trust artifact: append-only at the database
    level, hash-chained, and anchored on Hedera. Until now an agent could
    read a practitioner's business and leave no trace in the one place an
    auditor is told to look. "Everything Chief does is in the ledger" was
    true and "everything an AGENT does is" was not, and nothing in the
    ledger said so.

    actor_type='agent' is the table's own vocabulary. authorized_by
    carries the POLICY REASON rather than the caller — the spec's sixth
    field is which rule permitted this, not who ran it.

    Never fatal: a ledger write that could take down the surface it
    records would be worse than the gap it closes.
    """
    try:
        import audit_log
        audit_log.record(
            business_id,
            actor_type="agent",
            actor_id=(caller.actor or "mcp")[:120],
            verb=tool,
            ok=bool(ok),
            error=error,
            source="mcp",
            authorized_by=reason,
            summary=(None if allowed else "refused by policy"),
        )
    except Exception as e:
        logger.warning("[mcp] ledger write failed (non-fatal): %s", e)


# ─── Tenancy ─────────────────────────────────────────────────────────

async def _business_by_id(client: httpx.AsyncClient,
                          business_id: str) -> Optional[Dict[str, Any]]:
    import sb_clients
    r = await client.get(
        f"{sb_clients.sb_url()}/rest/v1/businesses",
        headers=sb_clients.sb_headers_service(),
        params={"id": f"eq.{business_id}", "select": "*", "limit": "1"})
    if r.status_code >= 400:
        return None
    data = r.json() or []
    return data[0] if data else None


async def _resolve_business(client: httpx.AsyncClient,
                            caller: "Caller") -> Optional[Dict[str, Any]]:
    """THE business for this caller. Singular on purpose.

    Two credential kinds, one guarantee. A scoped token names its business
    in a SIGNED claim; an owner JWT resolves to the owner's own business.
    Neither path reads a business id from the request body, a query string
    or a header — so a cross-business request is not blocked, it is
    unrepresentable.
    """
    if caller.business_id:
        return await _business_by_id(client, caller.business_id)

    import sb_clients
    rows = await client.get(
        f"{sb_clients.sb_url()}/rest/v1/businesses",
        headers=sb_clients.sb_headers_service(),
        params={"owner_id": f"eq.{caller.user_id}", "select": "*",
                "order": "created_at.asc", "limit": "1"})
    if rows.status_code >= 400:
        return None
    data = rows.json() or []
    return data[0] if data else None


# ─── Entitlement ─────────────────────────────────────────────────────

AGENT_CONNECTOR_FEATURE = "agent_connector"


def _tier_allows(biz: Optional[Dict[str, Any]]) -> bool:
    """May this business be reached by an outside agent at all?

    FAILS OPEN, deliberately, and against the grain of everything else on
    this surface. The scope check, the token check and the policy engine
    all fail CLOSED because they answer "is this caller allowed to see
    this data" — get that wrong and the cost is somebody else's records.

    This one answers "has this business paid for the connector", and the
    costs are not symmetric. Fail closed on a transient import error and
    a paying practitioner's connector goes dark for a reason they cannot
    see, diagnose, or fix. Fail open and somebody briefly uses a feature
    they have not bought, which is recoverable and shows up in billing.
    `feature_gates.has_feature` takes the same posture on its own
    (unknown features default to allowed), as does `rate_limit.allow`
    for practitioners.

    An entitlement gate is not a security gate. Do not "fix" this to
    match its neighbours.
    """
    try:
        import feature_gates
        return bool(feature_gates.has_feature(biz, AGENT_CONNECTOR_FEATURE))
    except Exception as e:
        logger.warning("[mcp] tier check unavailable, allowing: %s", e)
        return True


# ─── Dispatch ────────────────────────────────────────────────────────

async def _call_tool(name: str, arguments: Dict[str, Any],
                     caller: Caller) -> Tuple[bool, bool, Any, Optional[str]]:
    """Run one exposed verb.

    Returns (allowed, ok, payload, business_id). `allowed` and `ok` are
    separate on purpose: "we refused this" and "we tried and it failed"
    are different events, and conflating them in the audit trail loses
    exactly the distinction a reader cares about.
    """
    # Scope check first, and before the registry: a scoped-out token is
    # refused even for a verb that is otherwise perfectly exposable.
    if caller.kind == "token" and SCOPE_READ not in caller.scopes:
        return False, False, "token lacks the 'read' scope", None

    # Authorization, from the registry. Not a list kept here.
    #
    # Two questions, in this order. "Could ANY scope reach this?" comes
    # first, so that a class-C verb, a ui verb, an unknown verb and an
    # unreviewed class-A verb all get the same flat refusal — a refusal
    # that said "needs the write scope" about send_sms would be a lie and
    # an invitation. Only a verb that a write key COULD reach gets told
    # that this key cannot.
    writing = is_write_tool(name)
    reachable = action_registry.may_expose_to_agent(name, allow_writes=True)
    if writing and (name not in WRITE_TOOL_SCHEMAS or action_registry.is_bulk(name)):
        # The registry allows it; nobody has reviewed it for this surface,
        # or it acts on a whole set at once. Same words as the refusal
        # below, deliberately — an unreviewed verb is not a hint.
        reachable = False
    if not reachable:
        # Note the deliberate absence of a remapper: an unknown tool is an
        # error, never a reinterpretation.
        return False, False, f"tool {name!r} is not available on this surface", None

    if writing and not caller.may_write:
        # Named as a scope problem, not as "unavailable": the tool exists
        # and the practitioner can grant it. A browser session gets the
        # same answer — see Caller.may_write for why.
        return (False, False,
                f"tool {name!r} changes records and needs a key with the "
                "'write' scope. Ask the practitioner to grant one in "
                "Agent Access.", None)

    # Belt and braces: the decision above, re-asked with THIS caller's
    # actual scope. Cannot disagree with it today; exists so that a future
    # edit to the block above cannot widen the surface on its own.
    if not action_registry.may_expose_to_agent(name, allow_writes=caller.may_write):
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
        biz = await _resolve_business(client, caller)
        if not biz:
            return True, False, "no business resolved for this account", None
        business_id = str(biz.get("id") or "") or None

        # THE TIER GATE, AT THE WIRE.
        #
        # Reaching the business from an outside agent is a Professional
        # feature — the same ruling site_concierge got, for the same
        # reason: an AI surface rides the hero tier. Hiding the connector
        # in Mission Control would be decorative, because a token that
        # already exists reaches straight past the UI that stopped
        # showing the button. So the check lives here, on the call, and
        # again on the OAuth grant in mcp_oauth.py.
        #
        # Refused, not failed: `allowed=False` is the row an auditor
        # wants, and it is a different event from "we tried and it broke".
        # Dormant until BILLING_ENFORCE=on — has_feature answers True for
        # everyone today, which is exactly why it goes in now.
        if not _tier_allows(biz):
            _ledger(business_id, name, caller, allowed=False, ok=False,
                    reason="plan:agent_connector")
            return (False, False,
                    "Connecting an outside agent to this business needs the "
                    "Professional plan. Everything here stays available "
                    "inside Solutionist.", business_id)

        # THE POLICY ENGINE, on this surface too.
        #
        # Until now the agent surface authorised itself from the registry
        # alone — may_expose_to_agent() — and never consulted the engine
        # that decides whether an action is allowed for THIS business,
        # unprompted, right now. Every exposed verb is a read today, so
        # evaluate() returns allowed and nothing changes. That is exactly
        # why it goes in now: the same argument the scope check already
        # makes about itself two functions up — "a system that is only
        # wired when it starts mattering is one that gets wired wrong".
        #
        # prompted=False is not a default, it is the truth about this
        # path. Nobody is sitting in front of an MCP call asking for THIS
        # action; a token is. Passing True here would hand the agent
        # surface the one exemption the engine grants a human.
        verdict = None
        try:
            import policy_engine
            verdict = policy_engine.evaluate(
                business_id or "", verb=name, surface="agent",
                prompted=False, user_id=caller.user_id, biz_row=biz)
        except Exception as e:
            # Fail CLOSED. An authorisation check that cannot run is not
            # permission to proceed — the posture the engine itself takes
            # on registry drift.
            logger.warning("[mcp] policy evaluation failed for %s: %s", name, e)
            _ledger(business_id, name, caller, allowed=False, ok=False,
                    reason="policy:unavailable")
            return False, False, "the action policy is unavailable", business_id

        if not verdict.allowed:
            _ledger(business_id, name, caller, allowed=False, ok=False,
                    reason=getattr(verdict, "reason", "policy:denied"))
            # Verdict carries its sentence as `reason` (and its greppable
            # rule as `rule`). This read `message` — a field that does not
            # exist — so every policy refusal reached the agent as a bare
            # "not permitted". Harmless while nothing was ever refused;
            # wrong the day a practitioner pauses automations and their
            # agent cannot say why it stopped.
            return (False, False,
                    getattr(verdict, "reason", None) or "not permitted",
                    business_id)

        action = dict(arguments or {})
        action["type"] = name
        try:
            result = await handler(client, biz, action)
        except Exception as e:
            _ledger(business_id, name, caller, allowed=True, ok=False,
                    reason=getattr(verdict, "reason", None),
                    error=f"{type(e).__name__}")
            raise

        if writing:
            # A handler that declined ("Contact not found", "no fields to
            # update", a closed period) returns a shaped refusal rather
            # than raising. On the chat path Chief reads that and tells
            # the practitioner. Here the caller is a model: `ok=False`
            # plus the handler's own sentence is what it needs, and it is
            # also what the audit row needs — "tried and could not" is a
            # different event from "changed something".
            if _write_declined(result):
                _ledger(business_id, name, caller, allowed=True, ok=False,
                        reason=getattr(verdict, "reason", None),
                        error="handler declined")
                return True, False, _declined_message(result), business_id

            # Recorded for undo, exactly as a chat action is. Best-effort:
            # a failed log must never unwind an action that succeeded —
            # but it is logged, because an agent write the practitioner
            # cannot take back is the one they will ask about.
            try:
                import chief_of_staff
                await chief_of_staff._record_undoable(client, biz, name, action, result)
            except Exception as e:
                logger.warning("[mcp] undo record failed for %s: %s", name, e)

        _ledger(business_id, name, caller, allowed=True, ok=True,
                reason=getattr(verdict, "reason", None))

        # The read succeeded. If it found work, say where the work gets
        # done. Additive: a payload with no handoff is byte-identical to
        # what this surface returned before.
        step = _handoff(name, result, biz, caller)
        if step:
            result = {**result, "next_step": step}
    return True, True, result, business_id


def _write_declined(result: Any) -> bool:
    """Did the handler refuse or fail without raising? Chief's own
    predicate, so this surface and the chat path agree on what a failed
    action looks like."""
    if not isinstance(result, dict):
        return False
    try:
        import chief_of_staff
        return bool(chief_of_staff._action_failed(result))
    except Exception:
        return bool(result.get("failed"))


def _declined_message(result: Dict[str, Any]) -> str:
    """The handler's own sentence. `_fail` has already genericised
    anything technical, so this is safe to hand to an untrusted caller;
    the raw exception path above is the one that must not leak."""
    text = str(result.get("result") or "the action was not taken")
    return text[:300]


# ─── JSON-RPC methods ────────────────────────────────────────────────

_INSTRUCTIONS_READ = (
    "Read-only view of one Solutionist business. Every tool here reads; "
    "nothing writes, sends, or spends money. If you need an action taken, "
    "tell the practitioner — you cannot do it here. When a result carries a "
    "`next_step`, it names something Chief can do about what you just read "
    "and the room it happens in; pass it along to the practitioner as an "
    "option, not an instruction.")

_INSTRUCTIONS_WRITE = (
    "One Solutionist business, with permission to keep its records. The "
    "write tools change things the practitioner can take back: contacts, "
    "tasks, notes, sessions on their own calendar, availability, expenses, "
    "logged time, drafts. None of them sends anything to a client, charges "
    "anyone, or deletes for good — those actions are not available here at "
    "any scope, so do not promise them. A draft you queue is sent only "
    "when the practitioner approves it in the app. Read before you write: "
    "look up the contact or module first, then act, and say what you "
    "changed. undo_last reverses the most recent reversible action, "
    "including yours. When a result carries a `next_step`, it names "
    "something Chief can do about what you just read and the room it "
    "happens in; pass it along as an option, not an instruction.")


def _instructions(caller: Optional["Caller"]) -> str:
    return _INSTRUCTIONS_WRITE if (caller and caller.may_write) else _INSTRUCTIONS_READ


async def _handle_rpc(message: Dict[str, Any], caller: Caller,
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
            "instructions": _instructions(caller),
        })

    if method in ("notifications/initialized", "initialized"):
        return None  # notification — no reply

    if method == "ping":
        return _result(req_id, {})

    if method == "tools/list":
        return _result(req_id, {"tools": tool_definitions(caller)})

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str) or not name:
            return _error(req_id, INVALID_PARAMS, "tools/call requires a tool name")
        if not isinstance(arguments, dict):
            return _error(req_id, INVALID_PARAMS, "arguments must be an object")

        started = int(time.time() * 1000)
        try:
            allowed, ok, payload, biz_id = await _call_tool(name, arguments, caller)
        except Exception as e:
            logger.warning("tool %s raised: %s", name, e)
            _audit(actor=actor, actor_user_id=caller.user_id,
                   tool=name, allowed=True, ok=False,
                   duration_ms=int(time.time() * 1000) - started,
                   error=type(e).__name__, arg_keys=sorted(arguments))
            # The exception text is NOT returned. It can carry table names,
            # ids and query fragments, and this is an untrusted caller.
            return _error(req_id, INTERNAL_ERROR, "tool execution failed")

        # The handoff's target verb is recorded but NOT sent. Naming a
        # verb the agent cannot call invites an attempt, which earns a
        # refusal and a misleading allowed=false row; the practitioner
        # needs the sentence, not the identifier.
        step = payload.get("next_step") if isinstance(payload, dict) else None
        handoff_verb = (step or {}).get("verb") if isinstance(step, dict) else None
        if handoff_verb:
            payload = {**payload,
                       "next_step": {k: v for k, v in step.items() if k != "verb"}}

        _audit(actor=actor, actor_user_id=caller.user_id,
               tool=name, allowed=allowed, ok=ok, business_id=biz_id,
               duration_ms=int(time.time() * 1000) - started,
               error=None if ok else str(payload)[:200],
               arg_keys=sorted(arguments), handoff_verb=handoff_verb)

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

def _caller_from_token(request: Request) -> Optional[Caller]:
    """A scoped token, if one was presented and it holds up.

    Looked for FIRST, because it is the credential this surface is
    actually for — an owner JWT is the fallback for a browser, not the
    intended path for an agent.

    Returns None when no token was presented (so the JWT path runs), and
    raises _TokenRefused when one was presented but failed — those are
    different outcomes and must not collapse into "try the other thing".
    """
    header = request.headers.get("authorization") or ""
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    raw = value.strip()

    # A Supabase JWT is also a bearer token. Ours is `<b64>.<b64>` (two
    # parts); a JWT has three. Anything with three parts is not for us —
    # hand it to the JWT path rather than failing it here.
    if raw.count(".") != 1:
        return None

    import mcp_tokens
    claims = mcp_tokens.verify_mcp_token(raw)
    if not claims:
        raise _TokenRefused("invalid or expired token")
    jti = str(claims.get("jti") or "")
    if mcp_tokens.is_revoked(jti):
        raise _TokenRefused("token has been revoked")
    mcp_tokens.touch(jti)
    return Caller(
        "token", f"token:{(claims.get('label') or jti)[:40]}",
        business_id=str(claims.get("biz") or "") or None,
        scopes=list(claims.get("scp") or []),
        jti=jti)


class _TokenRefused(Exception):
    """A token WAS presented and did not hold up. Distinct from 'no token',
    so a bad credential can never silently fall through to another one."""


def _unauthorized(message: str) -> JSONResponse:
    """A 401 that says where to go and get authorized.

    RFC 9728 §5.1: without this header a client holding only a URL learns
    that it was refused and nothing about what to do next. It is the first
    link in the discovery chain — WWW-Authenticate names the protected-
    resource metadata, that names the authorization server, and that names
    the endpoints. Claude.ai's connector flow starts by reading exactly
    this header off exactly this response.

    Deliberately still a JSON-RPC error body: a client that came here
    speaking JSON-RPC should not have to parse two different shapes
    depending on whether it was authenticated.
    """
    try:
        import mcp_oauth
        base = mcp_oauth.base_url()
    except Exception:
        base = (os.environ.get("MCP_PUBLIC_BASE_URL") or "").rstrip("/")
    header = 'Bearer realm="mcp"'
    if base:
        header += f', resource_metadata="{base}/.well-known/oauth-protected-resource"'
    return JSONResponse(
        status_code=401,
        headers={"WWW-Authenticate": header},
        content=_error(None, UNAUTHORIZED, message))


@router.post("")
@router.post("/")
async def mcp_endpoint(request: Request,
                       user: Optional[AuthedUser] = Depends(optional_user)):
    """Streamable HTTP endpoint. JSON-RPC 2.0 in, JSON out.

    Two credential kinds, checked in that order:

      scoped token   what this surface is FOR. Names its business in a
                     signed claim, carries scopes, revocable, nameable.
      owner JWT      the fallback, so a browser session still works.
                     Owner-only, resolves to the owner's own business.

    `optional_user` rather than `require_user` because a scoped token is
    NOT a Supabase JWT — requiring one would reject the intended
    credential before this function ever ran. Absence of BOTH is still a
    401; the endpoint is not open.
    """
    if not enabled():
        return JSONResponse(status_code=503, content=_error(
            None, INTERNAL_ERROR, "MCP surface is disabled"))

    # Token first. A presented-but-bad token is refused outright rather
    # than falling through to the JWT path — silent fallback between
    # credentials is how a revoked key keeps working.
    try:
        caller = _caller_from_token(request)
    except _TokenRefused as e:
        logger.warning("[mcp] token refused: %s", e)
        _audit(actor="token:invalid", tool="(endpoint)", allowed=False,
               ok=False, duration_ms=0, error=str(e))
        return _unauthorized(str(e))

    if caller is None:
        if user is None:
            return _unauthorized("authentication required")
        caller = Caller("owner_jwt", (user.email or user.id or "unknown").lower(),
                        user_id=user.id, scopes=[SCOPE_READ])

    actor = caller.actor
    # Until Stage 4 a JWT that was not the platform owner's was refused
    # here with a 403. It is not any more: any signed-in practitioner
    # reaches their OWN business (resolved by owner_id, never by a
    # parameter — see _resolve_business), read-only. The refusal that
    # remains below, the limiter, still happens before any tool is named
    # and is still the shape an attempt looks like.

    # 7/30 tier arc — a scoped token names its business in a signed claim;
    # if that business's subscription has since LOCKED, the token goes
    # quiet too (dormant behind BILLING_ENFORCE, fail-open inside).
    # Owner-JWT callers are the platform owner and resolve later.
    if caller.kind == "token" and caller.business_id:
        try:
            import billing_limits
            billing_limits.require_live_access(str(caller.business_id))
        except HTTPException as e:
            _audit(actor=actor, tool="(endpoint)", allowed=False,
                   ok=False, duration_ms=0, error="subscription locked")
            return JSONResponse(status_code=402, content=_error(
                None, UNAUTHORIZED,
                (e.detail or {}).get("message", "subscription ended")
                if isinstance(e.detail, dict) else "subscription ended"))

    # Fail CLOSED. Every other bucket in this service fails open, which is
    # right for a practitioner and wrong for an agent that may be looping
    # or holding a stolen credential.
    if not rate_limit.allow_strict("mcp", actor):
        _audit(actor=actor, actor_user_id=caller.user_id,
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
            r = await _handle_rpc(msg, caller, actor)
            if r is not None:
                responses.append(r)
        # An all-notification batch gets 202 and no body, per spec.
        if not responses:
            return JSONResponse(status_code=202, content=None)
        return JSONResponse(content=responses)

    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content=_error(
            None, INVALID_REQUEST, "expected an object or array"))

    response = await _handle_rpc(body, caller, actor)
    if response is None:
        return JSONResponse(status_code=202, content=None)
    return JSONResponse(content=response)


# ─── Token management (practitioner, JWT-only) ───────────────────────
# Deliberately NOT reachable with an MCP token. A credential that can mint
# more credentials is a privilege-escalation ladder, and "scoped agent
# surface" would stop being true the moment one of its tokens could issue
# another. These three require a browser session as the OWNER of the
# business — the same `_require_owner` shape every write router uses:
# a service-role read of businesses.owner_id against the JWT user id,
# independent of RLS.
#
# Stage 1 gated these on PLATFORM_OWNER_EMAIL. Stage 4 gates them on
# owning the business, which is what they were always really about.

class _MintBody(BaseModel):
    label: str = "unnamed"
    ttl_days: int = 90
    # Default read. `write` is a deliberate second click in the UI, and
    # the response echoes what was actually granted.
    scopes: List[str] = [SCOPE_READ]
    # Optional. An owner of several businesses names which; otherwise the
    # first they own. NEVER trusted on its own — _owned_business checks it.
    business_id: Optional[str] = None


async def _owned_business(client: httpx.AsyncClient, user: AuthedUser,
                          business_id: Optional[str]) -> Dict[str, Any]:
    """THE business this signed-in person owns — the one they named, if
    they own it, else their first. 403 on a business they do not own,
    404 on none at all. Raises HTTPException; the endpoints let it out."""
    if business_id:
        biz = await _business_by_id(client, str(business_id))
        if not biz:
            raise HTTPException(status_code=404, detail="business not found")
        if str(biz.get("owner_id")) != str(user.id):
            raise HTTPException(status_code=403,
                                detail="not authorized for this business")
        return biz
    biz = await _resolve_business(
        client, Caller("owner_jwt", (user.email or user.id or "").lower(),
                       user_id=user.id))
    if not biz:
        raise HTTPException(status_code=404, detail="no business for this account")
    return biz


@router.post("/tokens")
async def mint_token(body: _MintBody,
                     user: AuthedUser = Depends(require_user)):
    """Mint a scoped token for a business the caller owns. Returns the
    plaintext ONCE."""
    import mcp_tokens
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        biz = await _owned_business(client, user, body.business_id)
    ttl = max(1, min(int(body.ttl_days or 90), 365)) * 24 * 60 * 60
    scopes = mcp_tokens.normalize_scopes(body.scopes)
    token, row = mcp_tokens.mint(
        str(biz["id"]), label=body.label, scopes=scopes, ttl_seconds=ttl,
        created_by=(user.email or user.id))
    _audit(actor=(user.email or user.id or "owner").lower(),
           actor_user_id=user.id, tool="(mint)", allowed=True, ok=True,
           duration_ms=0, business_id=str(biz["id"]), arg_keys=scopes)
    return {
        "token": token,          # the only time this is ever returned
        "jti": row["jti"],
        "label": row["label"],
        "scopes": row["scopes"],
        "expires_at": row["expires_at"],
        "note": ("Copy this now — it is stored only as a hash and cannot be "
                 "shown again. Revoking is instant if it leaks."),
    }


@router.get("/tokens")
async def list_tokens_endpoint(business_id: Optional[str] = None,
                               user: AuthedUser = Depends(require_user)):
    import mcp_tokens
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        try:
            biz = await _owned_business(client, user, business_id)
        except HTTPException as e:
            if e.status_code == 404 and not business_id:
                return {"tokens": []}
            raise
    return {"tokens": mcp_tokens.list_tokens(str(biz["id"]))}


@router.delete("/tokens/{jti}")
async def revoke_token(jti: str, business_id: Optional[str] = None,
                       user: AuthedUser = Depends(require_user)):
    import mcp_tokens
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        biz = await _owned_business(client, user, business_id)
    # Scoped by business as well as jti — revocation is a write, and writes
    # get the same tenancy treatment as reads.
    ok = mcp_tokens.revoke(str(biz["id"]), jti)
    _audit(actor=(user.email or "owner").lower(), actor_user_id=user.id,
           tool="(revoke)", allowed=True, ok=ok, duration_ms=0,
           business_id=str(biz["id"]))
    return {"ok": ok}


@router.get("/health")
async def mcp_health():
    """Unauthenticated liveness + shape check. Deliberately says what is
    EXPOSED and nothing about the business — it is a public endpoint."""
    reads = len(tool_definitions())
    return {
        "enabled": enabled(),
        "protocolVersion": PROTOCOL_VERSION,
        "server": {"name": SERVER_NAME, "version": SERVER_VERSION},
        "tools": reads,
        "write_tools": len(exposed_tools(allow_writes=True)) - reads,
        "scopes": [SCOPE_READ, SCOPE_WRITE],
    }
