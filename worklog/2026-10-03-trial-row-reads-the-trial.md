---
title: Trials get their free build and their credit limit at every gate
date: 2026-10-03
agent: Claude Code (Claude Opus 5.5)
asked: "make sure the cost aligns right with the usage. we saying 500 tokens can build a site and still talk with chief. make sure that is true."
status: shipped
prs: [kmj-intake-server#1215]
migrations: []
left_undone: []
decisions: ["usage_metering._biz_row is the row every metering gate reads, so it must carry every column trial_window_start needs"]
related: [2026-10-03-no-card-trial.md]
---
`usage_metering._biz_row` never selected `trial_ends_at`, so every gate that
loaded the business through it read a trial as not a trial. The trial's free
first build never happened in production (a real build is charged
1,000-1,300 credits, which emptied the 1,000 trial), and Chief and builds
measured trials against the plan's monthly allowance instead of the trial
tank. Found while proving the 500-credit no-card trial can build a site and
still talk with Chief. Tests now go through `_biz_row` with a fake table that
honours `select=`; a hand-built row hides this class of bug.
