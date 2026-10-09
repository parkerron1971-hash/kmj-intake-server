---
title: Open the marketing suite to every business (B14, on by default and announced)
date: 2026-10-08
agent: Claude Code (Claude Opus 5.5)
asked: "open to everyone because right now no one is using it so you can set how it will work for everyone."
status: done
prs: [kmj-intake-server #1350, solutionist-studio #1173]
migrations: []
left_undone: ["Chief's Content Plan verbs (chief_grow_actions plan_content, capture_idea, publish_post, publish_to_site) still write to Content Plan; the frontend now sends grow:content to the desk (F8/B16 retire the Meta path)", "count of saved marketing_desks rows in production: unknown (the read-only count was refused earlier); rows saved with plan_enabled false stay off by design"]
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

Finished 2026-10-08 (session 1314a369, Kevin approving the Reach review:
"ok all of the plans are great. let's do it."). Added
__tests__/test_marketing_open_to_all.py (30: switch defaults and kill
switches, plan_on / new_desk_row, announced keys, MARKETING_LADDER held to
plan_features, the words on /compare, /features, the FAQ and
/billing/plans, no posting-service name on the public pages, the FAQ no
longer sends people to the old Facebook connection). Updated the four suites
that pinned "unset means off". docs/MARKETING_DESK.md gained "Open to every
business" and its B5/B8/B9/B15 lines; the plan doc's by-hand item 2 is
marked done. The stale FAQ answer about publishing now points at Build,
Social Media and Grow, Marketing. MARKETING_AUTOPILOT_WORDS is in plain words
("the kinds of posts you trust can go out without asking"), matching the
frontend's plan cards. Railway: neither MARKETING_DESK nor
MARKETING_DESK_PUBLISHING is set, so the new defaults apply on deploy;
DAILY_SPEND_CAP_USD=150 staged 2026-10-08. Marketing suites: 1473 tests, all
passing after the updates.
