---
title: Class-night reminders - every student by email a few hours before a live class, and a church's member app by its Class nights notification
date: 2026-10-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "ok. let''s continue with those not done yet." (phase 5 of the approved class design; his 10/17 pick: reminders, and member notifications, yes)'
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio (the Course setup switch, next)]
migrations: [supabase/APPLY-2026-10-18-academy-class-reminders.sql (applied)]
left_undone:
  - "Text-message reminders: texting for businesses waits on the phone companies' approval"
  - "Love City's member app sends Class nights only once the church turns it on (Settings, Member page, notifications); it's off like every other kind until then"
decisions:
  - "Three hours before (not under half an hour: that late is noise); a class before 10 AM is told the evening before, 5 to 9 PM, never at dawn or late at night"
  - "Each night once: academy_live_reminder_claim marks it before a word goes out; the business is read first, so a night is never marked with nobody told"
  - "Email for every kind of business (any student, any live class); the push is the church member app's own Class nights kind, under the church's switch and each member's choice"
  - "On by default for every class (Kevin's yes), with an off switch per class in Course setup (the next FE PR); no class nights were scheduled anywhere when it went live"
  - "Only active students of a published class; a dropped student or a cancelled night never hears"
  - "Review on #1497: the business and its clock are read strictly before a night is claimed (a failed read is skipped, never a fallback clock); a night whose emails all failed is un-marked (academy_live_reminder_release) so the next tick retries, the idempotency keys keeping anyone from a second copy; a night moved to another time is reminded again (trigger)"
related: [2026-10-18-church-member-classes.md]
---
- `academy_reminders.py`: `due` (when, in the business's clock),
  `reminder_email`, `sweep_tick` (claim, email, push); scheduled every 15
  minutes in `kmj_intake_automation.py` (`academy_class_reminders`).
- `member_push.py`: the `classes` kind (Class nights).
- `supabase/APPLY-2026-10-18-academy-class-reminders.sql` (+ MIGRATIONS):
  rehearsed with a rollback probe, applied, verified.
- `__tests__/test_class_reminders.py` (17): the timing table (fails when the
  half-hour floor is dropped: rehearsed), the email words, one night told
  once by email and push, a claimed night left alone, never claimed early,
  never claimed when the business can't be read, one failed email doesn't
  stop the rest, the real email's link and key, the kind and the job.
