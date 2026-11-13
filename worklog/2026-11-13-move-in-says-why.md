---
title: Every one of the eleven Move-in things says why it is needed
date: 2026-11-13
agent: Claude Code (Claude Fable 5.2)
asked: "they don't explain like safety officers and why they are needed well. even some of the other ones. can we make sure that is good?"
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "The welcome briefing's recorded lines about each thing are unchanged (they are recordings with measured timings)."
  - "The pastor's handout PDF is redone separately, outside this repository, with the same words."
decisions:
  - "Words only: the same two lines the room already shows for each thing (what's asked, and why). No new part of the screen."
  - "Three things had no why at all (the tools used today, Sunday details, the room); they have one now."
  - "Safety officers: the why now says what member messaging is, that every message is checked and a harmful one is held, that an officer decides whether a held or reported message is delivered or removed, that staff don't read members' messages otherwise, and that messaging stays off until two are named. Each sentence was checked against messaging_router.py and member_portal_messaging.py."
  - "Kids rooms: the ages are how WE place each child in a room; check-in itself uses the room on the child's record, so the line does not say check-in reads ages."
  - "Photos are said to be for the website, which follows the first Sunday; nothing in the members' app was found that shows them."
  - "Chief's move_in_status now carries each still-to-do thing's ask and why, so a pastor who asks Chief what a safety officer is gets the room's answer. A thing already handed in is not explained again."
related: [2026-11-11-church-move-in-room.md, 2026-11-11-chief-knows-the-move.md]
---
Kevin read the Move-in list as a pastor would and found that several things, safety officers most of
all, said what to hand in but not why. `church_move_in.ITEMS` keeps the same keys, titles, lines and
rules; only `ask` (two of them) and `why` (all eleven) changed.
