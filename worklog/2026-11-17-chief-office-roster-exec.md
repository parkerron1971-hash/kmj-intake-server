---
title: Chief knows everyone in the office, and the Executive Pastor asks Chief for her team like the owner
date: 2026-11-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-17: "make sure the chief is aware of everyones duties and job description responsibility and also make sure Jessica has ability to request things from chief in regards to admins etc like I would as well"; then "I approve your ideas. make this happen" (one-on-ones from each admin''s week)'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "No Chief verb saves the monthly report's notes or sends it: both stay on its page (Office, Leaders, Monthly report)"
  - "The roster's descriptions show only words the owner wrote; a description Jessica or an admin writes shows as 'written (job_of reads it)' until the owner saves it. Kevin can widen this to the admins' words if he wants"
  - "The live prompt was not run against the model (no live evals: they bill production); handlers, gates, the roster text and its cache segment are tested"
  - "Moving a duty to an owner's or an admin's login by the owner is unchanged: the 2026-11-14 gap (a moved duty doesn't ask whether the login's person is a pastor) still holds for the owner and admins; the Executive Pastor's moves do ask (church_over)"
decisions:
  - "THE OFFICE goes in the per-business cached segment, after the church's menu (chief_prompt), read with the turn's context gather (chief_of_staff) and kept two minutes a replica; a duty move (church_duties._forget) or a description write (church_job_descriptions._written) drops it. Shown to the owner, admins and Managers; never a Member or Viewer"
  - "Whose words: a written title and the description's first line only when the owner wrote them in their own words (church_job_descriptions.mine for the owner) and nothing is instruction-shaped; anyone else's are only job_of's (which taints the turn). The owner's words already bind every login"
  - "CHIEF_BRIEF=lean shortens the manual, not the church's data: the roster is the same either way, and it carries the whose-job rule so lean can't move it to the lookup"
  - "Size: about 3,100 characters (~750 tokens, four a token) for Love City's office with five descriptions; caps: 12 logins named, 16 labels each, 6,000 characters (then the descriptions go, then the labels shorten)"
  - "One whose-job rule: an office duty, THE OFFICE; other work or someone outside the office, whose_job; someone's whole job, job_of (roster, manual, jobs line, whose_job's tool text, the assignments block)"
  - "The Executive Pastor's move rule (church_duties.overseer_refusal): not money, not her own oversight (monthly_report, oversee_lanes), and everyone who does it now and everyone it goes to (the lanes' defaults for []) is her or a Manager she is over (church_over: never the owner, an Admin, or a Manager whose person is a pastor or an elder). Undo is a move back under the same rule. changed_by is her. The PUT and the undo route ask the same function; another Manager still gets the old 404"
  - "move_duty and undo_duty moved from chief_areas.OWNERS to every login's verbs; the handler decides, so a lane login hears the same 'owner's or an admin's' words"
  - "Two new mid-turn reads, chief_only and sensitive: team_week (church_team_week.team behind the Office team page's gates) and monthly_report_draft (church_monthly_report.build behind _access); both on the tool loop's 12,000 list. The report's notes are fenced and raise the turn's taint (who wrote them isn't kept)"
  - "Her jobs line lists her own duties (not all 43 she covers) and what she can ask for: one_on_one for a one-on-one or the huddle, people_under, assignments_of, give_assignment and take-back, move_duty, undo_duty, job descriptions, team_week, monthly_report_draft; never 'ask the owner'. The one-on-one agenda rule (wins, stuck and how long, late, next, this week's jobs not done; nothing recorded) is in the roster and the manual"
related: [2026-11-02-chief-duties.md, 2026-11-02-exec-pastor-oversight.md, 2026-11-02-exec-pastor-monthly-report.md, 2026-11-12-church-job-descriptions.md, 2026-11-12-church-assignments.md, 2026-11-14-church-assignment-gaps.md]
---
Before this, Chief's prompt carried only the asker's own duty labels; everyone else's job was behind
three tools Chief had to think to call, and the owner and admins got nothing. Now every office turn
at a church carries THE OFFICE (`chief_office.py`): each office person's title, lane, who they
answer to, their duties and a line of their job, plus the one rule for "whose job is this?".

Jessica (the Executive Pastor) couldn't move a duty through Chief or on the page, and had no Chief
read for her team's week or the monthly report. Now `move_duty`/`undo_duty` work for her team
(`church_duties.overseer_refusal`, the same rule on the PUT), and `team_week` and
`monthly_report_draft` read what her pages show. Her jobs line tells Chief what to offer her,
including getting ready for each admin's one-on-one from their week.

Checked before building: the duties, oversight, monthly report, job descriptions and assignments
logs listed in `related`. The frontend checkout here isn't a git repo, so its worklog wasn't read.
Tests: `__tests__/test_chief_office.py` (27); the duties, areas, tool loop, prompt and cache suites.
