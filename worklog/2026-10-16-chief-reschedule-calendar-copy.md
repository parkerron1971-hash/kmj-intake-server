---
title: A booking Chief moves keeps its calendar copy (reschedule lost the sessions row)
date: 2026-10-16
agent: Claude Code (Claude Opus 5.5)
asked: "KAI brief (Fix lane): when Chief reschedules a booking, its calendar copy is cancelled and never recreated — reproduce, fix with exactly one copy at the new time, idempotent, failures said out loud with no names in logs; check the other Chief booking verbs"
status: in progress
prs: [kmj-intake-server#TBD]
migrations: []
left_undone:
  - "Codex cross-review (kai/reviews/), then merge on green. Not merged here."
  - "update_module_entry still moves a booking WITHOUT the double-book guard (it now moves the calendar copy too, but a generic entry edit can still put a booking on a taken time). Separate defect; route it through reschedule_booking if it matters."
  - "A calendar copy moved directly in the app's own calendar UI (not through Chief) still leaves the booking at its old time. Not checked on the frontend."
  - "What's-New entry (frontend repo, src/core/updates/whatsNew.ts; this session was limited to the backend worktree). Ship it after this PR is live. Draft: id '2026-10-16-moved-appointments-stay-on-calendar', area 'Chief', title 'Appointments Chief moves stay on your calendar', body 'When you ask Chief to move an appointment, it now moves on your calendar too, and its reminder goes out for the new time. Appointments that went missing from your calendar after an earlier move come back on their own within a few minutes. If the calendar can’t be updated, Chief tells you.'"
decisions:
  - "The calendar copy is the sessions row with [booking:{id}] in notes. Nothing here writes to Google or any outside calendar: outside_calendar.py is read-only busy times from an ICS feed. The copy is what the calendar, Chief's upcoming context and the SMS reminder sweep read."
  - "A moved booking gets a NEW copy at the new time and the stale one is cancelled, rather than moving the old row in place: reminders are de-duplicated per session id (sms_alerts.reminder_sweep), so a copy already reminded for its old time would never be reminded for its new one. The new copy keeps the old live copy's notes. The new copy is written before the old is cancelled, so a failure part-way never leaves none."
  - "Exactly one live copy, idempotent and race-safe: after writing, re-read and keep the lowest-id copy at the new time; cancel every other scheduled copy. Completed / no_show copies are history and are left alone."
  - "The mirror's dedupe no longer counts a cancelled copy at ANOTHER time (that is what a move leaves behind). So the 10-minute sync tick gives bookings the bug already hit their copy back after deploy. A cancelled copy at the booking's own time is still respected. A failed read now writes nothing (it used to write a second copy)."
  - "When the booking changed but its copy didn't, the action still succeeds (the change is real) and says so in its result, with calendar_updated: false; a print() line with ids only goes to the logs. _fail no longer logs its message, which often named the client."
  - "update_session on a booking's copy: a new time goes through reschedule_booking (guard included), a cancel through cancel_booking, so the booking and its copy move together."
related: [2026-10-08-booking-columns.md, 2026-10-08-booking-read-fix.md]
---
The bug: `reschedule_booking` cancelled the booking's `sessions` copy, then asked
`_mirror_booking_session` for a new one. The mirror's "already mirrored?" check
matched any session with the marker, including the one just cancelled, so it
wrote nothing. The booking moved, but it left the calendar and the reminder
sweep for good: the sync tick asks the same mirror and could never put it back.
The old unit test stubbed the mirror out, which is how it slipped through.

The fix lives in `booking_widget_router.py`: `sync_booking_session` (the shared
move path), `cancel_booking_sessions`, and the mirror's corrected dedupe. In
`chief_booking_actions.py`: reschedule and cancel use them and report a calendar
miss, and the hooks for `update_session`, `update_module_entry` and
`delete_module_entry` (wired in `chief_of_staff.py`). `booking_series.cancel_series`
counts copies it couldn't clear and says so. `sb_patch_as_service` gained
`redact=` (session rows can hold names, and PostgREST errors echo the row).

Tests: `__tests__/test_booking_calendar_copy.py` runs the real helpers against a
small in-memory PostgREST, including the booking-columns trigger. Its first four
tests failed on main (committed first, on their own).
