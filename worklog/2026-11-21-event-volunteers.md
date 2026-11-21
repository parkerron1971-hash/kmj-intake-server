---
title: An event's volunteers and its flyer, one structure (Services & Events, Who serves when, the flyer)
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-20: "when a event is made there should be questions asked normal service volunteers or special volunteers… request for an amount of volunteers for their event… a way to inser flyer for like a thumbnail… connect the volunteers to events", then "go" on the proposal https://claude.ai/artifact/98Z9QFcaZ6ZNQhLdarKHQB; 2026-11-21: "switch on today"'
status: shipped
prs: [kmj-intake-server#2019 (S1), kmj-intake-server#2023 (S2 the engine), kmj-intake-server#2026 (S3 around the event), kmj-intake-server#2028 (the picture's can_change for S4b), solutionist-studio#1668 (S4a New event), solutionist-studio#1669 (S4b the event's page and flyer thumbs), solutionist-studio#1670 (S4c Event requests and The week), kmj-intake-server#2029 (S5 Chief), kmj-intake-server#2030 (the migration applied), kmj-intake-server#2031 (teens and the overdue flag), solutionist-studio#1674 (What's New and the Help Center), "kmj-intake-server (this PR, the switch-on)"]
migrations: ["supabase/APPLY-2026-11-21-event-volunteers.sql (APPLIED 2026-11-21: ledger kmj-intake-server#2030)"]
left_undone:
  - "Spec section 10, not in this build: department leaders planning an event from the member app (call 5); the organizer changing numbers after the ask is on; a recurring event's volunteers; texts for event asks; two same-title event dates on one day after a move or rename"
  - "Frontend: the office's Serving page counts special helpers' event minutes in each person's hours and the year's total, but has no Events line (servingCore.personLine, By team)"
  - "Frontend: the event page's kids note still says \"offered only to people with a current background check\"; since #2031 a teen of 13 to 17 may take it too"
  - "Frontend: the office's picture shows a junior helper with no chip, and the member app's refusal for a child under 13 still reads \"Needs a background check. Ask the office.\" (2026-11-21-kids-roles-teens-overdue.md)"
  - "Ask Chief to make a flyer shows only where the Studio's Light Table is open (STUDIO_LIGHT_TABLE, owner when unset): its own switch-on"
  - "Office: the app has no field for an event's helper minutes (_serve_minutes), so events count the default 120"
decisions:
  - "Kevin's five calls as recommended: one-tap yes from whoever schedules the teams (straight on when that's the asker); teams start unticked at their Sunday number; special roles sign up in the app, public only when opened, kids roles check-only; special helpers earn hours; office logins only for now"
  - "Numbers live on the event date (worship_services.needs), null = the Sunday numbers, so the 11-17 dates are unchanged"
  - "The request is a server-only table; special roles, _flyer and _serve_minutes stay on the event's data, _flyer server-written and validated on every read"
  - "S2: EVENT_VOLUNTEERS opens only where CHURCH_EVENT_VOLUNTEERS does; it gates asking, answering, the scheduler's list and a date's numbers, never the picture or taking a waiting ask back"
  - "S2: straight on and a yes both claim the ask's row before the date is made (sunday_planning.make_date, the one way), and let it go if the date can't be; two asks or two yeses at once make one date"
  - "S2: notices go to the serve_schedule Managers (the owner when none) and the organizer through church_schedule_tell.to_login, claimed once in told_at / answer_told_at, held through quiet hours, retried by the 15-minute sweep; no office bell (it can't say whether it went)"
  - "S2: fixed a bug on the way: Fill the month could ask one person for two spots of one place at one service (busy() leaves the place's own spots out); do_fill now skips them"
  - "S2 after review: taking a date off cancels its ask; an ask left on with no date is never told and the sweep mends it (linked, cancelled, or waiting again); an unplanned Sunday keeps the church's usual Sunday times; a date's numbers are checked again after the write; an event with an ask can't go on another way"
  - "S2: the rest of the S2 calls are in docs/EVENT_VOLUNTEERS.md section 11"
  - "S3: the event's date follows it (follow on /changed and in the 15-minute sweep, a handful of reads a church): told through member_push_sends as event-moved-{assignment}-{time}-{n} so a person's latest move notice always names the date's time (a lost move put back is corrected), event-cancelled-{assignment} once; tell first then change; quiet hours hold the whole change and the serving sweep says nothing for that date meanwhile (unsettled); a rain date within 48 hours follows, older is flagged; a cancel takes every ask back by Take back's path, the date off, the ask closed last; changes only where the tell can go (_follows)"
  - "S3: the flyer goes through image_studio as the owner (normalize_image, the gallery row) with two EXIF-free JPEG copies in business-assets; limits read from the header before decoding; a gallery pick only for who may read the gallery (church_reader); every reader goes through flyer_of, which pins the event's folder and the copies' names; taking a flyer off isn't switch-gated; /events?event=<id> is one event's share preview"
  - "S3: a kids role needs church_serving.cleared (checks_of ok or due, never under 18: deliberately stricter than The week's flag, decided in review); the member app refuses by redirect notice (err=kids; err=filled names the role from the church's data, never the link); the office's picture says why (Check overdue, No check on file, Under 18); the public page shows only open roles, never kids"
  - "S3: special helpers' hours are church_serving.event_credits (the year's events only, the keys it needs; once per event, the longer of a team place and a role; archived after it started keeps its hours; a public sign-up never counts, via public or a public registration key), in the Serving page, My serving, The week and Reports; a read blip counts no events; nothing changes with the switch closed"
  - "S3: the rest of the S3 calls are in docs/EVENT_VOLUNTEERS.md section 11"
  - "Switch-on 2026-11-21 (Kevin: \"switch on today\", a Saturday, as #1866): EVENT_VOLUNTEERS and CHURCH_EVENT_VOLUNTEERS default on in the code (neither was ever set on Railway, so the web service and the worker read the same); rollback EVENT_VOLUNTEERS=off on both services; tests that leaned on the owner default now set owner, and a test each pins unset as on for any church and off as the rollback"
  - "Switch-on: special helpers' hours count every past event of this year with a role signed up by a member in the app or put on by the office or Chief, events made before today included (church_serving.event_credits is gated by the switch alone), so a church's year of hours goes up on deploy"
  - "Switch-on: church_findway.json re-exported from solutionist-studio #1674 on 07f13b37 (seven event answers, plus Visitor flow taking the Guests room's words and the giving-access answers the copy lacked); system_destinations.json is the frontend's again"
related: [2026-11-17-event-volunteer-dates.md, 2026-11-17-events-volunteer-list.md, 2026-11-11-light-table-step2.md, 2026-11-18-church-schedule.md]
---
Before building I read both repos' work logs. The 11-17 event-dates log (backend and
frontend) left "the event moved or renamed doesn't move its date", "a typed date isn't
added to Services & Events" and "no Sunday event date" undone; this build picks all three
up (spec 6.7-6.9). The Light Table logs (frontend 11-09, 11-11) make flyers for an event
but never attach one; spec 6.12 attaches them. Nothing else overlapped; open PR #2011
(the department week) touches `church_week.py` and `sunday_leading.py`, so S2 branches
after it merges.

S1 is `docs/EVENT_VOLUNTEERS.md` (the standing spec: the structure, the calls, the data,
the switch, who may do what, every rule and route, the build order), the migration, and
its PGlite check (`__tests__/event_volunteers_db.mjs`, 80 checks, in CI; eight sabotages
of the SQL each turned it red).

S2 is the engine, on main after #2019 and #2011. `event_volunteers.py`: the switch,
`ready()` (pinned off in conftest), the status, the event's volunteer picture, asking,
changing and taking back an ask, the scheduler's list and answer (routes on Who serves
when), `flyer_of` (the validator only), and the notices with their sweep.
`sunday_planning.make_date` is the one way an event date is made, from Add an event date
and from an ask; it takes Sunday afternoons and makes a typed date a Services & Events
entry when the switch is open. `serve_dates.needed()` counts every slot: Who serves when,
the member's ask page, a leader's Sundays, The week (and My department through it), My
week, and the Sunday-plan readers. Tests: `__tests__/test_event_volunteers.py` and
`__tests__/test_event_volunteers_readers.py`; the sabotages are in the PR.

S3 is the server around the event, on main after #2023. `event_volunteers.py` adds
`sync` (and `POST /{entry_id}/changed`, and `follow_tick` in the existing 15-minute
sweep), the flyer routes (`PUT`/`DELETE /{entry_id}/flyer`) and `date_extras` for Who
serves when and The week. The readers: `events_rsvp_router.build_occasions` (the
public page's card and its `?event=` share preview, the member app's Coming up in
both looks and the new Home's This week), `sunday_serving` (My serving's rows and ask
page), `/planning/requests`, the schedule and The week. `church_serving` gains
`cleared` (the kids rule, shared with The week's) and `event_credits` (hours), read by
the Serving page, My serving, `minutes_of` and Reports. `chief_roster.clean_roles`
keeps `kids` and `open`. No migration: told-once is `member_push_sends`. Tests:
`__tests__/test_event_volunteers_follow.py`, `test_event_volunteers_flyer.py`,
`test_event_volunteers_roles_hours.py`; the sabotages are in the PR.

After review (same PR): a person's latest move notice now always names the date's
time (the key counts their notices; a lost move put back is corrected), the serving
sweep says nothing for a date whose change waits (no 7 AM reminder for a cancelled
event), reminders re-arm only for moments still to come, a rain date follows within
48 hours, nothing changes where nobody would be told, the sweep reads each church once,
the hours read is bounded and degrades, archived-after keeps hours, public sign-ups
earn none, the flyer's limits are read before decoding and its gallery pick follows
the gallery's own rule, and flyer_of pins the event. Found on the way, not ours:
`test_member_portal_department_week.py` (2) and `test_member_lumen_home5.py` (2) fail
on plain main in the evening (quiet hours, the time of day), as they do on this branch.

Second review (same PR): the batched reads now page past PostgREST's 1,000-row cap
(the rows on the dates followed, the sweep's two finding reads), the move ledger is
read only for the people on those dates, newest first and paged, with a tie on n going
to the later-written notice; the hours read fails like the rest of church_serving
(never fewer hours, Reports never short); a reminder hold for a change over a day old is
said in the logs; spec section 9 S4 asks the office app to round-trip `via` and to hold
`_flyer` to the whole-match rule.
