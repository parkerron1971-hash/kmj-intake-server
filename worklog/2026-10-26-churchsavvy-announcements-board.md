---
title: ChurchSavvy's announcements board, and Sunday filling itself from it (round 5, server)
date: 2026-10-26
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-25: "we never create space for announcements to be able to be placed"; 2026-10-26 on the round 5 canvas: "these are a go. build it"'
status: in progress
prs: [kmj-intake-server (this PR), solutionist-studio (the board, the editor and the designs, next)]
migrations: [supabase/APPLY-2026-10-26-worship-announcements.sql (applied live 2026-10-26 after a rollback probe)]
left_undone: ["ministries sending their own (canvas board 20) and the Wednesday reminder", "bringing in calendar events (A4)", "the countdown you can grab, timers from the plan, the crawl and the lobby on its own (boards 22-26): later round 5 PRs"]
decisions: ["an announcement is made once with the days it shows; it retires itself the day after show_until, and shows until the day it happens when nobody said otherwise", "where it shows: room, lobby, online, phones; Sunday's spot and the welcome loop take the room's", "six designs (side, flyer, date, card, week, save); a design that needs a date or a picture falls back when it has none", "'This Saturday' counts a church's week from Sunday", "a board that can't be read leaves the rest of Sunday on screen: the loop shows the logo"]
related: [2026-10-20-churchsavvy-loops-quick-server.md, 2026-10-19-churchsavvy-show.md]
---
`worship_announce.py` (the rules: checking one, its tab on a day, what shows on a kind of screen nearest first, an announcement as a slide) and `worship_announce_router.py` (GET/POST/PUT/DELETE `/worship/announcements`, POST `/{id}/decide` for a ministry's request; the plan's part writes, anyone on the team reads). `worship_show.py`: an announcement item with `from_board` (and `count`, 1-8) and a loop with `from_board`, `logo_every` and `corner` compile from the board `worship_show_router._show` reads for the service's own day on the church's clock (`board_for`, `church_zone`). Exported with the account; not re-imported, since a picture points at the old business's files. Canvas: UZu4VsoY9KemkUGorz234j boards 18, 19 and 21.
