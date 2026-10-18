---
title: The website's class list and class pages - when each class meets, how its lessons open, what it asks of you, week by week, and the program as one journey
date: 2026-10-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "where can i see the layout of how people can choose a class" - then "I''m happy with it. build it" for the approved Class Schedule design (step 4 of 4)'
status: shipped
prs: [kmj-intake-server#TBD]
migrations: []
left_undone:
  - "The member app's Classes (board 13 of the Class Experience canvas) is phase 5"
  - "Uploads by class link, and Chief drafting the schedule"
decisions:
  - "A church's list is called Classes; others keep The Academy (or the owner's own headline)"
  - "The old intro said 'learn at your own pace' for every class; it now says each one tells you when it meets and what it asks"
  - "Published schedule items only, titles only: details stay in the classroom"
  - "A program leads the list with its tracks' dates (from their live classes, else when each meets) and Start with its first track"
  - "Times are said on the class's own clock (opens_tz), else the business's"
related: [2026-10-18-class-discussions.md, 2026-10-17-class-self-join.md]
---
- `academy_site.py`: the words (`when_line`, `pace_line`, `involves_line`,
  `week_rows`, `track_name`) and the pieces (`facts_html`, `weeks_html`,
  `program_html`, `SITE_CSS`); pure, no database.
- `public_site._serve_academy`: the class page reads the schedule, live
  classes and its program, and shows facts, week by week, the track and the
  teacher; the list reads every class's schedule and live dates and the
  programs, and leads with the program.
- `__tests__/test_academy_site.py` (7), including 6 PM on the class's clock
  across daylight saving.
