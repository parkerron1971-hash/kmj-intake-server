---
title: The booking reads see the bookings, and a failed read never says "free" (double-book guard)
date: 2026-10-08
agent: Claude Code (Claude Opus 5.5)
asked: "found while building B11 (#1330): fix the module_entries reads that ask for a duration_min column"
status: waiting on Kevin
prs: [kmj-intake-server#PENDING]
migrations: []
left_undone:
  - "The appointment_at and duration_min_at_booking COLUMNS are never written (production 2026-10-07: 0 of 39 active module_entries have the column set; all 12 dated bookings carry the time in data). Every reader that filters on the column still sees nothing: chief_booking_actions._find_booking (Chief finds no booking by name), booking_series._series_entries with from_iso (cancel from a date), booking_session_sync_tick's forward mirror, chief_availability, booking_rehearsal, and agent_site's open-chairs read in #1330. The root fix is a migration: a trigger that copies data->>appointment_at / data->>duration_min_at_booking into the columns with a safe cast, plus a backfill. Not done here"
  - "agent_site.py's open-chairs read is left to #1330 (same select defect); it should match on the column OR data and default an unknown length to 60, as availability_engine.BOOKING_SELECT / booking_window_filter / booked_rows now do"
  - "Frontend: the widget does not show config-anon's new slots_message when slots_unavailable is true; today it renders an empty calendar ('No availability on this day'). A one-line notice belongs in booking_calendar/external.tsx"
decisions:
  - "Bookings are read from the column OR data: availability_engine.BOOKING_SELECT (appointment_at, duration_min_at_booking, booked_at:data->>appointment_at, booked_min:data->>duration_min_at_booking) and booking_window_filter (whole-day text bounds; every stored shape starts YYYY-MM-DD, checked against production counts). The time comes from data (what reschedule moves) else the column; the length from the column else data else 60"
  - "The double-book guard raises SlotCheckFailed (an HTTPException 503, 'We couldn't confirm that time is still free. Please try again in a moment.') when the read fails or hits its row limit; zero rows is still free. The widget's book-anon and book answer that 503 (the widget shows the detail); Chief's create and reschedule say they didn't book or move anything; a weekly series skips that week with the reason 'couldn't check the calendar' and says so in the summary"
  - "Slot lists on a failed read: config-anon / config return every offering with [] plus slots_unavailable: true and slots_message (the form still loads; the shipped widget renders [] without crashing); GET /availability/{id}/slots answers 503 (its whole answer is slots, and no frontend calls it)"
  - "Also fixed on the way, because the guard now actually runs: a request with no length is checked as 60 minutes instead of skipped; a naive time is read as UTC (naive vs aware raised); Chief's reschedule leaves the booking being moved out of the check (a 30-minute move used to collide with itself); /availability/{id}/slots now reads active bookings only"
related: [2026-10-08-marketing-openings.md, 2026-10-01-sentry-first-night-fixes.md]
---
Three reads (the widget's open times, the double-book guard, GET
/availability/{id}/slots) selected a duration_min column module_entries does
not have. PostgREST answered 400, sb_get_as_service returned None and `or []`
turned it into "no bookings", so taken times showed as open and the guard let a
second customer book them. The production check also found the appointment_at
column empty on every row, so even the right select would have found nothing:
the reads now match the column or data. Production on 2026-10-07: the old
select 400s, the new one 200s; 12 active dated bookings in 2 businesses, no
overlapping pairs (no double booking happened), none in the future. Tests:
__tests__/test_booking_read_fix.py (no live calls).
