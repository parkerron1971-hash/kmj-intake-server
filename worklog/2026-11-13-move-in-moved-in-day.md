---
title: The Move-in room remembers the day a church first saw its move finished
date: 2026-11-13
agent: Claude Code (Claude Fable 5.2)
asked: "sounds good. let's build these with no problem! top tier experience with it."
status: in review
prs: [kmj-intake-server#1815]
migrations: []
left_undone: []
decisions:
  - "The day is kept on the church's first look at a finished move, not on our last check, so a pastor who was away still gets the moment on Home."
  - "It is one row in church_move_items under the reserved item `_moved_in` (its `checked_at`). No migration: the item column only limits length, and every read of the list keeps to the eleven."
  - "The day is kept once. If a church changes something later and the move finishes again, the first day stands."
  - "A day that can't be read or kept answers None and never fails the status: the menu's answer does not hang on it."
related: [2026-11-12-move-in-under-home.md, 2026-11-11-church-move-in-room.md]
---
Kevin approved three additions to the move (a card on Home, a clear ending, a place to look back),
built in solutionist-studio (its work log of the same date). The ending needs one fact from the
server: how long ago the move finished, so Home can say "moved in" for a while and then let it go.
`GET /church/move-in/status` now answers `finished_at` when `finished` is true
(`church_move_in._moved_in_at`). Tests: `__tests__/test_church_move_in.py` (38, two new).
