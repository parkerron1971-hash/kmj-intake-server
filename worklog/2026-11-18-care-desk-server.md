---
title: Prayer & care as a care desk, server half (names and roles on hand-offs, pastor-only crisis requests, lock with password)
date: 2026-11-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "not sure if you are clear on the fact that i like the prayer mock and want that built", with "yes page should and require a password and no work has been done but that should be custom to settings because others might like something else. help request should be align logins for now ... build it"'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: [supabase/APPLY-2026-11-18-care-lock.sql (not applied)]
left_undone:
  - "Frontend: the care desk itself (solutionist-studio worklog 2026-11-18-care-desk.md) must merge BEFORE this PR: from this PR the inbox asks for the password by default, and today's PrivateCarePanel can't answer it"
  - "Help to the treasurer (the pastor approves, the treasurer pays the provider and never sees the name or story) is church_help.py's, a separate PR: worklog 2026-11-18-help-treasurer-pays.md"
  - "Nobody waits for office logins: a heads-up when a request is handed to a login, a due time and \"you'll hear if it waits a day\" (needs columns; the prayer team already has all three)"
decisions:
  - "Hand-off list: each login's person (business_users.name, else its member record) and the titles of the roles that person holds; flags pastor (senior or pastoral job), care (People & Care lane, care job or care_need), office, treasurer (Treasurer lane or a treasurer role)"
  - "A request that needs a pastor (church_prayer.needs_pastor) is handed only to a login whose person holds a pastor role; the server refuses anyone else (400). Before this, any login could be picked"
  - "The teammate who has a request may give it back (assigned_to null on their own request); handing to anyone else stays the owner's (or the keeper's)"
  - "The owner may hand a shared, unprayed prayer to a different member of the prayer team (church_prayer.office_hand): due in a day, late steps start over. Never one kept with the pastors or one that needs a pastor (the database trigger refuses those too)"
  - "The lock: ministry_care_settings, default 10 quiet minutes and the password asked; a failed read is the default (locked). With the password on, every route that reads or changes a request needs a care proof (ledger_unlock scope care, bound to the church), which lasts the church's quiet minutes (an hour when it never locks by itself) and is renewed while someone works (POST .../unlock/renew). Counts and the settings read need no proof: no names, no words, no ids"
  - "Only the owner (or the People & care keeper) changes the lock, and only from behind it"
  - "Notes carry author_name; the office sees the prayer team's leader_due_at and leader_late_level"
related: [2026-11-01-care-inbox-people-care.md, 2026-10-27-church-key-doors-care.md, 2026-10-15-church-care-counts.md]
---
Kevin approved the care desk mock (artifact BJhieg2rPsVoEzqj2qCGmw) and said to
build it. This is the server half. `private_care.py` grew a richer `_team`, the
pastor-only guard, give-back, `counts`, `lane_of` (the same lanes the app draws)
and the lock (`lock_settings`, `unlock_ttl`, `require_open`, `save_lock_settings`).
`church_prayer.py` grew `office_people` and `office_hand`, and `office_fields`
now passes the due time and late level. `ledger_unlock.py` has a fourth scope,
`care`, bound to one church like access and danger, with a lifetime the caller
names (one minute to an hour). The routes are in `intake_endpoint.py`: new GET
`/counts`, GET/PUT `/settings`, POST `/unlock/renew`, and the lock in front of
list, update and notes. Tests: `__tests__/test_care_desk.py` (29); the older care
tests run as a church without the lock, since they pin who sees what.
