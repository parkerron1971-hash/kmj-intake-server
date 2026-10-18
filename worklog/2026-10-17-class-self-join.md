---
title: Free classes people join themselves (server) - a join form on the class page, the class link by email only, next tracks joined from the classroom
date: 2026-10-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "start" (phase 4b of the approved "One deck, every room" design: free classes people can join themselves)'
status: shipped
prs: [kmj-intake-server#1483]
migrations: [supabase/APPLY-2026-10-17-academy-self-join.sql (applied)]
left_undone:
  - "Course Studio's open/closed switch, the covers' 'People join themselves' and the classroom's Join button are the solutionist-studio PR that follows"
  - "Members signed in to the church app joining with one tap (no email) belongs to phase 5, the church layer"
decisions:
  - "Free and published is open by default (the approved design's 'People join themselves'); the owner can close a class to only the people they add"
  - "A class with a product is joined by paying, even before its checkout link exists"
  - "The class link goes to the address typed and never onto the page; the page reads the same whether the person was new, already in, or taken off"
  - "Someone the owner took off gets no link, and the owner is told they asked again"
  - "Limits like member sign-in: per network, then per business and address a one-minute cooldown and six a day, keyed on a digest of the address"
  - "A student joins another open track of their program from the classroom with their own link as the proof: nothing to type, no email"
related: [2026-10-17-class-programs.md, 2026-10-17-class-student-side.md]
---
- `academy_join.py`: `POST /academy/<id>/join` and `/course/<id>/join` (a
  business site and a standalone academy), the form (`join_box`, shared with
  the class page), the answers in the academy pages' own look, `enroll()`
  (lead_identity's one rule, then `academy_public_join`), and after the page
  has answered the email (`email_layout.render_html` with a new optional
  button) and the owner's notice.
- `public_site._serve_academy`: the form in place of "Get in touch" on a
  free, open class; "Next live class: Thursday, October 22 at 7 PM" in the
  business's time zone; a "Free" tag on the catalog.
- `rate_limit`: `class_join_ip`, `class_join_email_minute`, `class_join_email_day`.
- `__tests__/test_academy_join.py` (29); the database half rehearsed on
  production in a rolled-back transaction (see docs/MIGRATIONS.md).
