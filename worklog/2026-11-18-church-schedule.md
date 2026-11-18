---
title: The leaders schedule — who is away, who says yes, how many at once
date: 2026-11-18
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-18: "I want to be able to build Leaders schedule. this is for when leaders are planning time off and have certain obiligations so that we as a church can plan around meeting ... making sure that everyone is not gone at the same time on our services. allowing only so many people off at the same time. ... there should volunteers one and one for leadership ... divided amongs the department to manage there department as well." Then, on the five calls the plan rests on: "Yes build to all five"'
status: in progress
prs: [kmj-intake-server#1929, kmj-intake-server#1930]
migrations: [supabase/APPLY-2026-11-19-church-schedule.sql (not applied)]
left_undone:
  - "Apply supabase/APPLY-2026-11-19-church-schedule.sql by hand after review. Until it is there every /church/schedule route answers 404 and nothing else changes."
  - "S1-4 the notices and the hourly sweep (nobody is told of an ask or an answer yet); S1-5 Dates on the member app's Lead tab; S1-6 the Serving Away form asks instead, and the scheduler holds a waiting ask; S1-7 things that repeat. One PR each, in that order, each from the newest main."
  - "Until S1-4 and S1-5 land, an ask exists only for someone who calls the office routes: there is no screen for it (the office frontend comes after the backend) and no notice."
  - "CHURCH_SCHEDULE is read on the web service only today. Set it on BOTH services once S1-4's sweep ships."
  - "Step 2, the limit: its own migration (drafted in docs/CHURCH_SCHEDULE.md section 2.2, rehearsed once, not a file yet), then service days and the numbers, protected days, pairs, volunteers."
  - "The office frontend comes after the backend; the route shapes in docs/CHURCH_SCHEDULE.md section 4 are its contract."
  - "Before Dates opens for a church, its owner's own person record must be found (docs/CHURCH_SCHEDULE.md section 7, item 4)."
  - "For S1-4: withdrawing a yes tells whoever said it, and no column claims that notice yet (docs/CHURCH_SCHEDULE.md section 2.1, the last list)."
decisions:
  - "Kevin said yes to five calls: core leaders are pastors, elders, ministers, department leaders and overseers, with the office admins as their own group, and any name can be added or removed; the leaders' number starts at about one in four away on a Sunday, and each department leader sets their own with the volunteer coordinator; volunteers need no yes unless the date is full or they already agreed to serve it, then it goes to their team leader; the person over a leader on the leaders map says yes, and past the limit or on a protected Sunday only the owner or whoever oversees the office; two weeks' notice for planned time off, sickness and emergencies never blocked."
  - "Decided in the build, not by Kevin (all 21 are in docs/CHURCH_SCHEDULE.md section 7.2): one Postgres function, church_away_settle, writes the yes and its away date in one transaction; an approved ask becomes a serve_away row, so Who serves when learns nothing new; the reason never leaves church_away_asks; Admins do not change the roster, the notice days or the leaders and office numbers; a member-app session never carries the owner's across-the-board power; a department with no number has no limit; private reasons are cleared 90 days after the last day."
  - "The rules read the church's own data (church_over.above, roles, groups, departments, seats, its add and remove list), never a title word or a role key."
  - "church_away_asks is unrelated to church_map_asks and member_asks."
  - "Decided while building S1-2 and S1-3, not by Kevin (docs/CHURCH_SCHEDULE.md section 7.4 lists every one): nobody answers their own ask; the note that comes with an answer is as private as the reason; someone not on the schedule can't ask (the owner adds them first, the owner's own name included at a church with nothing set up); a waiting ask shows on the calendar only to those who may read it; too many waiting never blocks can't make it; who oversees the office is read fresh from the church's own rows, not from the minute-old duties cache."
related: [2026-10-23-sunday-planning-serving.md, 2026-11-04-church-map-chain.md, 2026-11-12-church-assignments.md, 2026-11-12-church-handovers.md, 2026-11-17-event-volunteer-dates.md]
---
**S1-2 and S1-3 (#1930, one PR): the switch, who is on the schedule, and asks.**
`church_schedule.py` is the engine and the office routes
(`/church/schedule/status`, `people`, `leaders`, `asks`, `asks/{id}/answer`,
`asks/{id}/withdraw`, `settings`). Switched by `CHURCH_SCHEDULE` (off | owner |
on, owner when unset), and every route answers 404 until the migration is
applied. Who is on the schedule is read from the church's own data (everyone
who leads something is in `leaders`, an office login's person who leads nothing
is in `office`), then its own add and remove lists, which only the owner and
whoever oversees the office change (not an Admin). An ask goes to the first
person `church_over.above` gives; short notice is flagged and never blocked;
"can't make it" and the owner's own ask are a yes at once with nobody deciding.
The yes and its away date are written by `church_away_settle` in one
transaction. `shape()` is the one place a reason leaves the server: the asker,
whoever it went to, the owner and whoever oversees the office read it; an
Admin, another leader and whoever keeps Who serves when never do.
`member_portal_messaging.leading_people` is new (the leaders room without the
office, taken out of `leaders_room_people`, which answers as before).
`conftest.py` pins the tables as "not there" for every other suite. Tests:
`test_church_schedule_roster.py` and `test_church_schedule.py`, on the four
fixture churches with the tables and the function modelled in
`church_schedule_fake.py`.

**S1-1 (#1929) holds the tables and nothing else.**
`supabase/APPLY-2026-11-19-church-schedule.sql` (**not applied**) makes
`church_away_asks`, `church_away_commitments`, `church_schedule_people` and
`church_schedule_settings`, adds `ask_id` and `kind` to `serve_away`, and adds
`church_away_settle()`. `docs/CHURCH_SCHEDULE.md` is the feature's standing doc:
what was found in the code, the tables, the plan for the modules and routes
still to write, the rules as a table, the PR split, and what was decided (with
which calls are Kevin's and which the build made). The four tables are in
`account_lifecycle.EXPORT_EXCLUDED` with a reason each; the ledger has the
file's row; `__tests__/church_schedule_db.mjs` (152 checks on PGlite) runs in
CI's database job.

The build spec's SQL was run for real and changed in seven places
(`docs/CHURCH_SCHEDULE.md` section 2.1 lists each with why): a null state is
refused by name, a state and its marks agree, an ask stays with its person, a
fact's ask is re-checked when the fact is moved, and the file ends with
`NOTIFY pgrst`.

Before building more here: read `docs/CHURCH_SCHEDULE.md` first, then check
whether the migration has been applied (`docs/MIGRATIONS.md`). Anything that
shows someone as away must read the fact in `serve_away`, not an ask's state.
Anything new that returns an ask must go through `church_schedule.shape()`.
