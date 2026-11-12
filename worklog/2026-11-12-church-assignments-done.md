---
title: Church assignments, PR B — weekly jobs know when they're done, the team page says so, the one-on-one
date: 2026-11-12
agent: Claude Code (Claude Opus 5.5)
asked: 'lets build what is missing (PR B of docs/CHURCH_ASSIGNMENTS.md, started after #1801 merged)'
status: shipped
prs: ["kmj-intake-server#1802"]
migrations: []
left_undone: ["Last week is judged as things stand now for four jobs (first-time guests, who serves when, the calendar, sermon up): nothing keeps their history", "The one-on-one's frontend (solutionist-studio) isn't built", "PR C (the member app's Lead tab: C1 and C2) and PR D (the Chief verbs)", "Kevin hasn't been asked about the rule Claude decided in the #1801 review: senior-job and pastor's-yes holders are under the owner only"]
decisions: ["Six weekly jobs judged, each test written out in docs/CHURCH_ASSIGNMENTS.md (PR B): first_guests, serve_schedule, calendar, sermons, attendance, shepherding", "done / not yet / late by the login's picked day else the catalog's; a read that fails, a job no test judges, or nothing to count claims nothing", "Judged only where CHURCH_ASSIGNMENTS is open for the church; closed, My week and the team page read nothing new", "The team page judges every login on one church_work_checks.Ctx after the rows are read: each table once for the church", "The one-on-one reads and records nothing: no check ticks anything off there", "Wording: the 'senior holders are under the owner only' rule is said to be Claude's decision (2026-11-12), not Kevin's, in church_over, the doc and the work logs", "Review round 1 (#1802): the keeper wall holds on the team page, the roll-up and the one-on-one (a walled job keeps its state, never its words; the one-on-one shows only the asker's own areas)", "One clock for every page that judges the week (church_work_checks.church_zone: availability, else the owner's profile); a clock that can't be read is a 503 everywhere; the test fixtures give the clock as data and patch no reader", "Attendance counts a service by its own day (its entry), never by when a headcount was edited; shepherding is cut at the job's day", "Last week (Claude's decision in the review, not Kevin's): the roll-up and each team page row say last week's result, judged at the end of each job's day; unread is never missed", "Review round 2 (#1802): a service is dated by its room's own date field, else the day its check-in landed; a headcount that might be the Sunday's is never said missed", "A fix for every church, switch on or off: My week's task lines and rhythm now read the church's one clock (availability, else the owner's profile) where they read chief_assignments._tz_for (availability, else UTC); a clock that can't be read never fails My week: its lines use the platform's default and the rhythm judges nothing"]
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

Review round 1 on #1802: the keeper wall (a walled job's words reached an overseer outside People
& care, and the one-on-one had no area cut), one clock for every page that judges the week,
attendance by the service's own day, shepherding cut at the job's day, and last week's result in
the roll-up and on each team page row.

Round 2 on #1802: attendance reads a service's date under its room's own date field and falls back
to the day a check-in landed, and a headcount that might be the Sunday's is said as couldn't be
read, never as missed. The clock change reaches every church, switch on or off: My week (its
task lines and its rhythm) reads the same clock as the team page, the church's availability zone
else its owner's profile, where before it read availability else UTC. A clock that can't be
read never fails My week: its lines use the platform's default and the rhythm judges nothing
(the team page and the one-on-one still answer 503).

Also corrected: the rule that senior holders are under the owner only was written as Kevin's call
in #1801. It was Claude's decision in that review, and Kevin hasn't been asked yet. church_over, the
doc and both work logs now say so.
