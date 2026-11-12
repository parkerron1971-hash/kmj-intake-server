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
`church_leader_tasks.leaders` keeps them out of the leaders list. "Everyone" never includes the
owner's own person.

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
- `kids_checked` (`space_leaders`, church_areas' count): done at none without a date;
- `follow_up_no_one`: people in follow-up with no one (the leaders note's `_no_one`, My week's
  count). It counts everyone in follow-up, not only first-time guests; done at 0;
- `churchsavvy_joined` (`worship_team`): done when nobody invited is still waiting and at least
  one has joined; nobody on it is not done;
- `serve_teams_led` (`serve_teams`, owner volunteers, against `group_members` leaders): done when
  each has one;
- `sermons_6` (`sermons`, published): the last six Sundays, each with its sermon; done at 6 of 6;
- `weekly_text` (`church_my_week._done` weekly_text).

Where there is nothing to count yet (no groups, no departments, no kids workers, no volunteer
teams) a check says so and claims nothing (`done: None`): a person confirms.

A passed check ticks its open task off: on read (the board, a person's list) and in the hourly
sweep, `status='done'`, `completed_at`, `checked_at` set, done by no one, filtered on its church,
still open and still naming the check. A check that fails to read says "Couldn't count just now"
and changes nothing.

## Weekly jobs know when they're done (second PR)

Extend `church_my_week._done` with first_guests, serve_schedule, calendar, sermons, attendance and
shepherding, each "by" the person's picked day, else the catalog's. The team page and the Monday
roll-up then say done / not yet / late for each job due this week instead of only its day.

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
| `DELETE /church/assignments/{task_id}?business_id=` | whoever handed it, or anyone over them | take it back |
| `POST /church/assignments/{task_id}/raise` | anyone over them | `{business_id, note?}` send a stuck item up to `above(me)` |
| `POST /church/assignments/start` | anyone over them | `{business_id, for}` make their first assignment |
| `GET /church/assignments/one-on-one?business_id=&for=` | anyone over them | finished in the last 7 days, stuck, the next five due, late, and this week's jobs done or not; plain lines, nothing recorded (second PR) |

The task is only the church's own: every task id is read with its `business_id` and its person
before any change.

As built in PR A: every route takes a Member seat or above (`business_access`), the body routes
through `business_access.assert_access`; then the church check (404), the switch
(`church_over.office_open`: the church, or the platform owner's own login; 404 closed), and
`church_over.is_over` (403 "They aren't someone you're over here."). `GET /church/assignments`
without `for` is your own. PATCH: the date, title and done_when by whoever is over them or whoever
handed it; done and stuck by them too. DELETE removes the task (logged). Raise marks it stuck if it
wasn't, and answers 409 at the top (nobody over you). Start is for someone you're over, never
yourself. `notes` (a task's description) can come with a hand-out. A money duty is refused for
anyone but the owner or an Admin login.

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
  "raised_to_you": [ITEM + {"whose": "Naiya Clark"}, ...]
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
`raised` line; the Lead tab's is PR C.

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
- **C (backend, member app):** the Lead tab's assignments and "Your people", after Kevin sees the mock.
- **D (backend):** the Chief verbs.
- **F1 / F2 (frontend):** My week + day picker; the board.
