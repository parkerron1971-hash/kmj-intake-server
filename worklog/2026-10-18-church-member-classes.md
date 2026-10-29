---
title: Classes in the church member app - Connect > Classes beside Groups, the next class night, the program road, one-tap join
date: 2026-10-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "ok. let''s continue with those not done yet." (phase 5, the church layer, of the approved "One deck, every room" class design; his 10/17 pick: classes in the member app, yes)'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: [supabase/APPLY-2026-10-18-academy-member-classes.sql (applied)]
left_undone:
  - "Class-night reminders as member notifications and email: the next PR"
  - "A live class doesn't count toward church attendance (the design's recap line): attendance is per Sunday/occasion, and counting class nights would change who reads as drifting; Kevin's call"
  - "Members' Home doesn't lead with class night yet; Connect > Classes does"
decisions:
  - "One read (academy_member_classes, service-only) with the member's own contact id from the member app's session: the member app doesn't sign people in as Supabase users"
  - "Join is academy_public_join as it is (the class page's step): only open, free, published classes; one they were taken off says the office can add them back"
  - "The tab shows only when the church has a published class (kept a minute), or in the owner's preview, so no church gets an empty tab"
  - "A program's open track is joined on the program's road, not repeated in Classes you can join"
  - "The owner's notice says they joined from the church app; the class link also goes to their email when they signed in by email"
  - "The owner's preview shows a sample class, road and class to join, tagged, with where to publish one"
related: [2026-10-17-class-self-join.md, 2026-10-18-class-schedule.md]
---
- `member_portal_classes.py`: `classes_on` (tab), `classes_for`, `join_class`
  + POST `/my/classes/join`, `after_join`, `render_classes` (next class
  night, road, your classes, classes you can join), `when_text`.
- `member_portal.py`: `/my/classes`, and the tab flag for Connect's pages;
  `member_portal_church.py`: `connect_tabs` (Groups, Classes, Messages),
  words, `/my/classes` allowed back; `academy_join.tell_owner(came_from=)`.
- `member_app_samples.py`: `classes()` + where; `member_app_ui.py`: the
  `.mb-cnext`, `.mb-road`, `.mb-cls`, `.mb-copen` styles (the app's tokens).
- `kmj_intake_automation.py`: the router, before public_site's.
- `supabase/APPLY-2026-10-18-academy-member-classes.sql` (+ MIGRATIONS):
  rehearsed with a rollback probe, applied, verified.
- `__tests__/test_member_portal_classes.py` (14). Rendered through
  `member_portal.serve` with made-up data at 390 (black and white bases,
  live now, joined, empty, owner preview) and 1366: no sideways scroll.
