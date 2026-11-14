---
title: Church assignments, the hourly sweeps take back a task an office seat handed a pastor or an elder (the Tasks screen's hand-made write)
date: 2026-11-14
agent: Claude Code (Claude Fable 5.2)
asked: "do the not built section because that allows for it to be setup before this pastor gets it"
status: in review
prs: [kmj-intake-server#1850]
migrations: []
left_undone:
  - "A hand-made browser write still lands. Until the next sweep, for up to an hour, the task can show on that person's My week or Lead tab. Nobody is told about it in that time. Closing the hour takes option 2 in docs/CHURCH_ASSIGNMENTS.md (the hand-off moves to a server route, then a small trigger), which needs the frontend."
  - "A task a pastor or an elder marks done inside that hour stays done and theirs: the sweeps read open tasks only."
  - "A task that was already told before this shipped is not looked at again. Only new, untold hand-offs are asked about."
  - "The sweeps run only where My tasks for leaders is on for the church (CHURCH_LEADER_TASKS). A church with that switch closed has no sweep, so nothing is taken back there."
  - "The login that handed it is told once. If that email fails, or the login has no address, it is not tried again: no column says a take-back was told, and none was added (no migration). The note on the task still says why."
  - "Frontend (solutionist-studio) not touched: the Tasks screen shows a taken-back task only as a task with the person's name in its title and why in its notes."
decisions:
  - "Option 3 from docs/CHURCH_ASSIGNMENTS.md, as written: church_office_tasks.tell_new and church_leader_tasks.tell_new ask church_over.may_hand(the login in tasks.handed_by, who it is handed to) before anything is claimed or told. One piece does it for both sweeps: church_leader_tasks.take_back."
  - "Taken back as the board leaves one: the task stays, the one column is cleared, the name goes in the title, the notes say why. Nothing else on the task changes and no told stamp is set."
  - "The notes do not say the board's NOT_HANDED sentence, because it starts 'The board named {name} for this' and no board named anyone here. They say a new one, church_over.TAKEN_BACK: 'This was handed to {name}, then taken back.' followed by the board's WHO_HANDS, word for word. NOT_HANDED and WHO_HANDS moved to church_over unchanged; church_board imports them, so cb.NOT_HANDED still reads."
  - "The login that handed it is told by the office sweep's own email and push (church_office_tasks.tell_taken_back): one email and one push for everything one sweep took back from them."
  - "The write that takes the task back is the claim (only while it is still that person's, still open, still untold). So two replicas take it back once, and it is taken back before the login is told, never the other way round."
  - "Never asked about: the owner's hand-offs, a task to yourself, a task no login handed (no handed_by). Only for a church, only while church_over.church_open is true; closed, nothing more is read."
  - "Who is a pastor unread: every hand-off that had to be asked about in that church is left exactly as it is for the next sweep, all of them, even ones already decided. The owner's are still told. Counted as rule_unread."
  - "The one person a task names is their login and their record together where they have both, as the board passes both. So the Executive Pastor's login can still hand the elder who answers to her on the map his task."
  - "A login that has left the church since it handed the task has no standing: its hand-off to a pastor is taken back, and nobody is emailed (it has no address)."
  - "Stats keep their shape and gain two each: office_taken_back and office_rule_unread, taken_back and rule_unread."
related: [2026-11-14-church-assignment-gaps.md, 2026-11-14-church-assignment-fixes.md, 2026-11-12-church-assignments.md]
---
The one path left around "admins can not give work to elders and pastors" was the Tasks screen's own write to
the database: no server code runs, so a request made by hand could hand a pastor or an elder a task. The hourly
sweeps that tell someone a task is theirs are where the server first sees it. Both now ask the rule first. A
hand-off the login may not make is taken back the way the board leaves one, nobody is told it is theirs, and the
login that handed it gets one email and one push saying why. Backend only, no migration, no frontend change.

Before building more here: docs/CHURCH_ASSIGNMENTS.md, "Every path that hands someone a task", and
`__tests__/test_church_task_sweep_rule.py`.
