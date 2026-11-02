---
title: Love City's office jobs are split into the real work each admin does
date: 2026-11-02
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-02: "yes fold it in, and track supplies in tasks", "churchsavvy is shapretta", "yes churchsavvy for worship team, announcements to shapretta. go". Earlier the same day: "laquesha is the right choice" for background checks, and drop "Ready for Sunday"'
status: in review
prs: ["kmj-intake-server (this PR)", "solutionist-studio (duty-split-ui)"]
migrations: []
left_undone:
  - "worship_team.PARTS_FROM_DUTIES still maps serve_schedule to the ChurchSavvy planner part, so Laquesha schedules in Planning until the Volunteers PR (another session) moves that part to production_schedule. worship_team.py and sunday_planning.py are that PR's and weren't touched here"
  - "The team page's due this week names days only, so a weekly job (building, prayer, youth, devotionals) isn't on it or in the Monday roll-up"
  - "The new duties gate nothing but background_checks: the front desk, decisions, the calendar, records and the rest are the week's jobs, their day, line and page"
decisions:
  - "47 duties (43 not money), each in one lane: Office & Leadership 13 (Naiya), People & Care 10 (Tiara), Sunday & Serving 8 (Laquesha, the volunteers), Media & Communications 10 (Shapretta, ChurchSavvy and production), Executive Pastor 2, Treasurer 4"
  - "Production has no church_duty_holders rows, so renaming and removing keys changed no one's job: care_board is gone (first_guests, care_visits, prayer, help_requests); sunday_ready was dropped before it shipped"
  - "Gated keys that changed lanes: rooms is the Office's alone (every room booked from one place; others send a room request), events Sunday & Serving's alone, churchsavvy_team and sunday_plan Media's alone (Laquesha is no longer a ChurchSavvy admin)"
  - "New key production_schedule (Media, Wed, opens Who serves when): the worship and production teams' half of Sunday's schedule; serve_schedule is the volunteer teams' half"
  - "devotionals moved from Media to People & Care (area People & care); supplies opens Tasks"
  - "The order of service (sunday_plan) opens Sundays, where ChurchSavvy's order is built; Planning's Order of service only shows it with each team's notes"
  - "Recording a background check, the reminders, and the check link and years: the owner, an Admin, or a Manager that holds background_checks; a Manager without it gets church_duties.refusal. Reading who's cleared: Kids & youth and People & care logins as before, and the duty's holders. A failed duties read is a 503; not a church is a 404 before any duty is read"
  - "weekly with no day said is its own group, Each week, after Sunday and before Once a month; its jobs are never today"
related: [2026-11-01-church-duties.md, 2026-11-02-week-rhythm.md, 2026-11-02-chief-duties.md, 2026-10-27-church-serving-hours.md]
---
`church_duties.CATALOG` holds the split; `church_my_week.DOOR` has a page for
each duty (each id checked against the app's churchStructure on
module-system); `placed()` knows "weekly". `church_serving._access` and
`_may_write` gate the checks on the duty. `docs/CHURCH_DUTIES.md`: the
catalog by lane, Love City's structure, "Where the lanes meet" (Sunday's
schedule split by team; the week's news list is Naiya's), the background
checks gate. Tests: `test_church_serving.py` (owner, admin, Laquesha, Tiara
reads but doesn't record, Jessica, a Manager no lane names, a moved duty, a
holder outside Serving's areas, a failed read, not a church),
`test_church_week_rhythm.py` (every door, Each week, Sunday & Serving's
week), and the duties, Chief duties, team week, media duties and My week
suites updated for the new catalog.
