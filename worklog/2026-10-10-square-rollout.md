---
title: Square pilot rollout
date: 2026-10-10
agent: Codex (GPT-6)
asked: "ok finish work on it"
status: in progress
prs: [kmj-intake-server#1356, solutionist-studio#1183]
migrations: ["APPLY-2026-10-08-square-connections.sql (pending)", "APPLY-2026-10-09-square-locations.sql (pending)"]
left_undone: ["merge and deploy", "live migrations and private sandbox configuration", "real Square sandbox acceptance"]
decisions: ["approved read-only pilot; no public production-seller enablement", "preserve current trunk changes"]
related: [2026-10-09-square-location-preview.md]
---
Integrated current trunk and resolved additive release-note/environment-example conflicts, retaining both sides. Revalidated 134 backend tests, 51 isolated PostgreSQL checks, and 22 browser tests; frontend production build passed. Railway target and Supabase project verified. Square developer browser session expired; Kevin has been asked to sign in while deployment preparation continues. No credentials recorded in source or logs.
