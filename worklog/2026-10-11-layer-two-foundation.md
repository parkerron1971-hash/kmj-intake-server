---
title: "Layer Two foundation migration: turn id, business brain, nightly pass"
date: 2026-10-11
agent: Claude Code (Claude Opus 5.5)
asked: "approved to build this. great plan ... build the best path forward (Kevin, 2026-10-11, after the Layer Two Phase 0 report)"
status: waiting on review
prs: [kmj-intake-server#1378]
migrations: [supabase/APPLY-2026-10-11-layer-two-foundation.sql]
left_undone: ["applying it to production: the SQL editor run was blocked by the permission classifier as a production deploy; staged for Kevin's one Run click"]
decisions: ["audit_log is not altered: its hash covers a frozen column list (ledger_canonical_v2), so the AI context rides inside payload, which the hash already covers and anchors", "business_brain_versions is exported and deleted with the business (the brain travels with it); chief_reflection_runs is excluded as an operations log", "owner reads through is_business_owner, writes service-role only"]
related: [2026-10-11-business-brain.md]
---
One additive migration for the Layer Two build: turn_id, lane, provider,
response_id and one-hour cache-write tokens on api_usage; turn_id on the
conversation archive, the approval queue and the outcome ledger; the queue keeps
Chief's original draft when the owner edits it and records who reviewed it; and
two new tables, business_brain_versions (append-only) and chief_reflection_runs
(one row per business per day). The code that uses it probes first, so it is safe
to merge before or after the SQL is applied.
