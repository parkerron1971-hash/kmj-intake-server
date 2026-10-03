---
title: Chief responsibilities, measurable goals and event recovery
date: 2026-10-03
agent: Codex (GPT-6)
asked: "another agent is working mysite build right now. please build out these plans you shared"
status: waiting on Kevin
prs: []
migrations: [supabase/APPLY-2026-10-03-chief-event-delivery.sql (pending)]
left_undone: [merge and deploy, manual migration, coordinated feature activation and production smoke check]
decisions: ["Keep MySite build separate", "Unknown effects require review, never blind replay", "Use existing assignment permissions", "Observed business progress is not causal attribution"]
related: [2026-09-30-agent-operations-plan.md]
---
Built a shared owner-scoped work report, fresh operating rules for event and
assignment runs, and named appointment/invoice/contact responsibilities. Added
durable event claims, bounded preparation retries, uncertain-action review and
owner acknowledgement. Generic retries now require a confirmed atomic claim;
errands cannot be replayed from that door. Measurement failures preserve prior
progress. The migration and activation runbook are in docs/CHIEF_FOLLOW_THROUGH.md.

Worked in isolated checkouts after reading both worklogs. Existing operations
watchdogs and MySite/voice work were not duplicated. The new recovery flag is
off until the migration and coordinated rollout; this is not live yet.

Validation: 435 backend tests passed, one expected failure; SQL migration and
recovery checks passed in PGlite. No live business actions were performed.
