# Church assignments: whoever is over people can start them, hand them work, and see it move

Kevin, 2026-11-11. The ask, in his words:

- "lets build what is missing" (the review: https://claude.ai/artifact/FDqG3nA3jBaNVaSzzviW5f).
- "we also need to allow for the admin to pick days for work load that works for them."
- "we also need to allow for Jessica to be able to hand out assignments to each of them as well."
- "whatever we are building, this needs to be a way for churches to set this up in a general
  sense when they establish leaders over people."

What the review found (origin/main 457f4c1f): every office login has its duties
(church_duties.CATALOG, 47) and a week by day (church_my_week.rhythm), and whoever is over the
lanes has See as, the team page and the Monday roll-up (church_team_week). Two things are
missing. Nobody hands a person a **first assignment**: what to gather before the weekly job can
run. And almost nothing knows when it's **done**: `church_my_week._done` knows the leaders note,
the weekly text and the monthly report, 3 of 47. Love City's live data since 10-27: 0 tasks
handed to anyone, 0 duty moves, the October monthly report never started.

## The rule (the general part)

Every church puts some people over others. The office: an Executive Pastor (or whoever the
church names to oversee the office) over the office logins. The ministry: an overseer over
department leaders, a department leader over the leaders of its teams and groups, anyone a
holder row says answers to them. **Whoever is over people gets the same three things, at
every church:**

1. **Start them:** a first assignment drawn from the jobs they hold, with dates.
2. **Hand them work:** an assignment with a date and what "done" means.
3. **See it move:** done, not yet, late, stuck; and send what's stuck up to whoever is over
   *them*.

And the person under them picks the days their weekly jobs fall on.

Who is over whom is **the church's own data**, never names or title words in code:
church_duties (who holds `oversee_lanes`, the seats) for the office, and church_map (holder rows'
`answers_to_contact_id`, departments' `leader_contact_id` / `overseer_contact_id` and their units)
for the ministry. Love City is the first church to use it, not the shape of it. The tests run it
at the four fixture churches (`__tests__/church_three.py`: Love City, Grace Baptist, New Hope,
Riverside).

## Decisions (mine, 2026-11-11)

1. **An assignment is a task** (`public.tasks`), handed to one person: a login (`assigned_to`) or
   one of the church's people (`assigned_contact_id`); `tasks_handed_to_one` already holds
   that. Reason: everything that tells, escalates and shows a handed task already works and
   stays the one list: the hand-off email and push (church_office_tasks, church_leader_tasks),
   late going up (to `handed_by` and the Executive Pastor; for leaders `chain_for`), My week,
   the team page's open/late counts, the Monday roll-up's late lines, the Lead tab's tasks, and
   Tasks → By person. New columns only add what an assignment has that a task didn't.
2. **"Over" is one function** (`church_over.py`), used by every route and every Chief verb here.
3. **The first assignment comes from templates in code** (`church_startup.py`), keyed by office
   duty and by leader switch, in general words. A church's own list is rows (tasks), so every
   church can change its own; Chief can draft for a new church.
4. **A check can tick an item off; it never invents one.** A check answers done / not yet /
   only evidence ("7 rooms listed": a person confirms). A check that can't be read claims
   nothing.
5. **Days are picked per person per duty** and read everywhere a duty's day is read today.
6. **Switch `CHURCH_ASSIGNMENTS` = off | owner | on**, default owner (the platform owner's own
   church, `member_asks.platform_church`, as church_team_week.church_open). Closed = the routes
   answer 404 and nothing reads the new columns. Set on both Railway services (the sweep runs on
   the worker). Turns on for everyone on a Thursday.
7. Money never travels through this: a Manager is never handed a money duty's start-up item
   (`church_duties.holds` already refuses money duties to Managers), and the board never shows
   an amount.

## The data (one migration: `supabase/APPLY-2026-11-12-church-assignments.sql`)

Additive, safe to run twice, `begin; … commit;`, a comment on every new column.

`public.tasks`, new nullable columns:

| column | what |
|---|---|
| `duty text` | the church_duties.CATALOG key, or the leader switch (`lead`, `oversee`) it belongs to (null = none) |
| `done_when text` | what done means, in the church's words (≤ 300) |
| `check_key text` | a church_work_checks key that can tick it off |
| `startup_key text` | the template it came from; null = handed by hand |
| `stuck_note text` | why it's stuck (≤ 500); null with `stuck_at` null = not stuck |
| `stuck_at timestamptz` | when it was marked stuck |
| `raised_at timestamptz` | when it was sent up to whoever is over the person who handed it |
| `raised_to uuid` | the login it was sent up to (or) |
| `raised_to_contact_id uuid` | the person it was sent up to (a check: never both) |
| `raised_by uuid` | the login that sent it up (added in PR A: the email names who sent it up, and no other column says) |
| `raised_told_at timestamptz` | the sweep told them (claimed before the send) |
| `checked_at timestamptz` | a check ticked it off (status done, done by no one) |

Also (PR A): checks `tasks_raised_to_one` (never both) and `tasks_assignment_lengths` (the two
lengths, and the shape of `duty`, `check_key`, `startup_key`); trigger `tasks_raised_same_business`
(the person it was sent up to is the task's own church's, as `tasks_leader_same_business` holds the
leader). `raised_to` and `raised_by` reference `auth.users` (set null on delete),
`raised_to_contact_id` references `contacts` (set null on delete).

The lock (#1801 review): the file holds ACCESS EXCLUSIVE on `tasks` until it commits, so it scans
nothing it doesn't have to. Every new column is null on every row that exists, so the two CHECKs and
the three foreign keys go in `NOT VALID`: nothing old is checked under the lock, and every row
written from then on is. Each can be validated later under a lighter lock. The three indexes are
built as they are (`tasks` is small on this platform). PGlite check: `__tests__/church_assignments_db.mjs`.

Index: `tasks_startup_once` unique on `(business_id, coalesce(assigned_to, assigned_contact_id),
startup_key) where startup_key is not null`, so a start-up item is made once per person.
The board needs no `(business_id, handed_by)` index: it reads by church, status and assignee, which
`tasks_handed_open` and `tasks_leader_open` already cover. PR A adds two small partial indexes for
the hourly sweep instead: `tasks_raised_untold` and `tasks_check_open`.

`public.church_duty_days` (server-only: RLS on, no policies, browser roles revoked):
`business_id uuid not null references businesses on delete cascade, user_id uuid not null
references auth.users on delete cascade, duty text not null, day text not null check (day in
('Mon','Tue','Wed','Thu','Fri','Sat','Sun')), set_by uuid, updated_at timestamptz default now(),
primary key (business_id, user_id, duty)`. Registered in `account_lifecycle.EXPORT_EXCLUDED` (sign-in
user ids mean nothing in another business; a restored church's logins pick their days again).

## church_over.py

```
under(biz, me) -> list of {kind: 'login'|'person', id, name, why}
is_over(biz, me, target) -> bool        # every write checks this
above(biz, who) -> list of the same     # who a stuck item goes up to
```

`me` / `who` is a login (user id plus its seat) or one of the church's people (contact id; a
member signed in to the member app). A login's person is its `business_users.contact_id`, else
the one contact its sign-in email names (`business_users_router.match_contact`'s rule, read for
every login at once; the owner's by their Auth email). `seat_person` is not used: it writes.

An office login is an Admin or Manager seat (a Member or Viewer login does no office jobs, as
`church_duties` says, and `member_portal_messaging.office_contacts` counts the same two).

Over an office login:
- the owner and every Admin are over every office login but their own;
- a login over the lanes (oversee_lanes: by role key, or the map's `office_overseer_roles`, or a
  duty move) is over every Manager login but itself; never over an Admin or the owner.

Over one of the church's people (only where `church_map.opened` gives a map: the church open and
`ready()`; closed or not ready, the owner, the Admins and a login over the lanes are over everyone,
as tasks for leaders work today):
- whose active holder row answers to me (`answers_to_contact_id`);
- the leader of a department I oversee (`overseer_contact_id`);
- the people of what hangs from a department I lead: its groups' leaders, its Serve teams'
  leaders (a role that covers a team, scoped to it) and the holders of its roles; while a
  department has no leader who leads, its overseer is over them directly (`chain_for`'s step 2);
- walked down: whoever is under someone under me is under me too, each person once;
- the owner and the Admins are over everyone who leads or holds a role.

Qualifying, as `church_map.chain_for` climbs: someone is over others through a department only
while they hold an active role with its switch (an overseer can oversee, a leader leads), through
answers-to while they hold any active role. The one under them needs nothing. (At New Hope, Kara
leads Kids but her role doesn't lead: she is under Amara and over no one.)

A person with an office login is their login (their work lands in My week), as
`church_leader_tasks.leaders` keeps them out of the leaders list. **The map never hands anyone a
login the office rule doesn't** (#1801 review): a person the walk reaches who has an office login is
added as that login only when the caller is the owner or an Admin, or the caller is over the lanes
and the login is a Manager seat; never an Admin's to anyone else, never the owner's. (Without this,
a Manager or a Member seat whose person the map puts over an Admin's person could read, change and
take back the Admin's tasks and move the Admin's money days.) The walk still goes on through them
to the people under them, who are persons.

**The owner's own identity** (`Church.top`) is never under anyone, not even the owner, and the walk
never goes through it: every one of the church's people whose email is the owner's sign-in email
(all of them: a family address too) and the owner's person however it was found. A failed read of
the owner's sign-in email (`messaging_router.owner_email_read`, which tells a failed read from "no
email") is a 503, never "the owner is nobody"; a good read is kept ten minutes per replica. In
`above()`, a step that is the owner's identity is the owner's login.

**The senior holders are under the owner only** (`Church.seniors`). This was Claude's decision,
made on 2026-11-12 in the #1801 review (round 2), not Kevin's: he hasn't been asked yet, and it is
his to confirm or change. The rule: every holder of a role whose *job* is the senior one (`church_roles`: the top of
every chain; a job, never a title) or, where the map names them, of a role that gives the pastor's
yes (`pastor_yes_roles`), who isn't the owner's identity. The owner can hand them work and start
them; no Admin, Manager or Member seat is ever over them, whatever the map says (an answers-to row
naming someone below them included), and no walk goes through them. So at a church on the Church of
Christ template, where "Elders (Shepherds)" is the senior role and several elders share the top,
the owner can start each elder and hand them work, and nobody else can (tested at Riverside set up
on that template). A senior holder's own stuck item goes up to the owner; a stuck item whose chain
ends at the senior role goes to that holder (their person; their login if they have an office
seat). So the senior pastor is never under an Admin even when his record carries another email than
the one he signs in with (he is then under the owner, who can't tell that person is himself).

**Known limit:** an owner whose contact record carries another email than his sign-in email *and*
who holds no senior (or pastor's-yes) role can't be told from any other leader, so he can still show
under an Admin (as a group's leader, say, or a role holder). The fix is data: put the owner's
sign-in email on his record, or give him the church's senior role.

**Pastors and elders (Kevin's rule, 2026-11-12):** no Admin's, lanes overseer's or closed-map
standing is over anyone who holds a role that shepherds either, nor over a login whose person
does; the owner and the map's own chain are. See "Pastors and elders, and From the office" below.

A money duty's day is picked only by the owner or an Admin (403 otherwise, whoever is over the login).

`above(who)`: for an office Manager login, whoever is over the lanes, else the owner; for a
login over the lanes or an Admin, the owner; for a person, `church_leader_tasks.overseer`
(`church_map.chain_for` where the map is open, `chain_above` where it isn't) then
`group_department`, the same steps a late task already climbs; at the top, the owner. Never
yourself. A step that is an office login's person is that login.

`why` is plain words for the board: "Office · Sunday & Serving", "Leads Youth", "Answers to
you", and further down "Youth Ministry (YWD) leader · under Yolanda". Loops end (each person
once). A failed read is a 503, never "nobody is under you".

Each login's duties come from the church's rows read once (`Church.held`: its seats, its moves, who
the Executive Pastor is), the same answer `church_duties.standing` gives (a test holds them equal at
all four churches), so the board doesn't read a dozen tables a login.

## church_startup.py (the first assignment)

`TEMPLATES`: a list of `{key, duty, title, done_when, week (1-4), check}`.

- Office items, keyed by CATALOG duty. Start from the four lists on the review page (Naiya's,
  Tiara's, Laquesha's, Shapretta's), reworded so they read right at any church: "Every room in
  the system", "The next 8 weeks on the calendar", "Every volunteer team has a leader",
  "ChurchSavvy's team has joined", and so on. One to three items per duty, about 5-9 per lane.
  Duties with nothing to gather have none. The Executive Pastor's lane gets "Start each office
  login's first assignment" and "A first one-on-one with each".
- Leader items, keyed by the person's role switches (church_map.can): `can_lead` → their team or
  group with its people, the day and time it meets, its room, its first need; `can_oversee` →
  meet each leader under you, and each has started their first assignment. Words only from
  the switches, never title words (`test_church_no_title_words.py`).

`start(biz, by, target)`: for the duties the target login does of its own, or the target person's
role switches (a role with `can_lead`, or a group they lead; a role with `can_oversee`), makes the
missing items as tasks handed to them
(`handed_by` = by, `startup_key`, `duty`, `done_when`, `check_key`, `due_date` = the church's
today + 7 × week). Made once per person per key (the unique index); a second start makes only
what's new and says how many it skipped. Returns what it made.

"Of its own" (corrected in PR A): `church_duties.duties_of` is every duty for the owner and the
Admins, and every non-money duty for the Executive Pastor's lane (it covers the whole office), so
starting the Executive Pastor from it would hand her 25 items. A login's own duties are its lanes'
starter duties (the Executive Pastor's lane only its two, `OVERSIGHT`), what was moved to it by
name, and for a Manager no lane names, what its areas give it; the owner's and an Admin's, their
stored lane's and what was moved to them. Never a money duty. So Love City's Jessica gets her two;
Minnie (Treasurer, all money) gets none; Grace's Sharon, who was moved every duty, gets every
office item.

PR A's lists (`church_startup.TEMPLATES`): Office & Leadership 6, People & Care 6, Sunday &
Serving 5, Media & Communications 6, over the lanes 2, `lead` 4, `oversee` 2; ten carry a check.

## church_work_checks.py

`CHECKS[key](ctx) -> {done: True | False | None, text}`. `ctx` reads each table once per church
per request, so a board of five logins doesn't read a table five times (church_team_week took
9-14 s for five logins before #1799; keep this inside one or two reads per check kind).

Start with the checks the code already counts or can count plainly, and mark the rest
evidence-only (`done: None`). The keys PR A ships:
- `rooms_listed` (`church_spaces`, active rooms): evidence, "7 rooms listed";
- `calendar_8_weeks`: each of the next 8 weeks (this one first) with a service or an event, read
  where the leaders note reads the calendar: the Sunday plans (`worship_services`) and Services &
  Events (the `event_roster` rooms' `module_entries`). **Corrected:** `events` is the activity log
  (`sms_broadcast` and the like), not the calendar. "3 of the next 8 weeks have something on the
  calendar"; done at 8;
- `departments_led` (`church_departments`, active): "9 of 12 departments have a leader"; done when
  every one has one;
- `groups_led`: active `groups` without a `group_members` leader (church_areas' count, read
  directly: `church_areas.build` fills the role library, a write); done at none without;
- `kids_checked` (`space_leaders`, space kids): **evidence only** (#1801 review). The table holds
  a check date on every row by its own rule (`background_check_on` is not null), so "every one has a
  date" could never fail, and it isn't the list of everyone who works with the kids (youth rows
  aren't kids workers). "4 kids leaders approved with a background check date"; a person confirms;
- `follow_up_no_one`: people in follow-up with no one (the leaders note's `_no_one`, My week's
  count). It counts everyone in follow-up, not only first-time guests; done at 0;
- `churchsavvy_joined` (`worship_team`): done when nobody invited is still waiting and at least
  one has joined; nobody on it is not done;
- `serve_teams_led` (`serve_teams`, owner volunteers, against `group_members` leaders): done when
  each has one;
- `sermons_6` (`sermons`, published): the last six Sundays, each with its sermon; done at 6 of 6;
- `weekly_text` (`church_my_week._done` weekly_text).

Where there is nothing to count yet (no groups, no departments, no volunteer teams) a check says so
and claims nothing (`done: None`): a person confirms. The evidence-only keys (`rooms_listed`,
`kids_checked`: `church_work_checks.EVIDENCE`) never tick, so the sweep never reads their items.

A passed check ticks its open task off: on read (the board, a person's list) and in the hourly
sweep, `status='done'`, `completed_at`, `checked_at` set, done by no one, filtered on its church,
still open and still naming the check. A check that fails to read says "Couldn't count just now"
and changes nothing.

## Weekly jobs know when they're done (second PR)

Extend `church_my_week._done` with first_guests, serve_schedule, calendar, sermons, attendance and
shepherding, each "by" the person's picked day, else the catalog's. The team page and the Monday
roll-up then say done / not yet / late for each job due this week instead of only its day.

### As built in PR B

`church_my_week._done_full(business, duties, today, now, tz, picks=, ctx=)` answers `{duty: {done,
text}}`; `_done` is the same without the words. The week is the one the church's own clock is in,
Monday to Sunday. The six jobs are judged only where `CHURCH_ASSIGNMENTS` is open for the church
(closed: the three it already knew, and nothing else is read). Each test, exactly
(`church_work_checks.WEEKLY`, each reader shared with the start-up checks where they count the same
thing):

| job (catalog day) | done when | reads |
|---|---|---|
| `first_guests` (Mon) | nobody who came into follow-up by the end of the job's day is waiting with no one (handed back, or never handed). It counts everyone in follow-up, as the leaders note and My week do (the board marks no first-time guest beyond a first check-in), and a card that came in after the day is next week's | `church_follow_ups` open or handed back (the same reader as `follow_up_no_one`) |
| `serve_schedule` (Wed) | every place on the volunteers' Serve teams (`serve_teams` owner volunteers, the team's group active, its active positions, each `needed` times) has a `yes` (`serve_assignments`) for every service planned this week's Sunday. Nothing planned that Sunday, or no volunteer places: nothing to count, it claims nothing. ChurchSavvy's teams are `production_schedule`'s, never counted here | the calendar's Sunday plans, `serve_teams`, `groups`, `serve_positions`, `serve_assignments` |
| `calendar` (Fri) | next week (the Monday to Sunday after this one) has at least one service or event on the calendar (the Sunday plans, or a Services & Events occasion), and every occasion in it names its place. Nothing next week: not done | `worship_services` and Services & Events, read where the leaders note reads them (the same reader as `calendar_8_weeks`) |
| `sermons` (Mon) | last Sunday (the day before this week's Monday) has a published sermon preached that day; its notes aren't counted | `sermons` (the same reader as `sermons_6`) |
| `attendance` (Sun) | this week's Sunday service has a count: a named check-in (`attendance`) or a headcount above zero (`attendance_headcounts`) **for that Sunday's service**, dated by the service's own entry (`module_entries`: its `_checkin_day`, else the date under its room's own date field, `events_rsvp_router.resolve_fields`, as `church_checkin` reads it; a check-in on an entry with no day, the day it landed, as `church_shepherd_signals._entry_days`; a class night is no service). So correcting last Sunday's count on this Sunday never marks this Sunday done (#1802 review). A headcount on an entry with no day, saved since that Sunday began, might be that Sunday's: then it can't be said either way (couldn't be read), never "missed" (#1802 review, round 2). Before that Sunday it is not yet, and nothing is read. A Sunday is a week's last day, so this job is never late within its week | `attendance` and `attendance_headcounts` since last week's Sunday, and their entries |
| `shepherding` (Thu) | every family drifting **by the end of the job's day** (a drift signal made by then, `church_shepherd_signals`' own rule, still open) has a touch logged since that week's Monday (a call, visit, text or seen at church: `church_shepherd_touches`). A family that starts drifting after the job's day is the next week's job (#1802 review). No family drifting: done. The groups who missed weeks aren't counted | `church_shepherd_signals` open or closed since last week's Monday, `church_shepherd_touches` since then |

The three it already knew are unchanged: the leaders note sent this week, last month's report sent,
a text announcement that reached someone since Monday (now read through the shared `texts` reader).

**One clock** (#1802 review): every place that judges a church's week (My week's rhythm and its tasks'
days, the team page, the Monday roll-up, the one-on-one, the checks) reads
`church_work_checks.church_zone`: `church_leader_tasks.zone`, the business's availability zone, else
its owner's profile, else the platform's. One that can't be read is a 503 on the team page, the
one-on-one and the board, never a quiet UTC; the roll-up and the sweep skip the hour. My week, every
church's office logins' first page, never fails on it (round 2): its own lines use the platform's
default clock (`PLATFORM_DEFAULT_TZ`, else UTC), its rhythm carries no done, not yet or late
(`"judged": false`, `"judged_text": "Done, not yet and late couldn't be checked just now."`), and the
log says so.
My week used `chief_assignments._tz_for` (availability, else UTC) before: at a church whose clock is
on the owner's profile, Monday 9 PM in Detroit was already Tuesday on My week. The tests now give each
church its clock as data and patch no clock reader, so two that disagree can't hide.

**done / not yet / late** (`church_my_week.job_state`): done when its test passes; otherwise late
once the job's day is over (the day the login picked, `church_duty_days`, else the catalog's last
weekday; the monthly report, the first Monday of today's month), not yet until then. A job no test
judges, a test with nothing to count, and a read that fails all claim nothing: no state, never done,
never late. Every reader reads its table once per `church_work_checks.Ctx`.

Where it shows:
- My week's rhythm: each judged item has `done` (as before) and, where the switch is open, `state`,
  `state_text` and `detail` (the test's words). The rhythm carries `judged` (false only when the
  church's clock couldn't be read, with `judged_text`).
- The team page (`church_team_week.team` → `judge_week`): after every row is read, one `Ctx` judges
  every login's jobs, so each table is read once for the church however many logins there are (a
  test holds a team of five and of nine to the same reads). Each `this_week` entry a test judged gets
  `state`, `state_text`, `detail` and `due`; each row gets `this_week_counts` and `last_week`; the
  page's `counts` get `late_jobs`. `this_week_text` (the days only) stays as it was.
- **The keeper wall** (#1802 review): for an overseer who doesn't work People & care (`care` False),
  a judged job in People & care, Kids & youth or Groups & classes keeps its done / not yet / late
  (it is the login's own work) and never its `detail` (a count of people in follow-up, of drifting
  families). The roll-up cuts each holder's copy the same way (`without_care`). The one-on-one cuts
  its jobs to the asker's own view (`church_team_week.view_of`), as See as cuts a rhythm
  (`rhythm_within`): a job outside it isn't there at all; their assignments are their own, whatever
  area.
- The Monday roll-up: each login's lines say "Late on the week: …" when a job is late, "This week:"
  carries each job's state ("Mon: First-time guests and welcome calls (late) · Wed: The weekly text
  and email (not yet)"), and **"Last week: 6 of 7 done; missed: The church calendar."**

**Last week** (`church_my_week.last_week`; Claude's decision in the #1802 review, not Kevin's, since a
Monday morning can never say "late" about this week): each job that fell last week and that a check
judges, judged the same way at the end of its own day (the day the login picks now, else the
catalog's). Judged as of then: the weekly text (one that reached someone from that Monday to the end
of its day), shepherding (signals made by then, touches by then), attendance (check-ins by then; a
headcount keeps no first-entered time, so one entered later still counts), the monthly report (sent
by then). Judged as things stand now, since nothing keeps their history: first-time guests (those in
follow-up by the day who have no one now), who serves when (the answers now), the calendar (the next
week as it is now), sermon up. The leaders note: done when its last record is that week's, missed
when it's older; a newer one replaced it, so it's said as couldn't be read. A read that failed is
said as couldn't be read, never as missed; a job with nothing to count isn't in it. It is on the team
page too, on the same reads (`last_week` on each row: `{done, of, missed, unread, text}`).

```json
"this_week": [
  {"duty": "first_guests", "label": "First-time guests and welcome calls", "days": ["Mon"],
   "text": "Mon: First-time guests and welcome calls",
   "state": "late", "state_text": "Late", "detail": "1 person in follow-up by Monday has no one",
   "due": "2026-11-09"},
  {"duty": "care_visits", "label": "Care and visits", "days": ["Tue"], "text": "Tue: Care and visits"}
],
"this_week_counts": {"done": 1, "not_yet": 0, "late": 1},
"last_week": {"done": 1, "of": 2, "missed": ["First-time guests and welcome calls"], "unread": [],
              "text": "Last week: 1 of 2 done; missed: First-time guests and welcome calls"}
```
`last_week` is absent when nothing of theirs was judged last week (or the switch is closed).
and on the page: `"counts": {"logins": 5, "late_tasks": 0, "unread": 0, "late_jobs": 8}`.
`state` is one of `done`, `not_yet`, `late`; an entry without it is named by its day only.

### The one-on-one (PR B)

`GET /church/assignments/one-on-one?business_id=&for=login:<id>|person:<id>`, for anyone over them
(never yourself), gated like every assignment route (a church, the switch, `is_over`). It reads and
records nothing: no check ticks anything off here.

```json
{"for": "login:<uuid>", "kind": "login", "id": "<uuid>", "name": "Tiara Adams", "today": "2026-11-12",
 "finished": [{"id": "<uuid>", "title": "…", "on": "Tuesday", "checked": false}],
 "stuck": [{"id": "<uuid>", "title": "…", "note": "Need the family list",
            "since": "2026-11-06T15:00:00+00:00", "days": 6, "sent_up": true, "sent_up_to": "Pastor Kevin"}],
 "late": [{"id": "<uuid>", "title": "…", "due": "2026-11-10", "due_text": "2 days late"}],
 "next": [{"id": "<uuid>", "title": "…", "due": "2026-11-19", "due_text": "Due Thursday, Nov 19"}],
 "jobs": [THIS_WEEK entries, as on the team page],
 "lines": ["Finished in the last week: “…” and “…”.",
           "Stuck: “…” for 6 days, sent up to Pastor Kevin.",
           "Late: “…”, 2 days late.",
           "Next: “…”, due Thursday, Nov 19; …",
           "This week's jobs: The front desk, Mon; The Monday leaders note, late; …"]}
```

`finished`: done in the last 7 days, newest first. `stuck`: longest first; `days` since it was
marked stuck. `late` and `next` leave stuck ones out; `next` is the next five by due date (no date
last). `jobs`: a login's jobs due this week in the asker's own view (empty for a person, who holds
no office duty; empty when none of theirs lies in the asker's areas). The `Late:` line only when
something is late; `This week's jobs:` only when there are jobs.

## Pastors and elders, and "From the office" (PR C1)

Kevin, 2026-11-12: "admins can not give work to elders and pastors but they can give them
things that is related to their area that they need for them to have."

### The rule

No office standing but the owner's is over a **shepherd** or a **senior**:

- A shepherd holds an active role that shepherds: the role's own switch (`church_map.can`, the
  map's row, else the role's own columns, else its job's), never a title word. A role whose switch
  follows the Ministers setting (`can_shepherd` null) shepherds when that setting is on
  (`church_shepherding.settings`, read only then; a failed read is a 503, never a yes). At Love
  City: the Executive Pastor, the Associate Pastor and the elders (the Prophets' switch is off). At
  Grace: its deacons, whose switch the church turned on. At New Hope: its associate pastors and
  elders. At Riverside: nobody (nothing is set up).
- A senior is as before (`church_over.Church.seniors`): under the owner only, never walked
  through.
- "Office standing" is an Admin's (every office login, every leader), a Manager's over the lanes
  (every other Manager login), and the closed map's fallback (the Admins and the login over the
  lanes over everyone). None of them reaches a shepherd or a senior, nor a login whose person is
  one (Jessica's login, at Love City: she is the Executive Pastor, so an Admin isn't over it).
- The ministry chain still counts, walked from a login's own person, as anyone's: Marcus (an
  elder) answers to Jessica on the map, so her login is over him through her person, not her
  seat. An Admin whose person an elder answers to is over that elder the same way.
- The owner is over everyone as before. A leader who doesn't shepherd is as before.
- **The old Hand to list** (Tasks, `GET /church/my-week/people`: the office logins and, with My
  tasks for leaders, the church's leaders) follows it too, while assignments are open for the
  church: for any seat but the owner it offers no shepherd and no senior, nor an office login
  whose person is one (`church_my_week.without_guarded`); a task to yourself stays. The owner is
  off it too where the owner's own person is a pastor or an elder (`Church.owner_guarded`: Love
  City's owner is its senior pastor); a church whose owner isn't one keeps the owner on the list
  (the coordinator's decision in the #1804 review). Hand-overs and Send up to the owner still go.
  Who is guarded that can't be read is a 503, never an unfiltered list.
- **Known limit, direct writes:** the office writes those tasks straight to the database
  (`tasks`, through the browser's own session and RLS), and the database doesn't refuse one for a
  pastor or an elder. A trigger would have to repeat who shepherds in SQL (each role's switch, the
  legacy and job fallbacks, the Ministers setting, the seniors and the owner's identity), which
  isn't simple enough to be safe, so the rule holds where the list is offered and in every server
  route.
- **Known limit, the board:** `church_board.make_tasks` still hands a pastor or an elder the
  follow-ups the board decided. That's the board's decision, recorded by the office, not the
  office giving work, so it stays as it is.

`Church.shepherds`, `Church.guarded` (shepherds | seniors); `_under` leaves `guarded` out of the
office part and the everyone part, then walks the map from the login's person for an Admin or a
lanes overseer whose church has someone guarded. Every route that asks `is_over` (hand one out,
start, the one-on-one, send up, take back, the board) follows it.

### From the office (`church_handovers.py`)

Something an office login sends one of the church's leaders for their area: `title` (140),
`note` (1000), `link` (https only, 500), `for_date`, `department_id`. **Never a task:** never late,
never escalated, never judged, never on a list of work. The leader taps Got it (`seen_at`); the
sender sees Seen or Not yet seen.

| Sender | May send to | Why, as the list says it |
|---|---|---|
| The owner, an Admin | any leader: holders of an active role, leaders of active groups, each active department's leader and overseer, and the owner's own person (never yourself) | "Oversees Youth", else what they do ("Elders", "Lead Pastor") |
| A Manager | the leader or overseer of an active department whose `support_duty` it holds (`Church.held`: its lanes, its moves, else its areas), or whose `area` is one of its areas (Who sees what; off, every area). The map closed: nobody | "Leads Youth · you help it as Youth and Teen Bible Study", "Leads Worship · it's in your Worship & media area" |
| A Member seat | nobody (403) | |

With `department_id`, a Manager may only name one it may send for; an Admin or the owner any
active department of the church's.

Routes (prefix /church, the assignment routes' gate: a church, the switch, then the role):

    POST /church/handovers                    {business_id, contact_id, title, note?, link?,
                                              for_date?, department_id?} -> {saved}
    GET  /church/handovers?business_id=       {sent: [...], counts: {sent, seen, not_seen}}: the
                                              last 90 days, newest first
    GET  /church/handovers/leaders?business_id=
                                              {leaders: [{contact_id, name, why, departments:
                                              [{id, name}]}]}
    POST /church/handovers/{id}/seen          {business_id} -> {saved: {id, seen, seen_at}}: Got
                                              it from My week (the login's own person); once,
                                              again answers with it as it is; anyone else's 404

A sent item: `{id, to: {contact_id, name}, title, note, link, for_date, for_date_text, department,
sent_at, from, seen, seen_at, seen_text}`.

Where it's read (and only by the one it's for: See as, another login's week, never reads or shows
it, and `church_team_week.within` drops it, #1804 review): My week's `from_office` (a login whose
own person it's for, the owner's included:
`[{id, title, note, link, for_date, for_date_text, department, from, sent_at, seen}]`, what they
haven't seen and then two weeks of what they have; `counts.from_office` is what they haven't
seen; `null` when it couldn't be read, and the week stands), and the member app's Lead tab (PR C2).

Told: the hourly sweep (`church_handovers.sweep_tick`, on the worker) sends each person one email
for what arrived since the last sweep, from the church, naming who sent each ("Jessica McCloud and
Minnie Tatum sent you 2 things"). Every hand-over is in it in full, grouped or not: its title, who
sent it (when several did), its department and day, its note and its link (#1804 review). Only an
https:// address becomes a link (`email_layout.render_html(https_only=True)`); an http:// one in a
note stays plain text. A reply goes to the one login that sent everything in it, when its address
is known, else to the church office, and the email says which. A person with an office login (the
owner's too) is told it's on My week; anyone else isn't pointed anywhere until the member app's
part ships (PR C2). Claimed before the send (`told_at`), let go when it fails; no email on file,
told anyway; one older than a week never told is left untold. A link's scheme is saved lower case
(`HTTPS://` would fail the table's case-sensitive check for good).

The table: `supabase/APPLY-2026-11-12-church-handovers.sql` (`church_handovers`, server-only;
the person and the department are its own church's by trigger; PGlite check
`__tests__/church_handovers_db.mjs`). Excluded from the export: the sender is a sign-in id, and
a restore must not claim anything was seen or told.

## Days

`GET /church/duty-days?business_id=&user_id=` (default me): each duty the login holds with its
catalog day, its picked day and whether it can move. `PUT /church/duty-days` `{business_id,
user_id?, duty, day | null}`: the login itself, or anyone over it; null puts it back. A duty
whose catalog day names Sat or Sun (the Sunday jobs: attendance, kids, the stream, the deposit)
doesn't move. "weekly", "as needed" and "monthly" duties can take a day ("when I work on it").
Read by `church_my_week.rhythm`, `church_team_week.due_this_week` and the roll-up, and by the
weekly done checks.

Corrected in PR A:
- the first-Monday report (`monthly_report`) doesn't move either: its date is the monthly
  report's own (`church_monthly_report.first_monday`), and saying "the first Tuesday" on My week
  while the report still came due on Monday would mislead;
- a monthly duty with a picked day stays monthly ("Once a month, on a Thursday" on My week) and
  stays out of the team page's week; a weekly or as-needed one with a day falls on it every week;
  a weekday one moves to it (`church_assignments.day_with`);
- days are read only where the switch is open for the church; a read that fails is the
  catalog's days (said in the log), never a 503 for My week or the team page. The team page and
  the roll-up read every login's days in one read.
- My week's rhythm items carry `movable` (switch open) and, when picked, `picked` and `usual`
  (the catalog's words).

## Routes (`church_assignments.py`, prefix /church)

Every route: `require_user`/the session pattern of church_team_week, the business's church check,
the switch (404 closed), and `church_over` for anything about someone else. Every write answers
with what it saved; a failed write is a 503, never a 200.

| route | who | what |
|---|---|---|
| `GET /church/assignments/people?business_id=` | anyone over someone | the board: each person under me, with open, late, stuck, done in the last 7 days, and their first assignment as n of m |
| `GET /church/assignments?business_id=&for=login:<id>\|person:<id>` | them, or anyone over them | their assignments (open, stuck, recently done) with each check's text |
| `POST /church/assignments` | anyone over them (or yourself) | `{business_id, for, title, due_date?, done_when?, duty?}` hand one out |
| `PATCH /church/assignments/{task_id}` | them, or anyone over them | `{business_id, done?: bool, stuck?: note \| null, due_date?, title?, done_when?}`; only the one over them changes the date, title and done_when |
| `DELETE /church/assignments/{task_id}?business_id=` | whoever handed it, or anyone over them; once sent up, whoever sent it up, whoever it went to, or anyone over them | take it back |
| `POST /church/assignments/{task_id}/raise` | anyone over them | `{business_id, note?}` send a stuck item up to `above(me)` |
| `POST /church/assignments/start` | anyone over them | `{business_id, for}` make their first assignment |
| `GET /church/assignments/one-on-one?business_id=&for=` | anyone over them | finished in the last 7 days, stuck, the next five due, late, and this week's jobs done or not; plain lines, nothing recorded (built in PR B; below) |

The task is only the church's own: every task id is read with its `business_id` and its person
before any change.

As built in PR A: every route takes a Member seat or above (`business_access`), the body routes
through `business_access.assert_access`; then the church check (404), the switch
(`church_over.office_open`: the church, or the platform owner's own login; 404 closed), and
`church_over.is_over` (403 "They aren't someone you're over here."). `GET /church/assignments`
without `for` is your own. PATCH: the date, title and done_when by whoever is over them or whoever
handed it; done by them or anyone over them; stuck by them too, until it's been sent up (below).
DELETE removes the task (logged). Raise marks it stuck if it wasn't, and answers 409 at the top
(nobody over you). Start is for someone you're over, never yourself. `notes` (a task's
description) can come with a hand-out. A money duty is refused for anyone but the owner or an Admin
login.

**Once it's been sent up** (a decision Claude made in the #1801 review on 2026-11-12, from Kevin's
wish that the person over them be in control; Kevin hasn't ruled on this rule itself), the
assignee can no longer clear its stuck mark, rewrite its note or clear its sent-up record (403).
Only whoever sent it up, whoever it went to, or anyone over the assignee can; clearing it clears the
sent-up record too. Marking it **done** still works for the assignee, and closes it: done is the
truth. The sent-up record stays on a done item, so whoever it went to sees it **resolved**, not
gone: `raised_to_you` keeps it for two weeks with `"resolved": true` (and `sent_up_at`), and their
My week shows a `raised_done` line ("“…” was sent up to you, and it's done now.") for a week. Reopened
(done: false), it is stuck and sent up again as it was.

Nor can the assignee **take it back** once it's been sent up (round 2: 403, even one she handed to
herself), so it never vanishes from the list of whoever it went to: only whoever sent it up, whoever
it went to, or anyone over the assignee. Both rules hold in the database too, not only against the
row as it was read: the assignee's own stuck change and a take-back allowed because you handed it
carry `raised_at=is.null` in their filter, and a send-up that landed in between wins (409).

**A write answers with what it saved, and nothing after it can fail** (round 2): everything that
answer needs and that could fail to read (the seats, who each login is, the owner's sign-in email,
the top and the seniors) is read before the write; a read that fails then is a 503 with nothing
saved, so a retry never makes a second copy. A name read after the write that still fails is
answered without the name (logged), never a 503 for a write that saved.

### What the frontend builds against

`GET /church/assignments/people?business_id=`

```json
{
  "church": "Love City Church",
  "today": "2026-11-12",
  "me": {"for": "login:<uuid>", "name": "Jessica McCloud"},
  "people": [
    {"for": "login:<uuid>", "kind": "login", "id": "<uuid>", "name": "Naiya Clark",
     "why": "Office · Office & Leadership",
     "open": 5, "late": 0, "stuck": 1, "done_7d": 1,
     "first": {"done": 1, "of": 6, "to_make": 0},
     "stuck_items": [{"id": "<uuid>", "title": "Every room in the system", "note": "Floor plan",
                      "since": "2026-11-12T15:00:00+00:00", "raised": false}],
     "next": [{"id": "<uuid>", "title": "The staff huddle and the leaders meeting set up",
               "due": "2026-11-19", "due_text": "Due Thursday, Nov 19", "late": false}]},
    {"for": "person:<uuid>", "kind": "person", "id": "<uuid>", "name": "Marcus Taylor",
     "why": "Answers to you", "open": 0, "late": 0, "stuck": 0, "done_7d": 0,
     "first": {"done": 0, "of": 0, "to_make": 0}, "stuck_items": [], "next": []}
  ],
  "counts": {"people": 5, "late": 1, "stuck": 1}
}
```

`open` counts every one not done, stuck ones too; `stuck_items` up to 5, `next` up to 3 (late
first, then by date, never a stuck one). `first.to_make` is how many items a start would make now
(0 once started; the button shows while it's above 0). Nobody under me: `"people": []`.

`GET /church/assignments?business_id=&for=login:<id>|person:<id>` (no `for`: mine)

```json
{
  "for": "login:<uuid>", "kind": "login", "id": "<uuid>", "name": "Naiya Clark",
  "mine": false, "can_change": true, "today": "2026-11-12",
  "first": {"done": 1, "of": 6, "to_make": 0},
  "open":  [ITEM, ...],
  "stuck": [ITEM, ...],
  "done":  [ITEM, ...],
  "raised_to_you": [ITEM + {"whose": "Naiya Clark", "sent_up_at": "…", "resolved": false}, ...]
}
```

`ITEM`:

```json
{"id": "<uuid>", "title": "Every room in the system", "notes": "",
 "status": "open | stuck | done", "due": "2026-11-19", "due_text": "Due Thursday, Nov 19",
 "late": false, "duty": "rooms", "duty_label": "Rooms",
 "done_when": "Each room the church uses is listed with its size.",
 "startup": true, "week": 1,
 "check": {"done": null, "text": "7 rooms listed"},
 "stuck": {"note": "Floor plan", "since": "2026-11-12T15:00:00+00:00"},
 "raised": {"at": "2026-11-12T15:00:00+00:00", "to": "Pastor Kevin"},
 "from": "Jessica McCloud", "completed_at": null, "checked": false}
```

`open` is late first then by date; `done` is the last 14 days, newest first (start-up items
count toward `first` whenever they were done); `check` is null without one (or once done);
`stuck` and `raised` are null unless stuck; `raised_to_you` only on your own list. The writes
answer `{"saved": ITEM}` (raise adds `"to": {kind, id, name}`), start answers `{"for", "name",
"of", "skipped", "made": [ITEM, ...]}`, DELETE answers `{"taken_back": {"id", "title", "for"}}`.

`GET /church/duty-days?business_id=&user_id=` (no `user_id`: mine)

```json
{"user_id": "<uuid>", "name": "Naiya Clark", "can_change": true, "over": false,
 "duties": [
   {"duty": "weekly_text", "label": "The weekly text and email", "catalog_day": "Wed",
    "usual": "Wednesdays", "picked": "Thu", "when": "Thursdays", "movable": true},
   {"duty": "records", "label": "Records, files and policies", "catalog_day": "monthly",
    "usual": "Once a month", "picked": null, "when": "Once a month", "movable": true}
 ]}
```

Every duty the login holds, in the catalog's order (the owner and an Admin: all 47). `over` is
true when you're reading someone you're over. `PUT /church/duty-days` answers `{"saved":
{"user_id", "duty", "label", "catalog_day", "picked", "when", "movable": true}}`; a duty that
doesn't move, or isn't theirs, is a 400.

## Telling people

- Handing out: the existing sweeps already tell a login (church_office_tasks) or a person
  (church_leader_tasks) once per task. A first assignment makes 5-9 tasks at once, so a sweep
  groups one person's new hand-offs from the same hour into **one** email and one push ("Jessica
  gave you 7 things for your first four weeks"), naming who handed them out.
- Raised: the sweep tells `raised_to` / `raised_to_contact_id` once (email + push), from the
  church, with the item, its stuck note and who sent it up. It shows on their My week (office) or
  Lead tab (member app) until the item is done or un-stuck.
- Late: unchanged (it already goes to `handed_by` and the overseer).

As built in PR A: the grouping happens only where the switch is open for the church (closed, one
email a task, exactly as before), and only when one sweep finds two or more new hand-offs for one
person (one alone is the email it always was). "for your first N weeks" when every one is a
start-up item (the start-up keys are read for those tasks only, where the switch is open), else
"N tasks". An email that fails lets every claim it carried go. A person (a leader) gets the email
only: no member push kind fits a task, as before, and the same holds for something sent up to a
person. The raised tell runs in `church_assignments.sweep_tick` (hourly, on the worker), which
also ticks off open items whose check now passes. My week shows what was sent up to a login as a
`raised` line (a `raised_done` one for a week once it's done); the Lead tab's is PR C.

The raised tell never loses an item to a failed read (#1801 review): a sign-in email that couldn't
be read (the owner's from Auth, a seat's) or people who couldn't be read is not "no email on file";
that item isn't claimed, and the next sweep tries again. Only a login that really has no email (or
has left) is claimed and told with nothing sent.

The sweep never starves (#1801 review): it reads only the churches the switch is open for (`on`:
all; `owner`: the platform owner's own churches, each one `church_open` also says yes to), only the
items a check can tick (`check_key` in `PASSABLE`: never an evidence-only one), and every row of
them page by page in id order (`sb_clients.sb_get_all_as_service`), so items a church never meets
can't crowd out the rest. A read that fails part-way acts on none of it, and the next hour tries
again.

Before the migration (#1801 review, checked by a test): with `owner`, the default, Love City's
hand-offs group as soon as this deploys. The grouping reads no new column but `startup_key`, for
those tasks only; that read fails before the migration and the email simply says "N tasks". The
sweep's own reads fail first and it does nothing.

## Where it shows

- Office app (solutionist-studio): My week opens with "Your assignments" (the first assignment
  as n of m, then handed ones), done/stuck on each; "How your week goes" gets a day picker per
  movable job; the team page becomes the board for anyone over people: one column per person,
  progress, stuck, "Send up", "Give an assignment", "Start their first assignment", the one-on-one.
- Member app (`member_portal_lead`): a leader's Lead tab shows their assignments with done/stuck;
  a leader who is over others gets "Your people": the same board on a phone. A mock goes to Kevin
  before this part is built.
- Chief (later PR): `give_assignment`, `start_first_assignment`, `mark_stuck`,
  `send_up_assignment`, `set_my_day`, `people_under` (a read); each placed in `chief_areas`
  VERBS/OWNERS; every handler returns `{result, label}`.

## PRs

- **A (backend):** the migration; church_over; church_startup; the routes above except the
  one-on-one; duty days read by rhythm, team and roll-up; the grouped hand-off tell and the raised
  tell; checks that tick items off (the list above). Tests at all four fixture churches.
- **B (backend):** weekly done for six jobs; the team page and roll-up say done / not yet / late;
  the one-on-one.
- **C1 (backend):** pastors and elders under the owner and the map only; From the office (the
  hand-overs, their table, routes and email).
- **C2 (backend, member app):** the Lead tab's assignments, sent up to you, From the office and
  "Your people", per the phone mock Kevin approved (2026-11-12: "phone view idea is good. we can
  move forward with that.").
- **D (backend):** the Chief verbs.
- **F1 / F2 (frontend):** My week + day picker; the board.
