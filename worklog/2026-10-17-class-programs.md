---
title: Programs (server) - a series of classes with a finish line, every track scheduled in one go, one certificate at the end
date: 2026-10-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "let''s start phase 4" (phase 4 of the approved "One deck, every room" design: boards 17-19, shelf and programs)'
status: shipped
prs: [kmj-intake-server#1480]
migrations: [supabase/APPLY-2026-10-17-academy-programs.sql (applied)]
left_undone:
  - "The shelf and program pages (Course Studio and the church's Classes) are the solutionist-studio PR that follows"
  - "Free classes people join themselves (the public class page) is the next part of phase 4"
decisions:
  - "A class belongs to one program at most; the order and each track's teacher live on the track"
  - "The page works out the dates (weekly, weeks skipped) and the server checks every lesson is the program's and keeps any class already coming"
  - "A program certificate is issued when the last track is finished and is valid while every track stays finished, like a class certificate"
  - "Teachers' names are the names people know them by, kept on the track; giving a teacher access to a class is still an email on its teaching team"
related: [2026-10-17-class-student-side.md, 2026-10-17-certificate-trigger-fix.md]
---
Database only; Course Studio and the classroom call these directly.

- `academy_programs`, `academy_program_courses` (+ same-business guard, RLS
  through definer helpers `academy_program_business`, `academy_program_teaches`,
  `academy_owns_business`).
- `academy_program_schedule(program, plan, duration, mode, capacity, finish_at)`
  calls `academy_schedule_live` for each planned lesson.
- `academy_program_certificates` + trigger; `academy_new_certificate_code`
  avoids both tables; `academy_certificate_check` returns `kind` and, for a
  program, its tracks and finish title.
- `academy_classroom.program` via `academy_classroom_program`; the class's
  teacher is its track's teacher when it has one.
- `account_lifecycle.py`: `academy_programs` is exported with the business
  and skipped on import (its tracks are keyed by the original course ids;
  the shelf offers the program again from the classes' series names).
