# kmj_intake_automation.py
# KMJ Creative Solutions — 24/7 Intake Automation Backend
#
# Handles:
#   1. Netlify form webhook → auto-qualify lead → notify Kevin
#   2. Scheduled follow-up sequences (runs every hour)
#   3. Testimonial requests (30 days post-delivery)
#
# Deploy to: Railway / Render / your existing FastAPI server
#
# Install: pip install fastapi uvicorn anthropic python-dotenv apscheduler httpx

import os
import llm_call
import rate_limit
import json
import httpx
import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from anthropic import Anthropic
from ai_proxy import router as ai_proxy_router
from intake_endpoint import router as intake_router
from nurture_agent import router as nurture_router
from session_agent import router as session_router
from contract_agent import router as contract_router
from payment_agent import router as payment_router
from growth_engine import router as growth_router
from module_agent import router as module_router
from chief_of_staff import router as chief_router
from notification_engine import router as notification_router
from whisper_proxy import router as whisper_router
from public_site import router as public_site_router
from email_sender import router as email_router
from meta_oauth import router as meta_router
from google_oauth import router as google_router
from stripe_proxy import router as stripe_router
from sms_service import router as sms_router
from foundation_router import router as foundation_router
from business_profile_router import router as business_profile_router
from practitioner_profile_router import router as practitioner_profile_router
from brand_engine_router import router as brand_engine_router
from voice_depth_router import router as voice_depth_router
from strategy_router import router as strategy_router
# Access-Enforcement 25a (Fork 25) — locked restricted-module entries (e.g. Giving)
from restricted_modules import router as restricted_router
from workflow_router import router as workflow_router
from growth_objective_router import router as growth_objective_router
from module_spec_router import router as module_spec_router
# Phase C.1 — Bookings archetype: customer-facing widget endpoints +
# contact-related-entries surfacing for ContactDetail.
from booking_widget_router import router as booking_widget_router
from contacts_router import router as contacts_router
# Phase C.1.2 — canonical pricing layer
from offerings_router import router as offerings_router
# Phase D.1.1 — availability + slot computation (customer-facing anon)
from availability_router import router as availability_router
# Phase D.2.1 — hosted booking page (practitioner-side config + URL resolver)
from booking_page_router import router as booking_page_router
# Phase VABI v1 — vertical-intelligence read endpoint for the frontend
from vertical_intelligence_router import router as vertical_intelligence_router
# Phase VABI v1.5 — per-business terminology + intelligence overrides
from terminology_overrides_router import router as terminology_overrides_router
from workspace_composer_router import router as workspace_composer_router
# Phase D.4 PR 1 — Stripe Connect OAuth + webhook receiver
from stripe_connect_router import router as stripe_connect_router
# Phase D.4 PR 2 — Charges / Payouts / Customers read proxy
from stripe_data_proxy import router as stripe_data_proxy_router
# Phase D.4 PR 3 — Booking pre-pay + refund endpoints (PR 3a removed
# the PR 3 invoices CRUD; the pre-existing OPERATE → Invoices surface
# is the canonical invoicing system).
from stripe_payments_router import router as stripe_payments_router
# Phase F.2 v1 — Plaid bookkeeping + reconciliation
from plaid_router import router as plaid_router
# Phase C.1.3 — Chief proactive-suggestion lifecycle
from chief_suggestions_router import router as chief_suggestions_router
# Pass 4.0a — Director Agent foundations
from agents.sparse_input_enrichment_router import router as sparse_enrichment_router
# Pass 4.0b — Director Agent: Critique loop
from agents.director_agent.router import router as director_router
# Pass 4.0b.5 — Slot system (image retrieval + management)
from agents.slot_system.router import router as slot_router
# Pass 4.0d PART 1 — Site content overrides (render-time text/color/slot)
from agents.override_system.router import router as override_router
# Pass 4.0d PART 2 — Chief unification (intent classifier + dispatcher)
from agents.chief_executive.router import router as chief_executive_router
# Pass 4.0g — Multi-module composition (Cathedral + Studio Brut + Module Router)
from agents.composer.router import router as composer_router

# Two route families carry a bearer credential as a URL path segment
# (auditor read links, store downloads), so the access log was recording
# working credentials. Installed at IMPORT time rather than under
# __main__: Railway starts uvicorn from the CLI, where __main__ never
# runs but this module is always imported.
from access_log_redaction import install as _install_log_redaction, scrub_sentry_event
_install_log_redaction()

# Arc 29 — error tracking. Env-gated: no-op until SENTRY_DSN is set on
# Railway, then every unhandled exception + slow request is captured.
# Optional dependency (sentry-sdk in requirements); import guarded so a
# missing package never blocks boot.
if os.environ.get("SENTRY_DSN"):
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=os.environ["SENTRY_DSN"],
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_RATE", "0.0")),
            environment=os.environ.get("RAILWAY_ENVIRONMENT", "production"),
            send_default_pii=False,  # never ship customer PII to Sentry
            # send_default_pii=False withholds headers and cookies but NOT
            # the request URL, and for those two routes the URL is the
            # credential. Without this, switching error tracking on would
            # ship live audit links to a third party.
            before_send=scrub_sentry_event,
        )
        print("   Sentry error tracking: ON")
    except Exception as _e:
        print(f"   [warn] Sentry init failed: {_e}")

# FastAPI serves /docs, /redoc and /openapi.json by default, and nothing
# here ever turned them off — so the most complete, machine-readable map
# of this platform (every path, parameter and response shape across ~650
# routes) was published unauthenticated to anyone who asked. It was also,
# by some distance, the most agent-legible artifact we had, which is the
# part worth sitting with: an interface for machines shipped by accident
# rather than by design.
#
# Off by default now; ENABLE_API_DOCS=1 restores them for local work.
# When there IS a public API it should be a deliberate, versioned
# document describing the routes we mean to support — not a mirror of
# every internal handler that happens to exist.
def api_docs_enabled() -> bool:
    """Exactly "1" opts in. A separate function so the rule can be tested
    without reimporting this module — reloading it re-registers ~100
    routers and 20 scheduler jobs, which is a heavy and side-effecting
    way to check a string comparison."""
    return (os.environ.get("ENABLE_API_DOCS") or "").strip() == "1"


_docs = api_docs_enabled()
app = FastAPI(
    title="KMJ Intake Automation",
    docs_url="/docs" if _docs else None,
    redoc_url="/redoc" if _docs else None,
    openapi_url="/openapi.json" if _docs else None,
)
# CORS — env-driven. Default stays "*" DELIBERATELY: auth is bearer-token
# (no cookies → no CSRF surface) and the public embeds (booking widget,
# intake forms) are fetched from arbitrary practitioner-site origins, so a
# hard allowlist would break them. To restrict the app-facing API anyway,
# set CORS_ALLOWED_ORIGINS to a comma-separated origin list on Railway —
# but keep in mind that also fences the public embeds.
_cors_origins = [
    o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "*").split(",") if o.strip()
] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,  # bearer tokens only — never cookie auth
)
# Compression (2026-08-02, performance pass). Composed sites are single
# documents with CSS + JS + JSON-LD inlined — routinely 100-250KB, and
# every byte was shipping uncompressed to every visitor on every view
# (the serve path is deliberately no-store, so nothing amortized it).
# HTML/CSS/JS compress ~6-8x. minimum_size skips payloads where the
# gzip header would cost more than it saves.
from fastapi.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=1024)
# Chief's chat stream must NOT ride through gzip — Starlette compresses
# a streaming body through one zlib stream that only drains on close,
# so every SSE delta arrived in a single burst at turn end (measured
# live, 2026-08-25). Added AFTER GZipMiddleware so it sits OUTSIDE it
# and strips Accept-Encoding before gzip decides. See sse_middleware.py.
from sse_middleware import NoGzipForStreams
app.add_middleware(NoGzipForStreams)
# Guarantee CORS headers on ALL error responses (500/404/422/unhandled) — an
# unhandled exception escapes CORSMiddleware otherwise, masking every error as
# a browser CORS block. See cors_error_handlers.py.
import cors_error_handlers
cors_error_handlers.install(app)
app.include_router(ai_proxy_router)
# Watchdog arc (2026-07-11) — client-error intake + error ring buffer.
try:
    from platform_watchdog import telemetry_router, attach_error_buffer
    app.include_router(telemetry_router)
    attach_error_buffer()
except Exception as _e:
    print(f"   [warn] telemetry router not mounted: {_e}")
app.include_router(intake_router)
# First-party anonymous site analytics (POST /api/track is public;
# GET /admin/traffic is platform-owner only). See site_analytics.py.
try:
    from site_analytics import router as site_analytics_router
    app.include_router(site_analytics_router)
except Exception as _e:  # never block boot on an analytics import
    logging.getLogger(__name__).warning(f"site_analytics not loaded: {_e}")
# The agent-facing MCP surface (Stage 1, 2026-07-28): read-only, and
# owner-only until Build 3's scoped tokens land. POST /mcp speaks JSON-RPC
# 2.0; the tool list is DERIVED from action_registry.may_expose_to_agent,
# so it cannot drift from the classification. Kill switch: MCP_ENABLED=off.
# Mounted inside a try/except like the analytics router above — an
# experimental surface must never be able to stop the service booting.
try:
    from mcp_server import router as mcp_router
    app.include_router(mcp_router)
except Exception as _e:
    logging.getLogger(__name__).warning(f"mcp_server not loaded: {_e}")
# OAuth 2.1 in front of that surface (2026-07-29). Exists so the connector
# can be added on claude.ai — which is the ONLY way a phone can reach it,
# since iOS/Android cannot run a local MCP server. Serves /.well-known
# discovery, RFC 7591 registration, a consent screen, and /oauth/token.
# The access token it issues is an ordinary mcp_tokens credential, so
# mcp_server's auth path is unchanged and revocation still works from
# Mission Control. Same try/except: an auth surface that fails to import
# must not stop the service booting.
try:
    from mcp_oauth import router as mcp_oauth_router
    app.include_router(mcp_oauth_router)
except Exception as _e:
    logging.getLogger(__name__).warning(f"mcp_oauth not loaded: {_e}")
app.include_router(nurture_router)
app.include_router(session_router)
app.include_router(contract_router)
app.include_router(payment_router)
app.include_router(growth_router)
app.include_router(module_router)
app.include_router(chief_router)
from chief_jobs import router as chief_jobs_router  # Feature 2 — queued desk jobs
app.include_router(chief_jobs_router)
app.include_router(notification_router)
app.include_router(whisper_router)
app.include_router(email_router)
app.include_router(meta_router)
app.include_router(google_router)
app.include_router(stripe_router)
app.include_router(sms_router)
# Twilio SMS rail (2026-07-04) — outbound send + signed inbound webhook.
# Coexists with the Telnyx sms_service until routing picks a lane.
from twilio_sms import router as twilio_sms_router
app.include_router(twilio_sms_router)
# SMS routing brain (Kevin's one-number architecture): binding-first
# routing, practitioner keywords, opt-out ledger, scoped broadcast.
from sms_routing import router as sms_routing_router
from consent_router import router as consent_router
app.include_router(sms_routing_router)
app.include_router(consent_router)
# Dedicated numbers (2026-09-02): a practitioner's own line, bought on
# the platform account, attached to the one Messaging Service.
from sms_numbers_router import router as sms_numbers_router
app.include_router(sms_numbers_router)
app.include_router(brand_engine_router)
app.include_router(voice_depth_router)
# THE OBSERVATORY — research a card (docs/STRATEGY_ROOM.md phase 3c)
app.include_router(strategy_router)
app.include_router(restricted_router)
app.include_router(workflow_router)
app.include_router(growth_objective_router)
app.include_router(module_spec_router)
# Phase C.1 — Bookings archetype
app.include_router(booking_widget_router)
app.include_router(contacts_router)
app.include_router(offerings_router)
# Phase D.1.1 — availability + slot computation (customer-facing anon)
app.include_router(availability_router)
import booking_series; app.include_router(booking_series.router)  # weekly series (operator-side, authed) — one line by design
# Phase D.2.1 — hosted booking page (practitioner-side config + URL resolver).
# Registered BEFORE public_site_router so its /booking-page/... routes
# match before the public_site `/{path:path}` catch-all.
app.include_router(booking_page_router)
# Online giving (ministry/nonprofit) — owner config (/giving/...) + the
# anonymous checkout (/public/giving/...). Same discipline: BEFORE
# public_site_router so nothing falls into the subdomain catch-all.
from giving_router import router as giving_router
app.include_router(giving_router)
# Public event RSVP (event_roster modules) — owner config
# (/events-public/...) + the anonymous signup (/public/events/...).
# Same discipline: BEFORE public_site_router so nothing falls into the
# subdomain catch-all.
from events_rsvp_router import router as events_rsvp_router
app.include_router(events_rsvp_router)
# Phase D.4 PR 1 — Stripe Connect OAuth + webhook receiver. Same
# discipline: BEFORE public_site_router so /payments/* doesn't fall
# into the subdomain catch-all.
app.include_router(stripe_connect_router)
# Step-up: /auth/step-up. The ledger keeps its own /audit/unlock —
# that route's pre-check is "may you READ this ledger", which is the
# right question there and the wrong one for a deletion gate.
import ledger_unlock as _ledger_unlock
app.include_router(_ledger_unlock.router)
# Phase D.4 PR 2 — Charges / Payouts / Customers data tabs proxy.
# Shares the /payments prefix with stripe_connect_router; FastAPI
# merges them cleanly because the routes don't collide.
app.include_router(stripe_data_proxy_router)
# Phase D.4 PR 3 — booking pre-pay (anon) + refund + invoices CRUD.
# All under /payments/* prefix; FastAPI merges with the other
# /payments routers cleanly.
app.include_router(stripe_payments_router)
# Phase F.2 v1 — Plaid Link, sync, webhook, summary, categorize rules
app.include_router(plaid_router)
# Phase G — Chief Bookkeeping Intelligence (proposals + learning signals)
from chief_bookkeeping_router import router as chief_bookkeeping_router
app.include_router(chief_bookkeeping_router)
# Phase H.3a — Reports suite (P&L, AR Aging, Cash Flow, Balance Sheet)
from reports_router import router as reports_router
app.include_router(reports_router)
# S11 close-out — approve/dismiss agent_queue drafts through the action
# layer (manager+ seats, audit_log rows) instead of client-side PATCHes
from approvals_router import router as approvals_router
app.include_router(approvals_router)
# Balance surface (2026-07-31) — the drawdown ledger's HTTP layer
from customer_balances_router import router as customer_balances_router
app.include_router(customer_balances_router)
# The Business Track (2026-08-04) — the established-business intake.
# Serves the day-one plug-in list from the same catalog the Business
# Coach recommends out of, so the conversation and the BUILD checklist
# can never disagree about what to switch on next.
from business_track_router import router as business_track_router
app.include_router(business_track_router)
# Wave C (2026-09-02): the room card behind "What is this room?" — no model call.
from room_card_router import router as room_card_router
app.include_router(room_card_router)
# Bring an existing client list in. /contacts had CSV export and no
# import; for a business that arrives with people, that was the first
# wall they hit.
from contacts_import_router import router as contacts_import_router
app.include_router(contacts_import_router)
# Structure Import, Stage 0 (2026-09-01). A business that arrives already
# running hands over its spreadsheet exports; the rubric proposes what
# each sheet IS (their people → contacts, their jobs → a pipeline module)
# and the run builds it. Kills "I'd have to rebuild everything".
from structure_import_router import router as structure_import_router
app.include_router(structure_import_router)
# Phase H.1 — Accounts Payable (bills + recurring bills)
from bills_router import router as bills_router
app.include_router(bills_router)
# THE SOURCING DESK stage 0 — a vendor as an entity instead of two free-text
# columns on a product. offerings.supplier_name/email stay as a cache of the
# primary link, and suppliers_router is the only thing that maintains them.
from suppliers_router import router as suppliers_router
app.include_router(suppliers_router)
# THE SOURCING DESK stage 1 - find vendors on the live web. Metered as an
# AI action on every tier, plus a per-business daily circuit breaker.
from sourcing_router import router as sourcing_router
app.include_router(sourcing_router)
# THE GRANTS ARC, lane 1 - federal opportunities from Grants.gov. NOT
# metered and not tier-gated: the API asks for no key, so there is
# nothing to bill, and charging for a free search would teach a
# practitioner that looking is expensive. Guarded by a rate limit only.
from grants_router import router as grants_router
app.include_router(grants_router)
# Phase I.1 — Double-entry General Ledger (backfill + verify)
from gl_router import router as gl_router
app.include_router(gl_router)
# Rails Arc 1 — the QuickBooks bridge (mapping layer + OAuth + journal push)
from quickbooks_router import router as quickbooks_router
from quickbooks_router import connect_router as quickbooks_connect_router
app.include_router(quickbooks_router)
app.include_router(quickbooks_connect_router)
# Rails Arc 4 — the unified audit log (append-only; reads owner-gated)
from audit_log import router as audit_router
app.include_router(audit_router)
# Rails demand-driven — e-sign via DocuSeal (proposal → signature → payment)
from docuseal_router import router as docuseal_router
app.include_router(docuseal_router)
# Rails demand-driven — receipt capture (Chief reads the photo)
from receipts_router import router as receipts_router
app.include_router(receipts_router)
# Document Intelligence — stored files finally get read (summarize / dates / ask / compare)
from doc_intelligence_router import router as docintel_router
app.include_router(docintel_router)
# Conflict-of-interest check — deterministic sweep; the check itself is the record
from conflicts_router import router as conflicts_router
app.include_router(conflicts_router)
# Document templates — nine data-aware documents into the approve → PDF → e-sign chain
from doc_templates_router import router as doctemplates_router
app.include_router(doctemplates_router)
# Rails demand-driven — payroll interest capture (Gusto, demand-gated)
from payroll_router import router as payroll_router
app.include_router(payroll_router)
# Session exit ramp (8/01) — strategy session end → setup plan
from setup_plan import router as setup_plan_router
app.include_router(setup_plan_router)
# Phase I.3 — Period closing
from accounting_periods_router import router as accounting_periods_router
app.include_router(accounting_periods_router)
# Phase I.3 PR2 — soft-lock audit trail
from period_overrides_router import router as period_overrides_router
app.include_router(period_overrides_router)
# Phase I.3 PR3 — accountant collaborators
from business_collaborators_router import router as business_collaborators_router
app.include_router(business_collaborators_router)
from business_users_router import router as business_users_router
app.include_router(business_users_router)
from entity_groups_router import router as entity_groups_router
app.include_router(entity_groups_router)
from launch_access import router as launch_access_router
app.include_router(launch_access_router)
# Approving a post, and scheduling what was approved — the door that
# satisfies the unattended gate in post_approval.py.
from content_approval import router as content_approval_router
app.include_router(content_approval_router)
# Arc 25 - practitioner referral loop (codes + attribution + rewards)
from referrals import router as referrals_router
app.include_router(referrals_router)
# Arc 26 - module composer (brand DNA -> deterministic section modules)
from site_composer import router as site_composer_router
app.include_router(site_composer_router)
# Arc 27 - e-commerce store (catalog page + multi-item Stripe checkout + orders)
from store_router import router as store_router
app.include_router(store_router)
# SCAN THE SHELF (2026-08-20) - identify a product from its barcode or a
# photo of its label. Read-only proposals + the barcode learning loop;
# registered after store_router because it imports its inventory helper.
from inventory_scan import router as inventory_scan_router
app.include_router(inventory_scan_router)
# SCAN THE SHELF rung two (2026-08-20) - the count session: one submit
# closes a stocktake, sets every counted product to what is on the shelf
# and answers with the variance.
from inventory_count import router as inventory_count_router
app.include_router(inventory_count_router)
# SCAN THE SHELF rung three (2026-08-20) - receiving: the tally that books
# in a delivery and closes the purchase order the reorder brain opened.
from inventory_receive import router as inventory_receive_router
app.include_router(inventory_receive_router)
# THE TILL (2026-08-20) - a counter sale IS an order (source='counter'),
# so it inherits the GL mapping, refunds, reports and audit triggers.
from counter_sale import router as counter_sale_router
app.include_router(counter_sale_router)
# Digital delivery (2026-07-31) - hosted product files + validated downloads
from store_files import router as store_files_router
app.include_router(store_files_router)
# Site Concierge (2026-08-01) - customer-facing website chat (NOT Chief):
# public widget/message/lead endpoints + operator settings/conversations.
# Registered BEFORE public_site_router so /public/concierge/* and
# /concierge/* never fall into the subdomain catch-all.
from site_concierge import router as site_concierge_router
app.include_router(site_concierge_router)
from rules_router import router as rules_router, proposals_router as chief_proposals_router
app.include_router(rules_router)
# Chief-in-your-pocket (2026-06-12) - Web Push (subscribe/test + senders)
from push_notifications import router as push_router
app.include_router(push_router)
app.include_router(chief_proposals_router)
# Phase F.1 — Stripe outbound contractor payments
from contractors_router import router as contractors_router
app.include_router(contractors_router)
# Phase VABI v1 — public read endpoint for vertical intelligence
app.include_router(vertical_intelligence_router)
# Phase VABI v1.5 — per-business overrides CRUD + Chief-driven generation
app.include_router(terminology_overrides_router)
# Workspace composer phase one — the registry, the five presets, the
# classifier and the override. See docs/WORKSPACE_COMPOSER_SPEC.md.
app.include_router(workspace_composer_router)
app.include_router(chief_suggestions_router)
app.include_router(business_profile_router)
app.include_router(practitioner_profile_router)
app.include_router(foundation_router)
# Pass 4.0a — Director Agent foundations
app.include_router(sparse_enrichment_router)
# Pass 4.0b — Director Agent: Critique loop
app.include_router(director_router)
# Pass 4.0b.5 — Slot system (image retrieval + management)
app.include_router(slot_router)
# Pass 4.0d PART 1 — Site content overrides (/chief/override*)
app.include_router(override_router)
# Pass 4.0d PART 2 — Chief unification (/chief/message, /chief/_diag/classify)
app.include_router(chief_executive_router)
# Pass 4.0g — Composer (/composer/_diag/*, /composer/_spike/*).
# Wired during the Pass 4.0g final merge to bring the multi-module
# pipeline into production. Endpoints are read-only diagnostics: route
# decision, hero composition, end-to-end pipeline, multi-module
# comparison page. Composer/router.py docstring previously flagged
# this wiring as "forward compatibility with the Pass 4.0g production
# wiring" — this is that wiring moment.
app.include_router(composer_router)
# Phase 4 of AUTH_PLAN — marketing-lead → user invite workflow.
# Owner-only triage panel (Settings → Leads) calls these endpoints.
from lead_admin import router as lead_admin_router, diag_router as lead_admin_diag_router
app.include_router(lead_admin_router)
app.include_router(lead_admin_diag_router)
# Mission Control / Platform Console — owner-only operator endpoints.
# Lives at /platform/* and powers the Mission Control module in the
# Tauri app.
from platform_console import router as platform_console_router
app.include_router(platform_console_router)
# Dev Bridge (2026-08-19) — Mission Control's Dev Desk dispatches dev
# tasks: the cloud lane fires @claude build issues, the local lane is
# polled by Solution Space on Kevin's machine. /platform/dev-desk/*
# (owner JWT) + /dev-bridge/* (device token / per-task report key).
from dev_bridge import router as dev_bridge_router
app.include_router(dev_bridge_router)
# The fix queue (2026-09-02) — support tickets ranked, dispatched into dev
# tasks, walked back when the fix ships, and answered by email.
# /platform/support/* (owner JWT) + /dev-bridge/tickets* (device token, so
# the ticket area in Solution Space renders without Kevin's JWT).
from support_router import router as support_queue_router
app.include_router(support_queue_router)
# Phase 5b of BILLING_PLAN — Stripe subscription billing.
# /billing/checkout (authed), /billing/portal (authed),
# /billing/webhook (Stripe signature-verified), /billing/status (open).
from stripe_billing import router as stripe_billing_router
app.include_router(stripe_billing_router)
# Campaigns Phase 1 (2026-07-21) — Chief-drafted marketing sequences
# over the existing email/SMS rails. /campaigns/* (all JWT-authed,
# ownership verified); the send sweep registers in startup() below.
from campaigns_router import router as campaigns_api_router
app.include_router(campaigns_api_router)
# S6 per-business email identity — /email-domain/* (owner-only). Domain
# lifecycle against Resend; sends resolve the custom from in email_sender.
from email_domains_router import router as email_domains_api_router
app.include_router(email_domains_api_router)
# Hardening pass 1 — data export + account/business deletion (GDPR
# portability + erasure). /account/export, DELETE /account/business/{id},
# DELETE /account. All JWT-authed, ownership verified server-side.
from account_lifecycle import router as account_lifecycle_router
app.include_router(account_lifecycle_router)
# Arc 29 fix — health routes MUST register before public_site, whose
# `/{path:path}` catch-all otherwise swallows /health* and returns its
# own "Not found" (the bug Kevin hit). Same discipline as booking/
# payments above. Handler bodies reference module globals (scheduler,
# BUSINESS_NAME, …) resolved at request time, so defining them here —
# above where those globals are assigned — is safe.
from fastapi import APIRouter as _APIRouter
from fastapi.responses import JSONResponse as _JSONResponse
_health_router = _APIRouter()


@_health_router.get("/health")
async def health():
    """Liveness: cheap, always 200 if the process is up."""
    return {
        "status": "running",
        "business": BUSINESS_NAME,
        "owner": OWNER_NAME,
        "active_projects": len(COMPLETED_PROJECTS),
        "scheduler": scheduler.running,
        "next_followup_check": str(scheduler.get_job("followup_check").next_run_time)
                               if scheduler.get_job("followup_check") else None,
    }


@_health_router.get("/health/ready")
async def health_ready():
    """Arc 29 — readiness probe: reaches dependencies + reports leader
    role and which optional integrations are configured. 503 when a hard
    dependency (Supabase) is unreachable so an uptime monitor can react."""
    import scheduler_lock
    checks: dict = {}
    supabase_ok = False
    try:
        import sb_clients
        r = sb_clients.sb_get_as_service("/businesses?select=id&limit=1")
        supabase_ok = r is not None
    except Exception as e:
        checks["supabase_error"] = str(e)[:200]
    checks["supabase"] = supabase_ok
    checks["role"] = process_role()
    checks["scheduler_running"] = scheduler.running
    checks["is_scheduler_leader"] = scheduler_lock.is_leader()

    # THE CHECK THE SPLIT CREATES A NEED FOR.
    #
    # A web replica reporting scheduler_running=false is correct and
    # says nothing about whether anything is scheduled. The lease does:
    # whichever process runs the scheduler refreshes it every RENEW_SEC,
    # so a lease older than a couple of ttls means NO replica anywhere is
    # running jobs — the silent failure this whole change makes possible.
    #
    # Reported, not folded into `ready`. A stale lease means the
    # scheduled work has stopped, not that this replica cannot serve
    # requests, and 503ing the web tier for it would turn a background
    # outage into a front-door one.
    try:
        checks["scheduler_lease_fresh"] = scheduler_lock.lease_is_fresh()
    except Exception as e:
        checks["scheduler_lease_fresh"] = None
        checks["scheduler_lease_error"] = str(e)[:120]
    checks["integrations"] = {
        "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "openai": bool(os.environ.get("OPENAI_API_KEY")),
        "stripe": bool(os.environ.get("STRIPE_SECRET_KEY")),
        "stripe_webhook": bool(os.environ.get("STRIPE_SIGNING_SECRET")
                               or os.environ.get("STRIPE_WEBHOOK_SECRET")),
        "resend": bool(os.environ.get("RESEND_API_KEY")),
        "resend_webhook_verified": bool(os.environ.get("RESEND_WEBHOOK_SECRET")),
        "plaid": bool(os.environ.get("PLAID_CLIENT_ID")),
        "push_vapid": bool(os.environ.get("VAPID_PRIVATE_KEY")),
        "sentry": bool(os.environ.get("SENTRY_DSN")),
        "billing_enforce": (os.environ.get("BILLING_ENFORCE") or "off").lower() == "on",
    }
    # A WEB REPLICA HAS NO SCHEDULER, AND THAT IS NOT AN OUTAGE.
    #
    # This line predates the role split and read `supabase_ok and
    # scheduler.running`, which was right when every process ran the
    # scheduler and became a trap the moment one could decline to. Set
    # PROCESS_ROLE=web and scheduler.running is false BY DESIGN — so
    # readiness would 503, Railway's healthcheck would fail, and the
    # entire web tier would never come up. The change meant to stop the
    # jobs running twenty times would instead have taken the front door
    # down.
    #
    # What this probe actually asks is whether the process is doing the
    # job it was configured to do. A web replica is ready without a
    # scheduler; a worker is not.
    scheduler_ok = scheduler.running or not runs_scheduled_jobs()
    ready = supabase_ok and scheduler_ok
    return _JSONResponse(status_code=200 if ready else 503,
                         content={"ready": ready, **checks})


app.include_router(_health_router)

# Auditor ledger links. MUST be above public_site_router: /public/audit/
# would otherwise be swallowed by its `/{path:path}` catch-all.
from auditor_portal import router as auditor_portal_router
app.include_router(auditor_portal_router)

# The agent-readable site API (2026-09-04): /public/agent/{slug}/… —
# services, per-date availability, and booking for a customer's agent.
# Same reason it sits here: the catch-all below would swallow it.
from agent_site import router as agent_site_router
app.include_router(agent_site_router)

# public_site_router MUST remain LAST — it defines `/` and `/{path:path}`
# catch-alls that would otherwise shadow every specific API route.
app.include_router(public_site_router)

# Lazy Anthropic client (beta-readiness audit 2026-07-13). This was the
# ONLY module-level API client in the repo — constructing it at import
# meant a missing/rotated ANTHROPIC_API_KEY took the ENTIRE backend down
# on boot (all ~60 routers, auth, booking, everything), not just the AI
# features. Now it's built on first use, so a key problem degrades the
# three legacy intake endpoints below and nothing else.
_anthropic_client: Optional["Anthropic"] = None


def client_messages_create(**kwargs):
    """Lazy accessor mirroring the old `client.messages.create(...)`
    call sites. Raises a clear error (caught by each endpoint) instead
    of failing at import."""
    global _anthropic_client
    if _anthropic_client is None:
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")
        _anthropic_client = llm_call.sdk_client(key=key)
    return _anthropic_client.messages.create(**kwargs)


OWNER_EMAIL = os.getenv("OWNER_EMAIL", "kevin@kmjcreative.com")
OWNER_NAME = os.getenv("OWNER_NAME", "Kevin McCloud Jr.")
BUSINESS_NAME = os.getenv("BUSINESS_NAME", "KMJ Creative Solutions")

# In production: replace with Supabase/DB
PENDING_FOLLOWUPS: list[dict] = []
COMPLETED_PROJECTS: list[dict] = []

# ─────────────────────────────────────────────────────────────
# SOLUTION TYPES (mirrors agentService.ts)
# ─────────────────────────────────────────────────────────────

PACKAGES = """
DONE-IN-A-DAY ($800, 1 day): Fast-track for churches/ministries/simple businesses.
THE CONNECT ($750–$1,000, 5–7 days): Connect tools, one automation, brand pass.
THE LAUNCHPAD ($1,500–$2,500, 10–14 days): Full brand, multi-page site, email automation.
THE FULL SOLUTION ($3,500–$6,000, 3–4 weeks): Everything + AI agent, full automation, 90-day support.
"""

# ─────────────────────────────────────────────────────────────
# AUTO-QUALIFY — runs when a form submission comes in
# ─────────────────────────────────────────────────────────────

async def auto_qualify_lead(submission: dict[str, str]) -> dict[str, Any]:
    """Call Claude to qualify a lead and draft a response email."""
    
    submission_text = "\n".join(f"{k}: {v}" for k, v in submission.items())
    
    system = f"""You are the 24/7 Intake Agent for {BUSINESS_NAME}, run by {OWNER_NAME}.
A new lead just submitted a contact form. Qualify them and draft a ready-to-send response.
{OWNER_NAME} will review this before sending. Write in his voice: warm, confident, never corporate.

{PACKAGES}

RESPOND ONLY IN VALID JSON:
{{
  "readinessScore": 8,
  "readinessLabel": "Ready | Almost Ready | Needs Nurturing",
  "recommendedSolution": "WEB_PRESENCE | BRAND_KIT | MARKETING_ENGINE | MINISTRY_PACKAGE | BUSINESS_SYSTEM",
  "recommendedPackage": "DONE-IN-A-DAY | THE CONNECT | THE LAUNCHPAD | THE FULL SOLUTION",
  "estimatedValue": "$X,XXX",
  "responseSubject": "email subject line",
  "responseBody": "complete ready-to-send response email from Kevin — warm, specific, clear next step",
  "internalNotes": "what Kevin should know before following up — read on them, red flags, budget signals",
  "urgencySignals": ["signals this lead has time pressure"],
  "nextAction": "Kevin's single most important next action"
}}"""

    response = client_messages_create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        system=system,
        messages=[{"role": "user", "content": f"New form submission:\n{submission_text}"}]
    )
    
    raw = response.content[0].text.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


async def notify_kevin(submission: dict, qualify_result: dict):
    """Send Kevin a notification with the qualified lead and draft response."""
    
    score = qualify_result.get("readinessScore", 0)
    label = qualify_result.get("readinessLabel", "Unknown")
    package = qualify_result.get("recommendedPackage", "")
    value = qualify_result.get("estimatedValue", "")
    next_action = qualify_result.get("nextAction", "")
    
    # Score emoji
    score_emoji = "🔥" if score >= 8 else "⚡" if score >= 6 else "🌱"
    
    # Notification payload — send to your email/SMS/Slack
    notification = {
        "type": "new_lead",
        "timestamp": datetime.now().isoformat(),
        "subject": f"{score_emoji} New Lead [{label}] — {submission.get('name', 'Unknown')} | {value}",
        "headline": f"{score_emoji} {label} ({score}/10) — {package} | {value}",
        "client_name": submission.get("name", "Unknown"),
        "client_email": submission.get("email", ""),
        "next_action": next_action,
        "internal_notes": qualify_result.get("internalNotes", ""),
        "urgency_signals": qualify_result.get("urgencySignals", []),
        "draft_email": {
            "subject": qualify_result.get("responseSubject", ""),
            "body": qualify_result.get("responseBody", ""),
        },
        "raw_submission": submission,
    }
    
    print(f"\n{'='*60}")
    print(f"NEW LEAD: {notification['subject']}")
    print(f"Next action: {next_action}")
    print(f"{'='*60}\n")
    
    # ── Write to file for the Solutionist Studio to pick up ──
    # The studio polls this directory for new lead notifications
    os.makedirs("./leads", exist_ok=True)
    filename = f"./leads/{datetime.now().strftime('%Y%m%d_%H%M%S')}_{submission.get('name', 'lead').replace(' ', '_')}.json"
    with open(filename, "w") as f:
        json.dump(notification, f, indent=2)
    
    # ── Optionally: POST to Supabase for the studio to read ──
    #
    # SERVICE ROLE, not the anon key. This wrote with SUPABASE_ANON_KEY
    # until 2026-09-01, which is the exact pattern docs/RLS_MODEL.md Rule 1
    # forbids: "Any server path using the anon key on a tenant-scoped table
    # breaks the moment its permissive policy is removed — this is exactly
    # what bit us." It was also the reason `leads` could not have RLS
    # switched on: enabling it would have silently killed this insert,
    # because the anon role would no longer pass any policy.
    #
    # Two smaller things this fixes on the way past. SUPABASE_ANON_KEY is
    # not a variable this project sets — .env.example documents
    # SUPABASE_ANON, and 42 call sites use that name against 4 that reach
    # for this one. So on any environment following .env.example, the
    # `if` below was simply false and every lead silently skipped the
    # write with no error, no log, and no row. And a failed write only
    # ever printed inside the except, so a 401 from a revoked grant would
    # have looked identical to success from the outside.
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_key:
        print("Supabase write skipped: SUPABASE_SERVICE_ROLE_KEY not set")
    if supabase_url and supabase_key:
        try:
            async with httpx.AsyncClient() as http:
                await http.post(
                    f"{supabase_url}/rest/v1/leads",
                    headers={
                        "apikey": supabase_key,
                        "Authorization": f"Bearer {supabase_key}",
                        "Content-Type": "application/json",
                        "Prefer": "return=minimal"
                    },
                    json={
                        "client_name": notification.get("client_name"),
                        "client_email": notification.get("client_email"),
                        "organization": submission.get("organization", ""),
                        "business_type": submission.get("business_type", ""),
                        "readiness_score": qualify_result.get("readinessScore", 0),
                        "draft_email": qualify_result.get("responseBody", ""),
                        "internal_notes": qualify_result.get("internalNotes", ""),
                        "urgency": qualify_result.get("urgencySignals", [""]),
                        "status": "pending",
                        "raw_answers": submission
                    }
                )
        except Exception as e:
            print(f"Supabase write failed: {e}")
    
    return notification


# ─────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────

@app.post("/webhook/netlify-form")
async def netlify_form_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Netlify sends form submissions here automatically.
    Set this URL in Netlify: Site Settings → Forms → Notifications → Webhook
    """
    try:
        body = await request.json()
    except Exception:
        form_data = await request.form()
        body = dict(form_data)
    
    # Netlify wraps form data in a 'data' key
    submission = body.get("data", body)
    
    if not submission:
        raise HTTPException(status_code=400, detail="No form data received")
    
    # Normalize field names from preflight form
    if 'client_name' in submission and 'name' not in submission:
        submission['name'] = submission['client_name']
    if 'email' not in submission and 'client_email' in submission:
        submission['email'] = submission['client_email']

    print(f"📬 New form submission: {submission.get('name', submission.get('client_name', 'Unknown'))}")
    
    # Run qualification in background — don't make Netlify wait
    background_tasks.add_task(process_lead, dict(submission))
    
    return {"status": "received", "message": "Lead processing started"}


async def process_lead(submission: dict):
    """Background task: qualify + notify."""
    try:
        qualify_result = await auto_qualify_lead(submission)
        await notify_kevin(submission, qualify_result)
        print(f"✅ Lead processed: {submission.get('name', 'Unknown')} — {qualify_result.get('readinessLabel')}")
    except Exception as e:
        print(f"❌ Lead processing failed: {e}")


@app.post("/webhook/manual-lead")
async def manual_lead(request: Request, background_tasks: BackgroundTasks):
    """
    Manually submit a lead for qualification.
    Use from Solutionist Studio when you get a walk-in or phone inquiry.
    """
    submission = await request.json()
    background_tasks.add_task(process_lead, submission)
    return {"status": "queued"}


@app.get("/leads/pending")
async def get_pending_leads():
    """Return unreviewed leads for the studio to display."""
    leads = []
    leads_dir = "./leads"
    if os.path.exists(leads_dir):
        for f in sorted(os.listdir(leads_dir), reverse=True)[:20]:
            if f.endswith(".json"):
                with open(os.path.join(leads_dir, f)) as fp:
                    leads.append(json.load(fp))
    return {"leads": leads}


@app.post("/projects/complete")
async def mark_project_complete(request: Request):
    """
    Call this when a project is delivered.
    Schedules automatic follow-up sequence.
    """
    data = await request.json()
    project = {
        "id": data.get("projectId"),
        "clientName": data.get("clientName"),
        "clientEmail": data.get("clientEmail"),
        "packageDelivered": data.get("packageDelivered"),
        "completedAt": datetime.now().isoformat(),
        "followups": [
            {"day": 3,  "type": "Check-in",            "sent": False},
            {"day": 7,  "type": "Feedback Request",     "sent": False},
            {"day": 30, "type": "Testimonial Request",  "sent": False},
            {"day": 60, "type": "Upsell",               "sent": False},
        ]
    }
    COMPLETED_PROJECTS.append(project)
    print(f"📋 Project marked complete: {data.get('clientName')} — follow-up sequence scheduled")
    return {"status": "scheduled", "followups": len(project["followups"])}


# ─────────────────────────────────────────────────────────────
# SCHEDULER — runs every hour, checks for due follow-ups
# ─────────────────────────────────────────────────────────────

async def generate_followup_email(project: dict, followup_type: str) -> dict:
    """Generate a follow-up email for a specific touch."""
    
    system = f"""You are writing a follow-up email on behalf of {OWNER_NAME} at {BUSINESS_NAME}.
Write in his voice — warm, genuine, never salesy or corporate.
This is a {followup_type} email. Keep it short (3-5 sentences max).
RESPOND ONLY IN VALID JSON: {{"subject": "...", "body": "full email text"}}"""

    msg = f"""Client: {project['clientName']}
Package delivered: {project['packageDelivered']}
Days since delivery: {followup_type}
Type: {followup_type}"""

    response = client_messages_create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system=system,
        messages=[{"role": "user", "content": msg}]
    )
    raw = response.content[0].text.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


async def check_followup_sequences():
    """Runs every hour. Finds due follow-ups and generates emails."""
    now = datetime.now()
    due_count = 0
    
    for project in COMPLETED_PROJECTS:
        completed_at = datetime.fromisoformat(project["completedAt"])
        
        for followup in project["followups"]:
            if followup["sent"]:
                continue
            
            due_date = completed_at + timedelta(days=followup["day"])
            if now >= due_date:
                print(f"⏰ Follow-up due: {followup['type']} for {project['clientName']}")
                
                try:
                    email = await generate_followup_email(project, followup["type"])
                    
                    # Write to leads dir for studio to pick up
                    os.makedirs("./followups", exist_ok=True)
                    filename = f"./followups/{now.strftime('%Y%m%d_%H%M%S')}_{project['clientName'].replace(' ', '_')}_{followup['type'].replace(' ', '_')}.json"
                    with open(filename, "w") as f:
                        json.dump({
                            "type": "followup",
                            "followupType": followup["type"],
                            "client": project,
                            "email": email,
                            "dueAt": due_date.isoformat(),
                            "generatedAt": now.isoformat(),
                        }, f, indent=2)
                    
                    followup["sent"] = True
                    due_count += 1
                    print(f"✅ Follow-up email drafted: {followup['type']} for {project['clientName']}")
                    
                except Exception as e:
                    print(f"❌ Follow-up generation failed: {e}")
    
    if due_count > 0:
        print(f"📬 {due_count} follow-up(s) ready for review")


# ─────────────────────────────────────────────────────────────
# STARTUP / SHUTDOWN
# ─────────────────────────────────────────────────────────────

scheduler = AsyncIOScheduler()


# ─── Process role ────────────────────────────────────────────────────
#
# One image, one start command, two jobs. PROCESS_ROLE decides whether
# this replica RUNS the scheduled work:
#
#   all     (default) web + scheduler in one process. Exactly today's
#           behaviour, so an unset variable changes nothing.
#   web     serves HTTP, runs NO scheduled jobs.
#   worker  runs the jobs. Still serves HTTP, deliberately — Railway
#           health-checks a port, and giving the worker the same app
#           means one image, one command, and /health tells you which
#           role you are looking at instead of you having to guess.
#
# WHY THIS IS THE WHOLE CHANGE. Leader election already exists (Arc 29):
# renew_tick refreshes a lease and every other job is .gate()d to the
# single leader, so extra replicas were already safe. What was NOT
# possible was a replica that deliberately runs no jobs. Registering a
# job and never calling scheduler.start() achieves exactly that, which
# is why this is a one-branch change rather than a second entrypoint.
#
# THE FAILURE MODE THAT MATTERS is not double-execution — the lease
# handles that. It is NOBODY running the scheduler: set every service to
# `web`, forget the worker, and the jobs stop with every health check
# still green. That is why the default is `all`, why the role is printed
# loudly at boot, and why /health/ready now reports whether the lease is
# actually being refreshed by SOMEONE.
def process_role() -> str:
    r = (os.environ.get("PROCESS_ROLE") or "all").strip().lower()
    return r if r in ("all", "web", "worker") else "all"


def runs_scheduled_jobs() -> bool:
    return process_role() in ("all", "worker")

# Jobs whose interval is at least this long get an explicit first run.
# Below it, the job fires soon enough after boot that the deploy clock
# does not matter.
STAGGER_THRESHOLD_MINUTES = int(os.environ.get("SCHEDULER_STAGGER_THRESHOLD_MIN", "60"))
STAGGER_SLOT_MINUTES = int(os.environ.get("SCHEDULER_STAGGER_SLOT_MIN", "2"))


def stagger_long_interval_first_runs(sched, *, now=None) -> list:
    """Give every long-interval job a first run shortly after boot.

    APScheduler schedules an interval job's FIRST run at now + interval,
    and that clock restarts with the process. On a repo that deploys
    several times a day, a 24-hour job is reset before it ever fires —
    it exists, it is registered, it is visible in the job list, and it
    never runs once. `stripe_usage_report` is on that list, which means
    metered usage was not reaching Stripe.

    Two jobs already passed next_run_time by hand. The problem with
    fixing this at the call site is that it has to be remembered twenty
    times and then again for the twenty-first job, silently, by whoever
    adds it. Doing it here means a new job is covered by existing code.

    Deliberate first runs are left alone: a job whose next_run_time is
    already meaningfully sooner than now + interval was set on purpose,
    and this must not overwrite that reasoning. Runs are staggered so a
    boot does not fire everything at once.

    Returns the ids it moved, for logging and for tests.
    """
    from datetime import datetime as _d, timedelta as _t, timezone as _z
    try:
        from apscheduler.triggers.interval import IntervalTrigger
    except Exception:
        return []

    now = now or _d.now(_z.utc)
    threshold = _t(minutes=STAGGER_THRESHOLD_MINUTES)
    moved, slot = [], 0
    for job in sched.get_jobs():
        trigger = getattr(job, "trigger", None)
        if not isinstance(trigger, IntervalTrigger):
            continue  # cron jobs already have a real wall-clock time
        interval = getattr(trigger, "interval", None)
        if interval is None or interval < threshold:
            continue
        scheduled = getattr(job, "next_run_time", None)
        if scheduled is not None and scheduled < (now + interval) - _t(seconds=30):
            continue  # someone chose this; leave it
        slot += 1
        try:
            job.modify(next_run_time=now + _t(minutes=STAGGER_SLOT_MINUTES * slot))
            moved.append(job.id)
        except Exception as e:
            print(f"   [warn] could not set first run for {job.id}: {e}")
    return moved


@app.on_event("startup")
async def startup():
    # Re-arm the URL-credential redaction. The import-time install above
    # is the one that matters under the uvicorn CLI (logging is
    # configured before the app module is imported), but uvicorn applies
    # its logging dictConfig to the `uvicorn.access` logger, and
    # dictConfig REPLACES a logger's filter list. If the two ever run in
    # the other order the filter would be silently dropped — and a
    # security control whose failure mode is silence gets a second,
    # order-independent install. It is idempotent.
    _install_log_redaction()

    # Arc 29 — leader election. renew_tick runs on EVERY replica and
    # refreshes the lease; all other jobs are wrapped with .gate() so
    # they execute on the single leader only. Single-replica deploys are
    # unaffected (the lock fail-safes to leader). try_acquire() once now
    # so the first job interval already knows its role.
    import scheduler_lock
    try:
        scheduler_lock.try_acquire()
    except Exception as _e:
        print(f"   [warn] initial lease acquire failed (defaulting leader): {_e}")

    # Action Ledger: publish the controlled vocabulary. Idempotent upsert
    # from action_registry + the event catalog, so a verb added in code is
    # registered by the next boot and its rows stop being stamped
    # verb_registered=false. Never fatal — the ledger records an
    # unfamiliar verb rather than losing the action.
    try:
        import audit_log as _al
        print(f"   [ledger] vocabulary synced: {_al.sync_action_types()} verbs")
    except Exception as _e:
        print(f"   [warn] ledger vocabulary sync failed: {_e}")

    # Hand-built sites (sites/<dir>/build.py) install themselves from the
    # repo on boot, hash-gated so an unchanged deploy writes nothing.
    # Background thread; never blocks or fails startup (site_sync.py).
    try:
        import site_sync as _site_sync
        _site_sync.sync_all_async()
    except Exception as _e:
        print(f"   [warn] site sync did not start: {_e}")

    scheduler.add_job(scheduler_lock.renew_tick, "interval",
                      seconds=scheduler_lock.RENEW_SEC, id="scheduler_lease_renew")
    g = scheduler_lock.gate
    scheduler.add_job(g("followup_check", check_followup_sequences),
                      "interval", hours=1, id="followup_check")
    # LGS Phase 3: drain the workflow_runs queue (Fork 7 — in-process cron, not a
    # frontend heartbeat). Internal workflows only for now; reactive/webhook paths
    # stay gated behind Stripe signature verification (Fork 21) + the connector slice.
    try:
        import workflow_engine
        scheduler.add_job(g("workflow_drain", workflow_engine.drain_tick), "interval", minutes=5, id="workflow_drain")
    except Exception as e:
        print(f"   [warn] workflow drain job not scheduled: {e}")
    # Automation Center (2026-07-03): Autopilot on a clock. The sweep was
    # chat-request-driven, so Full Auto did nothing while the practitioner
    # was away. Kill switch: AUTOPILOT_SWEEP=off.
    try:
        from chief_of_staff import autopilot_sweep_tick
        scheduler.add_job(g("autopilot_sweep", autopilot_sweep_tick),
                          "interval", minutes=10, id="autopilot_sweep")
    except Exception as e:
        print(f"   [warn] autopilot sweep job not scheduled: {e}")
    # Phase I.2 — GL live sync: drain the gl_sync_queue (no LISTEN/NOTIFY —
    # PostgREST only) + periodic divergence reconciliation. Env kill-switch:
    # GL_SYNC_POLLER=off disables both jobs without a code change.
    try:
        import os as _os
        if (_os.environ.get("GL_SYNC_POLLER") or "on").lower() != "off":
            import gl_engine as _gl
            scheduler.add_job(g("gl_drain", _gl.drain_tick), "interval", minutes=1, id="gl_drain")
            # Arc 19 — daily metered-usage report to Stripe (no-ops unless
            # BILLING_ENFORCE=on + Stripe configured).
            import usage_metering as _um
            scheduler.add_job(g("stripe_usage_report", _um.stripe_report_tick), "interval", hours=24,
                              id="stripe_usage_report")
            # Arc 20B — invoice_overdue rule trigger (daily; exactly-once
            # per invoice via the due_date == today-N window).
            import rules_engine as _rules
            scheduler.add_job(g("rules_overdue_tick", _rules.overdue_tick), "interval", hours=24,
                              id="rules_overdue_tick")
            # Chief-in-your-pocket - morning brief push, 13:00 UTC daily
            # (per-business timezones are a follow-on).
            import push_notifications as _push
            scheduler.add_job(g("push_morning_brief", _push.morning_brief_tick), "cron", hour=13, minute=0,
                              id="push_morning_brief")
            scheduler.add_job(g("gl_divergence", _gl.divergence_tick), "interval", minutes=15, id="gl_divergence")
            # Email Connect — pull recent INBOX mail from connected Google
            # mailboxes. 10 minutes because "did anyone email me?" is a
            # question people ask about the last hour, not the last day;
            # the per-run cap is what keeps a busy mailbox bounded, not a
            # long interval. Below the stagger threshold on purpose: it
            # fires soon enough after a deploy that the reset clock
            # APScheduler applies to interval jobs does not matter.
            import gmail_sync as _gmail
            scheduler.add_job(g("gmail_sync", _gmail.sync_tick), "interval",
                              minutes=10, id="gmail_sync")
            # Hermes (2026-07-04) — the comms watcher: hourly deterministic
            # pass over the SMS/email rails; findings → platform_changelog
            # → Business Chief snapshot. One brain, many senses.
            import hermes_agent as _hermes
            scheduler.add_job(g("hermes_tick", _hermes.hermes_tick), "interval", hours=1,
                              id="hermes_tick")
            # Email domain drift (setup room, Phase 1) — hourly re-check of
            # every VERIFIED sending domain. Without it a DNS record that
            # vanishes flips sends back to the platform address in
            # silence; the operator's "Verified" badge stays green and
            # nobody is told. Only changes are written.
            import email_domain_monitor as _edm
            scheduler.add_job(g("email_domain_monitor", _edm.monitor_tick), "interval",
                              hours=1, id="email_domain_monitor")
    except Exception as e:
        print(f"   [warn] GL sync jobs not scheduled: {e}")
    # A2P automated alerts (2026-07-07, campaign approved) — hourly
    # appointment-reminder sweep over sessions 22-26h out. Quiet hours,
    # consent rule, event-based dedupe + per-business toggle all live in
    # sms_alerts. Kill switch: SMS_ALERTS_ENABLED=0.
    try:
        import sms_alerts as _sms_alerts
        scheduler.add_job(g("sms_reminder_sweep", _sms_alerts.reminder_sweep),
                          "interval", hours=1, id="sms_reminder_sweep")
    except Exception as e:
        print(f"   [warn] sms reminder sweep not scheduled: {e}")
    # Dedicated numbers (2026-09-02) — hourly: hand back lines whose
    # release grace window has passed (SMS_NUMBER_RELEASE_GRACE_DAYS).
    try:
        import sms_numbers_router as _sms_numbers
        scheduler.add_job(g("sms_number_release_sweep", _sms_numbers.release_sweep),
                          "interval", hours=1, id="sms_number_release_sweep")
    except Exception as e:
        print(f"   [warn] sms number release sweep not scheduled: {e}")
    # THE LEAD ARC PR 2 (2026-08-14) — the notification engine, which
    # until now was imported as a ROUTER ONLY.
    #
    # `check_urgent`, `morning_brief`, `midday_ping` and
    # `evening_summary` existed, were reachable over HTTP, and nothing
    # in the codebase ever called them: not a scheduled job, not the
    # frontend. Meanwhile NotificationCenter.tsx shipped a settings
    # toggle for each of the four. Switches for alarms that did not
    # fire — and the hot-lead alert is one of them, so a lead could
    # arrive scored 90 and the system stayed silent.
    #
    # Cadence: the urgent check runs at URGENT_LOOKBACK_MINUTES so a
    # trigger cannot age out of the window between passes; it is cheap
    # because check_urgent_for_all pre-filters platform-wide before
    # touching any tenant. The three briefs are cron in UTC — 13:00 is
    # 9am ET / 6am PT, the same compromise push_notifications already
    # makes, and businesses do not store a timezone yet (Arc note in
    # push_notifications). Per-business local time is the follow-on.
    #
    # Kill switch: NOTIF_JOBS=off.
    if (os.environ.get("NOTIF_JOBS") or "on").strip().lower() != "off":
        try:
            import notification_engine as _notif
            scheduler.add_job(g("notif_urgent_check", _notif.check_urgent_for_all),
                              "interval", minutes=_notif.URGENT_LOOKBACK_MINUTES,
                              id="notif_urgent_check")
            scheduler.add_job(g("notif_morning_brief", _notif.generate_morning_brief_for_all),
                              "cron", hour=13, minute=5, id="notif_morning_brief")
            scheduler.add_job(g("notif_midday_ping", _notif.generate_midday_ping_for_all),
                              "cron", hour=17, minute=5, id="notif_midday_ping")
            scheduler.add_job(g("notif_evening_summary", _notif.generate_evening_summary_for_all),
                              "cron", hour=23, minute=5, id="notif_evening_summary")
            # THE LEAD ARC PR 5 — the lead nobody answered. Hourly, but
            # it raises at most ONE alert per business per DAY and only
            # inside waking hours. The frequency is so the first alert
            # lands soon after the threshold is crossed, not so the
            # practitioner gets reminded twelve times.
            scheduler.add_job(g("notif_unanswered_leads", _notif.unanswered_lead_sweep),
                              "interval", hours=1, id="notif_unanswered_leads")
        except Exception as e:
            print(f"   [warn] notification engine jobs not scheduled: {e}")
    # THE LEAD ARC PR 4 (2026-08-14) — the first-response clock.
    #
    # Nothing measured how long a lead waited before anyone answered.
    # This derives it from the records the outbound paths already leave
    # — an outbound SMS, an agent_queue row marked sent, a spine event,
    # a session, a status moved off 'lead' — rather than stamping it at
    # six send sites, one of which is the FRONTEND. A missed call site
    # would read as a lead nobody ever answered, and a false alarm is
    # the fastest way to teach someone to ignore a real one.
    #
    # Every 15 minutes: fresh enough for an alarm measured in hours, and
    # unanswered leads are re-scanned every pass on purpose, because a
    # response can still arrive. Kill switch: LEAD_RESPONSE_JOB=off.
    if (os.environ.get("LEAD_RESPONSE_JOB") or "on").strip().lower() != "off":
        try:
            import lead_response as _lead_response
            scheduler.add_job(g("lead_response_reconcile",
                                _lead_response.reconcile_tick),
                              "interval", minutes=15,
                              id="lead_response_reconcile")
        except Exception as e:
            print(f"   [warn] lead response reconcile not scheduled: {e}")
    # THE REORDER BRAIN (2026-08-18) — stock at/below its per-offering
    # reorder point raises ONE Chief notification per business whose tap
    # drafts the purchase order. Hourly so the alert lands soon after the
    # crossing, but a 72h dedup + the reorder_pending_at stamp mean a
    # standing condition never nags. Waking-hours guard inside.
    # Kill switch: REORDER_SWEEP=off.
    if (os.environ.get("REORDER_SWEEP") or "on").strip().lower() != "off":
        try:
            import reorder_engine as _reorder
            scheduler.add_job(g("reorder_sweep",
                                _reorder.low_stock_reorder_sweep),
                              "interval", hours=1, id="reorder_sweep")
        except Exception as e:
            print(f"   [warn] reorder sweep not scheduled: {e}")
    # Chief Layers arc (2026-07-09) — the weekly longitudinal insight
    # engine (Opus lane; eligibility + cadence + per-tick cap inside).
    # Kill switch: CHIEF_INSIGHTS=off.
    try:
        import chief_insights as _chief_insights
        scheduler.add_job(g("chief_insights", _chief_insights.insights_tick),
                          "interval", hours=6, id="chief_insights")
    except Exception as e:
        print(f"   [warn] chief insights job not scheduled: {e}")
    # Feed 2 (LAYER_TWO_ARCHITECTURE §6, 2026-07-27) — the cross-account
    # distillation job: what businesses in a vertical teach Chief becomes
    # knowledge the next business in that vertical starts with. Daily, one
    # vertical per run (spend stays flat as verticals multiply). The
    # k-anonymity floor and the per-business contribution toggle live
    # inside vertical_distill. Kill switch: FEED2=off.
    try:
        import vertical_distill as _vdistill
        scheduler.add_job(g("feed2_distill", _vdistill.tick),
                          "interval", hours=24, id="feed2_distill")
    except Exception as e:
        print(f"   [warn] feed2 distillation job not scheduled: {e}")
    # Feed 1 and Feed 1b → rows. Both project Python source-of-truth into
    # vertical_knowledge; both are diff-first, so the steady state is one
    # cheap read per vertical and no embeddings.
    #
    # CRON, NOT INTERVAL — and that is the whole point of this block.
    #
    # An interval job's first run is now+interval and the clock restarts
    # with the process. stagger_long_interval_first_runs() exists to fix
    # exactly that, and it does: it hands every long-interval job an
    # explicit next_run_time at boot. But the slots are
    # STAGGER_SLOT_MINUTES apart and CUMULATIVE, so a job late in the
    # registration order gets ~20-25 minutes, not two. On 2026-08-31 the
    # worker armed twelve jobs; vertical_curate was eleventh, came due at
    # 11:16:32, and a merge redeployed the worker at 11:16:09 — twenty
    # three seconds early. Its sibling vertical_seed, one slot and two
    # minutes ahead, fired and wrote its rows. The stagger did not fail;
    # it shrank the starvation window from 168h to ~24min, which is still
    # shorter than the gap between merges on a busy afternoon.
    #
    # A cron trigger has a real wall-clock time, so a redeploy does not
    # reset it — and stagger_long_interval_first_runs deliberately skips
    # cron jobs for that reason. DAILY rather than weekly because the job
    # is nearly free when there is nothing new, and because a weekly
    # cadence means an edit to a profile or playbook can sit a week before
    # it reaches Chief. Offset by ten minutes so the two never contend.
    #
    # Kill switch (both): VERTICAL_KNOWLEDGE=off.
    try:
        import vertical_knowledge as _vk
        scheduler.add_job(g("vertical_seed", _vk.seed_tick),
                          "cron", hour=4, minute=10, id="vertical_seed")
    except Exception as e:
        print(f"   [warn] vertical seed job not scheduled: {e}")
    # Feed 1b differs from the seeder in one way that matters: these rows
    # are RETRIEVED. build_vertical_learned_block reads curated + learned,
    # so this tick is the step that makes an edit to vertical_playbook
    # actually reach Chief — which is why it is the one that must not be
    # starved.
    try:
        import vertical_playbook as _vpb
        scheduler.add_job(g("vertical_curate", _vpb.curate_tick),
                          "cron", hour=4, minute=20, id="vertical_curate")
    except Exception as e:
        print(f"   [warn] vertical curate job not scheduled: {e}")
    # One calendar (2026-07-10) — mirror bookings into sessions so the
    # calendar, Chief's context, and SMS reminders all see them.
    # Kill switch: BOOKING_SESSION_SYNC=off.
    try:
        from booking_widget_router import booking_session_sync_tick as _bsync
        scheduler.add_job(g("booking_session_sync", _bsync),
                          "interval", minutes=10, id="booking_session_sync")
    except Exception as e:
        print(f"   [warn] booking-session sync not scheduled: {e}")
    # "Schedule anything" (2026-07-10) — Chief's deferred actions:
    # every minute, execute due chief_scheduled_actions rows through
    # the same ACTION_HANDLERS registry. Kill switch: CHIEF_SCHEDULER=off.
    try:
        import chief_scheduler as _chief_sched
        scheduler.add_job(g("chief_scheduled", _chief_sched.due_tick),
                          "interval", minutes=1, id="chief_scheduled")
    except Exception as e:
        print(f"   [warn] chief scheduled-actions job not scheduled: {e}")
    # Campaigns Phase 1 (2026-07-21) — execute due campaign touches
    # through the shared email/SMS rails (suppression + consent + quiet
    # hours inside). Kill switch: CAMPAIGNS=off.
    try:
        import campaigns_router as _campaigns
        scheduler.add_job(g("campaigns_tick", _campaigns.campaigns_tick),
                          "interval", minutes=1, id="campaigns_tick")
    except Exception as e:
        print(f"   [warn] campaigns sweep not scheduled: {e}")
    # Chief Layers arc — trusted-autonomy sweep: executes pending
    # proposals ONLY in categories the practitioner explicitly granted
    # after graduation (Trust Track). Kill switch: TRUSTED_AUTONOMY=off.
    # Watchdog arc (2026-07-11) — the system watches itself hourly:
    # services, DB latency, webhook backlog, ticket/build load, error
    # pressure; criticals push to the platform owner's phone (deduped).
    # Kill switch: PLATFORM_WATCHDOG=off.
    try:
        import platform_watchdog as _watchdog
        scheduler.add_job(g("platform_watchdog", _watchdog.watchdog_tick),
                          "interval", hours=1, id="platform_watchdog")
    except Exception as e:
        print(f"   [warn] platform watchdog not scheduled: {e}")
    try:
        from rules_router import trusted_sweep_tick as _trusted_tick
        scheduler.add_job(g("trusted_proposals", _trusted_tick),
                          "interval", minutes=10, id="trusted_proposals")
    except Exception as e:
        print(f"   [warn] trusted autonomy sweep not scheduled: {e}")
    # Balance surface (2026-07-31) — nightly drawdown sweep: yesterday's
    # completed sessions each consume one prepaid session (idempotent via
    # ledger session_id) + expiry warnings. Kill switch: BALANCE_SWEEP=off.
    try:
        import balance_sweep as _bsweep
        scheduler.add_job(g("balance_sweep", _bsweep.sweep_tick),
                          "cron", hour=9, minute=15, id="balance_sweep")
    except Exception as e:
        print(f"   [warn] balance sweep not scheduled: {e}")
    # Action Ledger Stage 5 (2026-08-07) — anchor every tenant that has
    # unanchored rows, to every configured provider. Two networks protect
    # against one failing; they do nothing about the likeliest failure,
    # which was nobody anchoring at all. A gap cannot be repaired later —
    # you cannot anchor last month at last month's timestamp — so this
    # bounds how long a record can sit unprovable.
    # Kill switch: LEDGER_ANCHOR_SCHEDULE=off. Cadence:
    # LEDGER_ANCHOR_INTERVAL_HOURS (default 6).
    try:
        import anchor_scheduler as _anchor_sched
        import ledger_anchor as _la
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz
        scheduler.add_job(g("ledger_anchor_sweep", _anchor_sched.sweep_tick),
                          "interval", hours=_la.schedule_interval_hours(),
                          id="ledger_anchor_sweep",
                          # AN INTERVAL JOB'S FIRST RUN IS now + interval,
                          # and the timer restarts with the process. On a
                          # repo that deploys several times a day, a 6h
                          # interval would be reset before it ever fired —
                          # the sweep would exist and never run once. An
                          # explicit first run a few minutes after boot is
                          # what makes the schedule real. Late enough to
                          # stay out of the boot storm; a no-op anyway when
                          # there is nothing new to anchor, so a redeploy
                          # loop costs two queries a time.
                          next_run_time=_dt.now(_tz.utc) + _td(minutes=3))
        # The Bitcoin upgrade tick — a SEPARATE clock on purpose. The
        # sweep is driven by new ledger activity; this is driven by
        # Bitcoin block times and has work to do even when nothing at
        # all is happening on the platform. Folding it into the sweep
        # would leave a quiet practice's proofs `submitted` forever,
        # which is the exact bug it exists to fix.
        scheduler.add_job(g("ledger_anchor_upgrade", _anchor_sched.upgrade_tick),
                          "interval", hours=1, id="ledger_anchor_upgrade",
                          next_run_time=_dt.now(_tz.utc) + _td(minutes=5))
    except Exception as e:
        print(f"   [warn] ledger anchor sweep not scheduled: {e}")
    # Lifecycle emails (2026-09-01) — the daily pass that tells a
    # practitioner their trial ends soon / has ended. Once per business
    # per email, stamped in businesses.settings; quiet while enforcement
    # is off. 14:30 UTC = a working-morning inbox across the US.
    # Kill switch: LIFECYCLE_EMAILS=off.
    try:
        import lifecycle_emails as _lifecycle
        scheduler.add_job(g("lifecycle_emails", _lifecycle.sweep_tick),
                          "cron", hour=14, minute=30, id="lifecycle_emails")
        # The week (2026-09-02): day-three and day-seven beats, once each.
        scheduler.add_job(g("week_beats", _lifecycle.week_beats_tick),
                          "cron", hour=14, minute=45, id="week_beats")
    except Exception as e:
        print(f"   [warn] lifecycle email sweep not scheduled: {e}")

    _staggered = stagger_long_interval_first_runs(scheduler)
    if _staggered:
        print(f"   [scheduler] first run armed for {len(_staggered)} long-interval "
              f"job(s): {', '.join(_staggered)}")
    if runs_scheduled_jobs():
        scheduler.start()
    else:
        # Jobs are registered above and simply never fire: an APScheduler
        # that was not started runs nothing. Cheaper and far less
        # error-prone than maintaining a second list of what a web
        # replica may schedule, which would drift the first time somebody
        # adds a job.
        print(f"   [role] {process_role()} — scheduler NOT started; a worker "
              f"replica must be running or NOTHING is scheduled")
    print(f"🚀 KMJ Intake Automation running  [role={process_role()}]")
    print(f"   Owner: {OWNER_NAME} | {BUSINESS_NAME}")
    print(f"   Scheduler: follow-ups hourly + workflow drain every 5 min")
    print(f"   Webhook: POST /webhook/netlify-form")


@app.on_event("shutdown")
async def shutdown():
    # .shutdown() raises SchedulerNotRunningError on a web replica, which
    # would turn every graceful stop into a noisy failed shutdown.
    if scheduler.running:
        scheduler.shutdown()



# ─────────────────────────────────────────────────────────────
# STRATEGIC PULSE — live web research briefing
# ─────────────────────────────────────────────────────────────

@app.post("/pulse")
async def run_pulse(request: Request):
    """
    Strategic Pulse Agent v2 — with live web search + observation context.
    Called automatically by Solutionist Studio on app open (morning window).
    Reads accumulated observations from the observer layer.
    Returns full briefing JSON.
    """
    # Anonymous, and the most expensive single request the platform
    # serves — a Sonnet call at 4k tokens with five forced web searches.
    #
    # spend_guard grew a per-tenant ceiling, and this endpoint is exactly
    # the case it CANNOT help with: an anonymous caller has no business
    # to bill, so the spend is unattributed and counts only toward the
    # PLATFORM ceiling. An unrated loop here therefore still does what it
    # always did — exhausts the shared cap and takes Chief offline for
    # every customer at once, for about fifty dollars. The rate limit
    # below is the only thing standing in front of that.
    #
    # Keyed on trusted_client_ip — the LAST X-Forwarded-For hop, which
    # Railway appends — not client_ip, which is the first hop and
    # therefore whatever the caller typed. On an unauthenticated surface
    # the limiter is a control rather than a courtesy, and a control
    # keyed on a value the attacker chooses is decorative. allow_strict
    # so that a limiter error denies instead of permitting.
    if not rate_limit.allow_strict("pulse", rate_limit.trusted_client_ip(request)):
        raise HTTPException(
            status_code=429, detail="Too many requests — try again shortly.",
            headers={"Retry-After": str(rate_limit.retry_after("pulse"))})

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    owner_name      = data.get("ownerName", "Kevin")
    business_name   = data.get("businessName", "KMJ Creative Solutions")
    income_this_month   = data.get("incomeThisMonth", 0)
    income_goal         = data.get("incomeGoal", 7000)
    active_projects     = data.get("activeProjects", 0)
    total_projects      = data.get("totalProjects", 0)
    completed_projects  = data.get("completedProjects", 0)
    pending_proposals   = data.get("pendingProposals", 0)
    pending_invoices    = data.get("pendingInvoices", 0)
    invoices_past_due   = data.get("invoicesPastDue", 0)
    queue_item_count    = data.get("queueItemCount", 0)
    high_urgency_count  = data.get("highUrgencyCount", 0)
    recent_clients      = data.get("recentClients", [])
    top_package         = data.get("topPackage", "")
    avg_project_value   = data.get("avgProjectValue", 0)
    days_into_month     = data.get("daysIntoMonth", 1)
    api_calls_this_month = data.get("totalApiCallsThisMonth", 0)
    current_month       = data.get("currentMonth", "")
    day_of_week         = data.get("dayOfWeek", "")
    observations        = data.get("observations", [])  # from pulseObserver

    days_left    = 30 - days_into_month
    pct_to_goal  = round((income_this_month / income_goal * 100)) if income_goal > 0 else 0
    pace_needed  = round((income_goal - income_this_month) / max(days_left, 1))

    # Format observations for context
    obs_text = ""
    if observations:
        critical = [o for o in observations if o.get("severity") == "critical"]
        warnings = [o for o in observations if o.get("severity") == "warning"]
        info     = [o for o in observations if o.get("severity") == "info"]
        obs_lines = []
        for o in critical:
            obs_lines.append(f"  🔴 CRITICAL: {o.get('note', '')}")
        for o in warnings:
            obs_lines.append(f"  🟡 WARNING: {o.get('note', '')}")
        for o in info[:3]:
            obs_lines.append(f"  ℹ️ INFO: {o.get('note', '')}")
        obs_text = "\n".join(obs_lines)
    else:
        obs_text = "  No observations logged yet."

    system = f"""You are the Strategic Pulse Agent for {business_name}, run by {owner_name}.
{owner_name} is a Solutionist who builds AI-powered tools, websites, and automation for small businesses, churches, and nonprofits in Muskegon, MI.

HIS FULL STACK:
- Solutionist Studio — AI client pipeline (proposals, invoices, content, docs)
- WiseStat — prop firm trading analytics + AI coach
- Sermon Studio — AI sermon prep for pastors
- Mina — church accounting with OCR
- MT5 EAs — automated trading bots (Hunter, Sniper, Trapper, First Strike, etc.)
- Services: Web presence, brand kits, marketing engines, ministry packages, business systems
- Income goal: $7–15K/month (services + trading + productized tools)

YOUR ROLE: Act as his overnight chief of staff who:
1. Reviewed the observations his monitoring system flagged
2. Did web research on market trends and opportunities
3. Is now delivering a morning briefing that is specific, honest, and actionable

SEARCH THESE TOPICS WITH web_search (do all 5 before writing JSON):
1. "AI tools small business 2025 2026 trends"
2. "church management software AI automation 2025"
3. "website builder AI competition pricing 2026"
4. "productized service business pricing models 2025"
5. One search specifically relevant to the most critical observation below

Be direct, warm, punchy — not corporate. Reference real tool names and prices from your searches.

RESPOND ONLY IN VALID JSON after completing all searches:
{{
  "greeting": "2-sentence punchy opener — reference the day + something specific from observations or data",
  "energyRead": "building | momentum | plateau | reset",
  "energyLabel": "short phrase like Gaining Speed or Time to Push",
  "incomeSnapshot": {{
    "thisMonthTotal": {income_this_month},
    "goalAmount": {income_goal},
    "percentToGoal": {pct_to_goal},
    "projectedEOM": 0,
    "gap": 0,
    "verdict": "1 honest sentence on income trajectory"
  }},
  "pipelineHealth": {{
    "activeCount": {active_projects},
    "stuckCount": 0,
    "proposalsPending": {pending_proposals},
    "urgentFollowUps": ["client — specific reason"],
    "verdict": "1 honest sentence on pipeline health"
  }},
  "observationSummary": {{
    "criticalCount": 0,
    "warningCount": 0,
    "topFlags": ["2-3 most important things the observer flagged"],
    "verdict": "1 sentence on overall system health from observations"
  }},
  "researchBrief": [
    {{
      "topic": "topic that was searched",
      "finding": "2-3 sentences with SPECIFIC real tool names, prices, trends found",
      "relevance": "why this matters to Kevin right now",
      "source": "tool name or publication"
    }}
  ],
  "systemImprovements": [
    {{
      "system": "WiseStat | Sermon Studio | Mina | Solutionist Studio | Trading EAs | Services",
      "issue": "specific gap identified",
      "suggestion": "specific improvement with detail",
      "impact": "high | medium | low",
      "effort": "quick | weekend | project"
    }}
  ],
  "addOnOpportunities": [
    {{
      "title": "short bold title",
      "description": "2 sentences — what it is and why Kevin is positioned to offer it now",
      "estimatedValue": "$X–$Y per client or /month",
      "whyNow": "specific reason this window is open",
      "action": "exact first step"
    }}
  ],
  "costWatch": {{
    "estimatedMonthlyCost": "$X–$Y estimate based on usage",
    "biggestCostDriver": "what agent/feature uses most tokens",
    "savingOpportunity": "specific way to reduce cost",
    "verdict": "1 sentence cost health read"
  }},
  "relevanceScore": {{
    "score": 0,
    "label": "Cutting Edge | Ahead of Curve | Current | Falling Behind",
    "strengths": ["specific things Kevin does that are ahead of market"],
    "threats": ["specific tools or trends that could displace services"],
    "nextMove": "1 bold move to extend his lead"
  }},
  "weeklyBoldPlays": [
    {{"day": "Today", "play": "specific action", "why": "why today", "value": "$X or outcome"}},
    {{"day": "Tomorrow", "play": "specific action", "why": "why", "value": "outcome"}},
    {{"day": "This Week", "play": "strategic action", "why": "strategic reason", "value": "impact"}}
  ],
  "topOpportunity": {{
    "title": "bold title",
    "description": "1-2 sentences",
    "estimatedValue": "$X–$Y",
    "action": "exact next step"
  }},
  "blindSpot": {{
    "title": "bold title",
    "description": "1-2 sentences",
    "fix": "specific fix"
  }},
  "boldMove": {{
    "title": "bold title",
    "why": "1 sentence",
    "how": "2-3 sentences exactly how to execute",
    "timeToExecute": "time estimate"
  }},
  "focusBlocks": [
    {{"time": "Morning", "task": "specific task", "why": "why this matters"}},
    {{"time": "Midday", "task": "specific task", "why": "why"}},
    {{"time": "Afternoon", "task": "specific task", "why": "why"}}
  ],
  "closingWord": "1 punchy line to send Kevin into the day with intention"
}}"""

    user_msg = f"""Today: {day_of_week}, {current_month}
Day {days_into_month} of ~30 ({days_left} days left)

INCOME:
- This month: ${income_this_month:,}
- Goal: ${income_goal:,} | {pct_to_goal}% complete
- Need ${pace_needed:,}/day to hit goal
- Avg project value: ${avg_project_value:,}

PIPELINE:
- Active: {active_projects} | Completed: {completed_projects} | Total: {total_projects}
- Proposals pending: {pending_proposals}
- Invoices: {pending_invoices} pending, {invoices_past_due} past due
- Queue: {queue_item_count} items ({high_urgency_count} high urgency)
- Recent clients: {", ".join(recent_clients) or "none yet"}
- Top package: {top_package or "none yet"}

API USAGE: ~{api_calls_this_month} calls this month

OBSERVER FLAGS (what the system noticed since last briefing):
{obs_text}

Now search the 5 topics, factor in the observer flags, and generate the full briefing."""

    try:
        response = client_messages_create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            system=system,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": user_msg}]
        )

        # Extract all text blocks (web search produces multiple content blocks)
        full_text = ""
        for block in response.content:
            if hasattr(block, "type") and block.type == "text":
                full_text += block.text

        full_text = full_text.replace("```json", "").replace("```", "").strip()

        # Find JSON in response
        start_idx = full_text.find("{")
        end_idx   = full_text.rfind("}") + 1
        if start_idx == -1 or end_idx == 0:
            raise ValueError("No JSON found in response")

        json_str  = full_text[start_idx:end_idx]
        briefing  = json.loads(json_str)
        return briefing

    except json.JSONDecodeError as e:
        print(f"Pulse JSON parse error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to parse briefing: {str(e)}")
    except Exception as e:
        print(f"Pulse agent error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/canva-callback")
async def canva_callback(request: Request):
    """
    Relay Canva OAuth callback to the local Tauri/dev app.
    Canva redirects here → we immediately redirect to localhost with the same params.
    """
    from fastapi.responses import HTMLResponse
    params = str(request.url.query)
    query = f"?{params}" if params else ""

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8" />
  <title>Connecting Canva...</title>
  <style>
    body {{ margin:0; background:#0f0f14; color:#fff; font-family:system-ui,sans-serif;
           display:flex; align-items:center; justify-content:center; height:100vh;
           flex-direction:column; gap:16px; }}
    .spinner {{ width:40px; height:40px; border:3px solid #333;
                border-top-color:#a855f7; border-radius:50%;
                animation:spin 0.8s linear infinite; }}
    @keyframes spin {{ to {{ transform:rotate(360deg); }} }}
    p {{ color:#888; font-size:14px; margin:0; }}
  </style>
</head>
<body>
  <div class="spinner"></div>
  <p>Connecting Canva to KMJ Studio...</p>
  <script>
    var DEV  = 'http://localhost:5173/canva-callback{query}';
    var PROD = 'http://127.0.0.1:1420/canva-callback{query}';
    window.location.href = DEV;
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)


# (/health + /health/ready moved above the public_site include — Arc 29
#  fix for the catch-all shadowing that returned "Not found".)


# ─────────────────────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8001))
    uvicorn.run("kmj_intake_automation:app", host="0.0.0.0", port=port)

# ─────────────────────────────────────────────────────────────
# DEPLOYMENT NOTES
# ─────────────────────────────────────────────────────────────
#
# 1. Environment variables needed:
#    ANTHROPIC_API_KEY=sk-...
#    OWNER_EMAIL=kevin@kmjcreative.com
#    SUPABASE_URL=https://brqjgbpzackdihgjsorf.supabase.co
#    SUPABASE_ANON_KEY=eyJ...
#
# 2. Deploy to Railway (free tier works):
#    railway login
#    railway init
#    railway up
#
# 3. Connect Netlify webhook:
#    Netlify Dashboard → Site Settings → Forms → Notifications
#    → Add Webhook → URL: https://your-railway-url.railway.app/webhook/netlify-form
#
# 4. In production, replace COMPLETED_PROJECTS list with Supabase query:
#    supabase.table('projects').select('*').eq('status', 'delivered').execute()
