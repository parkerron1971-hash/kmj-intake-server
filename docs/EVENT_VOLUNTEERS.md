# An event's volunteers and its flyer: one structure

Kevin, 2026-11-20:

> "when a event is made there should be questions asked normal service
> volunteers or special volunteers. this is needed so people can request for
> an amount of volunteers for their event. and also a way to inser flyer for
> like a thumbnail to this event. also since we have volunteer section we
> need a way to connect the volunteers to events as well. all of this should
> be able to flow so check out the connection and create the best structure"

The proposal (https://claude.ai/artifact/98Z9QFcaZ6ZNQhLdarKHQB, v1) was
approved with **"go"** the same day, with all five calls as recommended.
This file is the standing spec. Each PR of the build follows it and adds its
own decisions to section 11.

## 1. The structure in one paragraph

The event (a Services & Events entry, `module_entries` in an `event_roster`
module) stays the one home. Making one asks three things: about it, the
flyer, and the volunteers. **Regular volunteers** come from the Volunteers'
serving teams through Who serves when (`sunday_planning`), with the event's
own number for each place. They are asked for in a **request** that whoever
schedules the teams says yes to with one tap. **Special volunteers** are
roles on the event itself (`_roles`), filled by sign-ups or by the office
naming people, as today. The **flyer** is the event's picture wherever the
event shows. The event reads back one volunteer count across both kinds.

Before this, three things were missing:
- An event date on Who serves when asked every Volunteers place at its
  Sunday number (`serve_positions.needed`).
- The event's roles and the teams' places never met. The only link was
  `worship_services.event_entry_id`.
- No event had a picture. The Light Table made flyers *for* an event but
  never attached one to it.

## 2. Kevin's five calls (decided 2026-11-20)

1. **A request waits for one tap** from whoever schedules the Volunteers'
   teams (the `serve_schedule` duty, the owner, an Admin). If the organizer
   is one of them, it goes straight on, and the duty's holders are told.
2. **Serving teams start unticked.** Ticking a place starts it at its Sunday
   number, which the organizer then adjusts.
3. **Special roles take sign-ups in the member app.** The public events page
   shows a role only on a public event whose organizer opened that role to
   everyone. A role marked "works with kids" is offered only to people with a
   current background check, and never on the public page.
4. **Special helpers earn serving hours.** Each yes on a past event counts
   the event's helper minutes (`_serve_minutes`, 120 by default; the office
   can change it on the event).
5. **Office logins make events for now.** Department leaders planning events
   from the phone is a later step (section 10).

## 3. The data

### 3.1 `worship_services.needs` (jsonb, null)

Only an event date (`kind = 'event'`) has numbers, as
`{"<serve_positions.id>": n}`. Each `n` is a whole number from 1 to 50, and
there are at most 60 places. A place not named isn't needed that night. A
`null` means every Volunteers place at its Sunday number, which is how every
event date made before this keeps working. The database checks the shape
(`event_needs_ok`). The server checks that every key is an **active place on
one of this church's Volunteers teams** (`serve_teams.owner = VOLUNTEERS`).
ChurchSavvy's worship and production places never appear in `needs`.

### 3.2 `event_volunteer_requests`

One organizer's ask for the serving teams. See
`supabase/APPLY-2026-11-21-event-volunteers.sql` for every column and check.
The table is server-only (RLS on, no policies, browser roles revoked).

| status      | means                                                       | moves to |
|-------------|-------------------------------------------------------------|----------|
| `waiting`   | asked, nobody answered yet                                  | on, declined, withdrawn, cancelled |
| `on`        | yes: `service_id` is the event date it made                 | cancelled (the event went away) |
| `declined`  | no, with `decided_note` back to the organizer               | (final; the event may ask again) |
| `withdrawn` | the organizer, or a scheduler, took it back while waiting   | (final; the event may ask again) |
| `cancelled` | the event was deleted, archived, or moved into the past while live | (final) |

- At most one live (`waiting` or `on`) request per event. A second ask is a
  409 (23505 on `event_volunteer_requests_one_live`).
- `title`, `starts_at` and `place` are copies taken at ask time. The sync
  (6.7) refreshes them while the request is waiting, so the card reads right
  even after the event is gone.
- `told_at` / `answer_told_at` are the notice ledger. A send that failed
  is retried by the sweep, and nobody is told twice.

### 3.3 On the event (`module_entries.data`): no migration

| key | shape | written by | read by |
|---|---|---|---|
| `_roles[]` | `{id, label, needed}` as today, plus optional `kids: bool`, `open: bool` | the office (RolesEditor), Chief (`chief_roster.shape`) | events_rsvp_router, member app, office |
| `_flyer` | `{artwork_id, url, thumb, w, h, at}` | **the server only** (6.12) | every surface that shows the event |
| `_serve_minutes` | int 15-720 | the office (event page) | church_serving hours |

- `kids` means the role works with kids, so it needs a current background
  check. A missing key means false.
- `open` means the role may show on the public events page. A role with no
  `open` key keeps today's behavior: it shows on a public event, unless it is
  `kids`. Roles made through the new form always write `open` explicitly,
  false by default.
- `_flyer` sits in client-writable JSON, so **every reader validates it**
  (6.12). An entry whose `_flyer` fails validation shows no picture. That is
  never an error.

## 4. The switch

`EVENT_VOLUNTEERS = off | owner | on`, default **owner** (the platform
owner's own church, through `member_asks.platform_church`, as in
`serve_dates.open_for`). It switches on for every church on a Thursday.

- **The switch gates:**
  - the request routes;
  - the New event questions (the status route says `enabled`);
  - the flyer upload and attach;
  - Sunday-afternoon event dates;
  - typed dates becoming events;
  - the sync sweep;
  - hours for special helpers.
- **The switch never hides:** readers of `needs` always apply it, since only
  open churches can write it; flyers already attached; requests already on.
  People were asked and need to know.
- **`ready()`**: a column/table probe like `serve_dates.ready()` (kept ten
  minutes when present, one minute after a 42703/42P01). Before the
  migration, nothing selects `needs`, and the routes answer 404. Tests pin it
  in conftest, off by default, so every other suite reads as before.
  `serve_dates.fields()` adds `,needs` only when this probe says yes.

## 5. Who may do what

| who | ask (organizer) | answer, change numbers | see the event's volunteers | flyer |
|---|---|---|---|---|
| Owner, Admin | yes, and it goes **straight on** | yes | yes | yes |
| Manager holding `serve_schedule` | yes, straight on | yes | yes | yes |
| Any other Manager | yes, **waits** | no | yes | yes |
| Member login that works the office (`church_spaces._office` rule) | yes, waits | no | yes | yes |
| Viewer | no (403, the part's refusal) | no | read only | no |
| Member app (any person) | no | no | the event, its flyer, special roles' open counts | no |
| Department leader (member app) | no | no; they fill their teams' places on the event date as on a Sunday (`sunday_leading`, #2011) | their department's places | no |

"Schedules the teams" is exactly the rule that changes the Volunteers' teams
today: `sunday_planning._scheduler(biz, user)` then
`_team_gate(biz, who, VOLUNTEERS)`. Reuse it; don't write a second one.

## 6. Rules

### 6.1 Asking

`POST /church/event-volunteers/{entry_id}/request`
`{business_id, needs: {place_id: n}, note?}`

- The entry is one of this church's active event_roster entries, upcoming:
  its day and time parse on the church's clock (the date field; a bare date
  with no time is refused: "Give the event a start time first"), it isn't
  past, and it's within `EVENT_AHEAD_DAYS` (180).
- `needs`: 1-60 places. Each must be an active place of a Volunteers team of
  this church, with n 1-50. An unknown or ChurchSavvy place is a 400 that
  names the place ("Production isn't one of the Volunteers' places"). An
  empty `needs` is a 400 ("Tick at least one place, or untick Our regular
  serving teams").
- `note` is at most 300 characters, plain text, stripped.
- **Waiting** (the asker can't schedule the teams): the row is written
  waiting, and the duty's holders are told (7.1).
- **Straight on** (the asker can schedule the teams): the event date is made
  first (6.3, with these numbers). Then the row is written `on` with
  `decided_by` = the asker and `told_at` set. The duty's holders, other than
  the asker, get a notice that it's on.
- A live request already there is a 409: "This event already asked for
  volunteers. Change the numbers on it instead."
- An event already on Who serves when (an event date with this entry and no
  request, made the November 17 way) is a 409: "This event is already on Who
  serves when. Laquesha can change its numbers there." The words name the
  duty's holder by first name when there is one, else "whoever schedules the
  teams".

`PATCH` on the same path, while waiting, changes `needs` and `note`. Only
the asker or a scheduler may. Once the request is `on`, the organizer's
change is a 409: "It's on the schedule now. Ask {name} to change the
numbers."

`DELETE` on the same path withdraws a waiting request. Only the asker or a
scheduler may. Withdrawing an `on` request is a 409: "Take it off Who
serves when instead." That route already refuses while anyone was asked.

### 6.2 What the scheduler sees

`GET /planning/requests?business_id=` (the scheduler gate) returns the
waiting requests, soonest event first, plus the ones decided in the last 7
days. Each has the title, day words (`sd.day_label`), time, place, who asked,
the note, and each place's name, team and number next to its Sunday number.
It also has the flyer thumb (validated), the special roles' summary (labels
and numbers only, no names), and `entry_id`.

`GET /planning/schedule` and `GET /church/week` add `requests_waiting: n` so
Who serves when and The week can show the band without a second read.

### 6.3 Answering

`POST /planning/requests/{id}/answer`
`{business_id, answer: "yes"|"no", needs?, note?}`

- **yes**: `needs` may change the numbers, under the same checks as 6.1. The
  event date is made by the **same code as `POST /planning/dates` with an
  entry_id**. Extract that into one helper; never copy it. It uses the
  entry's title, day, time and place, plus `needs`. Then the request becomes
  `on` with `service_id` set. Every existing rule holds:
  - never past;
  - 180 days ahead at most;
  - 30 event dates still to come at most;
  - one live event date per entry;
  - one title once a day.

  If the event moved into the past while waiting, the request is
  `cancelled`: "The Youth Lock-in has already happened." The answer is a
  race-safe claim: `PATCH ... status=eq.waiting`. Two schedulers pressing
  yes at once make one event date. The second gets 409 "Already answered by
  {name}."
- **no**: the `note` is required (1-300): "Say why, so {organizer} knows
  what to do next." The request becomes `declined`, and the organizer is told.

### 6.4 Changing the numbers on the schedule

`PUT /planning/dates/{service_id}/needs` `{business_id, needs}` (the
scheduler gate; event dates only).

- `needs: null` returns the date to the Sunday numbers. The UI doesn't offer
  this, but the API keeps it.
- Lowering a place below a slot someone was asked for (`asked` or `yes`) is a
  409 that names the place and slot: "Someone was asked for Greeters 3. Take
  that ask back first." Removing a place follows the same rule.
- When a live request points at this date, its `needs` is updated to match,
  so the organizer's view reads the truth.

### 6.5 Counting places: `serve_dates.needed(service, place)`

There is one function: for an event date with `needs`, it returns
`int(needs.get(place_id, 0))`; otherwise `place["needed"] or 1`. Every slot
loop must use it. A place with 0 on an event date doesn't show for that
date, isn't counted as open, and can't be asked, offered or filled. Asking,
offering or filling one is a 409: "Greeters isn't needed for the Youth
Lock-in."

Readers to change (from `grep needed` on main 2026-11-20):
- `sunday_planning.py`: the board, `schedule`, `candidates`, the slot check
  in ask/offer, `fill`/`unfill`.
- `sunday_serving.py` (the slot loop near :275).
- `church_week.py` (the slot reads near :416 and :521).
- `member_portal_leading.py` (:178, :197), and `sunday_leading.py` after
  #2011.
- `church_leaders_note.py` (:456).
- `church_monthly_report.py` (:499).
- `church_work_checks.py` (:445), plus My week's "4 of 6 for Thursday's
  Outreach night".
- `church_weekly_briefing.py`, if it counts places.

Each reader selects `needs` through `sd.fields()` and passes the service row
to `needed()`. Add a test per reader where an event date with
`{greeters: 2}` shows two greeter slots and no usher slots.

### 6.6 Hours

`church_serving` counts serve_assignments with a yes as today: an event
date's assignment counts its own length, as built on 11-17. **New**: special
helpers. A signup on a past event (this year) counts as one event served,
for `_serve_minutes` (default 120, clamped 15-720), when it has:
- `contact_id` set,
- `status` "yes" (or missing, which reads as yes),
- `role` equal to one of the event's role ids (not "Attending").

It shows in the person's hours as **Events** beside Sundays, groups and
hand-added. A person on a team place *and* a special role at the same event
counts once, the longer of the two. Away dates earn none, as now. This is
gated by the switch.

### 6.7 Following the event (sync)

`event_volunteers.sync(biz, entry_id)` is called:
- after the office saves an entry (`POST /church/event-volunteers/{entry_id}/changed`,
  called by the FE after any event save; cheap, idempotent);
- by a sweep every 15 minutes over open churches, as a safety net for edits
  made elsewhere (Chief, another tab). Reuse the existing church sweep loop
  that `church_schedule_tell` uses; don't start a new thread.

For each live event date linked to the entry, and each waiting request:

| the event… | the event date | asked / yes people | the request |
|---|---|---|---|
| changed day or time (still upcoming) | `starts_at` follows | each told once: "The Youth Lock-in moved to Sat, Dec 12, 6:00 PM. You're still on Greeters. If you can't make it, tap I can't." Their yes stays. | copies refreshed |
| changed title or place | follows | not told (it's the same night) | copies refreshed |
| moved into the past, or more than 180 days out | stays where it was, flagged `event_moved` on Who serves when: "The event moved to {when}; this date didn't follow. Take it off or keep it." | not told | waiting → `cancelled` if past |
| archived, or status not active | asks taken back; date archived | each told: "The Youth Lock-in on Fri, Dec 11 was cancelled. You're off Greeters." | live → `cancelled` |
| deleted (request's `entry_id` went null) | the same as archived, for the date the request made | the same | `cancelled` |

- "Asks taken back" uses the same path as Take back on Who serves when, so
  reminders stop and swaps close.
- An event date made the November 17 way, with no request, whose entry is
  deleted keeps today's behavior: it stays as a typed date. Documented, not
  fixed.
- Tell each person at most once per change: key the notice on
  (assignment, `starts_at`) or (assignment, cancelled).

### 6.8 Typed dates become events

`POST /planning/dates` without `entry_id` (switch open) also writes a
Services & Events entry into the church's **first active event_roster
module** (oldest `created_at`), and links it:
- `title`, `date` as "YYYY-MM-DDTHH:MM" on the church's clock, `location`;
- `_visibility: "private"`, `signups: []`, `_roles: []`.

If the church has no events room, the date is made typed-only as today, and
the response says `"event": null`. If the entry write fails, the date isn't
made (a 503). There is never a half state.

### 6.9 Sunday-afternoon events

With the switch open, an event date may fall on a Sunday unless it starts
within 2 hours of a Sunday service (`kind = 'service'`, not a template) on
the same day: "That's during Sunday's service. Sunday services are already
on Who serves when." `_upcoming_events` stops dropping Sunday entries under
the same rule. A Sunday event date's words always carry the event's title
("Sunday, Dec 13 · Fellowship dinner"), never "Sunday's service".

### 6.10 Special roles

These are the existing `_roles` and signups, with three rules added:

- **Kids roles** (`kids: true`):
  - In the member app, I'll help shows only when the person has a current
    background check. Read it through the rule that The week uses for "Can't
    serve with kids yet", as one shared helper in `church_serving`; don't
    write a second one.
  - Without a check, the role reads "Needs a background check. Ask the
    office." with no button. The server refuses a signup the page didn't
    offer (a 403 in those words).
  - The public page never shows a kids role.
  - The office may still put anyone on one by name. The event page then
    marks that person "No background check on file".
- **Open roles** (`open: true`): the public events page shows only these on
  a public event. A role with no `open` key keeps today's behavior (3.3).
- **The member app's I'll help** works on any non-kids role, and on kids
  roles for checked people, on any event the person can see
  (`member_portal_church.can_see`). It writes the same signup the public page
  writes, with `contact_id` set. If the role is full, the answer is a 409:
  "Chaperones just filled up."

### 6.11 The event's volunteer picture

`GET /church/event-volunteers/{entry_id}?business_id=` (any office login):

```
{ request: {id, status, needs, note, asked_by_name, decided_by_name, decided_note} | null,
  date:    {service_id, starts_at, needs} | null,
  teams:   [{place_id, name, team, needed, slots: [{slot, state: open|asked|yes, name?}]}],
  special: [{role_id, label, needed, kids, open, people: [{name, contact_id?, checked?}]}],
  counts:  {all, yes, teams_needed, teams_yes, special_needed, special_yes},
  flyer:   {url, thumb, w, h} | null,
  serve_minutes: int }
```

- Before the request is `on`, `teams` lists the asked numbers with every
  slot `open` and `pending: true`.
- Names on team slots follow Who serves when's reading rule. A login that
  can't read Who serves when gets the counts and states without names.

### 6.12 The flyer

`PUT /church/event-volunteers/{entry_id}/flyer` takes one of:
- `multipart file`: JPG, PNG or WebP, at most 10 MB, at most 8000 px a side;
- JSON `{business_id, artwork_id}`: an `image_artworks` row of this church
  with status ready, such as a Light Table flyer or a gallery image.

`DELETE` on the same path removes the flyer (only `_flyer`; the artwork
stays in the gallery).

- **Who**: any office login who could edit the event, plus the switch open.
  A Viewer is a 403.
- **Upload**: run `image_studio.normalize_image`, then write an
  `image_artworks` row (status ready, prompt "Flyer: {title}") through
  image_studio's own store, so the flyer is also in the church's gallery and
  the Light Table.
- **Delivery copies**, made from the original by the server with Pillow,
  RGB JPEG, EXIF stripped:
  - full, at most 1600 px on the long side, quality 88;
  - thumb, 480 px wide, quality 82.
- **Where**: the public `business-assets` bucket at
  `{business_id}/event-flyers/{entry_id}/{artwork_id}.jpg` and `...-thumb.jpg`.
  The same artwork always lands at the same path, so attaching it again
  replaces its copies.
- **Then**: `_flyer = {artwork_id, url, thumb, w, h, at}`, written with the
  service role by a read-modify-write of `data`. The response returns the
  whole new `data` so the FE form saves on top of it, not over it.
- **Validation on every read**: `url` and `thumb` must start with
  `{SUPABASE_URL}/storage/v1/object/public/business-assets/{business_id}/event-flyers/`,
  and `w`/`h` must be ints 1-8000. Otherwise there is no flyer. One helper
  (`event_volunteers.flyer_of(data, business_id)`) is the only reader.
- **Who sees it**: wherever the event shows, and nowhere else.
  - Public event: the public events page card, its share preview
    (`og:image` = the full copy), and the member app.
  - Church-only event: the member app and the office only.
  - Invite-only event: only the people `can_see` lets in, and the office.
  - The URL is unguessable but public once known. This is said in the
    office's help text, and is the same as every flyer the church posts.
- **Where it shows**:
  - office: the event list and card, the church calendar entry, Who serves
    when's date header and request card, The week's event card;
  - member app: Home's Coming up, the events list and event page, the serve
    ask card (My serving) for an event date;
  - the public events page.

## 7. Notices and words

All notices use the existing paths:
- office logins: the office alert (`church_threads` / Today), as the room
  request does;
- member-app people: `member_push.send`, with the email fallback rules of
  `sunday_serving_alerts`.

Quiet hours hold, never drop.

### 7.1 To whoever schedules the teams (the `serve_schedule` duty's holders; the owner when none)

- **Waiting**: "{Asker} asked for volunteers for the {Title}, {Day words},
  {time}: 2 greeters, 1 on parking, 4 in kids rooms." Then "Open Who serves
  when to answer."
- **Straight on, by someone else**: "{Asker} put the {Title} on Who serves
  when, {Day words}: …" (the same list).
- **Withdrawn**: "{Asker} took back the ask for the {Title}."

### 7.2 To the organizer

- **Yes**: "{Name} put the {Title} on the schedule. Asks go out to the
  teams." If the numbers changed: "…with 3 in kids rooms instead of 4."
- **No**: "{Name} can't staff the {Title} with the teams: “{note}”"
- **Cancelled by the sync**: nothing. They made the change.

### 7.3 To volunteers

- Asked for an event date: as built on 11-17, in the real day's words, with
  the flyer thumb on the member app card.
- Moved, cancelled: section 6.7.

Words follow `docs/` house rules: plain, the person's own words for things
("Who serves when", "Services & Events", "the serving teams"), no system
words, no em-dashes.

## 8. Routes (summary)

| method | path | gate |
|---|---|---|
| GET | `/church/event-volunteers/status?business_id=` | any office login; returns enabled, ready, can_ask, can_schedule, the Volunteers teams and places with Sunday numbers, holder first names |
| GET | `/church/event-volunteers/{entry_id}?business_id=` | any office login (6.11) |
| POST / PATCH / DELETE | `/church/event-volunteers/{entry_id}/request` | 6.1 |
| POST | `/church/event-volunteers/{entry_id}/changed` | any office login (6.7) |
| PUT / DELETE | `/church/event-volunteers/{entry_id}/flyer` | 6.12 |
| GET | `/planning/requests?business_id=` | scheduler (6.2) |
| POST | `/planning/requests/{id}/answer` | scheduler (6.3) |
| PUT | `/planning/dates/{service_id}/needs` | scheduler (6.4) |
| POST | `/church/events/{entry_id}/help` (member app, under its own session) | the person (6.10) |

All routes: `require_user` (the member app's routes use its own session
rule). Each route does an owner/business check of its own, independent of
RLS. Ids are parsed as UUIDs before they reach a URL, and every value is
quoted.

## 9. Build order

1. **S1 · this file + the migration** (`APPLY-2026-11-21-event-volunteers.sql`,
   PGlite `__tests__/event_volunteers_db.mjs`). Kevin runs it.
2. **S2 · server, the engine**:
   - `event_volunteers.py` (status, request, answer, needs, the picture,
     `ready`);
   - `serve_dates.needed()` and the readers in 6.5;
   - the shared make-an-event-date helper;
   - Sunday afternoon (6.9), typed dates (6.8), notices 7.1/7.2.
   - Tests: the gate table in 5, every 409, the double-yes race, needs in
     every reader.
3. **S3 · server, around the event**:
   - sync and the sweep (6.7);
   - the flyer (6.12) and `flyer_of`, with the flyer added to
     `events_rsvp_router.build_occasions`, the public page card + og:image,
     the member app (Home, events, the serve card);
   - special-role rules (6.10) and I'll help;
   - hours (6.6).
4. **S4 · office (frontend)**:
   - the three questions in New event (event_roster's create form),
     including the flyer step: Upload / Pick from Creative Studio (the
     gallery's `ImageGallery onSelect`) / Ask Chief (the Light Table, started
     from this event);
   - the event page's Volunteers band and flyer;
   - Event requests on Who serves when and The week;
   - flyer thumbs in the event list, the church calendar and Home;
   - RolesEditor's two ticks (works with kids, anyone can sign up);
   - the FE calls `/changed` after every event save.
5. **S5 · Chief**: `create_module_entry` / `update_module_entry` for an
   event take `teams: [{place, n}]` and `flyer: "make"|artwork id`, and file
   the request through the same code. Plus a read verb, "how full is my
   event". Show before saving, as Chief does now.
6. **Switch-on PR** (a Thursday): `EVENT_VOLUNTEERS=on`, What's New, Help
   Center answers re-exported (`church_findway.json`).

Each step is its own PR, branched fresh from main. Never stack PRs.

## 10. Left for later (not in this build)

- Department leaders planning an event from the member app, waiting for the
  events holder's yes like a room request (call 5).
- The organizer changing numbers after the request is on; today they ask
  the scheduler.
- A recurring event's volunteers (each date asks on its own).
- Texts for event asks (app and email only, as Sundays).

## 11. Decisions made while building

### S1 (this PR)

- **Numbers live on the event date** (`worship_services.needs`), not in a
  side table, so every serving reader already holding the service row has
  them with no second read. Null keeps the 11-17 dates working unchanged.
- **The request is a server-only table**, not keys in `module_entries.data`.
  The office writes that JSON from the browser, and a request's status must
  not be forgeable.
- **The special roles, `_flyer` and `_serve_minutes` stay on the event**
  (`module_entries.data`). Every reader already holds that row, and the
  public page and member app already read `_roles`. `_flyer` is
  server-written and validated on read (6.12).
- **One live request per event** is enforced by a partial unique index. The
  server inserts and maps 23505 to a 409; it never upserts on it.
- **`event_needs_ok` checks only the shape.** "Is this one of the church's
  Volunteers places" needs a read, so it's the server's check.
