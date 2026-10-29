---
title: My tasks for leaders — hand a task to a leader with no office login; it's on their Lead tab
date: 2026-10-27
agent: Claude Code (Claude Opus 5.5)
asked: "yes build my tasks for leaders"
status: shipped, switched off (platform owner only until a Thursday)
prs: [kmj-intake-server#1623, solutionist-studio#1391, kmj-intake-server#1625]
migrations: [supabase/APPLY-2026-10-27-leader-tasks.sql (APPLIED 2026-10-27, verified), supabase/APPLY-2026-10-27-task-handed-by.sql (APPLIED 2026-10-27, verified)]
left_undone: ["Switch-on (a Thursday): CHURCH_LEADER_TASKS=on on BOTH Railway services, kmj-intake-server and kmj-intake-worker (the sweep runs on the worker); What's New entry in that switch-on PR", "No member push: no member_push kind fits a task (didn't invent one)", "Chief handing a task to a leader by name (create_task has no assignee yet)"]
decisions: ["leaders = the All group leaders room (member_portal_messaging.leaders_room_people), by name and role title, never an email", "one person per task: tasks_handed_to_one (assigned_to is null or assigned_contact_id is null)", "the office still writes tasks straight to the database; the server learns of a hand-off from an hourly sweep that claims leader_told_at before sending and lets it go when the send fails", "handing a task to someone else clears leader_told_at and late_told_at (trigger), so the new leader is told; a new due date clears late_told_at", "late goes up once, 8 AM to noon on the church's clock, only after the leader was told on an earlier day, one email per leader to the nearest held role above them (church_roles.chain_above, vacant roles passed over)", "owner mode: the office side for the platform owner only; the Lead tab and the emails for the platform owner's own church (member_asks.platform_church)", "a done task is never told about; done twice is done once", "2026-10-27, who handed it: tasks.handed_by, stamped by the database (an office login's own write is who they are, whatever it passes; the server's write names who acted; it can only be cleared by hand). A late task of a leader with no one above them goes back to whoever handed it out (the owner at their sign-in email, a login at its seat's); the Lead tab and the hand-off email name them by the Hand to list's names, else 'the church office'. It is in the readiness probe, so before its migration the feature stays quiet"]
related: [2026-10-26-task-hand-off.md, 2026-10-27-church-board.md, 2026-10-27-church-leaders-note.md, 2026-10-20-all-group-leaders-room.md]
---
Kevin's leaders (elders, the youth pastor, team leaders) work from the member app, not an
office login, so a task like "the youth pastor plans the fall retreat by Nov 15" couldn't
reach them. Now `tasks.assigned_contact_id` hands a task to one of the church's people.

- `church_leader_tasks.py`: the switch (`CHURCH_LEADER_TASKS`, default owner), the leaders
  list, the leader's own tasks and Done, and `sweep_tick`.
- `GET /church/my-week/people` returns `leaders` (`contact_id`, `name`, `title`) while the
  switch is open to the login and the migration is in; otherwise no key, and the app shows no
  Leaders group.
- Lead tab: `GET /my/lead/tasks` (late first, then by due date: "2 days late", "Due Friday,
  Nov 13"; notes; "From the church office"; recently done folded) and
  `POST /my/lead/tasks/{id}/done` (Origin rules and rate limit as the other Lead POSTs; checked
  against business and contact; anything else is a 404). Tasks joins the section switcher with
  an open count; someone with only tasks gets the tab and opens on them.
- Sweep: hourly (`church_leader_tasks_sweep` in kmj_intake_automation, leader replica, worker).
  New hand-off: claim `leader_told_at`, email "{Church}: a task for you" (email_layout +
  Resend, the church's identity, key `leader-task-<task>-<contact>`, reply-to the church
  office's own email), let the claim go on failure; no email on file is told anyway. Late:
  claim `late_told_at`, email "{Leader} has a task past due" to the overseer's holders.
- Board & minutes: `make_tasks` hands a no-login member's follow-up by contact (switch open,
  migration in); a login stays `assigned_to`.
- Before the migration: every read fails quietly (no Leaders, no Tasks, sweep reads nothing).

Checks: `__tests__/test_church_leader_tasks.py` (34), PGlite `__tests__/leader_tasks_db.mjs` (20),
and the neighbours (my week, board, Lead tab, leaders room, leaders note, prayer, shepherding,
groups, serve tab, member portal, brand voice) plus the guards (access ratchet, ownership
sweep, router type hints, seat access). One look at the Lead tab's Tasks at 375px, black and
white bases: fit the width, buttons 50px; the late label read faint on white, now `--error`.
