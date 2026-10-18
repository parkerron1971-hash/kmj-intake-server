---
title: Discussions and projects (server) - the class answers together with Amens, the teacher stars and hides, a starred answer on the TV; projects in steps across weeks
date: 2026-10-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "...discussions, projects, etc... share with me on how that looks" - then "I''m happy with it. build it" for the approved Class Schedule design (step 3 of 4)'
status: shipped
prs: [kmj-intake-server#TBD]
migrations: [supabase/APPLY-2026-10-18-academy-discussions.sql (applied)]
left_undone:
  - "The Schedule tab's discussion and project sheets, students answering and saying Amen, and the presenter's Show on the TV are the solutionist-studio PR that follows"
  - "The online live stage shows slides, not the TV's answer; in-room TV first"
  - "Uploads, Chief drafting the schedule, step 4 (the website)"
decisions:
  - "Kevin's pick: discussion answers are seen by the whole class (by first name); the teacher can hide any"
  - "Discussions don't count toward finishing unless the teacher switches it on; a project's steps count, the project row itself is never work"
  - "A discussion closes due_days after its week opens; late answers are refused with a plain sentence"
  - "A project step is ordinary homework with project_id, so its week, due date and saving are the ones homework already has"
  - "On the TV an answer shows with a label (the week), never a name; '{}' takes it down; old presenter calls keep working"
related: [2026-10-18-class-schedule.md, 2026-10-17-class-live-room.md]
---
- `supabase/APPLY-2026-10-18-academy-discussions.sql`: kinds `discussion` and
  `project`, `project_id` and its guard, answer ids/hidden/starred, Amens,
  `academy_item_answers`, the student's schedule and saving recreated,
  `academy_amen`, `academy_item_moderate`, the TV answer.
- `academy_calendar.py`: a discussion reads "Discussion closes: …".
- `__tests__/test_class_discussions.py` (6); the database half rehearsed on
  production in a rolled-back transaction (see docs/MIGRATIONS.md).
