---
title: The leaders schedule — who is away, who says yes, how many at once
date: 2026-11-18
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-18: "I want to be able to build Leaders schedule. this is for when leaders are planning time off and have certain obiligations so that we as a church can plan around meeting ... making sure that everyone is not gone at the same time on our services. allowing only so many people off at the same time. ... there should volunteers one and one for leadership ... divided amongs the department to manage there department as well." Then, on the five calls the plan rests on: "Yes build to all five"'
status: in progress
prs: [kmj-intake-server#1929, kmj-intake-server#1930, kmj-intake-server#1934, kmj-intake-server#1936, kmj-intake-server#1938, kmj-intake-server#1941, kmj-intake-server#1943]
migrations: [supabase/APPLY-2026-11-19-church-schedule.sql (applied), supabase/APPLY-2026-11-20-church-schedule-limits.sql (applied)]
left_undone:
  - "The migration is applied (2026-11-18, run by the owner, checked by the lead session with the file's Check block), and CHURCH_SCHEDULE is unset, which means owner: the schedule is open at the platform owner's own church and closed everywhere else. Everything built here is live there. Opening it for other churches means setting CHURCH_SCHEDULE=on on both services."
  - "S1-7 things that repeat (and telling whoever is over someone when one is added, its part of the Dates page, and the scheduler holding them on those days through church_schedule.holds). Its own PR, from the newest main."
  - "The office app has no screen for an ask yet (the office frontend comes after the backend): a login's notice still opens the office app, where the ask isn't shown. A login whose person is on the schedule answers in the member app, on Dates, as that person."
  - "Dates: the count beside it in the Lead tab's switcher is kept a minute a replica, so on another replica it can lag a minute after an answer (the Dates page itself is always fresh). An approved date taken off under Serving, Away now takes its ask back (S1-6); only one taken off while the switch is closed for the church still leaves its ask a yes, and Dates shows that one as Off the calendar."
  - "CHURCH_SCHEDULE is read on both services since S1-4 (the web service for the routes and each write's notice, the worker for the sweep). Unset means owner on both; to change it, set the same value on both. The sweep also works only the churches CHURCH_ASSIGNMENTS is open for."
  - "Open for Kevin or the lead session (docs/CHURCH_SCHEDULE.md sections 7.5 and 7.6): the owner's own time away tells nobody (the plan had the office overseer told); when the owner takes an ask back, whoever it went to is not told; who covers is picked from the people on the leaders schedule, anyone else is typed as a name; Who else is away never says what kind of time away it is; Dates does not tell a leader that their reason is cleared after 90 days."
  - "Open for Kevin or the lead session from S1-6 (docs/CHURCH_SCHEDULE.md section 7.7): when the places someone had agreed to serve can't be opened after a yes, it is logged once and nothing tries again; on a replica that has never read who is on the schedule, and can't, a leader's Away from the Serve page is saved at once, as before the leaders schedule (the lead session chose this so that a volunteer's Away never fails; one line is logged when it happens); someone on the leaders schedule sees no waiting ask under Away on My serving, only the way to Dates; the Away form there always asks for time off, tomorrow included, and can't make it stays under Dates; taking a yes back does not put them back on a place that opened; the test that renders main's own My serving beside this one is skipped in CI (one commit is checked out) and should be deleted the first time that page is changed on purpose."
  - "Step 2, the limit: its tables are applied (2026-11-18, run by the owner, checked by the lead session with the file's Check block), and S2-2 and S2-3 are built: the numbers, the service days, the protected days, and an ask past the number or on a protected day flagged and sent up. Live at the platform owner's church. Still ahead, each its own PR: S2-4 pairs (church_away_pairs, the pair flag) and S2-5 the volunteers' rules (volunteer_plan, team_leader, the Away form's volunteer branch, team_group_id). GET /church/schedule/volunteers is there and read only; its waiting list is empty until S2-5."
  - "The numbers, the usual service days and the protected days have no screen: they are set through the API (PUT /church/schedule/limits, POST /church/schedule/protected-days) until the office frontend exists. At the platform owner's church nothing is set, so the leaders number is the worked-out one in four, no department has a number, and no day is protected."
  - "Open for Kevin or the lead session from S2-2 and S2-3 (docs/CHURCH_SCHEDULE.md section 7.9): the one over the asker is not told when their ask goes up (only whoever it went up to is); a department's own leader or overseer counts toward its number only when they are on one of its Sunday teams; the recheck at the yes is not a lock, so two yeses in the same moment for two people can put a Sunday one over; a leader's Away from the Serve page on a full day goes up with no look first (the look is on Dates); nothing tells a leader whose waiting ask sits on a day that was made protected afterwards, until someone says yes to it; a department's leader sets its number as an office login, not yet from the member app."
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
  - "Decided while building S1-6 (docs/CHURCH_SCHEDULE.md section 7.7 lists every one): the hold reads who and which days and nothing else, fails open, and asks the switch, then the tables, then the church, so nothing is read where it isn't open; everyone with an ask still waiting is held, and everything that asks the board gets the hold (the office, a team's own leader, a teammate finding a sub, an event date, the worker's No answer yet note); a held person reads as away in the board's own words and is never in its list of who is away; a volunteer's Away never fails because of this (the lead session, in the review of #1938): when the roster can't be read again the last one read answers, and a replica that never read one saves the Away at once, as it always was; the roster rule stands as built (everyone who leads a group is on it; the lead session counted the platform owner's church and found nobody who leads only a small group); under owner, whose church it is is kept a minute even when it couldn't be read; a date whose ask is gone or already settled comes off as a plain date; a yes opens only places that are a yes, on days still to come, saved exactly as Can't make it saves one with Away for why, in the request straight after the write and never able to fail it; the serving flag is set when asked; Dates says before the yes that a place will open."
  - "Decided while building S2-2 and S2-3 (docs/CHURCH_SCHEDULE.md section 7.9 lists every one; the first three are the lead session's, the rest the build's): an ask past the number or on a protected day is never refused, it is flagged and goes up; can't make it and the owner's own are never looked at, never flagged, and still count for the next person; a waiting ask is neither counted nor shown, only an away date that was agreed; who may give an exception is the owner, and whoever oversees the office unless the asker is a shepherd or a senior; in the member app only the very person it went up to; only whoever it went up to is told, with one clause more than any notice (past the number, or on a protected day) and never how many, who or which day; the exception is the ask's flags still true at the yes, saved with the yes in one transaction; a yes on an ask that has run into something new never lands the first time, whoever presses it; an ask entered for someone never goes up to whoever entered it; full is at the number, and the asker's own away dates never count against them; a department's number counts the members of its Sunday teams and holds a leader only when they are one of them; two services on one day don't make a weekday usual, a service on two days does; an Admin sets no church-wide number, usual day or protected day, and can set a department's (an Admin holds every duty); on Dates the look before sending is a second press with what they typed still in the form, never a redirect (a reason never rides in an address) and never a script; step 2 has its own check for its tables, and on a database with step 1's file alone nothing of step 2 is read."
  - "Decided while writing S2-1 (docs/CHURCH_SCHEDULE.md section 7.8 lists every one, with each difference from the draft): church_away_settle, which the live code calls, is not dropped or changed; the exception a yes is given over has a function of its own name, church_away_settle_excepted, which calls it (this reverses decision 19: two functions of one name make Postgres refuse every six-argument call, and dropping and re-making the one would be undone by running step 1's file again); an exception sits only on a yes, is for a flag the ask has, and a bad one is refused by name with the yes undone; the person who set a department's number is checked to be the church's own; the usual service days are a plain list; the new checks are validated as they go in because both tables are days old; all three new tables are left out of the export."
related: [2026-10-23-sunday-planning-serving.md, 2026-11-04-church-map-chain.md, 2026-11-12-church-assignments.md, 2026-11-12-church-handovers.md, 2026-11-17-event-volunteer-dates.md]
---
**S2-2 and S2-3 (#1943, one PR): the limit on how many can be away at once.**
`church_schedule_limits.py` is new: the numbers (the leaders and the office each
have one, the church's own or one in four worked out; a department has one only
when a row says so), which days count (the church's own planned services, else
its usual weekdays, set or worked out from its plans, else Sunday; every
protected day; an event date for departments only), the protected days, and the
office routes `/church/schedule/limits`, `days`, `protected-days` and
`volunteers` (read only). Who is away is counted from `serve_away`, each person
once, never from an ask: a waiting ask is not counted and not shown.
`church_schedule.ask` looks before it writes: an ask that would put a service
day past the number, or that touches a protected day, is never refused. It is
flagged (`over_limit`, `protected_day`) and goes up (`goes_up`): to whoever
oversees the office, and from a shepherd or a senior to the owner alone. Only
someone who may give the exception says yes to it (`gives_exception`; in the
member app only the very person it went up to), and the yes is saved with its
exception by `church_away_settle_excepted` in one transaction. Every yes looks
again first (`_recheck`): one that has run into something new since it was asked
does not land; the ask is flagged, sent up and told to the new person, and the
one who pressed yes reads a 409 in plain words. "Can't make it" and the owner's
own time away are never looked at. The sweep never sends a flagged ask back down.
On Dates, "Ask for these days" on a full or protected day sends nothing the
first time: the page comes back with what they typed still in the form, what is
in the way, the nearest open service days and who can make an exception, and
"Ask anyway" sends it; both cards then say why, as a count and never a name.
Step 2 has its own check for its tables (`church_schedule_limits.ready()`,
pinned False by `conftest`): on a database with step 1's file alone none of this
runs and nothing of step 2 is read. No migration of its own; both were applied
on 2026-11-18 before this merged, so it is live at the platform owner's church
from its first deploy. Tests: `test_church_schedule_limits.py`, and additions
to `test_church_schedule_tell.py` and `test_member_portal_dates.py`, at New
Hope; each rule was broken once to see its test go red (55).
`church_schedule_fake.build(limits=True)` is a database with step 2's file,
and its default refuses everything that file adds.

**S2-1 (#1941): step 2's tables, and nothing else.**
`supabase/APPLY-2026-11-20-church-schedule-limits.sql` (**applied 2026-11-18**, after
step 1's file) adds the two group numbers and the usual service days to
`church_schedule_settings`, makes `church_schedule_department_limits` (one number
a department, no row = no limit), `church_protected_days` (one row a date a
church) and `church_away_pairs` (two people who can't be away together, saved
once, private), and gives `church_away_asks` `excepted` (the flags a yes was
given over) and `team_group_id`. `church_away_settle`, which the live code
calls, is not touched; `church_away_settle_excepted` is new, calls it, and saves
the exception on a yes it just made. No Python in that PR: nothing read any of
it until S2-2 and S2-3, and the deployed code named every column it read, so
running the file changed nothing anyone saw. The three tables are in `account_lifecycle.EXPORT_EXCLUDED`; the
ledger has the row; `__tests__/church_schedule_limits_db.mjs` (289 checks on
PGlite, each rule broken once to see it go red) runs in CI's database job, and
runs step 1's own check, unchanged, with this file applied after it.
`docs/CHURCH_SCHEDULE.md` section 2.2 is the map of the file and 7.8 lists every
difference from the draft.

**S1-6 (#1938): the leaders schedule meets Who serves when.** `church_schedule.holds`
is the scheduler's hook: `sunday_planning._Board` reads it once into `held`, and
someone whose ask still waits reads as away for those days (`candidates`, a 409
from an ask, skipped by a fill), in the board's own words, for the office, a
team's own leader, a teammate finding a sub and an event date. It selects who
and which days only, is never in `/planning/schedule`'s `away` list, fails open,
and reads nothing where the switch is off, closed for the church, or before the
migration. On the Serve page, Away for someone on the leaders schedule
(`takes`, the roster kept a minute) is asked for through `church_schedule.ask`
as that person, and the page says so by name with a way to Dates; a volunteer's
Away makes the same calls and the same page as before, byte for byte. Taking
off an away date that came from an ask takes the ask back through
`church_away_settle` (`withdraw_fact`). A yes, and a "can't make it" that
settles at once, opens the places that person had already agreed to serve
inside the days (`sunday_serving.open_places`, exactly what "Can't make it"
writes), after the write and never able to fail it; the ask carries `serving`,
and Dates says so while it waits. No migration of its own. The schedule's
migration was applied on 2026-11-18, before this merged, so all of this is live
at the platform owner's church from its first deploy; at every other church the
switch is closed and nothing is read. Tests: `test_sunday_planning_holds.py`, at New Hope
through the real scheduler, engine and member routes; each rule was broken
once to see its test go red.

**S1-5 (#1936): Dates on the member app's Lead tab.** `member_portal_dates.py` serves
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
migration; it wasn't there at all until the schedule's own was applied
(2026-11-18). Tests:
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
on, owner when unset), and every route answered 404 until the migration was
applied (2026-11-18). Who is on the schedule is read from the church's own data (everyone
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
`supabase/APPLY-2026-11-19-church-schedule.sql` (**applied 2026-11-18**) makes
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

Before building more here: read `docs/CHURCH_SCHEDULE.md` first. The migration
is applied (`docs/MIGRATIONS.md`), so anything merged here is live at the
platform owner's church at once. Anything that
shows someone as away must read the fact in `serve_away`, not an ask's state.
Anything new that returns an ask must go through `church_schedule.shape()`.
Anything new in the member app calls the engine as a person
(`member_portal_dates._ch_me`), never as a login.
Anything new that tells someone about an ask goes through
`church_schedule_tell` and starts from `_bare()`: a notice never carries the
reason or the note.
Anything new that schedules people asks `sunday_planning._Board.is_away` (or
`candidates`), which already knows who is held; it never reads
`church_away_asks` itself, and never puts a held person in a list of who is
away.
Anything new that reads one of step 2's tables or columns, or looks at the
limit, asks `church_schedule.step2()` first: `ready()` is true with step 1's
tables alone.
Anything new that counts who is away reads `church_schedule_limits.picture`
(the facts, each person once): never a waiting ask, which a count would give
away.
Anything new that decides who answers an ask goes through
`church_schedule.may_decide`: a flagged ask is answered only by someone who may
give its exception, and in the member app only by the very person it went up to.
