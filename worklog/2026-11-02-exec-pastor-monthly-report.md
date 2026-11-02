---
title: The Executive Pastor gathers the monthly report from the admin lanes, with nothing about money
date: 2026-11-02
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-01: "gathering the reports from admin should be Jessica", and the monthly report has "nothing about money" (docs/CHURCH_DUTIES.md step 6)'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: [supabase/APPLY-2026-11-02-church-monthly-report.sql (applied 2026-11-02)]
left_undone:
  - "Apply supabase/APPLY-2026-11-02-church-monthly-report.sql (until then the page and the send are a 503 and My week leaves the line out)"
  - "FE: the monthly report page (GET/PUT/send) and its door (My week's line opens operate:monthly-report, a leaf the app doesn't have yet)"
  - "Set CHURCH_MONTHLY_REPORT on a Thursday (owner, the default, is Love City)"
decisions:
  - "Numbers only from tables the app already keeps (church_board_items + tasks, church_space_bookings, church_leader_roles, attendance + headcounts through church_reports' occasions and first-visit rule, sms_messages and events for reach as church_reads counts it, ministry_care_requests, church_reads.group_drift, worship_services + serve_* as sunday_planning reads them, group_members for teams, sermons, social_publications). No money table is read, and the payload and email carry no money key (asserted)"
  - "A number the church doesn't keep (no rooms, no Sunday teams, no connected accounts, no sermons, no meeting tasks, no groups) leaves its line out; a failed read leaves it out and is named in the section's `missing`"
  - "Prayer & care counts follow the Reports pack's rule: People & care's (a login whose areas leave it out doesn't get them). Drifting is today's, so only this month's and last month's reports carry it"
  - "Notes and the last send live in church_monthly_reports (business_id, month), server-only; exported with the business, skipped on import (a restore must not claim a report went out)"
  - "The send goes to the owner's sign-in email, from the church, through church_leaders_note.deliver, reply-to the sender; claimed on send_id (two presses send once; one in flight under 10 minutes is a 409), put back when the email fails; a resend needs force"
  - "Review: every write after the email is checked (twice). A send that went but wasn't noted answers recorded false with a warning and leaves the month sending; a sending row past its 10-minute hold goes again only with force, so the pastor never gets it twice unasked; a failed email whose claim can't be let go says when to try again"
  - "My week shows last month's report from this month's first Monday (due today, then late) to a Manager who does monthly_report, until it's sent; never to the owner or admins (they hold every duty; the owner is who it goes to); a read that fails leaves the line out, never the week"
  - "Its own switch, CHURCH_MONTHLY_REPORT (off | owner | on; owner is the platform owner's own church), since PR 1's CHURCH_TEAM_ROLLUP isn't on main"
related: [2026-11-02-exec-pastor-oversight.md, 2026-11-01-church-duties.md, 2026-10-27-church-reports-pack.md, 2026-10-27-church-leaders-note.md]
---
`church_monthly_report.py` (new): the draft (GET), her notes (PUT) and the
send (POST /send) under /church/monthly-report, registered in
`kmj_intake_automation.py`; `church_my_week.build` gains the due line;
`rate_limit` gains `church_monthly_report_send`; `account_lifecycle` lists the
table. Tests: `__tests__/test_church_monthly_report.py` (24); the My week,
Reports pack, leaders note, duties, export/import, ownership sweep and ratchet
suites still pass.
