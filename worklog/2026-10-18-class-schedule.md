---
title: The class schedule (server) - homework past the slides, gatherings, students' work and the teacher's reply, one rule for finished, the class on the student's calendar
date: 2026-10-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "a schedule that can be created where the teacher can set lessons, live sessions, homework that could be beyond the visual" - then "I''m happy with it. build it" for the approved Class Schedule design (step 2 of 4)'
status: shipped
prs: [kmj-intake-server#TBD]
migrations: [supabase/APPLY-2026-10-18-academy-schedule.sql (applied)]
left_undone:
  - "The teacher's Schedule tab, homework kinds, students' This week and Add to my calendar are the solutionist-studio PR that follows"
  - "Uploads (a photo, a file, a voice note) need their own upload by class link; the item kind exists, saving refuses until a file is there"
  - "Chief drafting the schedule from the lessons; discussions and projects (step 3); the website's class list and pages (step 4)"
decisions:
  - "An item lives in a week through its lesson: it opens when that lesson opens for the student, and homework is due due_days after (6 = the day before next week's class), on the class's own clock"
  - "Kevin's pick: homework counts toward finishing by default, gatherings don't; one rule (academy_enrollment_settle) decides finished for lessons and items alike"
  - "Ticking an item never undoes a teacher's 'finished'; only finishing a lesson can reopen a class, as it always could"
  - "A lesson's own quiz stays in the lesson, where it already counts, instead of a second quiz system"
  - "Classmates' answers show only when the teacher chooses to share an item, and then by first name"
  - "The calendar feed is keyed by the class link, built from the classroom's own two reads, so it never shows a draft or a locked week's details"
related: [2026-10-18-class-opens-together.md, 2026-10-17-class-student-side.md]
---
- `supabase/APPLY-2026-10-18-academy-schedule.sql`: `academy_schedule_items`,
  `academy_item_work`, `academy_classroom_schedule`, `academy_save_item_work`,
  `academy_item_feedback`, `academy_items_done`, `academy_enrollment_settle`,
  `academy_complete_lesson` recreated on the one rule.
- `academy_calendar.py`: `GET /academy-calendar/<class link>.ics` (live classes,
  due dates, gatherings; escaped and folded per RFC 5545, never cached).
- `account_lifecycle.py`: the schedule goes out with the business, and is not
  restored onto re-minted class ids.
- `__tests__/test_class_schedule.py` (13); the database half rehearsed on
  production in a rolled-back transaction (see docs/MIGRATIONS.md).
