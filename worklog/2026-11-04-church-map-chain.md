---
title: Church leaders map, PR 6 — the person chain (who a late item, a drifting family or a waiting prayer goes up to)
date: 2026-11-04
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03: take the leaders flow further, for every church that subscribes ("what i don''t want is what i build works for love city but is broken and messed up for other churches"); design 4V41zJz1kEJGdeo4J9D2Ym approved'
status: in review
prs: ["kmj-intake-server (this PR)"]
migrations: [supabase/APPLY-2026-11-04-church-map.sql (applied 2026-11-03 with PR 2; nothing new here)]
left_undone:
  - "CHURCH_MAP defaults to owner (Love City only). When it goes on, set it on BOTH Railway services (server and worker); nothing was set here"
  - "Love City's map is still empty in production, so its chain is today's until step 4 enters the department sheet (Marcus answering to Jessica, say)"
  - "choose's Serve sign-up with no team leader going to the team's department leader then overseer (spec table, church_follow_up row) was built in neither PR 4 nor PR 6; it needs its own PR"
  - "PR 7: settings take effect (money levels, pastor's yes, office overseers) and room asks go to the rooms duty; scenario needs 1 and 3"
decisions:
  - "chain_for's steps keep chain_above's shape: a role, a department step titled '<department> overseer|leader' with the qualifying role's job, or the answers-to person's role"
  - "Step 2 (the item's department's leader, then its overseer) applies only from the item's own person, and not when they oversee it, so nobody is sent back down"
  - "After a map step the walk continues from the role the person qualified through; step 4 is today's chain to the top, never re-mapped"
  - "pass_targets adds holders who answer to the leader as a person, still only on roles that take passed-on prayer"
  - "A group leader with no role: their group's department (leader, else overseer) before handed_by; a failed groups read skips that leader until the next sweep"
  - "A failed map read is the reader's failed read: the follow-up and prayer sweeps skip the church, tell_late returns, pass_targets is None"
related: [2026-11-04-church-map-fixture.md, 2026-11-04-church-map-core.md, 2026-11-04-church-map-switches.md, 2026-11-04-church-map-writes.md]
---
`church_map.chain_for` walks up from a person. It goes to their department's overseer first, then the
item's department's leader and then its overseer, then the person they answer to, and after that
today's `church_roles.chain_above`. Each person is named once and each department climbed once, so a
loop ends. Anyone who no longer holds a role with the right switch is passed over. The support duty is
never a step.

It is wired, only where `church_map.opened(biz)` returns a Map, into Shepherding's chain, the follow-up
sweep's one-day and three-day steps, the prayer late ladder and `pass_targets`, the shepherd signals'
told name and weekly climb, and leader tasks (the first step, plus a group leader's department). When
the map is closed or before the migration, today's call runs unchanged.

Scenario needs 2 and 4 now pass at all three churches (9 pass, 3 xfail for PR 7). Every baseline in
`test_church_three_today.py` holds. New tests are in `test_church_map_chain.py`.
