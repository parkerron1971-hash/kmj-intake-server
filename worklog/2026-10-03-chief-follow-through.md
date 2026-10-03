---
title: Chief responsibilities, measurable goals and event recovery
date: 2026-10-03
agent: Codex (GPT-6)
asked: "another agent is working mysite build right now. please build out these plans you shared"
status: shipped
prs: [kmj-intake-server#1239, solutionist-studio#1120]
migrations: [supabase/APPLY-2026-10-03-chief-event-delivery.sql (applied)]
left_undone: []
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
watchdogs and MySite/voice work were not duplicated. The recovery feature is
not yet activated; migration status and rollout are tracked separately below.

Validation: 435 backend tests passed, one expected failure; SQL migration and
recovery checks passed in PGlite. No live business actions were performed.
Final source-contract review confirmed approvals use the existing draft state
and failed errands remain actionable in the report; all 26 follow-through tests pass.

Kevin then authorized "make the migration". Applied it through the Supabase
Management API at 2026-10-03 20:43 UTC after a successful live rollback rehearsal.
Verified RLS, all six service-only functions, browser denials, business cascade
and zero delivery rows. Receipt: docs/CHIEF_EVENT_MIGRATION_VERIFICATION.json.
The additive schema was applied before merge under this explicit instruction;
no feature flags were changed and no customer work was started.

Kevin authorized continuing deployment. Full CI found two outcome-ledger
fixtures missing a mock for the newly required profile lookup (12,359 other
tests passed). Added the scoped fixture; deployment remains gated on full CI.

The corrected full CI passed: 12,372 tests, 17 skipped, one expected failure,
plus browser sabotage and SQL migration checks. Production rollback-only
recovery rehearsal passed nine checks with zero remaining fixture events;
all six live report sources loaded. Web and worker were restarted with
CHIEF_AGENT=off to drain legacy runs, then CHIEF_DURABLE_EVENTS=on was staged
without deploying. Trunk advanced during CI; merged its latest MySite changes
without conflicts and reran the required gate before release.

PR #1239 merged as 873fc9c and deployed on both Railway services. After both
paused deployments replaced legacy processes, the temporary CHIEF_AGENT
overrides were removed and both services explicitly redeployed. Verified
chief_agent.enabled() and chief_event_delivery.enabled() are both True inside
both running containers; health/readiness and the scheduler lease are healthy.
Unsigned report requests return 401; the signed-in desktop shortcut returned
all six sources, five fixture work items and two needing attention, without
restarting work. Release receipt: docs/CHIEF_FOLLOW_THROUGH_RELEASE.json.

Frontend #1120 is also live. Its phone-specific drawer needed a follow-up
shortcut (solutionist-studio#1122); that correction and verification are tracked
in the frontend worklog. No backend activation work remains.

The final live report also exposed internal job-kind names in titles. The
rollout follow-up now uses chief_jobs.KIND_META's existing business labels and
a plain fallback, with coverage for known and unknown kinds. No job execution
or MySite build behavior changes.
