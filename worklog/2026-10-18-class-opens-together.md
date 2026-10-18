---
title: How lessons open (server) - a class can run together from a start date, late joiners catch up
date: 2026-10-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "when we are building the class from scratch, it should be allowed to be select 1 lesson per week or all the lessons released at once" - then "I''m happy with it. build it" for the approved Class Schedule design (step 1 of 4)'
status: shipped
prs: [kmj-intake-server#TBD]
migrations: [supabase/APPLY-2026-10-18-academy-opens-from.sql (applied)]
left_undone:
  - "Asking it when a class is started, and the together choice in Course setup, are the solutionist-studio PR that follows"
  - "Live classes on each week's meeting time, homework kinds, discussions and projects are steps 2 and 3 (the schedule)"
decisions:
  - "Kevin's pick: one a week counts from the class's start date for a class with dates; someone who joins late finds the weeks already past open"
  - "No start date keeps the old rule: lessons count from the day each person joins"
  - "All at once ignores a start date; a custom schedule counts each lesson's days from it"
related: [2026-10-17-class-self-join.md, 2026-10-17-class-student-side.md]
---
- `supabase/APPLY-2026-10-18-academy-opens-from.sql`: `academy_courses.opens_from`;
  `academy_lesson_unlock` (the one rule the classroom, slides, journal, work
  and finishing a lesson already share) counts from it.
- `public_site._learn_unlock` takes the start date (the older /learn pages);
  the class page's line about how lessons open comes from
  `academy_join.release_note`: "One lesson a week, together, from Thursday,
  October 22 at 6 PM." in the business's time zone, or "since … Join now and
  the weeks so far are open to catch up." once it has started.
- `__tests__/test_class_opens_together.py` (10), sabotage-checked (6 fail with
  the start date ignored); the database half rehearsed on production in a
  rolled-back transaction (see docs/MIGRATIONS.md).
