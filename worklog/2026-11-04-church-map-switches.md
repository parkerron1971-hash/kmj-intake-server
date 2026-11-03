---
title: Church leaders map, PR 4 — switches replace words (who shepherds, choose's tie-break, the leaders room)
date: 2026-11-04
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03: take the leaders flow further, for every church that subscribes ("what i don''t want is what i build works for love city but is broken and messed up for other churches"); design 4V41zJz1kEJGdeo4J9D2Ym approved'
status: in review
prs: ["kmj-intake-server (this PR)"]
migrations: [supabase/APPLY-2026-11-04-church-map.sql (applied 2026-11-03 with PR 2; nothing new here)]
left_undone:
  - "CHURCH_MAP defaults to owner (Love City only). When it goes on, set it on BOTH Railway services (server and worker); nothing was set here"
  - "PR 5: map writes and /church/map routes; propose() is still a stub"
  - "PR 6: chain_for (Shepherding's _chain, the sweep, prayer, signals, leader tasks); scenario need 2 at Love City and New Hope, need 4 at Grace and New Hope"
  - "PR 9: delete SHEPHERD_TITLE/MINISTER_TITLE, LEADER_JOBS and choose's word tie-break (they are the closed path until CHURCH_MAP=on everywhere); the lint stays xfail until then"
decisions:
  - "church_map.opened(biz) is every reader's entry: False when closed or not ready (today's code untouched), else load(biz); a None is the reader's own failed read (Shepherding None/503, start skips the hand-off, the leaders room None), never today's people"
  - "role_rows on an open map: every senior and pastoral role as today, plus any other job whose can_shepherd isn't false; null follows Ministers (switch 'ministers'); lead stays the senior job"
  - "The leaders room adds an active department's leader and overseer when they hold any active role; can_lead/can_oversee gate the chain (PR 6), not the room"
  - "Scenario need 2 at Grace passes from PR 4 (D2 has no department and no answers-to, so today's chain is PR 6's line); its strict xfail is removed"
  - "test_church_leader_tasks' role rows now carry their job's switches: its fake answers any select, so the platform church's map opens there as in production"
related: [2026-11-04-church-map-fixture.md, 2026-11-04-church-map-migration.md, 2026-11-04-church-map-core.md]
---
Where `church_map.church_open(biz)` and `ready()` are both true, a role's stored switches now decide
three things instead of its title or job. `church_shepherding.role_rows` reads `can_shepherd`.
`church_follow_up.choose` breaks a tie by `made_for`. The leaders room reads `can_lead`, keeps the
answers-to seat and adds each active department's leader and overseer who holds a role. Closed, or
before the migration, today's code runs as it was.

Every baseline in `test_church_three_today.py` holds with the map closed, open and empty, and open
without the migration. That file now reads through `shep.load`/`_member_ctx` and hands `choose` the
map, as `start` does. New tests are in `test_church_map_switches.py`. Before building more here:
PR 6's `chain_for` should reuse `opened()` the same way.
