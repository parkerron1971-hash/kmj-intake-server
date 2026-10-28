---
title: Class nights after they end - counted in a church's attendance, the room, and the slides to who missed it
date: 2026-10-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "let''s continue so we can finish up", then, asked whether online class nights count toward church attendance: "Count class nights"'
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio (the room, the console and the recap, next)]
migrations: [supabase/APPLY-2026-10-18-academy-class-nights.sql (applied)]
left_undone:
  - "Recording the class: waits on Kevin's own storage keys"
decisions:
  - "A class night is its own private occasion in Services & Events (the room Sunday check-in uses), named for the class and the night, on the church's clock; never on the public events page or a member's own"
  - "Who came: online (in the live room) or in the room (their own tap on their class link, or the teacher's mark); online / self / staff like every other check-in, never a first-time visitor"
  - "A class night is never a Sunday to the drifting rule, even one held on a Sunday afternoon (church_shepherd_signals): drifting stays Sundays only, Kevin's 10/17 rule"
  - "Counted once, within ten minutes of the end; a night that ended more than 3 days ago is left as it is; any other kind of business is simply marked done"
  - "Review on #1499: a failed missed-class email is tried again twice within the tick; the night is un-marked only when nobody heard (a send outage), never after some went out, since a later resend could pass the idempotency keys' 24 hours (the teacher can ask days after); what is still unsent is logged"
  - "The slides to who missed it only when the teacher asks (during class or after, in Course Studio): active students who were in the class before it ended and came neither way, once, by email with the way into their class"
related: [2026-10-18-class-reminders.md]
---
- `academy_class_nights.py`: `sweep_tick` (count, then the missed emails),
  `_occasion`, `night_name`, `missed_email`; scheduled every 10 minutes in
  `kmj_intake_automation.py` (`academy_class_nights`).
- `academy_live_router.py`: `here` (a student, while the class is on),
  `mark` (a teacher marks or unmarks a student of this class), `missed`
  (the teacher's ask, during or after class), and the roster says who is
  in the room and whether the slides go out.
- `church_shepherd_signals.py`: a class night's attendance is never a
  recorded Sunday.
- `supabase/APPLY-2026-10-18-academy-class-nights.sql` (+ MIGRATIONS):
  rehearsed with a rollback probe, applied, verified.
- `__tests__/test_class_nights.py` (25) and one in
  `test_church_shepherd_signals.py` (fails when the class-night exclusion
  is dropped: rehearsed); the roster test in `test_academy_live.py` reads
  the room.
