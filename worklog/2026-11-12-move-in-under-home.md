---
title: The Move-in room's status says when the move is finished
date: 2026-11-12
agent: Claude Code (Claude Fable 5.2)
asked: "we need to reorder the move in section. that should be under the home section until everything for move in is complete and then it disappears when finished"
status: in review
prs: [kmj-intake-server#PENDING]
migrations: []
left_undone:
  - "Chief is not told the move is finished in any new way: move_in_status already reads each thing's state."
decisions:
  - "Finished means every thing is CHECKED by us (giving: live with Stripe), not merely handed in. A thing only handed in can still come back needing a change, and the church has to be able to see that in its room."
  - "The room is not closed when finished: only the menu lets it go. Its address still opens it."
  - "A finished question that can't be read answers not finished, so the room stays on the menu."
related: [2026-11-11-church-move-in-room.md, 2026-11-12-move-in-first-sunday.md]
---
Kevin wants the Move-in room under a church's Home door while the move is going on, and gone from
the menu once it is done. The menu asks one small question per login,
`GET /church/move-in/status`; it now also answers `finished` (`church_move_in._finished`: the item
states only, so the question stays a small read). The menu move itself is in solutionist-studio
(its work log of the same date).
