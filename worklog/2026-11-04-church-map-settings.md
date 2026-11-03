---
title: Church leaders map, PR 7 — the church's settings take effect (money levels, pastor's yes, board yes, office overseers) and room asks go to the rooms duty
date: 2026-11-04
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03: take the leaders flow further, for every church that subscribes ("what i don''t want is what i build works for love city but is broken and messed up for other churches"); design 4V41zJz1kEJGdeo4J9D2Ym approved'
status: in review
prs: ["kmj-intake-server (this PR)"]
migrations: [supabase/APPLY-2026-11-04-church-map.sql (applied 2026-11-03 with PR 2; nothing new here)]
left_undone:
  - "CHURCH_MAP defaults to owner (Love City only). When it goes on, set it on BOTH Railway services (server and worker); nothing was set here"
  - "Love City's levels and pastor's-yes picks are unset in production, so its money is today's until Kevin sets them (owner only, PUT /church/map/settings)"
  - "A board-yes role holder who sits on no board has no Board tab: they reach /my/board/approvals by the email's link. A door on the Lead tab is its own PR"
  - "PR 5's settings check compares the two levels only when both are set; a pastor level above $2,500 with the board's left null gives a board step before the pastor's"
  - "PR 8: areas and job guesses stop deciding; PR 9 deletes the executive_pastor key query once CHURCH_MAP is on everywhere"
decisions:
  - "A role pick (church_map.picked): null is today's rule; a list names active roles; none named ('{}' or all since archived) is the owner for the pastor's yes and nobody for the office (so the owner hears)"
  - "/my/board/approvals opens through church_money_levels.board_people, not boards_of: board-yes holders are added there and to board (a login by its email); the Board tab stays church_board_members"
  - "Room asks phone church_duties.holders_of(biz, 'rooms') wherever the map is open, empty too, so Love City's open empty map adds Jessica (ROOMS_OPEN in test_church_three_today); the bell is unchanged"
  - "A failed map read is the reader's own: money levels and duties 503; overseers and room_phones the owner alone"
  - "#1716 review fix, a separate commit: a half-made department (units and clean-up both failed) is marked a draft from the office, and only such a draft is taken over by the same login's retry; an active unit-less department gets the 400"
related: [2026-11-04-church-map-fixture.md, 2026-11-04-church-map-core.md, 2026-11-04-church-map-switches.md, 2026-11-04-church-map-writes.md, 2026-11-04-church-map-chain.md]
---
Where `church_map.opened(biz)` is a Map, the church's own settings decide. Its money levels apply to
`required`, `page_view`, Check requests' `LEVELS_ON` and the member app's board copy. `pastor_yes_roles`
decides who gives the pastor's yes. Every active holder of a role with `can_board_yes` gives a board
member's yes, by their person in the member app or by a login whose email is theirs.
`office_overseer_roles` decides who oversees the office (`church_duties.overseer_keys` for the
Executive Pastor's lane, and `church_office_tasks.overseers`). A room request's phone alerts go to the
rooms duty's holders (`member_asks.room_phones`). Closed, or before the migration, every path is
today's.

Scenario needs 1 and 3 now pass at all three churches (12 of 12). Every baseline in
`test_church_three_today.py` holds, except Love City's room alerts on an open map, which the spec
corrects. New tests are in `test_church_map_settings.py`.
