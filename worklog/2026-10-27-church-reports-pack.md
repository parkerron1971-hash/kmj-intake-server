---
title: The Reports pack — the year's numbers a church is asked for, the annual report and a CSV (server)
date: 2026-10-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Church Office Prototypes (https://claude.ai/artifact/2vGqaUZUynRuiFVKuQEZWo), the "Reports pack" tab → Kevin, 2026-10-27: "lets go with your list" (the sixth and last); "make sure that the design is top tier"'
status: shipped, switched off (platform owner only until a Thursday)
prs: [kmj-intake-server (this PR), solutionist-studio (the page, its own PR)]
migrations: []
left_undone:
  - "Switch-on: CHURCH_REPORTS=on on Railway on a Thursday (it defaults to owner)"
  - "Groups are kept as they are today, so a past year's groups numbers are '—' (no history table). A yearly snapshot would fix that"
  - "Members on a past day are today's list rewound through logged status changes (events, contact_status_changed). A status changed outside the app's logged paths isn't in the log; a church whose people were imported after that day gets '—'"
  - "The register, help requests, check requests and paid sign-ups need their migrations applied; until then those numbers say '—' with the reason"
  - "Chief can't read the reports (no action handler)"
decisions:
  - "Lane: Build, under the Build item 'Love City leaves Subsplash (M-1)'"
  - "No migration. Every number comes from a table that already exists; a source that isn't there yet is '—' with its reason, never a zero"
  - "Who: the owner, admins and Office logins (church_areas; while Who sees what is off, every login, as before). Giving: the owner, admins and the church's active accountant (giving_records.require_finance's rule); anyone else gets {kept: true} and no giving table is read for them. Funerals follow the register: People & care's, never an Office login's"
  - "Attendance is services only (the app's rosterKind: its type, else its room's noun, else a Sunday), each service the headcount or the names if more (Attendance's own rule); services nobody counted are left out of the average"
  - "Giving reads paid gifts less refunds in the UTC year, the same read the year-end statements use, so the two agree. Giving against budget is the books' revenue budget through this month (this year) or the whole year (a past one)"
  - "Serving hours reuse church_serving's own readers and arithmetic (its suite pins them); a record that's gone takes its hours with it, as on the Serving page"
  - "Care is counts and sums: help amounts, needs and days, and Prayer & care requests by their day (not the backfill). No name, no story, no person's id leaves the server"
  - "Plain def handlers (FastAPI's worker threads, never the event loop); the seven sections read side by side on a small pool; the report is kept two minutes per church, year and view so the page, its print and its CSV read once"
related: [2026-10-27-church-register.md, 2026-10-27-church-serving-hours.md, 2026-10-27-church-help.md, 2026-10-27-church-checks.md, 2026-10-27-church-event-signups.md]
---
`church_reports.py` (new): the switch (`CHURCH_REPORTS` off | owner | on,
owner by default, like `church_keys.py`), who sees what, the seven sections
(people, Sunday, groups, serving, giving, care, events) and three routes under
`/church/reports` (status, the year's numbers, the CSV). Every number carries
the place it came from; the module docstring lists each source. Mounted in
`kmj_intake_automation.py` after the register; `.env.example` has the switch.

Checks:
- `__tests__/test_church_reports.py`: 25 tests (each number's arithmetic on a
  made-up church, members rewound to January 1, an import or a late start
  making it '—', the register's counts, guests once each, groups and a past
  year's '—', serving hours, giving less refunds with funds and the budget,
  giving kept from an Office login with no giving table read, funerals, help
  and families helped, no name or story anywhere, events and sign-ups,
  another church unreachable and never counted, reads past 1000 rows paged,
  missing sources and failed reads saying why, a section that breaks, a
  church's first year, the years, the CSV and its formula guard). Twenty-one
  rules broken on purpose: all twenty-one caught.
- The access ratchet, seat access, step-up routes, route type hints, and the
  register and serving suites pass.
