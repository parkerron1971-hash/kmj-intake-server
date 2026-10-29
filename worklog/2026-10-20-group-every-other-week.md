---
title: Groups that gather every other week
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-20: "you can continue to work on things." Left from the approved canvas "Church Groups, Together": every-other-week schedules (gatherings were weekly with skips)'
status: shipped
prs: [kmj-intake-server#1538, solutionist-studio#1315]
migrations: [supabase/APPLY-2026-10-20-group-every-other-week.sql (applied)]
left_undone: ["monthly schedules (the first Thursday): a leader skips the weeks between for now"]
decisions: ["groups.meet_every 1 or 2 and groups.meet_from, a date the group gathers that the two-week cycle counts from; without one it stays weekly", "the next gathering, the coming list (RSVPs, Bring something, study) and the 5 PM reminder all skip the off weeks; skips still work on top", "a leader picks it on the Meet tab: from the coming one or the week after; once tonight's gathering is over, the coming one is next week's; back to every week clears the start", "it reads 'Every other Thursday · 7:00 PM'"]
related: [2026-10-20-group-gatherings.md]
---
`group_gatherings`: `on_cycle`, used by `next_on`, `upcoming` and `reminders`; `regular_text`; `set_schedule(every=, first=)`; the leader's form (How often, Starts). `member_portal_groups`: reads the cycle; the schedule route passes it on. Migration: the two columns.

Checks: 9 tests in `test_group_every_other_week.py` (10 sabotages caught, the last after asserting the page's query reads the new columns); `group_every_db.mjs` 5 checks on PGlite, in CI; 217 tests across the group and member files and the access ratchet. Rollback probe on the live database before applying.
