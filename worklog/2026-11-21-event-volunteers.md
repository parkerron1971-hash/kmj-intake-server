---
title: An event's volunteers and its flyer, one structure (Services & Events, Who serves when, the flyer)
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-20: "when a event is made there should be questions asked normal service volunteers or special volunteers… request for an amount of volunteers for their event… a way to inser flyer for like a thumbnail… connect the volunteers to events", then "go" on the proposal https://claude.ai/artifact/98Z9QFcaZ6ZNQhLdarKHQB'
status: in progress
prs: [kmj-intake-server (S1, this PR)]
migrations: [supabase/APPLY-2026-11-21-event-volunteers.sql (NOT APPLIED)]
left_undone:
  - "S2 server engine: event_volunteers.py, serve_dates.needed() in every slot reader, requests and answers, Sunday afternoon, typed dates become events (docs/EVENT_VOLUNTEERS.md section 9)"
  - "S3 server around the event: sync + sweep, the flyer and flyer_of on every reader, special-role rules and I'll help, hours for special helpers"
  - "S4 office frontend: the three questions in New event, the event's Volunteers band, Event requests on Who serves when and The week, flyer thumbs"
  - "S5 Chief: teams and flyer on create/update_module_entry, how full is my event"
  - "Switch-on PR on a Thursday (EVENT_VOLUNTEERS=on, What's New, Help Center re-export)"
decisions:
  - "Kevin's five calls as recommended: one-tap yes from whoever schedules the teams (straight on when that's the asker); teams start unticked at their Sunday number; special roles sign up in the app, public only when opened, kids roles check-only; special helpers earn hours; office logins only for now"
  - "Numbers live on the event date (worship_services.needs), null = the Sunday numbers, so the 11-17 dates are unchanged"
  - "The request is a server-only table; special roles, _flyer and _serve_minutes stay on the event's data, _flyer server-written and validated on every read"
related: [2026-11-17-event-volunteer-dates.md, 2026-11-17-events-volunteer-list.md, 2026-11-11-light-table-step2.md]
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
