---
title: The leaders schedule — who is away, who says yes, how many at once
date: 2026-11-18
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-18: "I want to be able to build Leaders schedule. this is for when leaders are planning time off and have certain obiligations so that we as a church can plan around meeting ... making sure that everyone is not gone at the same time on our services. allowing only so many people off at the same time. ... there should volunteers one and one for leadership ... divided amongs the department to manage there department as well." Then, on the five calls the plan rests on: "Yes build to all five"'
status: in progress
prs: [kmj-intake-server#1929, kmj-intake-server#1930, kmj-intake-server#1934]
migrations: [supabase/APPLY-2026-11-19-church-schedule.sql (not applied)]
left_undone:
  - "Apply supabase/APPLY-2026-11-19-church-schedule.sql by hand after review. Until it is there every /church/schedule route answers 404, nobody is told anything, the hourly sweep reads nothing, and nothing else changes."
  - "S1-6 the Serving Away form asks instead, and the scheduler holds a waiting ask; S1-7 things that repeat (and telling whoever is over someone when one is added, and its part of the Dates page). One PR each, in that order, each from the newest main."
  - "The office app has no screen for an ask yet (the office frontend comes after the backend): a login's notice still opens the office app, where the ask isn't shown. A login whose person is on the schedule answers in the member app, on Dates, as that person."
  - "Dates: the count beside it in the Lead tab's switcher is kept a minute a replica, so on another replica it can lag a minute after an answer (the Dates page itself is always fresh). Until S1-6, an approved date taken off under Serving, Away leaves its ask a yes; Dates shows it as Off the calendar."
  - "CHURCH_SCHEDULE is read on both services since S1-4 (the web service for the routes and each write's notice, the worker for the sweep). Unset means owner on both; to change it, set the same value on both. The sweep also works only the churches CHURCH_ASSIGNMENTS is open for."
  - "Open for Kevin or the lead session (docs/CHURCH_SCHEDULE.md sections 7.5 and 7.6): the owner's own time away tells nobody (the plan had the office overseer told); when the owner takes an ask back, whoever it went to is not told; who covers is picked from the people on the leaders schedule, anyone else is typed as a name; Who else is away never says what kind of time away it is; Dates does not tell a leader that their reason is cleared after 90 days."
  - "Step 2, the limit: its own migration (drafted in docs/CHURCH_SCHEDULE.md section 2.2, rehearsed once, not a file yet), then service days and the numbers, protected days, pairs, volunteers."
  - "The office frontend comes after the backend; the route shapes in docs/CHURCH_SCHEDULE.md section 4 are its contract."
  - "Before Dates opens for a church, its owner's own person record must be found (docs/CHURCH_SCHEDULE.md section 7, item 4)."
decisions:
  - "Kevin said yes to five calls: core leaders are pastors, elders, ministers, department leaders and overseers, with the office admins as their own group, and any name can be added or removed; the leaders' number starts at about one in four away on a Sunday, and each department leader sets their own with the volunteer coordinator; volunteers need no yes unless the date is full or they already agreed to serve it, then it goes to their team leader; the person over a leader on the leaders map says yes, and past the limit or on a protected Sunday only the owner or whoever oversees the office; two weeks' notice for planned time off, sickness and emergencies never blocked."
  - "Decided in the build, not by Kevin (all 21 are in docs/CHURCH_SCHEDULE.md section 7.2): one Postgres function, church_away_settle, writes the yes and its away date in one transaction; an approved ask becomes a serve_away row, so Who serves when learns nothing new; the reason never leaves church_away_asks; Admins do not change the roster, the notice days or the leaders and office numbers; a member-app session never carries the owner's across-the-board power; a department with no number has no limit; private reasons are cleared 90 days after the last day."
  - "The rules read the church's own data (church_over.above, roles, groups, departments, seats, its add and remove list), never a title word or a role key."
  - "church_away_asks is unrelated to church_map_asks and member_asks."
  - "Decided while building S1-2 and S1-3, not by Kevin (docs/CHURCH_SCHEDULE.md section 7.4 lists every one): nobody answers their own ask, nor (the owner aside) one they entered; the asker, the owner and whoever oversees the office take one back; can't make it is for the days inside the church's notice days (two at least), farther out is asked for as time off; only the one person the owner is needs no yes; a login that is no longer an Admin or Manager seat has left the office; the note that comes with an answer is as private as the reason; someone not on the schedule can't ask (the owner adds them first, the owner's own name included at a church with nothing set up); a waiting ask shows on the calendar only to those who may read it; too many waiting never blocks can't make it; who oversees the office is read fresh from the church's own rows, not from the minute-old duties cache."
  - "Decided while building S1-4 (docs/CHURCH_SCHEDULE.md section 7.5 lists every one; the first is the lead session's, the rest the build's): taking back tells whoever it went to when the asker does it and they had been told, and tells the asker when the owner or whoever oversees the office does it, sent once and never tried again; no notice and no log line ever says the reason or the note; time off and another commitment read the same on a lock screen; an answer and the nudge wait out quiet hours as a planned ask does; an ask is sent on only when its `to` has left the nearest step over the asker, never round the same step; one nudge an ask, for good; the sweep follows CHURCH_ASSIGNMENTS as well as CHURCH_SCHEDULE; only the reason is cleared at 90 days."
  - "Decided while building S1-5 (docs/CHURCH_SCHEDULE.md section 7.6 lists every one; the first is the lead session's, the rest the build's): the note that came with an answer is cleared with the reason, 90 days after the last day; on Dates a member-app session is always a person, so the owner's own person and the person of whoever oversees the office read and answer only what went to them; how many asks wait for someone is kept a minute beside the roster, so the Lead tab and the tab bar cost no read on a page view; what is kept decides the switcher, never the page, which reads fresh; who covers is picked from the people on the schedule (200 at most), never the whole church; Who else is away says a name, the days and who covers, never the kind; a refusal comes back as the page's own plain words by a short code; a note goes with not this one only; short notice is said before and after a planned ask and never on can't make it; the page's header shows no role names; a notice's words are unchanged, only where it opens and its button."
related: [2026-10-23-sunday-planning-serving.md, 2026-11-04-church-map-chain.md, 2026-11-12-church-assignments.md, 2026-11-12-church-handovers.md, 2026-11-17-event-volunteer-dates.md]
---
**S1-5: Dates on the member app's Lead tab.** `member_portal_dates.py` serves
`/my/lead/dates` and its writes. One of the church's people asks for time off
(first day, last day, time off or another commitment, a private reason, who
covers), says "I can't make it" (the days just ahead, on the calendar at once,
no yes), takes one back, says yes or not this one (with a short note) to what
went to them, and sees who else is away: a name, the days and who covers,
never why. Every call into `church_schedule` is made as a person
(`_ch_me`), so nobody carries a login's across-the-board view there.
`church_schedule.section` gives the Lead tab's switcher its Dates entry and
count, and `member_portal._leads` the tab itself, from what is kept a minute
(the roster, and now `waiting_kept`): no read on a page view. Someone not on
the schedule with nothing waiting on them sees no change. A person's notice
opens this page (`church_schedule_tell.MEMBER_PAGE`, button "Open your
dates"). The sweep now clears the answer's note with the reason. No
migration; not there at all until the schedule's own is applied. Tests:
`test_member_portal_dates.py`, at New Hope on `test_member_portal_assign`'s
harness; each rule was broken once to see its test go red.

**S1-4 (#1934): who is told, and the hourly sweep.** `church_schedule_tell.py`.
`church_schedule.ask`, `answer` and `withdraw` hand the row on once the write is
back (`_after`, a thread of its own), never inside it, and a notice that fails
never fails the write. A new ask tells whoever it went to once (`told_at`,
claimed in the database before the send and let go when nothing could be sent);
"can't make it" goes at once and a planned ask waits out the church's quiet
hours. An answer tells the one who asked once (`answer_told_at`); a yes nobody
had to give tells nobody. One of the church's people gets a push and a line in
their conversation with the church, and an email only when no phone was
reached; an office login gets the office app's push and an email. Taking back
is told once, straight after the write. The sweep (`church_schedule_sweep`,
hourly on the worker, listed in `TICKS`) tells what a write couldn't, sends one
nudge three days on, sends a waiting ask on when who is over the asker changes,
and clears the reason 90 days after the last day (since S1-5, the answer's
note with it). It reads nothing with the
switch off or before the migration, and never works a sample church. The reason
and the note are in no notice and no log line: every row is cut down at the
door (`_bare`), the sweep never selects them, and `sb_patch_as_service` now
takes `redact=`. No migration. Tests: `test_church_schedule_tell.py`, at New
Hope through the real routes and senders; each rule was broken once to see its
test go red. `church_schedule_fake` now keeps what a write hands on in
`db.later` and does not run it.

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
Anything new in the member app calls the engine as a person
(`member_portal_dates._ch_me`), never as a login.
Anything new that tells someone about an ask goes through
`church_schedule_tell` and starts from `_bare()`: a notice never carries the
reason or the note.
