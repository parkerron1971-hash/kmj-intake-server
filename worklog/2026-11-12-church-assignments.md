---
title: Church assignments, PR A — whoever is over people starts them, hands them work, sees it move
date: 2026-11-12
agent: Claude Code (Claude Opus 5.5)
asked: 'lets build what is missing; allow for the admin to pick days for work load that works for them; allow for Jessica to be able to hand out assignments to each of them as well; a way for churches to set this up in a general sense when they establish leaders over people'
status: in progress
prs: []
migrations: [supabase/APPLY-2026-11-12-church-assignments.sql (NOT applied)]
left_undone: ["Kevin applies the migration by hand, then merges; until then the routes answer 503 for Love City (CHURCH_ASSIGNMENTS defaults to owner)", "PR B: weekly done for six jobs, done / not yet / late on the team page and roll-up, the one-on-one", "PR C: the Lead tab's assignments and Your people (mock to Kevin first)", "PR D: the Chief verbs", "F1 / F2 (frontend): My week's Your assignments and day picker; the board", "Not timed on production: no sign-in to call it with. The board is about 20 reads for a church of 7 logins and 12 leaders in the fake"]
decisions: ["An assignment is a task; the new columns only add duty, done_when, check_key, startup_key, stuck, raised and checked_at, plus raised_by (the email names who sent it up)", "Over is church_over, from the church's seats and leaders map: qualifying as church_map.chain_for climbs, walked down each person once, a person with an office login is their login", "A first assignment is the duties a login does of its own (the Executive Pastor's lane is its two, not the 25 it covers), or a person's switches", "The calendar check reads worship_services and Services & Events, not events (the activity log)", "The first-Monday report doesn't move; a monthly duty with a day stays monthly", "The grouped tell only where the switch is open, only for two or more in one sweep"]
related: [2026-11-11-church-team-week-together.md, 2026-11-02-exec-pastor-oversight.md]
---
Kevin's review (artifact FDqG3nA3jBaNVaSzzviW5f) found every office login has duties and a week,
but nobody hands anyone a first assignment, and almost nothing knows when a job is done. This is
the backend for the general rule: whoever a church puts over people starts them, hands them work
and sees it move, and the people under them pick their days. The plan is
`docs/CHURCH_ASSIGNMENTS.md` (the spec, corrected where the code proved it wrong).

Built: `church_over.py` (under / is_over / above, from church_duties and church_map, never names
or title words), `church_startup.py` (31 templates and start), `church_work_checks.py` (ten
checks that tick items off), `church_assignments.py` (the routes but the one-on-one, picked days,
the raised tell and the hourly sweep), picked days read by My week's rhythm, the team page and
the Monday roll-up, the grouped hand-off tell in church_office_tasks and church_leader_tasks, a
`raised` line on My week, `CHURCH_ASSIGNMENTS` (off | owner | on, default owner), and the
migration. Tests run the rule at Love City, Grace Baptist, New Hope and Riverside.

Before building more here: the response shapes the frontend uses are in the doc's "What the
frontend builds against".
