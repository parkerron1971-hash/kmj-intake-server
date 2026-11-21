---
title: Chief's help answers for Visitor flow and a guest's notes
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: 'One Visitor flow room (Kevin picked it); the flow looks like the mock'
status: shipped
prs: []
migrations: []
left_undone: []
decisions: ["only the four changed answers are copied from the app's export; the export's two giving-access answers stay out until their switch is on (as #2034 did)"]
related: [2026-11-21-visitor-flow-one-room.md]
---
The server's copy of the app map (church_findway.json, Chief's "where is" and
"how do I") gets the four answers the app changed in solutionist-studio#1675:
the board's "Mark a follow-up step done" and "Leave a note about a guest" (a
first-time guest in Visitor flow: open them, Notes & steps), and Visitor
flow's "See which new people nobody has reached" and "See how many new people
came back" (true of both the guests' room and the counts page). These are the
four answers' text only, copied from `node scripts/export-church-map.mjs`.
