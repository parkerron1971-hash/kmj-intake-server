---
title: Church leaders map — a Serve sign-up for a team with no leader goes to its department
date: 2026-11-04
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03: take the leaders flow further, for every church that subscribes ("what i don''t want is what i build works for love city but is broken and messed up for other churches"); design 4V41zJz1kEJGdeo4J9D2Ym approved'
status: in review
prs: ["kmj-intake-server (this PR)"]
migrations: [supabase/APPLY-2026-11-04-church-map.sql (applied 2026-11-03 with PR 2; nothing new here)]
left_undone:
  - "CHURCH_MAP defaults to owner (Love City only). Love City's production map is empty, so its Serve sign-ups route as today until step 4 enters the department sheet"
  - "The sweep still takes a follow-up's team from the holder row's scope. A department leader's row has none, so a leader of several departments has a late sign-up told to every overseer of their departments (chain_for rule 1), not only the team's"
decisions:
  - "Order where the map is open: the team's own leader, then the leader of the active department its Serve option hangs from, then that department's overseer, then today's oversees_teams and chain"
  - "A leader counts while they hold an active role with can_lead, an overseer one with can_oversee: the same seat chain_for picks (shared as church_map._seat), so leader_role is the role they qualify through"
  - "The reason names the step as chain_for titles it: '…which has no leader yet; it goes to the Youth leader.'"
  - "No new late-ladder code: the department leader leads the department, so chain_for's first rule sends it to the overseer, then today's chain"
related: [2026-11-04-church-map-chain.md, 2026-11-04-church-map-areas.md]
---
PR 6's log left this undone: `choose` now asks `church_map.team_head` before `oversees_teams`, only where
`church_map.opened(biz)` is a Map. Closed, or before the migration, it is today's code. A failed map read
already stops `start()`, so the sign-up waits as on any failed read.

At the three test churches, every team that hangs from a department reaches the same person it reaches
today, with a new reason. The cases that differ are a vacant or no-longer-qualifying department leader
(the overseer gets it) and a department leader other than the role that oversees the team. New tests are in
`__tests__/test_church_map_serve.py`. Every baseline in `test_church_three_today.py` holds.
