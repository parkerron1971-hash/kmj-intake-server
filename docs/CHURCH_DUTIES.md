# Church duties: what each office login does

Kevin, 2026-11-01 (Love City's office checkup): "we have to either give chief the ability to make
adjustment and help the churches make adjustments like these or come up with a better way that
allows for a general structure plan and customize roles as well." Then: "yes the duties part would be
great, but you would make the changes for love city directly but chief would do other churches."

## The idea

- **Areas say what a login sees.** These are `church_areas`: the menu, the data walls, and what
  reaches the login. Unchanged.
- **Duties say what a login does.** A duty is one job, such as sending the weekly text,
  gathering the monthly report, or approving pay-backs. A duty carries:
  - the gates it opens (the routes and buttons that do the job);
  - the Chief actions it opens;
  - its day in the week;
  - its one-line training step.
- **A lane is a bundle of duties.** A church starts from a general structure (its lanes'
  default duties), then moves duties one at a time. Moving a duty is one change. The gate, the
  menu button, My week's "due" line, the walkthrough and Chief all follow, with no code change.

## Rules nothing breaks (Chief included)

1. Money duties go only to a money login (the owner or an Admin seat). A Manager can't hold one:
   the PUT refuses it, and `holds()` says no to a Manager for a money duty even if a row names them.
2. Whoever asks for money never approves it. The money ladder (`church_money_levels`) is
   untouched.
3. The owner, or an Admin, makes every change. Chief moves a duty only on the owner's or an
   admin's word, and suggests anything it thinks of first. For Love City, the session sets it
   directly, at Kevin's word.
4. Every change is recorded (who, what, when, from and to) and can be undone.
5. Area walls stay walls. A duty never opens an area's guarded part. Giving names, kids' medical
   notes and pastors-only notes keep their keepers.
6. The owner and Admins hold every duty. A duty moves between Managers: naming who does one
   gives it to them and takes it from the lane's other Managers, who had it by default. Nothing
   ever takes a duty from the owner or an Admin.

## Where it lives

- `church_duties.py`:
  - `CATALOG`: each duty's key, label, area (one of `church_areas.AREA_ORDER`), money flag, lanes,
    day, training line (`does`) and what it opens (`opens`, plain words for the docs and the app);
  - `STARTER`: each lane's default duties, read from the catalog's lanes;
  - `holds(biz, user, duty)`, `require(biz, user, duty)` and `duties_of(biz, user_id, role)`;
  - routes: `GET /church/duties` (a Manager seat or above), `PUT /church/duties/{duty}` and
    `POST /church/duties/{duty}/undo` (the owner or an admin);
  - the change log.
- Tables (`supabase/APPLY-2026-11-01-church-duties.sql`, server-only: RLS on, no policies):
  - `church_duty_holders` (business_id, duty, user_id, given_by, given_at; one row a login a duty);
  - `church_duty_changes`, the log (from_holders, to_holders, changed_by, changed_at; an undo is a
    change too, with `undoes` naming the change it put back, which gets `undone_at`);
  - `church_duty_set()`, one move in one transaction: the holders it no longer names go, the new ones
    come, the log row is written.
  With no row for a duty, the lane defaults decide, so nothing changes until a church moves a duty.
- `/team/my-role` returns `duties` (every key for the owner and Admins), so the app can show each
  button to the login that does the job. Left out for a business that isn't a church, and whenever
  the read fails: my-role never fails for it, and a failed read waits 45 seconds before my-role
  tries again (before the migration, that's every Manager's app load). A job gate never waits: it
  asks every time, and a failed read is a 503.
- Switched by `CHURCH_DUTIES` (off | owner | on; owner until a Thursday). The switch gates the
  routes only; `holds()` answers whatever it says, since it reads only rows an owner or admin wrote.

## Who holds a duty

- The owner and every Admin login: every duty, money ones too.
- A Manager: its lane's default duties, while nobody has moved that duty. Once any row names who
  does a duty, only the rows decide it.
- A Manager's lane is the one stored on its login (`business_users.lane`, set at the invite or in
  Logins & areas), else the lane its **picked** areas are exactly (`church_areas.lane_of`). Chief's
  guess at a login's areas never makes a lane.
- **A Manager no lane names** does the non-money duties in the areas it works (its view: the
  church's pick, else Chief's guess), as each job's area check decided before duties. The whole
  church (nothing places it), or Who sees what not on, is every non-money duty. A view that can't
  be read is a 503.
- **The Executive Pastor** is a lane no login is given (`executive_pastor`): a login whose person
  holds the Executive Pastor role (by its key or the catalog's, said yes to) is in it, on top of any
  lane of its own. She covers any lane: her defaults are **every non-money duty** (the leadership
  plan Kevin approved 10-27, "Manager login with every area picked"; Kevin 11-01: "Jessica will be
  over the admin team"). A login tied to its person (`business_users.contact_id`) is only that person; one
  that isn't is found by its email, and only when the email names exactly one of the church's
  people, or the one whose first name the login gave.
- Members, Viewers, logins that left, and anyone outside a church: none.
- A read that fails is a 503, never a yes. A login's duties are kept a minute per replica; a change
  clears that replica's at once.
- `require()` refuses with whose job it is: "“The weekly text and email” is Naiya's job here. The
  owner or an admin can give it to you in Logins & areas."

## The office's gates (step 2a, 2026-11-01)

In a church (`church_follow_up.is_church`) each job below opens to the owner, an Admin, or a login
that `holds()` its duty; a Manager without it gets `require()`'s 403, naming whose job it is. A
failed duties read is a 503. Any other business keeps its gate exactly, and every other check the
route made stays (the switch, the card, the seat on that church, the keepers).

| Duty | Where | What it opens in a church | What stays as it was |
|---|---|---|---|
| weekly_text | `sms_routing._may_announce` | `/sms/broadcast` (now or later), `/sms/broadcast/reach`, `/sms/groups`, `/sms/scheduled` (list, cancel); the scheduled send checks the duty again at send time | The keyword (`/sms/keyword`) stays an admin's: it is the church's inbound identity, not the weekly text |
| meetings | `church_board._access` | Counts as a boss: sets boards up (new, rename, archive, seats, the people list) and sees and writes every board, as the owner and Admins do (meetings, attendance, minutes, sending them, recording their approval, tasks) | Board members keep their own boards; a viewer reads; the member app's Board tab and its money yes are untouched |
| chat_rules | `messaging_router._chat_rules_keeper` | `PATCH /messaging/settings` (on or off, how long chats are kept), still needing its two safety officers to turn on | Naming safety officers and the Safety room: the owner and the named officers |
| rooms | `church_spaces._access` | Booking straight away, approving, keeping the spaces; the Rentals list without one amount (`rental_list` in `me`). The Office's alone since the split (2026-11-02): every room is booked from one place | Fees, deposits and bills: the owner and Admins (`rentals` in `me` still means the page with its money); Member and Viewer logins still go by the Office area |
| events | `church_event_signups._office` | The sign-ups' status, summary and each event's sign-ups | Prices, places, cancelling and the export: the owner and Admins (one PUT carries prices with the rest) |
| leaders_note | `church_leaders_note._access` | The draft and the send | Once a week; the leaders room as the list |

A Manager no lane names keeps what its areas gave it: the duty's own area decides, as `holds()`
says. Event sign-ups were the one job whose old area (the Office) isn't its duty's (Website &
outreach), so for them a Manager no lane names also keeps the Office area's yes until the church
moves the events.

### Background checks (2026-11-02)

Kevin, 2026-11-02: "laquesha is the right choice" for background checks. `church_serving._access`
and `_may_write` (Sunday › Serving, which is only for churches):

- **Recording a check** (`POST /church/serving/checks`), the reminders (`/checks/remind`), and the
  check link and years in `PUT /church/serving/settings`: the owner, an Admin, or a Manager that
  `holds()` `background_checks` (the Sunday & Serving lane's by default, so Laquesha; the Executive
  Pastor's; a Manager no lane names whose areas include Kids & youth or the whole church). A Manager
  that doesn't hold it, Kids & youth or People & care in its areas or not, gets `refusal()`'s words:
  "“Background checks” is the Sunday & Serving lane's job here." A Member or Viewer keeps "Only the
  owner, an admin or a manager changes this." The page's `can.remind` is this, so the record and
  remind buttons show only to who does it.
- **Reading who's cleared** (`checks` in the page and the status): Kids & youth's and People &
  care's logins as before, **and** whoever holds the duty, so Tiara still sees who's cleared for the
  kids' rooms, and Laquesha (Worship & media alone) sees the checks she records. A holder whose areas
  leave Serving out (the duty moved to the Office's login) reaches the page by the duty.
- The hours (adding, taking off, the team and group lengths) stay any manager's, as before.
- A failed duties read is a 503 for a Manager (the status says no, quietly); the owner and Admins
  read no duties. A business that isn't a church is a 404 before any duty is read.
- Moving `background_checks` moves both: named to Tiara alone, Laquesha (and the Executive Pastor's
  default) no longer record or, by the duty, read them.

## Moving a duty

- `PUT /church/duties/{duty}` with `{business_id, user_ids}`. `[]` or `null` puts the duty back to
  its lanes' defaults. Refused (400): a money duty for anyone but the owner or an Admin login; a
  login that isn't an active seat on that church; a Member or Viewer login (they don't do office
  jobs); more than 12. The same names again change nothing and log nothing.
- `POST /church/duties/{duty}/undo` with `{business_id}` puts the newest change back, and again
  the one before it. It won't hand a duty back to someone who can't hold it now (409, name who
  does it instead). Nothing left: 404.
- A duty moved to logins that have all left (or been made Members) is nobody's but the owner's and
  the admins': the lanes don't take it back by themselves. The page marks it `needs_someone` (and
  lists those duties at the top) so the owner names someone or puts it back to the lanes.

## Step 2b: media's jobs and ChurchSavvy's parts (built 2026-11-01)

Kevin, 2026-11-01: "church savvy should be connected with shapretta mcclain right from the list
since she over media". Only churches change; every other business keeps its gate exactly. In a
church a gate opens to the owner, an Admin, or a login that `holds()` the duty
(`church_duties.does_job`). A Manager whose job it isn't gets `refusal()`'s words; a Member, a
Viewer or a stranger gets the gate's own refusal, never whose job it is. A failed duties read is a
503. Every other check a route makes stays (switches, billing, spend guards, the seat on that
church, posting only to the church's own connected accounts).

| Duty | Gate |
|---|---|
| posts | The marketing desk's writes (`business_marketing._poster_row`; the planner's run and preview use the same check) and GET /engine's `can_edit`; Chief's desk verbs (`chief_marketing_actions`) and picture posts (`image_posting`, `chief_social_actions`) |
| clips | Posting a clip (`clip_posting`, Chief's `post_clip`); covers with Find my best clips (`clip_finder.start_run`), Make cover and the cover worker (`clip_covers`), made as the owner's on the church's credits (`clip_finder.church_cover_owner`) |
| website | The site builder (`public_site._require_business_owner`, and set-site-type and expand-design-brief, which were Admin and up); the events page config (`events_rsvp_router`) |

Image Studio's reads (2026-11-02): covers and post pictures are made as the owner's images, so
the gallery and one image (`GET /ai/images/gallery/{id}`, `GET /ai/images/{id}/{image_id}`) open
to an Admin or a login that holds posts or clips (`image_studio.church_reader`). They are read as
the service role, pinned to that church, and each preview is signed in that church's folder only.
Image Studio's writes (generate, upload, publish) stay the owner's.

Kept as they were: offers (`business_marketing._owner_row`, what customers pay, the owner's);
any site_config key naming the domain (`custom_domain`, `custom_domain_status`, the Cloudflare ids)
in smart-config, refused for a website Manager and left to the owner and the admins; the composer's
own routes, including domain connect, verify and disconnect (`site_composer`, already Member and
up, untouched); the speaker photo for covers (Image Studio's owner check); the livestream and the
media library (seat checks plus ChurchSavvy parts, as before).

**ChurchSavvy parts** (`worship_team.PARTS_FROM_DUTIES`, read by `roles_of`): the owner and an
Admin seat keep every part. A church's Manager gets:

| Duty | Part |
|---|---|
| churchsavvy_team | admin (everything, who's on the team too) |
| sunday_plan, production_schedule | planner |
| serve_schedule | scheduler (who serves when, never the plan, songs, screens or setup) |
| stream | media and booth |

plus any parts the team gave it. A Manager with none of those reads ChurchSavvy only, the way a
viewer seat does: Tiara and Naiya no longer change the Sunday plan. Since the split (2026-11-02,
"churchsavvy is shapretta"), `churchsavvy_team` and `sunday_plan` are Media's alone: Shapretta is
ChurchSavvy's admin, and so is Jessica (the Executive Pastor covers every lane). Laquesha (Sunday &
Serving) is a scheduler by `serve_schedule`: she schedules, and never changes the order of service.
A scheduler is a duty's part only, never an invite. Which teams each person schedules is
`sunday_planning`'s (see "Where the lanes meet"). Volunteers (team rows, no seat) are unchanged.
A Manager of a business that isn't a church keeps every part.

**The team list** (`GET /worship/team`) names each office login by its person
(`business_users_router.seat_person`), else the name it gave, and only a login nothing names by its
email. Each staff entry keeps `name`, `kind` and `you`, and gains `role`, `email`, `lane` (the label:
the stored lane, else the picked areas', and Executive Pastor), `lanes` (keys) and `parts`.

**Clip alerts** (`clip_finder.notify`): "clips are ready" goes to whoever started the run, then, in a
church, to every other login that does the clips duty (`church_duties.holders_of`: the owner, the
admins, and each Manager that holds it), once each. A read that fails sends it to the starter alone,
as before.

## Step 6a: over the lanes (built 2026-11-02)

Kevin, 2026-11-01: "Jessica will be over the admin team". Whoever holds `oversee_lanes` (the
Executive Pastor by default, or whoever it moves to) gets three things, in `church_team_week.py`,
switched by `CHURCH_TEAM_ROLLUP` (off | owner | on; owner is the platform owner's own church):

- **See as** (`GET /church/my-week?as_user=`): another Manager login's week, never an Admin's,
  the owner's or a Member's. The page carries `seeing_as` (name, role, lane). The owner and the
  admins see as anyone, whatever the switch says.
- **The team page** (`GET /church/my-week/team`, also the owner's and the admins'): each Manager
  login with its name and lane, its open and late tasks (the church's day), the follow-ups and the
  prayer and care requests handed to it that are still open (counts, never names or what was
  asked), and what's due this week from its duties (each duty's catalog `day`). No money. One
  login's failed read is a 503 for its row; the overseer's own row is left out (that's My week).
- **The Monday roll-up**: in each church's Monday morning (its own clock, 8 to noon), one email and
  a push to My week for each Manager over the lanes (`church_duties.manager_holders`), never the owner
  or an admin. Once per church per ISO week, kept in `businesses.settings.church_team_rollup`.

A duty never widens what a login sees: the overseer's See as is cut to her own areas (her own
team's tasks always; follow-ups, care, each area's line and gaps only where she works), and the
follow-up and care counts on the team page and in the roll-up go only to an overseer who works
People & care. A roll-up that reached some holders and not others tries the rest the next hour.

A Manager no lane names holds every duty in the areas it works (the rule above), so with Who sees
what off, or nothing placing it, it is over the lanes too until a church moves `oversee_lanes`.

## The catalog

Kevin, 2026-11-02: "yes fold it in, and track supplies in tasks", "churchsavvy is shapretta", and
"yes churchsavvy for worship team, announcements to shapretta. go". The first cut's coarse duties
are split into the real jobs each admin does: 47 duties (43 that aren't money), each in one lane.
The care board became People & Care's jobs one by one. Production has no `church_duty_holders`
rows (nothing has ever moved a duty), so renaming or taking a key out changed no one's job. Each
new duty gates nothing but `background_checks` (above): the rest are the week's jobs, their day,
their training line and their page. Two keys that gate already changed lanes: `rooms` is the
Office's alone (Sunday & Serving sends a room request), and `events` is Sunday & Serving's alone.
`churchsavvy_team` and `sunday_plan` are Media's alone, so Shapretta (and Jessica) are ChurchSavvy's
admins and Laquesha isn't.

"Day" is the catalog's: a weekday (or two), "weekly" (Each week, no day said), "monthly" or
"first Monday" (Once a month), or "as needed" (Any day). The door is the page How your week goes
opens (`church_my_week.DOOR`, `area:id` in the app's church menu, each checked against
churchStructure on module-system).

**Office & Leadership** (Naiya's lane; area Office unless said): 13

| Duty | Label | Day | Door | Gates |
|---|---|---|---|---|
| front_desk | The front desk | Mon | operate:queue | |
| leaders_note | The Monday leaders note | Mon | operate:leaders-note | `church_leaders_note` |
| meetings | Meetings and minutes (the huddle, the all-leaders meeting, each board's minutes) | Tue, monthly | operate:board | `church_board` |
| decisions | Decisions to done | Tue | operate:tasks | |
| weekly_text | The weekly text and email (and the week's news list) | Wed | operate:sms | `sms_routing` |
| calendar | The church calendar | Fri | operate:calendar | |
| rooms | Rooms (every room booked from one place) | Fri | operate:spaces | `church_spaces` |
| building | The building and safety | weekly | operate:tasks | |
| records | Records, files and policies | monthly | operate:documents | |
| chat_rules | Chat rules (Messages & safety) | as needed | operate:messaging | `messaging_router` |
| leaders_list | The leaders list and department sheet | as needed | operate:leaders | |
| new_leaders | Welcoming new leaders | as needed | operate:leaders | |
| supplies | Supplies (tracked in Tasks) | as needed | operate:tasks | |

**People & Care** (Tiara's lane; area People & care unless said): 10

| Duty | Label | Day | Door |
|---|---|---|---|
| first_guests | First-time guests and welcome calls | Mon | operate:follow-up |
| care_visits | Care and visits (the care board, with the deacons) | Tue | operate:care |
| prayer | Prayer | weekly | operate:care |
| help_requests | Help requests | as needed | operate:help |
| shepherding | Shepherding | Thu | operate:shepherding |
| groups | Groups and classes (Groups & classes) | Thu | operate:groups |
| member_records | Member records and the directory | as needed | operate:directory (one of the doors) |
| kids | Kids: check-in, pickup, the rooms open (Kids & youth; the workers are Sunday & Serving's) | Sun | operate:kids |
| youth | Youth and Teen Bible Study (Kids & youth) | weekly | operate:groups |
| devotionals | Devotionals and the reading plan | weekly | build:devotionals |

**Sunday & Serving** (Laquesha's lane, the volunteers; area Worship & media unless said): 8

| Duty | Label | Day | Door | Gates |
|---|---|---|---|---|
| serve_schedule | Who serves when (the volunteer teams) | Wed | operate:serve-schedule | ChurchSavvy scheduler part; Volunteers' teams in sunday_planning |
| serve_teams | Teams and team leaders | monthly | operate:serve-teams | |
| new_volunteers | New volunteers | as needed | operate:serve-teams | |
| background_checks | Background checks (Kids & youth) | monthly | operate:serving | `church_serving` (recording) |
| serving_thanks | Serving hours and thank-yous | monthly | operate:serving | |
| events | Events and sign-ups (Website & outreach) | Thu | build:events-page | `church_event_signups` |
| outreach_nights | Outreach nights: Love Works and City Serve (Website & outreach) | Thu | operate:serve-schedule | |
| attendance | Sunday attendance | Sun | operate:attendance | |

**Media & Communications** (Shapretta's lane: ChurchSavvy and production): 10

| Duty | Label | Area | Day | Door | Gates |
|---|---|---|---|---|---|
| sunday_plan | The order of service | Worship & media | Tue | operate:sundays | ChurchSavvy planner part |
| production_schedule | Worship and production teams | Worship & media | Wed | operate:serve-schedule | (the Volunteers PR gives it the planner part) |
| churchsavvy_team | ChurchSavvy's team | Worship & media | as needed | operate:worship-setup | ChurchSavvy admin part |
| announcements | Sunday announcements | Worship & media | Fri | operate:worship-announcements | |
| stream | The livestream | Worship & media | Sat, Sun | grow:live | ChurchSavvy media and booth parts |
| sermons | Sermon up | Worship & media | Mon | grow:sermons | |
| clips | Clips and covers | Website & outreach | Mon | grow:video-clips | `clip_posting`, `clip_finder` |
| posts | Posts | Website & outreach | Thu | grow:marketing | `business_marketing` and the rest (step 2b) |
| flyers | Flyers and graphics | Website & outreach | Thu | grow:create | |
| website | The website | Website & outreach | as needed | build:my-site | `public_site`, `events_rsvp_router` |

The order of service opens Sundays (ChurchSavvy's Plan), where the order is built. Planning's
Order of service (`serve-order`) shows that same plan with each team's notes and sends a change to
ChurchSavvy, so it isn't where the job is done.

**The Executive Pastor** (Jessica): monthly_report (first Monday, operate:monthly-report) and
oversee_lanes (Mon, operate:team) are hers alone, and by default she covers every non-money duty.

**The Treasurer** (an Admin login), money: deposit (Sun, Mon), books (Mon, monthly), pay (Wed),
store (as needed).

The area is where the job lives (the app's grouping). It opens nothing: a duty never widens what a
login sees.

## Love City's structure (the lanes' defaults; nothing has moved)

- **Naiya Clark**, Office & Leadership (13): front_desk, leaders_note, meetings, decisions,
  weekly_text, calendar, rooms, building, records, chat_rules, leaders_list, new_leaders, supplies.
- **Tiara Adams**, People & Care (10): first_guests, care_visits, prayer, help_requests, shepherding,
  groups, member_records, kids, youth, devotionals. She reads who's cleared for the kids' rooms;
  recording a check is Laquesha's.
- **Laquesha Bailey-Smith**, Sunday & Serving, the volunteers (8): serve_schedule, serve_teams,
  new_volunteers, background_checks, serving_thanks, events, outreach_nights, attendance.
- **Shapretta McClain**, Media & Communications, ChurchSavvy and production (10): sunday_plan,
  production_schedule, churchsavvy_team, announcements, stream, sermons, clips, posts, flyers,
  website.
- **Jessica McCloud**, Executive Pastor: every non-money duty by default (43; monthly_report and
  oversee_lanes are hers alone).
- **The treasurer** (an Admin login): every duty; the money ones (deposit, books, pay, store) are
  the lane's.

All of this is the lanes' defaults, so Love City needs no rows until a duty moves. A move names
the duty's whole list in one PUT: moving weekly_text to Naiya alone takes it from Jessica too.

## Where the lanes meet

Every duty is in one lane. Two things are still shared, and each is split so one person answers
for each part:

1. **Sunday's schedule, split by team.** The volunteer teams (greeters, ushers, kids workers,
   parking, hospitality, outreach) are Laquesha's: `serve_schedule`. The worship and production
   teams are Shapretta's, with the worship pastor: `production_schedule`. Both open Who serves
   when, one schedule with two doors: each Sunday team is ChurchSavvy's or Volunteers'
   (`serve_teams.owner`, supabase/APPLY-2026-11-02-serve-team-owner.sql), and `sunday_planning`
   lets each login change only its own teams, while everyone reads the whole Sunday.
   `serve_schedule` gives the ChurchSavvy scheduler part, `production_schedule` the planner.
2. **The week's news list** is Naiya's, with the weekly text and email (`weekly_text`). Shapretta's
   posts and Sunday announcements draw from it; they don't keep their own list.

Everything else that crosses a lane is a hand-off, not a shared job: a leader or an event sends
Naiya a room request (`rooms`); a new leader's background check is asked of Sunday & Serving
(`new_leaders` to `background_checks`); the kids' rooms are Tiara's (`kids`) and the workers in them
Laquesha's (`serve_schedule`); a help request over the fund's limit goes to the treasurer and the
pastor.

## Build order

1. `church_duties.py`, the tables, the routes, and Love City's rows. Tests. (Built, except Love
   City's rows, which wait on the migration.)
2. The job gates read duties: the weekly text, boards, chat rules, rooms, event sign-ups, the
   marketing desk, clips, the site and the events page, ChurchSavvy parts. A Manager no lane
   names keeps what its areas gave it (decided in review, 2026-11-01).
3. Chief: `list_duties`, `move_duty` and `undo_duty`, for other churches. (Built 2026-11-02: step 3
   below.)
4. FE: Settings → Logins & areas gains Duties per login; buttons follow `my-role.duties`;
   ChurchSavvy's team list shows lanes.
5. The member app's "Request a pay-back" goes to the treasurer's queue.
6. Jessica's view: See as, the roll-up, Tasks by person, and the monthly report. (See as, the
   team page and the roll-up built 2026-11-02: step 6a.)
7. "Your week": each duty's day and training line make the week band and the walkthrough. (My
   week's `rhythm` built 2026-11-02: step 7a.)

## What changed from the plan (2026-11-01, step 1)

- Rule 6 said duties only ever add to a Manager. Moving a duty takes it from the lane's other
  Managers (that is what "a row moves a duty" means); it only ever adds for the owner and Admins.
- The catalog carries `opens` in plain words, not gates and Chief verbs: no gate reads a duty
  until step 2, and no Chief verb until step 3. They join the catalog then.
- The routes gained `POST /church/duties/{duty}/undo`; the PUT takes the duty's whole list, and
  `[]` puts it back to the lanes.
- A Member or Viewer login can't be given a duty (they hold none).
- Love City's rows aren't in this step: the tables don't exist until the migration is applied.
- Review (2026-11-01): the Executive Pastor's defaults are every non-money duty (she covers any
  lane), and a Manager no lane names does the duties in the areas it works, so wiring a gate to
  `require()` never takes away what an area check gave.

## Step 3: Chief reads and moves duties (built 2026-11-02)

Kevin, 2026-11-01: "give chief the ability to make adjustment and help the churches make
adjustments like these … you would make the changes for love city directly but chief would do
other churches". `chief_duties.py`:

- **`list_duties`** (a read, also mid-turn): each duty under its lane, with who does it ("lanes:"
  for the defaults today, "moved to" for named logins, and logins named that can't do it now), which
  need someone, and the office logins by name, role and lane. For anyone who may open the duties page
  (a Manager seat or above). No money amounts.
- **`move_duty`** `{duty, to: [names or login ids]}`, `[]` back to the lanes: the owner or an Admin
  only; a Manager is told "Moving a duty is the owner's or an admin's." `duty` is a key or a label.
  Names resolve to the church's logins exactly: a whole name, or a first name only one login has, or
  a login id; an unknown or shared name changes nothing and says which. Then `church_duties.move()`,
  the PUT's own code (the route now calls it too), so every rule above holds: money only to a money
  login, never a Member or Viewer, one log row, the same names again change nothing. The reply is
  the record: before, now, logged, and `undo_duty` puts it back. Never on nobody's word (an unattended
  call is refused).
- **`undo_duty`** `{duty}`: `church_duties.undo()`, the undo route's code. `undo_last` reaches it too
  (`action_inverse`: a move's inverse names its change, and is refused once another change came after).
- **The THIS LOGIN line**: a church login that isn't the owner or an Admin is told "Their jobs
  here: …" in the turn's tail (`chief_areas.turn_for` → `block`), so "is the weekly text my job?" gets
  the church's own answer. A church whose duties can't be read says so instead of guessing.
- Switched with the routes, `CHURCH_DUTIES` (owner: the platform owner's own login, read by the
  signed-in person's id); off, Chief says duties aren't on yet. The line isn't switched, since the
  job gates read duties whatever it says.
- Action tags only, never native write tools: `mcp_server.WRITE_TOOL_SCHEMAS` is also the outside
  agent's list, which carries no signed-in person. All three are `chief_only` in the registry.
- `chief_areas`: `list_duties` is every office login's (the handler keeps it to a Manager seat and
  above); `move_duty` and `undo_duty` are the owner's and admins' (`OWNERS`), so a lane's login is
  told it's the owner's or an admin's, never "ask whoever has the Office".

## Step 6b: the monthly report (built 2026-11-02)

Kevin, 2026-11-01: "gathering the reports from admin should be Jessica", with "nothing about money".
Whoever holds `monthly_report` (the Executive Pastor by default), the owner or an Admin works it in
`church_monthly_report.py`, switched by `CHURCH_MONTHLY_REPORT` (off | owner | on; owner is the
platform owner's own church):

- `GET /church/monthly-report?business_id=&month=YYYY-MM` (last month by default): one section a lane,
  from numbers the app already keeps. Office & Leadership: tasks from meetings done and late, rooms
  booked, new leaders. People & Care: first-time guests and how many were reached since, Prayer &
  care received and closed (People & care's counts, as in the Reports pack), people drifting from
  their groups (today's, so only this month and the one before). Sunday & Serving: attendance at each
  service, serving places filled and open, people new to a Sunday team. Media & Communications:
  sermons, clips and posts. A number the church doesn't keep, or whose read failed, is left out
  (a failed one is named in the section's `missing`). Counts only, and nothing about money.
- `PUT /church/monthly-report`: a note per lane, kept in `church_monthly_reports`
  (`supabase/APPLY-2026-11-02-church-monthly-report.sql`).
- `POST /church/monthly-report/send`: the numbers and the notes, emailed to the owner from the
  church (the leaders note's path), once a month; a resend needs `force`.
- My week: due on the first Monday, to the Manager who does it, until it's sent.

## Step 7a: How your week goes, on My week (built 2026-11-02)

Kevin, 2026-11-01: "a way for some sort of video or training or something that can be given so
they know how there week will go so they can see what they suppose to do with no problem."
`GET /church/my-week` gains `rhythm` for a church login (and for the login seen with `as_user`),
built in `church_my_week.rhythm` from the duties it holds (`church_duties.standing`):

- `every_job`: the owner or an Admin, who holds every duty (all of them are listed too).
- `today`: the church's own day (`{key: "Mon", label, date}`, on the clock My week already reads).
- `days`: Monday to Sunday, then Each week (`week`: "weekly" with no day said, 2026-11-02; its
  jobs are never `today`, since the day isn't said), then Once a month (`month`: anything
  "monthly", and "first Monday"), then Any day (`any`: "as needed"); only the days with something
  on them. A duty on two days ("Mon, Tue") is on both; "Tue, monthly" is a Tuesday once a month,
  never every Tuesday. The team page's "due this week" names days only, so a weekly job isn't on it.
- Each item: `key`, `label`, `does` (the training line), `area`, `when` (said: "Sundays and
  Mondays", "The first Monday of the month"), `days`, `door` (`church_my_week.DOOR`, one per duty;
  a test fails when a duty has none), `today`, and `done` only where a read the job already keeps
  tells: the leaders note sent this week (its own last send, on its own clock), last month's report
  sent (or sending), a text announcement that reached someone since Monday. Every other duty leaves
  `done` out.
- A `done` read that fails leaves that duty's `done` out; a duties read that fails leaves `rhythm`
  out. My week stands either way. A business that isn't a church gets none.
- See as: the seen login's rhythm. Whoever is over the lanes sees only the jobs in her own areas
  (`church_my_week.rhythm_within`, the rule `church_team_week.within` keeps for the rest of the week).

The app's band and walkthrough read this (solutionist-studio, "How your week goes").
