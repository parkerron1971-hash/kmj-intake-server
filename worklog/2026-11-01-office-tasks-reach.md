---
title: A task handed to an office login reaches them, and a late one goes to the Executive Pastor
date: 2026-11-01
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-01: "go through each admin that is connected and make sure that there access point have everything that is connected to there role" … "Jessica will be over the admin team as well" … "every area that is block setup or partly. lets make sure we build"'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: [supabase/APPLY-2026-11-01-office-task-told.sql (applied 2026-11-01)]
left_undone:
  - "Chief's create_task can't hand a task to a person yet (B9 Later in the office checkup artifact)"
  - "The admins' own church roles (Leaders & roles), so the chain of who answers to whom covers them: with the duties layer"
decisions:
  - "Told once by email (the sign-in address, from the church, naming who handed it) and a push to operate:tasks; the email holds the claim, the push never does (most phones aren't subscribed yet)"
  - "Handed to yourself, or to a login that has left: marked told, nothing sent"
  - "Late, in the church's morning (church_leader_tasks.LATE_FROM–LATE_UNTIL): once, to whoever handed it and to the Executive Pastor (a login whose record holds executive_pastor, by key or catalog key); no Executive Pastor, or her own task: the owner. One email per person told, deduped."
  - "Every task already handed to a login is backfilled as told by the migration, so nothing floods anyone's inbox on the first run"
  - "handed_by now stamps hand-offs to a login too (the trigger was leader-only); a new login or due date clears the stamps (tasks_seat_told_reset)"
  - "Same switch as My tasks for leaders (CHURCH_LEADER_TASKS, on in Railway on both services); its own hourly job, church_office_tasks_sweep"
related: [2026-10-27-leader-tasks.md, 2026-10-26-task-hand-off.md]
---
`church_office_tasks.py` (new), scheduled in `kmj_intake_automation.py`
next to the leader tasks sweep. It reuses `church_leader_tasks`' email path,
names (`handers`), sign-in emails (`hander_email`), the church's clock and
claims. Tests: `__tests__/test_church_office_tasks.py` (13), plus the PGlite
check `__tests__/office_task_told_db.mjs` (17 checks). The leader tasks,
My week and scheduler suites still pass (310).
