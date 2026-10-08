---
title: Open the marketing suite to every business (B14, on by default and announced)
date: 2026-10-08
agent: Claude Code (Claude Opus 5.5)
asked: "open to everyone because right now no one is using it so you can set how it will work for everyone."
status: in progress
prs: [kmj-intake-server marketing-open-to-all (draft)]
migrations: []
left_undone: ["docs/MARKETING_DESK.md: the 'Open to every business (2026-10-08)' section (defaults and kill switches), and the B8/B9/B15 lines that still say MARKETING_DESK and MARKETING_DESK_PUBLISHING default off", "docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md: annotate 'Kevin, by hand' item 2 as done where it is", "new __tests__/test_marketing_open_to_all.py: switch defaults, publishing default, plan_on and the desk rows made with the plan on, announced keys on /compare, /features and the FAQ, MARKETING_LADDER held to plan_features, no vendor names, /billing/plans marketing_by_plan", "existing suites that pin the old defaults, not yet updated: test_audience_plans (the levels are not on sale yet), test_business_marketing_dispatch (the switch parametrization), test_platform_marketing_suite and test_platform_out_of_tenant_fanout (unset MARKETING_DESK used to mean off), possibly others", "run every suite the task lists; only test_business_marketing_planner has run (97 passed)", "frontend: BillingPanel.FEATURE_LABELS has no labels for the three marketing keys, so the in-app plan cards show raw keys once this merges unless the frontend adds them (or reads /billing/plans marketing_by_plan)", "count of saved marketing_desks rows in production: unknown (the read-only count was refused by the permission system)"]
decisions: ["MARKETING_DESK and MARKETING_DESK_PUBLISHING are read only in marketing_switches.py; unset or empty = on for every business; off (also false, no, 0) = the kill switch; a MARKETING_DESK value with no business id in it switches nobody on", "plan_enabled defaults to on for a business with no saved desk row (business_marketing.plan_on); rows the server makes write it explicitly because the column still defaults to false (no migration); an owner who turned it off stays off", "the fan-out's candidates are now every business in scope with a connected account, less desks saved with plan_enabled false", "the ladder's words live once in feature_gates.MARKETING_LADDER and feed /compare, /features, the FAQ and /billing/plans (marketing_by_plan); the barber plans show on the public pages only once offered"]
related: [2026-10-07-marketing-plan-gates.md, 2026-10-08-platform-out-of-tenant-fanout.md]
---
Work in progress, stopped for a reboot. Built so far (committed on branch
marketing-open-to-all): `marketing_switches.py` (the one reader of both
switches); the planner, `platform_suite._tenant_desk_on` and
`business_marketing.publishing_on` read it; `DESK_DEFAULTS['plan_enabled']`
is True with `plan_on()` used by the three scheduled-run checks, and
`ensure_desk` / `PUT /settings` write the plan on when they make a row; the
fan-out's candidates start from connected accounts; the three keys left
UNANNOUNCED_FEATURES and `_NOT_A_ROW`; compare rows, a features-page ladder
and four FAQ entries (Marketing group) from `feature_gates.MARKETING_LADDER`;
`.env.example` updated. Solutionist's own business stays out (#1345
unchanged); the per-tick cap, jitter and 60% spend deferral are unchanged;
`POST_FOR_ME_PILOT_BUSINESSES` untouched. See left_undone for the rest.
