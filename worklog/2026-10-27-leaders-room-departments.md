---
title: Department leaders join the All group leaders chat
date: 2026-10-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-27, after approving the Love City leadership plan (artifact D68g78Hu7ULPXpwgkg1v5Y): "this is good. let''s build"'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "The chat keeps its name, All group leaders, though department leaders are in it now"
decisions:
  - "Who's in: leaders of active groups, plus everyone holding an active role that leads: a job in LEADER_JOBS (senior, pastoral, ministry, team, welcome, teach) or a role another role answers to (the Intercessor leader, the Deacons). A role that leads nothing stays out: the Intercessors, the Care team, the kids workers, the office"
  - "Read live as before: nobody is added by hand, and a role that stops leading (nobody answers to it any more) leaves the room"
  - "The Lead page's door and Connect's door follow the room, so the welcome lead and the worship pastor now see them"
related: [2026-10-20-all-group-leaders-room.md, 2026-10-17-role-library.md]
---
`member_portal_messaging.leaders_room_people` widened from group leaders and
pastoral roles to every role that leads (`LEADER_JOBS`, or one another role
answers to through `church_role_defs.reports_to`). The room's page says
"Everyone who leads a group or a ministry at {church}, and its pastors".
This is the plan's "department leaders in the leaders chat"; the Monday
leaders note (a separate PR) emails the same people.

Check: `__tests__/test_member_leaders_room.py` now pins the welcome lead in,
an Intercessor leader in only while the Intercessors answer to her, an
intercessor and a kids worker out, and the Lead page door for a department
leader but not for a role that leads nothing.
