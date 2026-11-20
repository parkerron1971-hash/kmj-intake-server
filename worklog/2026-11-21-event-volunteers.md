---
title: An event's volunteers and its flyer, one structure (Services & Events, Who serves when, the flyer)
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-20: "when a event is made there should be questions asked normal service volunteers or special volunteers… request for an amount of volunteers for their event… a way to inser flyer for like a thumbnail… connect the volunteers to events", then "go" on the proposal https://claude.ai/artifact/98Z9QFcaZ6ZNQhLdarKHQB'
status: in progress
prs: [kmj-intake-server#2019 (S1, merged), kmj-intake-server (S2 the engine, this PR)]
migrations: [supabase/APPLY-2026-11-21-event-volunteers.sql (NOT APPLIED)]
left_undone:
  - "Kevin applies supabase/APPLY-2026-11-21-event-volunteers.sql; until then every S2 route answers 404 (the status says ready: false) and no read selects worship_services.needs"
  - "S3 server around the event: sync (POST /church/event-volunteers/{entry_id}/changed) and adding it to event_volunteers.sweep_tick (already on the worker every 15 minutes), the flyer upload/attach and flyer_of on every reader, special-role rules and I'll help, hours for special helpers"
  - "S4 office frontend: the three questions in New event, the event's Volunteers band (GET /church/event-volunteers/{entry_id}), Event requests on Who serves when and The week (requests_waiting, GET /planning/requests, the answer), the schedule's per-service `needed`, flyer thumbs"
  - "S5 Chief: teams and flyer on create/update_module_entry, how full is my event"
  - "Switch-on PR on a Thursday: EVENT_VOLUNTEERS=on AND CHURCH_EVENT_VOLUNTEERS=on (the first opens only where the second is), What's New, Help Center re-export"
decisions:
  - "Kevin's five calls as recommended: one-tap yes from whoever schedules the teams (straight on when that's the asker); teams start unticked at their Sunday number; special roles sign up in the app, public only when opened, kids roles check-only; special helpers earn hours; office logins only for now"
  - "Numbers live on the event date (worship_services.needs), null = the Sunday numbers, so the 11-17 dates are unchanged"
  - "The request is a server-only table; special roles, _flyer and _serve_minutes stay on the event's data, _flyer server-written and validated on every read"
  - "S2: EVENT_VOLUNTEERS opens only where CHURCH_EVENT_VOLUNTEERS does; it gates asking, answering, the scheduler's list and a date's numbers, never the picture or taking a waiting ask back"
  - "S2: straight on and a yes both claim the ask's row before the date is made (sunday_planning.make_date, the one way), and let it go if the date can't be; two asks or two yeses at once make one date"
  - "S2: notices go to the serve_schedule Managers (the owner when none) and the organizer through church_schedule_tell.to_login, claimed once in told_at / answer_told_at, held through quiet hours, retried by the 15-minute sweep; no office bell (it can't say whether it went)"
  - "S2: fixed a bug on the way: Fill the month could ask one person for two spots of one place at one service (busy() leaves the place's own spots out); do_fill now skips them"
  - "S2: the rest of the S2 calls are in docs/EVENT_VOLUNTEERS.md section 11"
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
