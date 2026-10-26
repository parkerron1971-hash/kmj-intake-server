---
title: A task can be handed to one person, and lands in their week
date: 2026-10-26
agent: Claude Code (Claude Opus 5.5)
asked: "continue (after: yes go with your picks and build it… keep building after you show me)"
status: in progress
prs: [kmj-intake-server (this PR), solutionist-studio (Tasks, Hand to)]
migrations: [supabase/APPLY-2026-10-26-task-hand-off.sql]
left_undone: ["Chief handing a task to someone by name (create_task has no assignee yet)", "handing tasks over for businesses that aren't churches (it rides Church Areas for now)", "switch on with CHURCH_AREAS=on (Thursday)"]
decisions: ["one person per task: tasks.assigned_to is the login's user id, like sessions.assigned_to", "it hands work over and grants nothing: who can read and change tasks is unchanged", "names, never whole addresses, in the Hand to list (the logins list is the admins')", "a task in the morning note reads 'Your task: <title>'"]
related: [2026-10-26-who-sees-what.md, 2026-10-26-who-sees-what-phone.md]
---
Kevin's ask was that the load is shared: teams have their part, and the system is the one
room where it all meets. My week (#1595) shows what's handed to a person, but a task couldn't
be handed to anyone. Now `tasks.assigned_to` holds the login a task was handed to.
`church_my_week.build` lists the caller's open handed tasks, late first ("A task handed to you ·
2 days late"), so they lead My week, the person's Home and the morning note.
`GET /church/my-week/people` lists who a task can be handed to (the owner and each active
office login, by their own name from the church's list; else the part of the email before
the @), for anyone who can change tasks. The app's Tasks page gets a Hand to picker in its own PR.
