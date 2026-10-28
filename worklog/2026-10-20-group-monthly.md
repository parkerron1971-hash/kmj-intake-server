---
title: Groups that gather once a month
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-20: "let''s continue so we can finish up". Left from the approved canvas "Church Groups, Together": schedules beyond weekly and every other week'
status: shipped
prs: [kmj-intake-server#1540, solutionist-studio#1317]
migrations: [supabase/APPLY-2026-10-20-group-monthly.sql (applied)]
left_undone: []
decisions: ["once a month = groups.meet_every 4 with meet_nth: the first, second, third, fourth or last of its weekday (5 = the last, so a five-Thursday month still lands on its last)", "the next gathering (looks 100 days ahead), the coming list (35 days a gathering, so 8 ahead fits) and the 5 PM reminder follow it; skips still work on top", "a leader sets it on the Meet tab (How often: Once a month, the … one); another choice clears it", "it reads 'First Thursday of the month · 7:00 PM'"]
related: [2026-10-20-group-every-other-week.md, 2026-10-20-group-gatherings.md]
---
`group_gatherings`: `MONTHLY`, `NTH`, `nth_of`, `is_last`, `on_cycle` for once a month, the longer look-ahead, `regular_text`, `set_schedule(nth=)`, the leader's form. `member_portal_groups`: reads meet_nth; the route passes it on. Migration: the check widened to 1, 2, 4 and meet_nth.

Checks: 9 tests in `test_group_monthly.py` (10 sabotages caught, after adding a month whose Thursdays fall on the 7th, 14th, 21st, 28th and an eight-ahead list); `group_monthly_db.mjs` 5 checks on PGlite, in CI. Rollback probe on the live database before applying.
