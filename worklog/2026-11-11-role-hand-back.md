---
title: A role or login taken away takes its work with it
date: 2026-11-11
agent: Claude Code (Claude Opus 5.5)
asked: "do a setup for all roles to be done that way so if a person is removed automatically the emails etc is as well with no problems"
status: in progress
prs: [kmj-intake-server#TBD]
migrations: []
left_undone:
  - "Church email per role (prayer@ follows the prayer leader) is scoped, not built: https://claude.ai/artifact/WYc8oLMAerrqDkCBa5Dq2t. Its role addresses must resolve live from church_leader_roles, the same rule as here."
  - "Work handed back goes to the office or Prayer & care, as before; it is not re-handed to the role's next holder on its own."
  - "Department leader/overseer seats (church_departments) name a person, not a role, so taking a role away doesn't clear them."
decisions:
  - "What came through a role is told apart by its key (leader_role), not its team: removing one team under the same key keeps the other team's work."
  - "Leader tasks go back to tasks.handed_by (the office's list when no one is named) once the person is out of the leaders room."
  - "A failed read is never 'nobody holds anything': the sweep passes over a church whose roles couldn't be read."
related: [2026-10-17-church-leaders.md, 2026-11-11-email-setup-namecheap.md]
---
Kevin is planning church email where role addresses (prayer@) follow whoever
holds the role. He asked that every role work that way, so removing a person
takes their access and work with them, "with no problems". Access was already
read live everywhere (Lead tab, lanes, money levels, messaging), but work
*handed* to a person stayed with them in four cases:

1. `remove_role` returned follow-ups and prayer only when the person held no
   other role. Removing an Intercessor leader who still led a team left
   private prayer requests on her Lead tab.
2. Open leader tasks (`tasks.assigned_contact_id`) never came back, even when
   the person no longer led anything and couldn't open the Lead tab.
3. The hand-back writes went unchecked and were counted as done.
4. Revoking an office login left its open tasks and owner-assigned care
   requests on a dead login. The revoke also returned ok on a failed write,
   and a failed login read skipped the rank check.

Built:
- `remove_role` now returns what came through the removed role, even while
  other roles remain. Each write is checked, and it reports
  `prayer_returned`, `tasks_returned` and `failed`.
- `church_follow_up._sweep_handed` runs every few minutes as a safety net:
  anything handed through a role its leader no longer holds goes back,
  however the role was lost.
- `church_leader_tasks.return_tasks` runs on removal and in the hourly sweep.
- `business_users_router.revoke` runs a checked revoke followed by
  `hand_back_login`.
- Tests are in test_church_follow_up.py (6 new), test_church_leader_tasks.py
  (4 new) and test_revoke_hands_back.py (6).
