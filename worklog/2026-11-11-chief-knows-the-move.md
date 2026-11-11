---
title: Chief knows a church's move and fills an item in as a draft
date: 2026-11-11
agent: Claude Code (Claude Fable 5.2)
asked: "should this be a process that chief does ... yes. and you can allow chief to fill items as well"
status: in review
prs: [kmj-intake-server#1792, solutionist-studio#1513]
migrations: []
left_undone:
  - "Chief isn't told about the move on every turn: it reads it when asked (move_in_status). A line in the turn's context for a church that is mid-move would cost every church turn; not added."
  - "No setup-list step on Home points at the Move-in room: the room is open for the platform's own church only, and a step that opens a closed page is a dead end. Add it with the switch-on (business_track_actions, a done-probe on the room's progress)."
  - "Nothing handed in is loaded automatically yet (services, kids rooms, groups, office logins, safety officers)."
  - "Not tried with a real Chief turn in production yet: the handlers are tested against the room's own code, not against the model."
decisions:
  - "The room is the record; Chief is the guide. Chief never hands an item in: a person presses Hand in."
  - "A fill saves a draft through the room's own cleaning and write. A line given replaces that line; an unknown line changes nothing and says so, so Chief can't say it saved something that was dropped."
  - "Tags only, chief_only: the verbs need the signed-in person, so they are never an outside agent's or a native write tool."
  - "Placed with the Office, as the room is."
related: [2026-11-11-church-move-in-room.md]
---
`chief_move_in.py`: `move_in_status` (a mid-turn read: the eleven items, where
each stands, what each holds and still needs, what's next, and each item's
lines by key), `fill_move_in` (`{item, answers}`: a draft into one item) and
`undo_move_in_fill` (the item's lines as they were, `undo_last`'s inverse).
Who may use them is the room's own check (`church_move_in._access`), by the
signed-in person's id. `operate/move-in` joined `system_destinations.json`, so
`navigate` opens the page. The hand-in email now says where to look (Mission
Control, Customers, Move-ins), which exists since solutionist-studio#1513.

Before building more here: the prompt section is `CHURCH MOVE-IN` in
`chief_prompt.py`, next to `CHURCH DUTIES`; the item keys and lines come from
`church_move_in.ITEMS`, so the handout, the page and Chief change together.
