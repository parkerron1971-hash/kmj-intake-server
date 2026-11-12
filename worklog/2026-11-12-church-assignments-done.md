---
title: Church assignments, PR B — weekly jobs know when they're done, the team page says so, the one-on-one
date: 2026-11-12
agent: Claude Code (Claude Opus 5.5)
asked: 'lets build what is missing (PR B of docs/CHURCH_ASSIGNMENTS.md, started after #1801 merged)'
status: in progress
prs: []
migrations: []
left_undone: ["The Monday roll-up says this week's states; on a Monday morning nearly everything is not yet. Last week's results in the roll-up are not built", "The one-on-one's frontend (solutionist-studio) isn't built", "PR C (the member app's Lead tab, after Kevin sees the mock) and PR D (the Chief verbs)", "Kevin hasn't been asked about the rule Claude decided in the #1801 review: senior-job and pastor's-yes holders are under the owner only"]
decisions: ["Six weekly jobs judged, each test written out in docs/CHURCH_ASSIGNMENTS.md (PR B): first_guests, serve_schedule, calendar, sermons, attendance, shepherding", "done / not yet / late by the login's picked day else the catalog's; a read that fails, a job no test judges, or nothing to count claims nothing", "Judged only where CHURCH_ASSIGNMENTS is open for the church; closed, My week and the team page read nothing new", "The team page judges every login on one church_work_checks.Ctx after the rows are read: each table once for the church", "The one-on-one reads and records nothing: no check ticks anything off there", "Wording: the 'senior holders are under the owner only' rule is said to be Claude's decision (2026-11-12), not Kevin's, in church_over, the doc and the work logs"]
related: [2026-11-12-church-assignments.md, 2026-11-11-church-team-week-together.md]
---
PR B of `docs/CHURCH_ASSIGNMENTS.md`, after PR A (#1801) merged and its frontend (solutionist-studio
#1522) shipped. No migration.

Built: `church_work_checks` readers shared between the start-up checks and the weekly jobs, and
`WEEKLY` (six tests, each in the doc's table); `church_my_week._done_full`, `due_day` and
`job_state`, with My week's rhythm carrying `state`, `state_text` and `detail`;
`church_team_week.judge_week` (the team page's `this_week` entries, `this_week_counts`, the page's
`late_jobs`) and the roll-up's "Late on the week" and "This week" lines with each state; and
`GET /church/assignments/one-on-one`.

Also corrected: the rule that senior holders are under the owner only was written as Kevin's call
in #1801. It was Claude's decision in that review, and Kevin hasn't been asked yet. church_over, the
doc and both work logs now say so.
