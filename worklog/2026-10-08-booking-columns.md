---
title: Bookings fill their own columns (module_entries appointment_at / duration_min_at_booking)
date: 2026-10-08
agent: Claude Code (Claude Opus 5.5)
asked: "follow-up of #1335: the root fix for the module_entries booking columns"
status: waiting on Kevin
prs: [kmj-intake-server#1338]
migrations: [supabase/APPLY-2026-10-08-booking-columns.sql (pending, apply after merge)]
left_undone:
  - "Apply supabase/APPLY-2026-10-08-booking-columns.sql after the merge, then run the VERIFY queries at its bottom (expect 3 functions, 1 trigger, 0/0 unfilled, 12 active bookings with a time, 9 with a length, 17 rows with a time in all)"
  - "Until it is applied these still filter on the empty column and see no bookings: chief_booking_actions._find_booking by name and _find_series_id (Chief can't find an upcoming booking or series by name), booking_series._series_entries with from_iso (cancel a weekly series from a date cancels nothing), booking_session_sync_tick's forward mirror and cancel sync, chief_availability and booking_rehearsal (read appointment_at=not.is.null), growth_intelligence_router's dated booking records. No code change: each needs the column, and the migration fills it"
  - "agent_site.slots_for in non-strict mode (the agent site, the Site Concierge, B7's capacity signal) still counts a failed bookings read as nothing booked, as before; the submit guard refuses a taken time. Only B11's strict mode raises"
  - "The draft Acuity PR #1257 adds its own BEFORE trigger on module_entries (acuity_booking_guard) that also sets these columns from data, with hard ::timestamptz / ::integer casts that raise on bad data. If it is revived, it should rely on this trigger (or public.booking_ts / booking_min) rather than a second copy"
decisions:
  - "The rule: data is the source of truth. The columns follow data on insert and whenever data's time or length moves (a reschedule moves data), and fill when empty; a statement that writes a column itself is left alone (insert with the column, an update that changes it, a deliberate clear), so the trigger never undoes a deliberate write; data with no readable time changes nothing (never cleared, never guessed)"
  - "Column writers found (both repos, 2026-10-08): none. Every backend and frontend write puts the time and length in data only. The only writer is the unmerged draft #1257 (Chief's reschedule PATCHes data and the column with the same value), which the rule keeps"
  - "public.booking_ts reads a bare date as midnight UTC, a time with Z or an offset as that instant, a time without one as UTC, anything else as NULL (an exception block: a booking write never fails on its data). STABLE, not IMMUTABLE (the text-to-timestamptz cast is STABLE). availability_engine.booking_instant uses the same pattern; __tests__/booking_time_cases.json holds the cases both must agree on (checked in Python and in PGlite)"
  - "Backfill side effects (production 2026-10-08: 17 rows, 12 active + 5 archived): updated_at moves on those rows (they rise once in an updated_at-sorted list; booking rows are not rosters, so no roster compare-and-save trips), one db:module_entries_update audit row each (append-only, an honest record), a realtime UPDATE each. The GL enqueue triggers don't fire (money fields only). require_standard_module_store would fail the whole apply for a row in a restricted module: there are none"
  - "Readers switched to the shared read (availability_engine BOOKING_SELECT / booking_window_filter / booked_rows, plus the new booked_start): agent_site.slots_for (a no-length booking now holds 60 minutes, not 0), business_marketing_openings.read_history (whole days read, the exact 60 days kept in Python, date-only bookings counted), marketing_signals._bookings (created_at rides along for the like-for-like count; padded days fall outside bookings_from's windows; every row still counts toward the row limit). #1330's strict mode unchanged"
  - "chief_availability.evaluate and booking_rehearsal.rehearse count a booking with no length as DEFAULT_BOOKED_MIN (60) instead of refusing. Without this, applying the migration would have made both refuse every check for business A (3 active, past bookings without a length). A length that is there but outside 1-1440 still refuses"
related: [2026-10-08-booking-read-fix.md, 2026-10-08-marketing-openings.md]
---
The booking columns on module_entries were never written, so every read that
filtered on them saw no bookings. A migration adds a trigger that keeps the
columns in step with data (plus safe casts and a backfill of the 17 rows that
carry a time), and the three live readers that filtered on the column alone
(the agent site / Site Concierge / open chairs slots, the open-chairs booking
history, B7's bookings signal) now use the shared column-or-data read, so they
work before the migration is applied. Production read-only check on
2026-10-08: the new slots_for read returns 12 rows, 12 bookings, across the
2 businesses (11 and 1); the old column read returned 0. Tests:
__tests__/test_booking_columns.py and __tests__/booking_columns_db.mjs (PGlite,
in CI).
