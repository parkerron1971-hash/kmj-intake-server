---
title: Square Appointments account connection foundation
date: 2026-10-08
agent: Codex (GPT-6)
asked: "ok great. let's keep going"
status: in progress
prs: []
migrations: ["supabase/APPLY-2026-10-08-square-connections.sql (pending)"]
left_undone: ["merge and manual migration", "backend Square secrets and pilot owner configuration", "live sandbox OAuth acceptance", "frontend connection and location selection", "booking preview/import, webhooks and calendar safeguards", "scheduled refresh and revocation retry"]
decisions: ["existing Square sellers connect their own accounts through OAuth", "read-only scopes; no payment access or booking writes", "pilot disabled by default", "encrypted tokens and service-only state; one merchant per business/environment"]
related: []
---
Prepared the next connection-only checkpoint after Square app signup. Reviewed both repositories' work logs: no existing Square connector; relevant fixes cover outside-calendar access and booking/session projection. Built owner-gated OAuth start/callback, browser-bound one-use state, encrypted credentials, location discovery, on-demand refresh and revocation with race protection. Saved and verified the Square sandbox redirect URL; no secrets were copied and no production account was connected.

Validation: 112 targeted Python tests pass (22 new Square tests plus related export/logging/card regressions); 40 PostgreSQL security/state checks pass, including migration replay, browser-role denial, cross-tenant merchant uniqueness and disconnect/callback/refresh races. Added the SQL checks to the existing CI job. Live database and Square end-to-end validation remain pending. Full setup/verification and the booking-sync follow-up are in docs/SQUARE_CONNECTION_SETUP.md. Feature stays off until the listed deployment steps are completed.
