---
title: Church assignments, three fixes before they open to every church (Chief takes one back, the board follows the pastors rule, any department for a leader)
date: 2026-11-14
agent: Claude Code (Claude Fable 5.2)
asked: "ok got it. we need to finish up this preparation"
status: in review
prs: [kmj-intake-server#1844]
migrations: []
left_undone:
  - "Frontend (solutionist-studio) not touched: the For a leader picker doesn't read all_departments yet, and the board's screen doesn't show not_handed_text. Until it does, a follow-up left for the owner shows only as a task with the person's name in its title."
  - "undo_last still doesn't reach give_assignment: take_back_assignment is class C (it removes the task for good) and no inverse may be class C. 'Undo that' after a give is a take-back in words, and the prompt and action_inverse say so."
  - "Chief's take-back names only open and stuck assignments. A done one is still removed from the board."
  - "Someone who handed an assignment and is no longer over that person can take it back on the board, but can't name them to Chief (Chief looks people up among who the login is over)."
  - "The database still doesn't refuse a task the office writes straight to it for a pastor or an elder (the known limit in docs/CHURCH_ASSIGNMENTS.md, unchanged)."
  - "CLAUDE.md says 266 ACTION_HANDLERS; there were 350 before this PR and 351 after. Not changed here."
decisions:
  - "Take-back is one function now, church_assignments.take_back: the DELETE route's own lines moved into it unchanged, and both the route and Chief's take_back_assignment call it. No new rule."
  - "take_back_assignment is class C, not A: it is a hard delete of the task (its stuck note and what was done on it too). So it runs when someone asks, never on Chief's own idea, and undo can't be wired to it. Kevin can overrule: class A plus an inverse is about ten lines, but it would make a hard delete undo-reachable and auto-eligible."
  - "A board follow-up for a pastor or an elder that the login may not hand them is still made, handed to no one, with the person's name in its title and why in its notes; the answer lists it in not_handed and not_handed_text. Refusing the whole press, or dropping the follow-up, would lose the board's decision; the name in the title is how a member with no login was already shown."
  - "The board asks church_over.may_hand: the owner hands every one out; anyone hands themselves their own; someone who isn't a pastor or an elder is handed theirs as before; a pastor or an elder only by a login that is over them (is_over, so the ministry chain on the map still counts). It does not ask is_over for everyone: a board's secretary is over no one, and that would stop every follow-up."
  - "The owner counts as a pastor here only where the owner's own person is one (Church.owner_guarded), as the Hand to list already reads it."
  - "The board follows the rule only while assignments are open for the church (church_over.church_open), as the Hand to list does. Closed, it reads nothing more and hands them out as before."
  - "all_departments is always in the leaders answer: every active department for the owner and an Admin, an empty list for a Manager. Each leader's own departments list is unchanged and send is unchanged."
related: [2026-11-12-chief-assignments.md, 2026-11-12-church-handovers.md, 2026-11-12-church-assignments.md]
---
Kevin said these three gaps "need to fix for later for sure", and they are wanted before assignments open to
every church on Thursday, Nov 19. All three are backend only, no migration.

Chief can take an assignment back (`take_back_assignment`, by the board's own rules). A board's "make tasks"
no longer hands a pastor or an elder work around the rule: that follow-up waits in Tasks for the owner. The
hand-over list tells the owner and an Admin every department they may send for (`all_departments`).

Before building more here: docs/CHURCH_ASSIGNMENTS.md has each of these under its own heading, and the two
screens (the For a leader picker, the board's Make tasks) still need the frontend to read the new keys.
