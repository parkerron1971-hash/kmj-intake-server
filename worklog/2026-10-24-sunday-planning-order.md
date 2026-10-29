---
title: ChurchSavvy Planning, step 4 — one order of service for every team (server)
date: 2026-10-24
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-23: "planning, team communication and assignments"; "This is a good build. i agree with your plan."; "let''s keep building as planas well."'
status: shipped
prs: [kmj-intake-server#1572, solutionist-studio#1341 (Operate → Sunday → Order of service)]
migrations: [supabase/APPLY-2026-10-24-serve-notes.sql (applied 2026-10-24 after a live rollback probe built from the file: a team's note and everyone's, then a second for the same team, a group that isn't a Sunday team, a team that isn't an id and another church's service all refused, rolled back)]
left_undone: ["the Sunday pack in the member app (board 9): kmj-intake-server, step 5", "editing the items themselves from Planning, for a church with Planning and no ChurchSavvy screens (today they're ChurchSavvy's plan)", "what changed since Friday, and who was told (board 3's Changed Sat)"]
decisions: ["the items stay ChurchSavvy's plan (worship_services.items), the one plan the slides read; Planning's notes for each team live beside it in serve_notes, so a save in ChurchSavvy never overwrites a team's note", "a note is for one Sunday team or for everyone serving (\"all\"), one per item each, up to 300 characters; an empty note takes it off; only whoever schedules writes one", "each item's time is the start plus the minutes before it; items under a section called Before count back from the start, so they end as the service begins; items under After (the goodbye loop) follow the end without moving it", "a song in the order is its title, key and the band's order (its parts' names, V1 C B) from the library, never its words"]
related: [2026-10-23-sunday-planning-teams.md, 2026-10-24-sunday-planning-alerts.md]
---
`sunday_order.py`: `GET /planning/order` (one service's order: each item's time, length, who, and its notes by team; the teams; the coming services) and `PUT /planning/order/notes`. `serve_notes` is server-only like the rest of serve_*, kept inside one church by its own trigger (that church's service, one of its Sunday teams).

Checks: 5 tests in `test_sunday_order.py` (11 sabotages caught: Before counted forward, After moving the end, a song's words in the order, a reader writing a note, a reader told they can, a note on a section, another church's team, an empty note kept, a no-longer-serving team's notes shown, a long note kept, the switch ignored); `serve_notes_db.mjs` 15 checks on PGlite (7 migration sabotages caught).
