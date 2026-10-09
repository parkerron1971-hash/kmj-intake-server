---
title: Square location selection and appointment preview
date: 2026-10-09
agent: Codex (GPT-6)
asked: "ok so let's work on this next phase"
status: in progress
prs: [kmj-intake-server#1356]
migrations: ["supabase/APPLY-2026-10-08-square-connections.sql (pending)", "supabase/APPLY-2026-10-09-square-locations.sql (pending)"]
left_undone: ["frontend implementation awaiting design review", "merge, migrations and private deployment configuration", "live sandbox acceptance", "booking import and calendar projection", "webhooks and background refresh/reconciliation"]
decisions: ["Square is authoritative; this phase previews without importing", "saved active locations belong to the connected merchant", "connection and selection revisions reject stale/in-flight results", "partial preview is explicit"]
related: [2026-10-08-square-connection-pilot.md]
---
The existing backend draft passed its full CI job. Rebased that same open draft on current main and added owner-gated location selection and appointment preview. Reads Square in at-most-31-day windows with pagination, bounds responses to 200 rows/20 booking pages/45 seconds, de-duplicates by source ID/version and preserves Square statuses. Customer details and notes are omitted. No calendar, customer, payment or reminder records are written.

Validation: 134 targeted Python tests and 51 isolated PostgreSQL checks pass. Covers location ownership, selection CAS, disconnect/reconnect races, role grants, migration replay, cursor loops, time-zone query encoding, date bounds, partial-result reporting and provider failure. Existing credentials remain backend-only. Both live migrations and real Square acceptance are still pending.

UI drafts are being generated with 12ui and placed on the Superdesign review canvas. The existing Integrations card is the insertion target; keep the app navigation and use theme tokens. Do not copy the generated sample sidebar into the app. No frontend product code has changed until the user approves the panel design.
