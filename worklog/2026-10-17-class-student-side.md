---
title: The student's side of a class (server) - their own notes and ticks, the class slides without teacher notes, the brand, and a certificate anyone can check
date: 2026-10-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, after the live class room went live: "yes start phase 3" (phase 3 of the approved "One deck, every room" design: boards 12-16, the student side)'
status: shipped
prs: [kmj-intake-server#1478]
migrations: [supabase/APPLY-2026-10-17-academy-student-side.sql (applied)]
left_undone:
  - "The classroom itself (course home, lesson on its slides, notes, memory verse practice, talk it over, this week, certificate page) is the solutionist-studio PR that follows"
  - "A program's one certificate across several courses (The Making's four tracks) and the next-steps road belong to the shelf and programs phase"
  - "Classes in the member app, reminders and notifications belong to the church phase"
decisions:
  - "A student's notes, thoughts and ticks are theirs alone: server-only table, read and written through their class link; the teaching team does not see them"
  - "Thoughts and ticks are keyed by a short fingerprint of the question or item, so an edited item starts unticked instead of moving to another line"
  - "A certificate code is issued once, the first time a course is finished, and kept if the student goes back over a lesson and finishes again; while unfinished the check says not valid and gives no name"
  - "Students get the teacher's saved deck with every note stripped; with no saved deck the classroom builds the slides from the lesson's words, as the Slides tab does"
related: [2026-10-17-class-live-room.md, 2026-10-17-class-slides.md]
---
Database only; the classroom calls these straight from the browser with the
student's class link (no Python change).

- `academy_lesson_journal` + `academy_save_journal(token, lesson, notes?, thoughts?, ticks?)`:
  any part left out is kept; sizes and key shapes checked; the lesson must be
  open to this student.
- `academy_lesson_slides(token, lesson)`: `{saved, revision, slides}` with notes
  stripped, or `{saved:false}`.
- Certificates: `academy_enrollments.certificate_code` (8 letters and digits, no
  I/O/0/1), a trigger issues it on finishing, existing finished enrollments
  backfilled (there were none); `academy_certificate_check(code)` for anyone.
- `academy_classroom` adds the course id, cover, teacher name, business type,
  brand kit, enrollment status and certificate, and the journal;
  `academy_student_live` adds `attended_minutes`; `academy_my_school` adds each
  class's brand, status and certificate.
