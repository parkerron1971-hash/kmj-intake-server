---
title: Church leaders step 2, PR B3b — people on drafts, the half-made mark, the pickers' choices, who changes a role's switches
date: 2026-11-05
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03: approved step 2 (design 4V41zJz1kEJGdeo4J9D2Ym, "Your two ideas"): launching with leaders who have not said yes, and switch changes for an Admin seat (decisions 2 and 3)'
status: in progress
prs: [kmj-intake-server#1726]
migrations: [supabase/APPLY-2026-11-05-church-map-step2.sql (applied 2026-11-03, B2)]
left_undone:
  - "B10: the gap line for a planned ask (asked into X at launch), once B9 gives the track's asks a shape"
  - "F1: RoleDetail's switch toggles (an admin's; the board yes the owner's) and LeadersRoles.tsx:119 off team_leader"
  - "F3: the department editor's pickers, from GET /church/map?with=choices"
decisions:
  - "A draft department names anyone among the church's people; its gaps say what each needs (leader_needs, overseer_needs) or that they were asked and haven't said yes (leader_asked, overseer_asked)"
  - "An active department also takes someone with an invited row on an active role with the switch (decision 2); going live checks the leader and overseer even when the request names neither"
  - "chain_for and team_head pass over any holder row that isn't active, whatever rows a caller hands in"
  - "unfinished_at is set only by the failure path and decides the retry alone: no ten-minute or same-login guess; a save to a draft by its id clears it; before step 2's file nothing is marked and nothing taken over"
  - "Switch refusals are 403s with words; a board yes sent as it reads isn't a change; POST /church/roles takes the same rule so no Manager makes a role with the board's yes"
  - "The switch seat rule holds at every church; a role PATCH naming a switch is logged as one change only where the map is open to the login and step 2's file is there; its fields a role part doesn't keep are written first, unlogged, as today"
related: [2026-11-05-church-step2-changes.md, 2026-11-05-church-step2-migration.md, 2026-11-04-church-step2-fixture.md]
---
`church_map.save_department` now lets a draft department name anyone among the church's people. An active
one, or a draft going live, takes a leader or overseer who holds a role with the switch or was asked into
one and hasn't said yes. `view()`'s gaps say what each person needs, and `_seat` passes over any row
not said yes to. At each test church, Youth's overseer swapped for someone asked leaves the late task and
follow-up going exactly where they go with the seat vacant.

`unfinished_at` replaces `_left_behind`'s guess. `GET /church/map?with=choices` returns the pickers'
choices, each with the department it already hangs from. A role's switches on `PATCH` and `POST
/church/roles` need an admin seat, and its board yes needs the owner. A switch save is logged as one
change the map's Undo puts back (`church_map_batch.save_role`). `church_follow_up.role_name` reads what a
role covers, not the `team_leader` key. Details are in docs/CHURCH_LEADERS_STEP2.md, "As built in B3b".
