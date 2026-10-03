---
title: A cancelled or plan-less business has no AI on the server either
date: 2026-10-03
agent: Claude Code (Claude Opus 5.5)
asked: 'make the small change (cancelled paid subscriptions had no AI limit on the server)'
status: shipped
prs: [kmj-intake-server#1231]
migrations: []
left_undone: []
decisions: ["no plan means allowance 0 at the meter, like an ended no-card trial; bought credit packs still work, measured from when the plan or trial ended", "grace (past_due/unpaid/incomplete), comped, grandfathered, and active/trialing on an unrecognised price are untouched"]
related: [2026-10-03-reverse-trial.md]
---
A subscription that ended, or a business that never had one, had no plan and
so an allowance of None, which the meter read as no limit: only the app's
lock screen stood between it and Chief on the API. usage_summary now holds it
like an ended no-card trial, and require_units says what to do.
