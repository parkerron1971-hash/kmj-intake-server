---
title: Every group has a leader, part 2 — who a group answers to reaches the chain; the leaders map on for every church (M-8)
date: 2026-11-28
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin said GO on mission M-8: answers to can be a specific person, with the role as the fallback; YES, switch the leaders map (CHURCH_MAP) on for every church as part of this, check nothing breaks at the other church first"
status: waiting on Kevin
prs: [kmj-intake-server#2121]
migrations: []
left_undone:
  - "groups.answers_to_contact_id comes from part 1's file (#2120, supabase/APPLY-2026-11-28-group-leads.sql); until it is applied the map reads no group links and nothing changes"
  - "CHURCH_MAP now defaults to on in code: it opens for every church when this merges. Rollback: set CHURCH_MAP=owner on BOTH Railway services"
decisions:
  - "Checked first, read-only, against production with CHURCH_MAP=on in memory: the map, its view, the role library, church_over and its groups all load at all three churches with role settings; the two other than Love City have no departments and no answers-to links, so their chains are today's (test_church_three_today pins open-and-empty as today)"
  - "A group's item climbs to the person the group answers to first (while they hold an active role), then on up from them; someone without a role is passed over"
  - "church_over: that person is over the group's leaders; leader tasks: a group leader with no role goes to them"
  - "A failed read of the groups' links is {} (logged), never a failed map: a groups blip must not take down who-does-what"
  - "The default flips in code (church_map.mode), not only on Railway, so both services follow at merge; tests written before keep owner through conftest, since their fakes predate the map's tables"
  - "Leaders & roles carries each holder's person (answers_to_contact_id, answers_to_name) once the map is ready, for FE #1735"
related: [2026-11-28-m8-group-leads.md, 2026-11-04-church-map-chain.md]
---
Part 2 of M-8. `church_map`: `Map.group_links` (groups.answers_to_contact_id,
probed per church), `chain_for` step 0, default on. `church_over._direct`,
`church_leader_tasks.group_department`, `church_roles.library` holders.
`test_church_map_group_person.py` (8). The desk's wide suite (church, chief
church, map, Lead tab, groups, Sunday, member asks): 4513 passed.
