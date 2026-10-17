---
title: A booking's calendar copy follows the booking (reschedule lost it; it never existed in production)
date: 2026-10-16
agent: Claude Code (Claude Opus 5.5)
asked: "KAI brief (Fix lane): when Chief reschedules a booking, its calendar copy is cancelled and never recreated — reproduce, fix with exactly one copy at the new time, idempotent, failures said out loud with no names in logs; check the other Chief booking verbs. Then Codex's cross-review (kai/reviews/core-reschedule-1465-review.md, request changes): fix P1-1..P2-4 and both should-fixes, tests first; KAI: one APPLY file, the code changes nothing until it is applied, decide no-contact bookings, go-live order and who starts getting texts in the PR."
status: in progress
prs: [kmj-intake-server#1465]
migrations: [supabase/APPLY-2026-10-16-booking-calendar-copies.sql]
left_undone:
  - "NOT APPLIED: supabase/APPLY-2026-10-16-booking-calendar-copies.sql. Applying it starts reminder texts to booking clients, so it is Kevin's, and only after the go-live order: (1) the frontend calendar stops drawing a session whose notes carry [booking:...] as a second appointment (CalendarView already draws the booking from module_entries; frontend lane, via KAI); (2) Kevin applies the file; (3) within 10 minutes the sync tick writes copies for upcoming bookings and reminders start."
  - "Codex re-checks #1465. Not merged here."
  - "Who starts getting texts (production 2026-10-16, counts only): 12 active bookings in 2 businesses; 6 have a contact, 1 has a phone that normalises, and that 1 has consent, no STOP, reminders on, not paused. None is upcoming, so applying today texts nobody. SMS_ALERTS_ENABLED is unset on Railway (on); Twilio is configured."
  - "Other readers of sessions will start seeing booking copies once applied: Chief's upcoming-sessions context, the Sessions panel, the desk's scheduled() (deskData.ts merges it with bookings). Each should treat a [booking:] session as the booking it copies; check them with the frontend dedupe."
  - "update_module_entry still moves a booking WITHOUT the double-book guard (its copy now follows). Separate defect; route it through reschedule_booking if it matters."
  - "A copy moved directly in the app's own calendar UI (not through Chief) still leaves the booking at its old time. Frontend, not checked."
  - "What's-New entry (frontend repo, src/core/updates/whatsNew.ts), after the APPLY file is in: reminders for booked clients, and moves through Chief keep them right. Draft: id '2026-10-16-booking-reminders', area 'Chief', title 'Booked clients get a reminder text', body 'Clients who book with you now get a text reminder the day before, if they agreed to texts. When you ask Chief to move or cancel an appointment, the reminder follows. If Chief can't update it, Chief tells you.'"
decisions:
  - "Root cause behind the reported bug: no booking has ever had a calendar copy. The mirror writes session_type 'booking' and production's sessions_session_type_check never allowed it (0 marked sessions in production on 2026-10-16). The refusal went to a logger, which never reaches Railway's logs. sessions.contact_id is also NOT NULL, and the 6 hand-made bookings have no contact."
  - "The copy is the sessions row with [booking:{id}] in notes, read by the reminder sweep, Chief's upcoming context and the no-show fee button. The practitioner's calendar (CalendarView) draws the booking itself, so a missing or stale copy costs the reminder, not the calendar. Chief's messages say 'reminder' for that reason. Nothing here writes to Google: outside_calendar.py only reads busy times."
  - "One database function does every copy write: public.booking_session_sync(business, booking, row). It locks the booking row (FOR UPDATE), so syncs of one booking, and writes to it, never interleave (P1-1). It reads the booking it locked, not the caller's copy; a caller holding an old time gets 'stale' and reads again. It runs whole or not at all, so a half-done move can't exist (P1-2). An inactive booking keeps no copy and never gets one back (P1-3). Every call reconciles to the booking as it is, so a repeated edit repairs (P2-4). No row limit (the 50-row history bug)."
  - "The function's absence is the switch: until the APPLY file is in, PostgREST answers PGRST202, sync_booking_session returns 'off', nothing is written and nothing is said. That is exactly production's behaviour today, without the false 'couldn't update your calendar' the first version of this PR would have shown on every move."
  - "A moved booking gets a NEW copy and the old one is cancelled, not moved in place: reminders are de-duplicated per session id. The newest live copy's notes come along. A copy whose newest version at the booking's own time was cancelled, completed or marked no-show is not put back."
  - "Reminders follow the booking, not the copy: right before each send, sms_alerts re-reads the booking and sends only if it is active, at this copy's time, and this copy is its one live copy (oldest first). A stale or leftover copy is never texted, even one a failed write left behind, and even one fetched before a mid-sweep change. A failed read sends nothing; the next hourly pass retries."
  - "No client contact: no copy, said plainly ('It has no client contact linked, so no reminder text goes out for it.'). A contact is never made up for one (KAI's call)."
  - "Durable repair: the 10-minute tick syncs every upcoming booking, active or not, through the same function, so any failed sync is repaired within 10 minutes. It stops at once while copies are off."
  - "Booking PATCHes (reschedule, cancel, recurring cancel) are redacted (PostgREST errors echo the row, name included) and land only while the booking is active, so a cancel that lands mid-move wins."
related: [2026-10-08-booking-columns.md, 2026-10-08-booking-read-fix.md]
---
The reported bug: `reschedule_booking` cancelled the booking's `sessions` copy,
then asked `_mirror_booking_session` for a new one. The mirror's "already
mirrored?" check matched the copy it had just cancelled, so it wrote nothing.

Behind it, while answering Codex's review: no booking has ever had a copy.
Production's `sessions_session_type_check` refuses `session_type 'booking'`,
which is what the mirror writes. So the reminder sweep has never texted a
booked client, and the first version of this PR would have told the
practitioner "I couldn't move it on your calendar" on every move.

Round 2 (Codex's review): `supabase/APPLY-2026-10-16-booking-calendar-copies.sql`
allows the type and adds `public.booking_session_sync`, which every path calls
through `booking_widget_router.sync_booking_session`. Chief's reschedule,
cancel, update_session, update_module_entry and delete_module_entry use it, and
so do the widget's create, the weekly series and the tick.
`sms_alerts.reminder_sweep` checks the booking before each send.
`sb_clients.sb_rpc_as_service` tells a missing function from a failure.

Tests: `__tests__/test_booking_calendar_copy.py`
- The 4 failing tests from round 1, then 15 more reproducing Codex's findings
  (commit cdef0df4, run against the round-1 code first).
- A fake with production's sessions constraints, the real reminder sweep, and
  a second business.
- `__tests__/booking_session_sync_db.mjs` runs the SQL on PGlite in CI.
- `__tests__/test_booking_session_sync_sql.py` runs overlapping moves, syncs
  and a cancel on a real Postgres server: locally only, with
  BOOKING_SYNC_PG_DSN set (PGlite has one connection).
