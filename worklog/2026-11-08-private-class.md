---
title: A private class (server) - on no public page, offered to nobody, read by no other office login, not counted in attendance
date: 2026-11-08
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "i will only be doing this with her so i believe private access" (eight weeks of assignments for a leader he is considering ordaining)'
status: shipped
prs: [kmj-intake-server#1770]
migrations: [supabase/APPLY-2026-11-08-academy-private-class.sql (applied)]
left_undone:
  - "Chief has no verb to make a class private; it's set in Course setup"
  - "A private class put in a program would still show on that program's road to its other students; nothing stops it being added to one"
decisions:
  - "A new column, not a stricter self_join: 'only people you add' keeps a public page on purpose (it asks people to get in touch), and other churches' closed classes shouldn't vanish from their sites"
  - "Default off, per class, so nothing changes for anyone until an owner chooses it; that's why it didn't wait for a Thursday"
  - "A private night is marked counted with no occasion, the way a non-church's is, because Services & Events would show the office its name and who came"
  - "A private class is never a milestone; the office drafts those"
  - "An office login who is a named teacher of the class keeps its roster; enrollments have no teacher policy of their own"
related: [2026-10-17-class-self-join.md, 2026-10-18-class-nights-counted.md, 2026-10-18-church-member-classes.md]
---
"Only people you add" closes the sign-up form and nothing else. The class's
title, description and lesson titles stayed on the public website, and any
office login could read the class, its lessons, its homework items and its
enrollment rows, which hold the student's class link and the teacher's notes.
The July seat migration's `tenant_member_read` is why.

`academy_courses.private` closes the rest: `academy_course_open`, the seat
policies on all four tables (through the definer helper
`academy_course_private`, RLS_MODEL rule 2), the website's class list and class
page, the site's Courses door, the member app's Classes tab (its one student
still gets it, `in_a_class`), class-night occasions, milestones, the role
library's class picker, and what Chief says on publishing.

`__tests__/academy_private_db.mjs` signs in as the owner, an office login, a
named teacher and another church's owner on a real Postgres and reads through
RLS. Check it before changing who reads a class.
