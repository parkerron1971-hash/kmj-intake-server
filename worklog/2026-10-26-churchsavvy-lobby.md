---
title: ChurchSavvy's lobby TV on its own (round 5, server)
date: 2026-10-26
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-25: "there is so much upgrade this needs. what other ideas we can add to this?" (F2, the lobby TVs on their own loop); 2026-10-26 on the round 5 canvas: "these are a go. build it"'
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio (Setup → Lobby TV and the lobby screen running its week)]
migrations: [supabase/APPLY-2026-10-26-worship-lobby.sql (APPLIED LIVE 2026-10-26 after a rollback probe)]
left_undone: ["ministry links to send announcements (board 20), the Wednesday reminder and the calendar import"]
decisions: ["each lobby screen keeps its own week in worship_screens.lobby; empty means it follows the booth, as every lobby screen did before", "a week is up to 12 times: days (0 is Sunday), from and to on the church's clock, and what: the welcome loop (the service itself while it's on), this week, a countdown to a named night, or off; any other hour is dark", "what it shows: announcements marked Lobby, the countdown before each service, the service while it's on, the time and the day, a verse for the day (KJV), the logo between; all on until turned off", "the verse for the day is the member app's (member_portal_bible.VERSES), KJV only", "the lobby's page sends the church's time zone, so a TV box on the wrong clock still keeps the church's hours"]
related: [2026-10-26-churchsavvy-timers.md, 2026-10-26-churchsavvy-announcements-board.md]
---
`worship_show.py`: `clean_lobby` / `_clean_lobby_time` / `default_lobby_times`, `lobby_verse`. `worship_show_router.py`: `lobby` on a screen (saved by setup, read by its link; an older shape that no longer passes follows the booth), and `GET /worship/screen/{token}/lobby` (lobby screens only): its week, the board marked Lobby for today (`board_for(…, "lobby")`; a board that can't be read leaves the rest), the verse, the next service (not a template, from 3 hours ago on) and the church's zone. Migration: one jsonb column with a shape check, rehearsed in a rollback probe (an existing screen reads `{}`; a too-big or array value is refused), then applied. Tests: `__tests__/test_worship_lobby.py`. Canvas UZu4VsoY9KemkUGorz234j board 26.
