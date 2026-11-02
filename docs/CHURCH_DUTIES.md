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
3. The owner, or an Admin, makes every change. Chief proposes and the owner says yes. For Love
   City, the session sets it directly, at Kevin's word.
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
- `require()` refuses with whose job it is: "“The weekly text” is Naiya's job here. The owner or an
  admin can give it to you in Logins & areas."

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
| rooms | `church_spaces._access` | Booking straight away, approving, keeping the spaces; the Rentals list without one amount (`rental_list` in `me`) | Fees, deposits and bills: the owner and Admins (`rentals` in `me` still means the page with its money); Member and Viewer logins still go by the Office area |
| events | `church_event_signups._office` | The sign-ups' status, summary and each event's sign-ups | Prices, places, cancelling and the export: the owner and Admins (one PUT carries prices with the rest) |
| leaders_note | `church_leaders_note._access` | The draft and the send | Once a week; the leaders room as the list |

A Manager no lane names keeps what its areas gave it: the duty's own area decides, as `holds()`
says. Event sign-ups were the one job whose old area (the Office) isn't its duty's (Website &
outreach), so for them a Manager no lane names also keeps the Office area's yes until the church
moves the events.

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
| sunday_plan, serve_schedule | planner |
| stream | media and booth |

plus any parts the team gave it. A Manager with none of those reads ChurchSavvy only, the way a
viewer seat does: Tiara and Naiya no longer change the Sunday plan. Shapretta (Media) and Laquesha
(Sunday & Serving) are ChurchSavvy admins, and so is Jessica (the Executive Pastor covers every
lane). Volunteers (team rows, no seat) are unchanged. A Manager of a business that isn't a church
keeps every part.

**The team list** (`GET /worship/team`) names each office login by its person
(`business_users_router.seat_person`), else the name it gave, and only a login nothing names by its
email. Each staff entry keeps `name`, `kind` and `you`, and gains `role`, `email`, `lane` (the label:
the stored lane, else the picked areas', and Executive Pastor), `lanes` (keys) and `parts`.

**Clip alerts** (`clip_finder.notify`): "clips are ready" goes to whoever started the run, then, in a
church, to every other login that does the clips duty (`church_duties.holders_of`: the owner, the
admins, and each Manager that holds it), once each. A read that fails sends it to the starter alone,
as before.

## The catalog (first cut)

| Duty | Area | Lane by default | Opens | Day |
|---|---|---|---|---|
| weekly_text | Office | Office & Leadership | Announcements: send, schedule, to a group (`sms_routing`) | Wed |
| leaders_note | Office | Office & Leadership | The Monday leaders note (`church_leaders_note`) | Mon |
| meetings | Office | Office & Leadership | New boards, seats, minutes, tasks from decisions (`church_board`) | Tue, monthly |
| rooms | Office | Office & Leadership, Sunday & Serving | Book and approve rooms; the rentals list without amounts (`church_spaces`) | Fri |
| chat_rules | Messages & safety | Office & Leadership | Member chat rules (`messaging_router`) | as needed |
| leaders_list | Office | Office & Leadership | Leaders & roles | as needed |
| care_board | People & care | People & Care | Follow-up, care inbox (shared), help requests | Mon, Tue |
| shepherding | People & care | People & Care | Shepherding, groups who missed weeks | Thu |
| kids | Kids & youth | People & Care | Kids check-in, rooms, approved adults | Sun |
| sunday_plan | Worship & media | Sunday & Serving | ChurchSavvy planning: order of service (planner part) | Tue |
| serve_schedule | Worship & media | Sunday & Serving, Media (production) | Who serves when (`sunday_planning`) | Wed |
| events | Website & outreach | Sunday & Serving, Media | Event sign-ups, a room for the event | Thu |
| attendance | Worship & media | Sunday & Serving | Record Sunday attendance | Sun |
| posts | Website & outreach | Media & Communications | The marketing desk, posts and Chief's post actions (`business_marketing`) | Thu |
| clips | Website & outreach | Media & Communications | Post clips and make covers (`clip_posting`, `clip_finder`) | Mon |
| stream | Worship & media | Media & Communications | The livestream, the booth, the media library (ChurchSavvy media and booth parts) | Sat, Sun |
| website | Website & outreach | Media & Communications | The site builder and the events page (`public_site`, `events_rsvp_router`) | as needed |
| churchsavvy_team | Worship & media | Media & Communications, Sunday & Serving | Who's on ChurchSavvy's team (ChurchSavvy admin part) | as needed |
| monthly_report | Office | Executive Pastor | Gather the monthly report from the admin lanes, no money | first Monday |
| oversee_lanes | Office | Executive Pastor | See as over the lanes, the Monday team roll-up | Mon |
| deposit (money) | Giving & money | Treasurer | Service counts, the Sunday deposit match | Sun, Mon |
| books (money) | Giving & money | Treasurer | Bank matching, reconcile, categories, statements | Mon, monthly |
| pay (money) | Giving & money | Treasurer | Bills, pay-backs and check requests to approve | Wed |
| store (money) | Giving & money | Treasurer | Store orders | as needed |

The area is where the job lives (the app's grouping). It opens nothing: a duty never widens what a
login sees.

## Love City's structure (to set directly once the migration is applied)

- **Naiya Clark**, Office & Leadership: weekly_text, leaders_note, meetings, rooms, chat_rules,
  leaders_list.
- **Tiara Adams**, People & Care: care_board, shepherding, kids.
- **Laquesha Bailey-Smith**, Sunday & Serving: sunday_plan, serve_schedule, events, attendance,
  rooms.
- **Shapretta McClain**, Media & Communications: posts, clips, stream, website, churchsavvy_team,
  serve_schedule (the production team).
- **Jessica McCloud**, Executive Pastor: every non-money duty by default (monthly_report and
  oversee_lanes are hers alone).
- **The treasurer** (an Admin login): every money duty.

All of this is the lanes' defaults, so Love City needs no rows until a duty moves. A move names
the duty's whole list in one PUT: moving weekly_text to Naiya alone takes it from Jessica too.

## Build order

1. `church_duties.py`, the tables, the routes, and Love City's rows. Tests. (Built, except Love
   City's rows, which wait on the migration.)
2. The job gates read duties: the weekly text, boards, chat rules, rooms, event sign-ups, the
   marketing desk, clips, the site and the events page, ChurchSavvy parts. A Manager no lane
   names keeps what its areas gave it (decided in review, 2026-11-01).
3. Chief: `list_duties` and `move_duty` (a proposal the owner approves), for other churches.
4. FE: Settings → Logins & areas gains Duties per login; buttons follow `my-role.duties`;
   ChurchSavvy's team list shows lanes.
5. The member app's "Request a pay-back" goes to the treasurer's queue.
6. Jessica's view: See as, the roll-up, Tasks by person, and the monthly report.
7. "Your week": each duty's day and training line make the week band and the walkthrough.

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
