---
title: My week shows how a login's week goes, from the duties it holds
date: 2026-11-02
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-01: "a way for some sort of video or training or something that can be given so they know how there week will go so they can see what they suppose to do with no problem." Approved: the band and a narrated walkthrough on My week (docs/CHURCH_DUTIES.md step 7)'
status: in review
prs: [kmj-intake-server (this PR), solutionist-studio (How your week goes)]
migrations: []
left_undone:
  - "The walkthrough and the band are the app's (solutionist-studio PR, How your week goes)"
  - "The events duty opens the events page: a church's Services & Events room has its own module id, so no fixed door reaches its sign-ups"
  - "serve_schedule opens Who serves when, which shows only where Sunday Planning (SUNDAY_PLANNING) is on"
  - "A scheduled announcement doesn't make the weekly text done until it goes"
decisions:
  - "`rhythm` is attached in the route (own week and See as), not in build(): church_morning builds every login's week each morning and needs none of it"
  - "Days: Monday to Sunday, then Once a month (anything monthly, and first Monday), then Any day (as needed); only days with something on them; a duty on two days is on both; Tue, monthly is never every Tuesday"
  - "Today is the church's day on the clock My week already reads (chief_assignments._tz_for); the first Monday is the monthly report's today; a weekday-once-a-month duty is never today (which week isn't said)"
  - "done only from reads the jobs keep: the leaders note's last send this week (its own clock), last month's report row with a send_id, an sms_broadcast event since Monday that reached someone. Everything else leaves done out"
  - "A done read that fails leaves that duty's done out; a duties read that fails leaves rhythm out. My week is never a 503 for the rhythm"
  - "The owner and Admins: every_job and every duty, money ones too, without a read"
  - "See as: the seen login's rhythm; the Executive Pastor over the lanes sees only the jobs in her own areas (rhythm_within, within's rule)"
related: [2026-11-01-church-duties.md, 2026-11-02-exec-pastor-monthly-report.md, 2026-11-02-exec-pastor-oversight.md, 2026-10-27-church-leaders-note.md]
---
`church_my_week.py`: a DOOR per duty (operate/grow/build page ids from the
app's churchStructure), `placed()` (a catalog day to its group),
`rhythm()`, `_done()` and `rhythm_within()`; the route adds `rhythm`.
`docs/CHURCH_DUTIES.md` step 7a says the shape. Tests:
`__tests__/test_church_week_rhythm.py` (19: a door for every duty, by day,
today on Chicago's clock, the first Monday, the three done reads, failed
reads, See as, not a church) and one in `test_church_team_week.py` (the
overseer's view stays in her areas); the My week, team week, leader tasks,
monthly report, duties, morning and leaders note suites still pass.
