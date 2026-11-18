---
title: Who serves when schedules the volunteer teams for an event that isn't on a Sunday
date: 2026-11-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, about Laquesha scheduling greeters, ushers, parking, kids workers and hospitality for a Thursday outreach night, a Saturday event or a Wednesday Bible study: "build that"'
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio (the Add an event date PR)]
migrations: [supabase/APPLY-2026-11-17-event-volunteer-dates.sql (APPLIED 2026-11-18 by Kevin; read back)]
left_undone:
  - "CHURCH_EVENT_VOLUNTEERS is owner by default (Love City only): switch it on for every church on a Thursday"
  - "An event moved or renamed in Services & Events doesn't move its event date: the date keeps the day, time, name and place it was added with (take it off and add it again while nobody was asked)"
  - "A typed event date isn't added to Services & Events or the church calendar (one picked from there is that entry already)"
  - "No event date on a Sunday: a Sunday afternoon event can't get its own volunteer schedule yet"
  - "Chief has no verb to add an event date; he can point Laquesha at Add an event date (the Help Center answer)"
  - "A team leader's Lead page still says 'Your team's Sundays' and 'Fill the next five Sundays' when an event date is among them; the office's Serving hours screen still counts event dates under Sundays"
decisions:
  - "An event date is a worship_services row of kind 'event' (not a new table): serve_assignments already references worship_services, so asks, subs, reminders, the member app, the .ics, the alerts and the hours follow it with no second read"
  - "ChurchSavvy never sees one: every read of the Sunday plans adds serve_dates.plans_only() (worship_show_router list, one service, save, delete, the lobby's next; sunday_order's order, Today and upcoming; the leaders note; the monthly report; the countdown's count; the work checks' plans). The member's pack reads it (plans=False)"
  - "Before the migration nothing selects or filters on the new columns (serve_dates.ready: a probe kept ten minutes when there, a minute when PostgREST says 42703, a blip keeps the last answer); tests pin it off in conftest so every other suite reads as before"
  - "Only the Volunteers' teams serve an event date (sunday_planning.serves): ChurchSavvy's door doesn't list it; ask, offer and fill refuse or skip a ChurchSavvy team's place on it (409); a worship or production team's leader never sees it"
  - "It isn't one of a team's Sundays a month (no cap, not counted in the month's load); 'I can do another Sunday' isn't offered for it"
  - "Who adds one: whoever changes the Volunteers' teams (serve_schedule, the owner, an Admin). Never a Sunday, never past, at most 180 days ahead, 30 still to come at most, an entry once while it's on, one title once a day; it comes off only while nobody was asked, and the switch never traps one"
  - "Who serves when now reads from today, not from the coming Sunday, so this week's Thursday shows before its Sunday; the Sundays shown are still five"
  - "The member hears the real day: 'Can you serve on Greeter, Thursday, Nov 19?', 'Laquesha asked for Outreach night', 'Next Thursday you're on Greeter', 'Your Thursday', 'Starts at 7:00 PM', the .ics with the event's name and place. A Sunday's words are unchanged"
  - "My week judges Sunday alone and says the week's event dates beside it: '3 of 8 places on Sunday's volunteer teams have a yes, and 4 of 6 for Thursday's Outreach night'"
  - "CHURCH_EVENT_VOLUNTEERS = off | owner | on, owner by default (member_asks.platform_church, as new_here)"
related: [2026-11-17-events-volunteer-list.md, 2026-11-02-volunteers-door.md]
---
Before building I read both repos' work logs: `2026-11-17-events-volunteer-list.md` (backend) and
`2026-11-17-events-room-request.md` (frontend) both left exactly this undone ("Who serves when
schedules Sundays only"); nothing else overlapped.

- `serve_dates.py` (new): the switch, the column probe (`ready`, `fields`, `plans_only`), the day's words.
- `sunday_planning.py`: `GET /planning/events`, `POST /planning/dates`, `DELETE /planning/dates/{id}`;
  `serves`; the window from today; the board, ask, offer and fill keep ChurchSavvy's teams off an
  event date; `event_dates` on status and the schedule.
- Plan readers filtered: `worship_show_router.py`, `sunday_order.py`, `church_leaders_note.py`,
  `church_monthly_report.py`, `worship_count_auto.py`.
- Words: `sunday_serving.py`, `member_portal_serving.py`, `sunday_serving_alerts.py`, `serve_links.py`,
  `sunday_leading.py`, `member_portal_leading.py`, `church_serving.py` (`other_days`).
- `church_work_checks.py`: `event_dates`, `_event_lines`, `job_serve_schedule`.
- `church_findway.json` re-exported from the frontend (the Help Center answer "Schedule volunteers
  for an event that isn't on Sunday"; it also carries a "Plan the week now" answer already on the
  frontend's trunk).
- Tests: `__tests__/test_event_volunteer_dates.py` (13), `__tests__/event_volunteer_dates_db.mjs`
  (PGlite, 26, in CI), the one status test that names every key.
- Docs: `docs/CHURCH_DUTIES.md` ("Event dates on Who serves when"), `docs/MIGRATIONS.md`, `.env.example`.
