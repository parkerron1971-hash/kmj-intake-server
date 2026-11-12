---
title: The first Sunday is a line in the Move-in room
date: 2026-11-12
agent: Claude Code (Claude Fable 5.2)
asked: "I like everything so lets build this right"
status: in review
prs: [kmj-intake-server#PRNUM]
migrations: []
left_undone:
  - "Nothing reads the date yet: no countdown on Home, no day-by-day plan. It is kept so those can be built on it."
  - "It is free text (\"Sunday, November 22, 2026\"), like the room's other lines, not a date column."
decisions:
  - "Kept in the Sunday item's answers, not a new table or column: no migration, the room's own save and Chief's fill already carry it, and the office can change it there."
  - "It is not what makes the item ready to hand in: the services still are."
related: [2026-11-11-church-move-in-room.md, 2026-11-11-chief-knows-the-move.md]
---
Kevin approved the welcome briefing for a new church (a playable test he
steered over several rounds, 2026-11-11 and 11-12) and said to build it. Its
last chapter asks "When is your first Sunday with us?". This is the backend
half of that question: `church_move_in.ITEMS` gives the `sunday` item a first
line, `first_sunday` ("Your first Sunday with us"), saved through the room's
existing `PUT /church/move-in/sunday` as a draft like any other line.

The briefing itself is in solutionist-studio (see its work log of the same
date). It reads the room, adds the date to the Sunday item's answers and saves
them back, so nothing already typed there is lost.
