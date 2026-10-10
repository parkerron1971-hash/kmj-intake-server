---
title: Square location selection and appointment preview
date: 2026-10-09
agent: Codex (GPT-6)
asked: "ok so let's work on this next phase"
status: in progress
prs: [kmj-intake-server#1356, solutionist-studio#1183]
migrations: ["supabase/APPLY-2026-10-08-square-connections.sql (pending)", "supabase/APPLY-2026-10-09-square-locations.sql (pending)"]
left_undone: ["merge, migrations and private deployment configuration", "live sandbox acceptance", "booking import and calendar projection", "webhooks and background refresh/reconciliation"]
decisions: ["Square is authoritative; this phase previews without importing", "saved active locations belong to the connected merchant", "connection and selection revisions reject stale/in-flight results", "partial preview is explicit"]
related: [2026-10-08-square-connection-pilot.md]
---
The existing backend draft passed its full CI job. Rebased that same open draft on current main and added owner-gated location selection and appointment preview. Reads Square in at-most-31-day windows with pagination, bounds responses to 200 rows/20 booking pages/45 seconds, de-duplicates by source ID/version and preserves Square statuses. Customer details and notes are omitted. No calendar, customer, payment or reminder records are written.

Validation: 134 targeted Python tests and 51 isolated PostgreSQL checks pass. Covers location ownership, selection CAS, disconnect/reconnect races, role grants, migration replay, cursor loops, time-zone query encoding, date bounds, partial-result reporting and provider failure. Existing credentials remain backend-only. Both live migrations and real Square acceptance are still pending.

12ui generated reference images and HTML. Its final prototype save and one resume failed with EPERM/fsync on Windows. The generated connected panel was extracted into a local review artifact and visually checked in Chrome. Publishing the branded artifact to Superdesign was rejected by automatic approval review; it stays local, with user layout approval still pending. Responsive/mobile implementation and design closeout have not run. The existing Integrations card is the insertion target; keep the app navigation and use theme tokens. Do not copy the generated sample sidebar into the app. No frontend product code has changed until the user approves the panel design.

Continuation: Kevin approved the panel. Frontend draft solutionist-studio#1183 now implements connection, saved locations and read-only previews, with 22 passing browser checks including mobile and business-switch races. Frontend build and typecheck gates pass (0 live-app errors; legacy whole-tree baseline 14). The backend full CI passed at 908c168. Both migrations, private deployment configuration and real Square sandbox acceptance remain pending. Automated external design comparison was blocked for potential UI egress; local screenshots and light/mobile states were checked instead. See frontend worklog/2026-10-09-square-appointments-panel.md for details.
