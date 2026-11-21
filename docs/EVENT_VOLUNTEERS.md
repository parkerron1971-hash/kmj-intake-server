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

`EVENT_VOLUNTEERS = off | owner | on`, default **on**: on for every church
since 2026-11-21. Kevin said "switch on today", ahead of the usual Thursday,
as he did for ChurchSavvy's Sunday tools (#1866). It opens only where
`CHURCH_EVENT_VOLUNTEERS` (`serve_dates.open_for`, the 11-17 event dates) is
open too, and that one's default is **on** from the same day. Neither variable
is set on Railway, so the code's default decides on the web service and on the
worker alike (#1882's pattern: a live church feature is on in the code too).
`owner` is the platform owner's own church (`member_asks.platform_church`).

- **Rollback:** `EVENT_VOLUNTEERS=off` on Railway, on **both**
  kmj-intake-server and kmj-intake-worker (the worker runs the 15-minute
  sweep that tells missed notices and follows moved events). `owner` returns
  it to the platform owner's church. `CHURCH_EVENT_VOLUNTEERS=off` closes it
  too, and hides Add an event date as well.

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
- **A person's latest move notice always names the date's time.** Each
  notice is claimed in the member notes' ledger (`member_push_sends`) under
  `event-moved-{assignment}-{time}-{n}`, where `n` counts that person's move
  notices for the date. Two replicas reach for the same key and one wins; an
  event that goes back to a time it had before is told again. Someone whose
  latest notice names another time than the date's (told, then the move was
  lost, then the office put it back) hears "The Youth Lock-in is back to Fri,
  Dec 11, 6:00 PM." A cancel is `event-cancelled-{assignment}`, once.
- **A rain date:** a date whose start passed less than 48 hours ago follows
  its event to a new time still ahead, and its people are told. One that
  started longer ago stays where it was, flagged `event_moved` (why
  `started`), so a change is never silently ignored.
- While a change waits for quiet hours to end, the serving sweep says
  nothing for that date: no ask, no reminder (a cancelled event's morning
  reminder never goes at 7 AM).

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
  - In the member app, I'll help shows only to someone with a current
    background check (ok or due in `church_serving.checks_of`) or to a teen
    of 13 to 17, as a junior helper: checks are for adults (Kevin,
    2026-11-21, "yes and yes"). One helper decides it
    (`church_serving.cleared`, through `kids_status`), and the age comes from
    the birthdate `checks_of` already reads, with no read of its own. An
    adult whose check ran out, anyone with no check on file, and a child
    under 13 are never offered a kids role.
  - The week reads the same `checks_of` for its own flag: someone on a kids
    team's place soon with no check on file ("Can't serve with kids yet")
    or, since the same day, a check that ran out ("Check overdue"). Under 18
    is never flagged there.
  - Anyone not offered it reads "Needs a background check. Ask the office."
    with no button. The server refuses a signup the page didn't offer (a 403
    in those words).
  - The public page never shows a kids role.
  - The office may still put anyone on one by name. The event page then
    says why that person may not take it: "Check overdue", "No check on
    file" or "Under 13" (only to a login that may read who's cleared). A
    junior helper reads like anyone cleared: `checked` true, no words.
- **Open roles** (`open: true`): the public events page shows only these on
  a public event. A role with no `open` key keeps today's behavior (3.3).
- **The member app's I'll help** works on any non-kids role, and on kids
  roles for checked people, on any event the person can see
  (`member_portal_church.can_see`). It writes the same signup the public page
  writes, with `contact_id` set and `via: "member"`. If the role is full,
  the answer is "Chaperones just filled up.", the role's name read from the
  church's own data on the server (the link carries only the event and the
  role's ids).

### 6.11 The event's volunteer picture

`GET /church/event-volunteers/{entry_id}?business_id=` (any office login):

```
{ request: {id, status, needs, note, asked_by_name, decided_by_name, decided_note, can_change} | null,
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
- **Validation on every read**: `url` must be exactly
  `{SUPABASE_URL}/storage/v1/object/public/business-assets/{business_id}/event-flyers/{entry_id}/{artwork_id}.jpg`
  and `thumb` the same with `-thumb.jpg` (one artwork id, a whole match),
  and `w`/`h` must be ints 1-8000. Otherwise there is no flyer. One helper
  (`event_volunteers.flyer_of(data, business_id, entry_id)`) is the only
  server reader. **The office app (S4) reading `data._flyer` itself must hold
  it to the same rule** before it shows the picture.
- **Who sees it**: wherever the event shows, and nowhere else.
  - Public event: the public events page card, its share preview
    (`og:image` = the full copy), and the member app.
  - Church-only event: the member app and the office only.
  - Invite-only event: only the people `can_see` lets in, and the office.
  - The URL is unguessable but public once known. This is said in the
    office's help text, and is the same as every flyer the church posts.
  - My serving shows an event date's flyer to the people asked or offered a
    place there, whatever the event's visibility: they already see its title
    and time, so the picture tells them nothing more.
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

**Status, 2026-11-21: every step is built and merged, and the switch is on.**
S1 #2019 (the migration applied 2026-11-21, ledger #2030), S2 #2023, S3 #2026,
the picture's `can_change` for S4b #2028, S4 solutionist-studio #1668, #1669
and #1670, S5 #2029, Kevin's two calls #2031, and the switch-on (step 6:
this repo's switch-on PR, and solutionist-studio #1674 for What's New and the
Help Center).

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
   - the FE calls `/changed` after every event save;
   - the FE round-trips each signup's `via` unchanged when it saves an event
     (the `Signup` shape is wider now: `via` is what keeps a public sign-up
     from earning hours);
   - the FE validates `data._flyer` with `flyer_of`'s whole-match rule (6.12)
     before it shows the picture.
5. **S5 · Chief**: `create_module_entry` / `update_module_entry` for an
   event take `teams: [{place, n}]` and `flyer: "make"|artwork id`, and file
   the request through the same code. Plus a read verb, "how full is my
   event". Show before saving, as Chief does now. A role Chief makes writes
   `open` (and `kids`) explicitly, since a role with no `open` keeps today's
   public behavior and shows on the public page.
6. **Switch-on PR** (done 2026-11-21, a Saturday, on Kevin's "switch on
   today"): `EVENT_VOLUNTEERS` and `CHURCH_EVENT_VOLUNTEERS` on in the code,
   What's New, Help Center answers re-exported (`church_findway.json`).

Each step is its own PR, branched fresh from main. Never stack PRs.

## 10. Left for later (not in this build)

- Department leaders planning an event from the member app, waiting for the
  events holder's yes like a room request (call 5).
- The organizer changing numbers after the request is on; today they ask
  the scheduler.
- A recurring event's volunteers (each date asks on its own).
- Texts for event asks (app and email only, as Sundays).
- Two event dates with the same title on one day, after a move or a rename
  (the one-title-a-day rule holds only when a date is made). Left as it is.

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

### S2 (the engine)

- **The switch opens only where event dates are open too.** `open_for` is
  `EVENT_VOLUNTEERS` and `serve_dates.open_for` (`CHURCH_EVENT_VOLUNTEERS`),
  since a yes makes an event date. Switching it on for every church means
  both.
- **What the switch gates:** asking, changing an ask, answering, the
  scheduler's list (`GET /planning/requests` is a 404 and `requests_waiting`
  reads 0 while it's closed), changing a date's numbers, Sunday-afternoon
  dates and typed dates becoming entries. **Not gated** (only `ready()`): the
  picture, and taking a waiting ask back (like taking an event date off).
- **The status route never 404s for a seat here.** Before the migration, or
  with the switch closed, it answers `{enabled: false, ready}`, so the New
  event form can always ask it. Every other route is a 404 then.
- **Straight on claims first.** The ask's row goes in as `on` (decided by the
  asker), which takes the event's one live ask, and only then is the date made
  and `service_id` set. If the date can't be made, the row comes back out. Two
  asks at once can never make two dates.
- **Straight on's notice is held like any other.** `told_at` is written empty
  and claimed by the notice to the other holders, so quiet hours hold it and
  the sweep retries it. With nobody else to tell, it's stamped at once.
  `answer_told_at` is stamped at the write: the asker decided it.
- **A yes claims, then makes the date, and lets go if the date can't be
  made.** The claim sets `on` with the numbers while `status=eq.waiting`. If
  `make_date` refuses (the event went on Who serves when another way, it lost
  its time), the claim goes back to waiting and the refusal is said. An event
  that went into the past, or was archived or deleted, is `cancelled` with a
  409 in plain words. A yes with no numbers uses the ask's, without any place
  retired since. A yes may carry a note (`decided_note`).
- **Who is told of an ask (7.1):** the Managers holding `serve_schedule`
  (`church_duties.manager_holders`), the owner when nobody does. The owner and
  the Admins aren't told of every ask. Nobody is told of their own.
- **How an office login is told:** `church_schedule_tell.to_login` (a push to
  the office app and an email), the leaders schedule's path. The ledger counts
  a notice told when either went. The office bell isn't rung: it can't say
  whether it went, which the ledger needs.
- **A yes's words:** at once, "with 3 on Usher instead of 4" when the numbers
  changed. Told later by the sweep (which can't know what changed), it says
  the numbers it went on with. Every list is "{n} on {place}", since a place's
  name is the church's own.
- **Taken back:** by the asker, the holders hear when they were told of the
  ask. By a scheduler, the asker hears "{Name} took back your ask for the
  {Title}". Once, straight after, never retried.
- **The sweep** (`event_volunteers.sweep_tick`) is on the worker every 15
  minutes now; S3 adds following the event to it. It reads asks and answers
  untold for under a week and leaves anything under two minutes old to the
  write's own send. It's quiet with the switch off (not one read) and before
  the migration, and never for a sample church.
- **Names:** the owner by the church's name for them (`practitioner_name`),
  everyone else by first name, never an email address, "The office" when
  there's none. A scheduler told "it's on" hears "Change its numbers on Who
  serves when"; anyone else hears whom to ask.
- **The picture:** the live ask, else the latest one, so a no and its note
  still read. A special role's people carry no `checked` yet (S3's kids rule).
  Names on team slots need Who serves when open to the login and a Planning
  part there (`worship_team.roles_of`).
- **Changing a date's numbers:** the refusal names the place and the spot
  ("Usher 2"). An open spot past the new number (offered to the team, or a
  no) goes with it. Back to the Sunday numbers (`needs: null`), the live ask
  reads every Volunteers place at its Sunday number (its own can't be null).
- **The schedule** gives each service `needed: {place_id: n}` for the places
  that serve it (0 included), and each event date its `needs`.
- **Sunday afternoons:** "within 2 hours" is less than two hours either side
  of a Sunday service's start that day. A Sunday entry with no time is never
  offered: it can't be told from the service.
- **A typed date's entry** goes into the oldest active events room
  (`created_by: who_serves_when`). The entry is written first, then the date.
  If the date can't be written, the entry is deleted.
- **The readers of the Sunday plans alone** (the leaders note, the weekly
  letter, the monthly report) select `needs` through `fields()` and count
  through `needed()`, but never see an event date (`plans_only`).
  ChurchSavvy's Today (`sunday_order`) reads only Sunday plans and isn't
  changed.
- **A Sunday event date's member words** (the ask, My serving, the pack, the
  `.ics`, the alerts' ask and nudge) carry its title and say "Starts at",
  never the service. The week-before and day-of reminders are as on 11-17.
- **My week** says nothing for an event date whose numbers come to no
  Volunteers place (it said "0 of 0").
- **A note** is plain text: its spaces kept to one, at most 300 letters.
- **Fixed on the way: Fill the month asked one person for two spots of one
  place.** `_Board.busy` leaves the place's own spots out (so a spot can be
  asked again), so with more than one spot and nobody else rested, fill could
  ask the same person for both. Event dates made it likely (many spots, no
  Sundays-a-month cap), so `do_fill` now skips anyone already on that place at
  that service. Asking by hand is as before.

#### S2, after review

- **Taking a date off closes its ask.** `DELETE /planning/dates/{id}` cancels
  the `on` ask that made it before the date comes off (if that can't be
  written, nothing comes off), so the event may ask again. Nobody is told:
  they did it.
- **An ask is never on with no date for long, and never told so.** The
  notices skip an `on` ask with no date. Every write after a date is made is
  checked: the undo of a straight on, and the release of a yes, are logged
  when they fail. A date that was made is never a 503: the link is logged and
  left to the sweep. The sweep mends an ask left `on` with no date for more
  than two minutes. It links the event's live date when there is one.
  Otherwise an ask put straight on is cancelled (its asker was told it
  failed), and an answered one waits again rather than being cancelled, so
  the organizer's ask isn't lost to a database blip. Nobody is told of a mend.
- **An unplanned Sunday keeps the usual times.** Sundays are planned a few at
  a time, but event dates go 180 days out. On a Sunday with no service planned
  yet, the two-hour rule uses the church's usual Sunday times: those of its
  Sunday services from 8 weeks before today to 8 weeks after. With none, it
  uses 10:30, the time Add the next five Sundays gives (no church setting
  holds a service time). It applies on every path: a typed date, an ask,
  straight on, a yes (refused before the claim, so the ask still waits), and
  the list of events to pick from.
- **Changing a date's numbers looks twice.** After the write it reads the
  asks again. One for a spot past the new numbers that landed meanwhile puts
  the numbers back, with the same 409.
- **An event that asked can't go on another way.** Add an event date with an
  entry that has a live ask is a 409: "This event already asked for
  volunteers. Answer its ask on Who serves when instead."
- **A yes for an event that is no longer coming up** says so by name: "The
  Youth Lock-in isn't coming up in Services & Events anymore."

### S3 (around the event)

**Following the event (6.7)**

- **The ledger is the member notes' own.** Each notice is claimed in
  `member_push_sends` (unique on business, kind and `ref_id`, shared by every
  replica and the worker) before anything goes: kind `serving`, `ref_id`
  `event-moved-{assignment}-{time}-{n}` (about 85 letters) or
  `event-cancelled-{assignment}`. The push goes through `member_push.send`
  with no `ref_id` of its own, so the one claim covers the email too. No
  migration.
- **A person's latest move notice names the date's time** (after review). A
  key on (assignment, time) alone said nothing when an event went 6, 7, 6, 7:
  the last 7 was already "told". `n` counts the person's move notices, so
  every real move is a new key and two replicas still meet on the same one.
  The ledger is read for the people on the dates being followed only, newest
  first and paged whole (a capped read once lost the newest rows and brought
  the silent move back). The latest is the highest `n`, and between two of
  the same `n` (two replicas racing two new times) the later written.
  Someone whose latest notice names
  another time than the date's hears it's back ("is back to Fri, Oct 30,
  6:00 PM"); that covers a sync that told people, lost the date's write, and
  then the office put the event back.
- **Tell first, then change.** A crash in between leaves the next sync to
  finish, and the ledger keeps anyone from hearing twice. A claim that can't
  be read stops the change for now. A claim that landed keeps it, even when no
  phone or email was reached, as the serving reminders do.
- **Quiet hours hold the whole change** while anyone would hear of it: the
  date follows with the first sweep after 7 AM. Meanwhile the serving sweep
  says nothing for that date (`event_volunteers.unsettled`, read by
  `sunday_serving_alerts.church_tick`): no ask, no reminder, for an event that
  went away or moved and hasn't been followed yet. That ends the race between
  quiet hours ending and the 7 AM morning reminder. A change that is undone
  in the night lets the reminders go as before. A date held for a change made
  more than a day ago is said in the logs, so a follow stuck on a failing read
  shows.
- **Who hears:** a yes, and an ask that already went out. An ask still
  waiting to go out says the new time when it goes. Offered spots, no's and
  someone asked to cover hear nothing.
- **The words** use the short day, "Sat, Oct 31, 7:00 PM". A yes reads "If
  you can't make it, tap Change my answer." (the ask page's own button). An
  ask not answered yet reads "You were asked for Greeter. Tap Yes or Can't
  that day."
- **The reminders follow a move**, by `sunday_serving_alerts.moments` (due()'s
  own rule, factored out): a yes's mark is cleared only for a reminder whose
  moment for the new time is still to come. One whose window already opened
  (the day-before evening, the morning of) keeps its mark and never goes
  twice.
- **"Doesn't follow"** covers a move into the past, past 180 days, into a
  Sunday service (the 2-hour rule), an event that lost its start time, and
  (after review) a date that started more than 48 hours ago (`started`).
  `event_moved` is worked out when Who serves when is read (`{to, why,
  words}`), only with the switch open; nothing is stored. A read that fails
  there (the Sunday check) leaves no flag; the page never fails over it.
- **A rain date** (after review): a date whose start passed less than 48 hours
  ago follows a new time still ahead, told as any move. 48 hours covers a
  weekend postponement decided the morning after.
- **A cancel takes back every row on the date** (offered spots and no's
  included) through `sunday_planning.do_take_back`, takes the date off, and
  closes the ask last: until then the ask points the next sync at a deleted
  event's date.
- **A date that already happened is never cancelled**, and its ask stays on.
- **A new title or place** follows on the date. A waiting ask's copies follow
  its event; an on ask's copies (title, place, starts_at) now follow its date
  too, so its card reads right and the sweep can tell a recent ask from a
  long-past one.
- **The change gate is the tell gate** (after review): `_follows` is the
  switch open for the church itself, event dates open there, never a sample
  church. `/changed` is a 404 elsewhere, so the platform owner's own login at
  a church the switch isn't open for never moves or cancels a date that
  nobody would be told about. A sample church doesn't follow at all.
- **One church, a handful of reads** (after review). The sweep finds the
  churches with something to follow in two reads (dates from an entry still
  to come or started in the last 48 hours; asks waiting, or on for a date not
  long past), each paged in a stable order so no church is missed past the
  server's 1,000-row cap. Then it reads each church once: its dates, its
  asks, their events (two reads), the rows on those dates (paged: a short
  read never reads as "nobody's on this date") and, when anyone would hear,
  their move notices. `/changed` reads the same set and acts on its own event and on the
  asks whose event was deleted. The sweep's answer gains `followed`, `moved`,
  `cancelled` and `people_told` only with the switch on.

**The flyer (6.12)**

- **Made as the church's owner** (`image_studio.build_actor`, set after the
  gate and reset after), like every server-made picture. Prompt "Flyer:
  {title}".
- **A gallery picture only for who may read the gallery** (after review): the
  owner, or a login `image_studio.church_reader` lets in (an Admin, whoever
  does the posts or the clips). Anyone else is a 403 "Pictures from the gallery
  are for the owner, an admin, and whoever does the posts or the clips. Upload
  the flyer instead." It must be ready, with its original in the church's own
  folder; another church's is a 404.
- **The limits are read from the header** (after review): the kind, 8000 px a
  side and 25 megapixels (`normalize_image`'s own cap) before a pixel is
  decoded or turned. Each refusal says what is wrong: over 10 MB, not a JPG,
  PNG or WebP, too big in pixels, or couldn't be read.
- **A phone photo is turned upright** from its EXIF before `normalize_image`.
  The thumb is never made bigger than the picture; `w` and `h` are the full
  copy's.
- **The write** is guarded by the event's `updated_at` when it has one, tried
  four times, then a 409. Taking a flyer off doesn't need the switch (after
  review): after a rollback the office can still take one down.
- **`flyer_of` pins the event** (after review): a whole match of the event's
  own folder and the artwork's two names, not a prefix.
- **The readers.** `build_occasions` adds `flyer` only when it is handed the
  church's id. The public card shows the thumb, opening the full copy.
  `/events?event=<id>` is one event's own page for its share preview. The
  member app's Share link still opens `/events` (its tests pin it). The member
  app shows it on Coming up and its cards in both looks, the new Home's This
  week card, and My serving's ask row, coming row and ask page (styled inline,
  so a page with no flyer is byte for byte what it was). Home's lead card keeps
  the church's photo. The office: `/planning/requests` (`flyer` beside
  `flyer_thumb`), the schedule's event dates, The week's event-date cards.

**Special roles (6.10)**

- **Kids roles stay on the stricter rule** (decided in review, from
  Kevin's "current background check"): ok or due in `checks_of`, never under
  18. The week keeps its own flag (blocked only) for now; both read
  `checks_of`. Teens and The week's overdue flag go to Kevin separately.
  (Both changed 2026-11-21: see "Kevin's two calls" below.)
- **The member app is form posts with redirects**, so a refusal comes back as
  the page's notice: `err=kids` "Needs a background check. Ask the office."
  and, for a full role, `err=filled&entry={id}&role={id}`: the page looks the
  role's name up in the occasions it already read for that person (after
  review), so a crafted link can't put words on the church's app. A full
  role's code is now `filled`, not `role`. The redirect's values are
  URL-encoded.
- **The office's picture says why** (after review): a kids role's people carry
  `checked` and `check` ("Check overdue", "No check on file", "Under 18"),
  only for a login `church_serving` lets read who's cleared. ("Under 18" is
  "Under 13" since 2026-11-21.)
- **The public page:** a role that says neither `kids` nor `open` reads
  exactly as before. A hidden role's public signup is the same 400 as a role
  that isn't there.

**Hours (6.6)**

- **`church_serving.event_credits`** reads only the year asked, by each
  room's own date field, and only the keys hours need (the day, signups,
  `_roles`, `_serve_minutes`, the public registrations), never every event's
  whole data (after review). A read that fails fails the hours the way every
  other hours read does (a 503, Reports' "couldn't be read"): church_serving
  never shows fewer hours than there are, and Reports never comes out short.
- **An event archived after it started keeps its hours; archived before, it
  was called off** (after review). `module_entries` keeps no `archived_at`, so
  its `updated_at` (moved by every save, the archive's included) stands in:
  an archived event edited again after its day would read as archived after.
- **Only a member's own word earns hours** (after review): the member app's
  signup (from the person's session, `via: "member"`) and people the office or
  Chief put on. A public sign-up, matched to a contact only by the email
  someone typed, never does: new ones carry `via: "public"`, and one from
  before `via` was written is known by the event's own registration key for
  that person's email. The office app (S4) keeps `via` on signups it saves.
- An event with a time counts once it has started; a bare date once its day
  is over. One credit per person per event, however many roles. A team place
  at the event's own date and a role there count once, the longer; a tie goes
  to the team place.
- **Its readers:** the Serving page (each person's `events` and
  `event_minutes`, the totals' too), My serving ("an event you helped at"),
  `minutes_of` (The week, and through it My department and Chief's schedule
  reads) and Reports' Serving numbers. With the switch closed it answers
  before reading a single event.
- **Chief:** `chief_roster.clean_roles` keeps `kids` and `open` when they are
  true or false. A role Chief makes writes `open` explicitly (S5).
- **Left as they are** (decided in review): a private or invite-only
  event's flyer on My serving for the people asked (6.12), and two same-title
  dates on one day after a move (section 10).

### S5 (Chief)

`chief_event_volunteers.py`. Chief writes no rule of its own. It calls the
office's code, as the signed-in login and never as the owner:
- the status reader (`status`): the gate, `can_ask`, the Volunteers' places
  and their Sunday numbers, and who schedules the teams;
- the ask's own checks before anything is written (`ask_blocks`, factored out
  of the POST route, plus `clean_needs` and the note);
- the gallery's rule (`gallery_reader`, `_artwork`);
- then, once the event is saved, the office's own order: the flyer
  (`attach_flyer`, the PUT route's body factored out), the ask (`ask`, the
  POST route itself), and the follow (`changed`, the route the app calls
  after every save).

`enabled()` is the status route's `enabled`, factored out so Chief asks the
same question.

**Show before saving, bound to what was shown.** This is enforced in code,
in the leaders schedule's look:
- A save that asks the teams, puts a gallery picture on, or loosens a role's
  tick saves nothing the first time. Its result says what saving will do:
  the event, its day and time, the places and numbers, who gets the request
  or that it goes straight on, the roles, any tick it loosens, and the flyer,
  including when it replaces the event's current one. The label is the
  read-back the person hears.
- The look is claimed in `member_push_sends`, the member notes' server-only
  ledger, as S3's follow already uses it. The kind is `chief_event_look`, and
  `ref_id` is the login plus a sha256 of the exact params, the read-back and
  who gets the request.
- Sent again with `"confirmed":true` after their yes, it saves only by
  consuming that claim: unused, this login, the same params, under 30
  minutes old. The consume is one write (shown to used), so two sends or two
  replicas can't both save one look. Anything else (another plan, another
  login, too old, already saved) shows the look again.
- A send repeated after its save is "already saved", with the event's name
  and day. It's never shown or armed again, so a yes to it saves nothing.
  That holds for SAVED_HOURS (24 hours) after the save, and, for a new event,
  only while an event of that name is still in the room: a plan saved and
  then taken away may be shown and saved again. A different plan always gets
  its own look.
- A second send in the turn that showed it doesn't count: they haven't heard
  it yet.
- A confirmed send on a tainted turn is held, without using up the look,
  until they say it again.
- `"make"` alone has no look, since nothing reaches anyone.

Why not a signed token the model sends back: the history the app returns
holds only the reply's cleaned prose. A token in an action's result never
reaches the next turn unless it's put on the screen. A server-side claim
needs no token, is replica-safe, and needs no migration.

**Once a turn.** A save that went ahead is kept on the turn's context, by
its event and its own digest. The very same send again in the turn gets the
first answer, marked so the door logs no second undo, and nothing is filed
twice. A different change to the same event in the turn (the teams, then a
flyer) goes ahead on its own. The same send as a tag in the reply, after the
native call already ran, is dropped (`chief_tool_loop.remaining_tag_actions`).

**What stops an ask is said before saving, and nothing is saved.** That
covers:
- an unknown or ChurchSavvy place, or one that could be two;
- a word that is both a place and a team;
- one place given two numbers;
- a number past 50, or a note past 300 letters;
- no start time, an event that's past or too far away, or a Sunday service;
- a picture the gallery's rule refuses.

Each is in the server's own words. A refusal that can only happen after the
save (another ask landing in between, a database blip) keeps the event saved
and says what didn't go, also in the server's words.

**An ask already there, or the event already on Who serves when, never blocks
the rest of a change.** The other changes (its time, its place) save, and the
teams are left out. Chief has no way to change an ask's numbers, so the words
say where they change: on the event's Volunteers and flyer page, or by
whoever schedules the teams. With nothing else to save, nothing is saved,
and the same words are said.

**Places as a person says them.** They resolve against the status reader's
places:
- any case, singular or plural, a trailing "team" dropped;
- "Team: Place" or "Place (Team)" when two teams share a name;
- a team that has one place;
- digits in the words ("2 greeters, parking").

No number means the place's Sunday number (call 2). Anything else is named
back with the church's places, never guessed. There is no partial match.

**Where asking isn't open, the event saves exactly as today** with teams and
flyer left out, and the result says why in plain words. This covers:
- the switch closed, or event dates closed;
- the migration not in;
- nobody signed in: an unattended run, or an outside agent. The native tools
  are also the agent surface's list, so it sees the keys, but its turn has no
  login;
- a Viewer (the part's refusal);
- a Member login that doesn't work the office (`NOT_OFFICE`).

**A role's ticks.** Where asking is open (`enabled`, as the office shows the
two ticks), a role Chief makes writes `kids` and `open` outright, false
unless said. That includes a role made for a person put on a role nobody
listed.
- A role named again takes a tick only when one was said. A role Chief
  doesn't touch keeps its keys exactly.
- A tick that lets more people in on a role already there is shown first,
  saved only on the person's yes, and held on a tainted turn. That's `kids`
  turned off (no background check needed any more) or `open` turned on (the
  public page).
- With nobody signed in, no tick the model sent is taken, and every role
  keeps its own.
- A new event with no roles named still writes no `_roles`, so the room's
  usual roles apply as before.
- Where asking is closed, no tick is written and none is taken. The public
  page honors `open: false` whatever the switch says, and the office has no
  tick there to undo one.

**"make" is the Light Table, and Chief never starts it from a save.** The
only server path that makes a flyer for an event is the Studio's Light Table
(`studio_light_table`, through `creative_director.handle_design_flyer`). It
is:
- the church owner's (`images.business`), behind `STUDIO_LIGHT_TABLE`;
- class C and paid: credits, the spend guard before every paid call, the 20
  a day limit, metering through `llm_call` and `api_usage_logger`, but no
  `rate_limit` on the design route;
- drawn in the background, so the picture isn't ready in the same save;
- put on the event only when the person presses Use as the flyer (S4a's
  FlyerStudio on the event's page).

Starting it inside a class-A save would skip the class-C gate, so Chief hands
over the office's way instead:
- to the owner with the Light Table open: the event's Volunteers and flyer,
  then Ask Chief to make one;
- to an owner without it: make one in the Studio and pick it from the
  gallery;
- to anyone else: upload one, or pick one on the event's page.

**The events-room setup.** With builds on, `chief_build_runtime.route_actions`
folds a reply that makes the events room and the event into one background
setup. That setup runs with nobody signed in, so the event's teams and flyer
can't go with it. A receipt says so instead of dropping them without a word.
Where asking is open it says "once it's saved, ask again"; where it isn't, it
says asking the serving teams (or putting a flyer on) isn't on here yet.

**How full is my event** is `event_volunteers`, a read that is Chief's alone
(`chief_only`, sensitive). It needs the signed-in login, so it's off the
outside agent and KAI surfaces, like `serving_week`.
- Every business's tools carry it, so its description is one short line:
  only where the turn's EVENT VOLUNTEERS line shows.
- Where asking is open, it returns the picture route's own reader, as the
  login. Names on team spots and the check words reach Chief exactly where
  the picture gives them.
- Elsewhere (closed, not ready, not a church) it answers from the event's
  own roles and sign-ups, as its room shows them, with no word of the
  serving teams. Who may read the names is decided before anything is read.
  Where the office's own picture has a gate (`_login`: an office login of a
  church whose teams have owners, with the migration in), that gate decides,
  switch or no switch; a login it refuses hears its refusal. Where it has no
  gate (before the migration, Who serves when off, not such a church), the
  rooms are read with the login's own token, as `list_module_entries` reads
  them, so the database's rules decide. Never names read as the server.
- Someone else's words raise the turn's taint on the turn's own context.
  That covers the ask's note, the answer's note, and the names on the
  event's own roles, which members and the public type. It also covers
  whatever `untrusted_text.defuse` found inside the read's thread: the
  thread's copy of the count would be lost, so the thread hands it back.
  Team spots' names (contacts, which a stranger may type on the booking
  widget) are fenced too.
- An event is found by its id or its name. Its whole name comes before a
  part of one; for an event that repeats under one name, the next one.
  Anything else is named back with the days.

**The prompt.** The per-church availability rides the turn's tail (chief
chat's login block, beside the leaders schedule's `turn_line`), never a
cached segment. The switch's owner mode opens it by login, a Viewer's line
differs, and it changes on a Thursday. The universal and per-business
segments are unchanged. The write tools' schema is static for every business
and says "only where the turn's EVENT VOLUNTEERS line shows". The tools'
cache refreshes once at deploy.

**A plain change to an event is followed at once,** as the office's save is.
An `update_module_entry` with no roles, teams or flyer calls `changed` after
the save. The entry is read with its room's archetype embedded
(`custom_modules(archetype)`), so it's still one read. The room, the gate
and the events page are read only for an events room's entry, signed in, at
a church the follow itself opens for (`_follows`: the switch open for the
church, not just for a login, event dates open there, never a sample church;
the owner mode's lookup is kept ten minutes). In owner mode every other
church, even with the platform owner's own login there, pays nothing. A new
event's follow has the same gate. Every other update reads exactly what it
read before, and answers as before.

**The registry.** `create_module_entry` and `update_module_entry` stay class
A. A waiting ask is taken back on the event's page, one that went straight on
comes off Who serves when, and a flyer comes off on the event's page. Each is
shown first, needs the person's yes, and never runs unattended or from an
outside agent. The Chief-only reads' review list (`test_tool_loop.py`)
gained `event_volunteers`.

### The switch-on (2026-11-21)

- **Both defaults are `on` in the code**, not on Railway (neither variable
  was ever set there), so the web service and the worker can't disagree.
  Rollback is `EVENT_VOLUNTEERS=off` on both (section 4).
- **What every church sees change once it deploys:**
  - Add an event date on Who serves when (the 11-17 feature), for whoever
    schedules the Volunteers' teams. Its What's New went out on 11-17 to every
    church, while the feature was still open only at the platform owner's church.
  - New event's three questions, Volunteers and flyer on each event's card,
    Event requests on Who serves when and The week's line, the two role ticks,
    Sunday-afternoon event dates, and typed dates becoming Services & Events
    entries.
  - Moved and cancelled events followed by the sweep, and their volunteers
    told.
  - Chief's teams and flyer on an event, and "how full is my event".
  - **Hours:** special helpers' event minutes count in the Serving page, My
    serving, The week (`minutes_of`) and Reports. That is every past event of
    this year with a role signed up by a member in the app or put on by the
    office or Chief, events made before today included, at `_serve_minutes`
    or 120 minutes. A church whose events have role sign-ups sees its year's
    hours go up on deploy. `event_credits` is the one reader gated by the switch
    alone, not by `ready()`.
- **Not changed by the switch-on:** the flyer reader, `needs` readers and the
  picture already answered whatever the switch said. The Studio's Light Table
  (Ask Chief to make a flyer) is its own switch, `STUDIO_LIGHT_TABLE`, owner
  when unset.
- **The office's Serving page** shows those hours in each person's total, but
  has no Events line yet: the person line lists Sundays, gatherings and hours
  added only (a frontend follow-up).
- **The Help Center's export** (`church_findway.json`, from
  solutionist-studio #1674 on 07f13b37) also brought the two giving-access
  answers (#1654) that module-system had and this copy didn't.
  `system_destinations.json` is the frontend's copy again (it gains the
  `guests` route beside #2034's alias).

### Kevin's two calls (2026-11-21)

Asked: "Should teens be allowed as junior helpers on kids roles? Right now
anyone under 18 is refused." and "Should The week flag volunteers whose
background check has expired? Today it only flags people with no check on
file." Kevin: **"yes and yes"**.

**Teens on kids roles (6.10).**
- A teen of 13 to 17 may take an event's kids role as a junior helper, with
  no check of their own: checks are for adults. A child under 13 is still
  never offered one. An adult's check must still be current (ok or due), so
  an overdue check is still refused.
- The age is worked out by `checks_of` from the birthdate it already reads
  for `teen`, and rides on its row as `age`. `church_serving.kids_status`
  turns `teen` into `junior` (13 to 17) or `child` (under 13), and
  `cleared` lets in `KIDS_ROLE_OK` (ok, due, junior). No new read per
  person. A `teen` row can't lack an age (teen needs a birthdate), and one
  that did would read as a child.
- The member app's offer and the server's re-check both go through
  `cleared`, so they can't disagree. The office's picture marks a junior
  helper `checked: true` with no words, like anyone cleared, and says
  "Under 13" for a child. The member app's refusal words are unchanged
  ("Needs a background check. Ask the office.").
- The Serving page, My serving and the check reminders still read `teen`
  as before: none of them asks a teen for a check.
- No switch of its own: it applies wherever an event has a kids role, and
  the office and Chief make those only where EVENT_VOLUNTEERS is open (it
  opens only where CHURCH_EVENT_VOLUNTEERS does).

**The week flags a check that ran out (docs/CHURCH_SCHEDULE.md 8.4).**
- Someone on a kids team's place at a service still to come in the week
  shown, whose check ran out (`overdue` in `checks_of`), is flagged as well
  as someone with no check on file (`blocked`). Under 18 is never flagged.
- Shape: the same state, `cant_serve_kids`, for both, so every reader of a
  row's state treats them alike with no change: the office page's chip and
  its tone (the frontend's `STATE_TONE`, which reads any state it doesn't
  know as `open`), the counts (still on the schedule), Look at first's order,
  My department's "The office is handling this place" and its quiet
  no-answer line, and Chief's `serving_week`. A new field on every row,
  `check_status`, says which (`blocked`, `overdue`, or null). The row's
  `state_words` is "Check overdue", and Look at first says "{department}:
  {name}'s background check is overdue." / "{first}'s background check ran
  out on Mar 1, 2022. {first} is on for Sunday." (the year only when it
  isn't this one). The frontend shows both verbatim, so it needs no change.
- Private exactly as before: only a login church_serving lets read who's
  cleared sees it; for anyone else the page is byte for byte the page with
  a current check. The member app's My department never says why.
- Left as it is: a check still good today that runs out before a service
  later in the week shown reads On (checks_of's `due`), as it did.
