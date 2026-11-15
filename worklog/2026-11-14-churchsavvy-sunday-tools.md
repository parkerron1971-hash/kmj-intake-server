---
title: "ChurchSavvy Sunday tools: countdown for minutes and by itself, sermon notes as an outline, fonts and backgrounds"
date: 2026-11-14
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-14: countdown "we can set like 5 min or 15 min", started by a person or a pre-service clock, with background graphics; sermon notes with points and statements, better than Proclaim''s "--"; background and font choices. On the mock (canvas 3pdndYa6gYJCPy4W9EHRyi): "nice! build and merge everything"'
status: in progress
prs: ["kmj-intake-server (this PR): the CHURCHSAVVY_SUNDAY_TOOLS switch"]
migrations: []
left_undone: ["the countdown build", "the sermon outline build", "the fonts and background library build", "switch CHURCHSAVVY_SUNDAY_TOOLS=on on a Thursday (both services)"]
decisions: ["one switch for the three tools, owner by default; it opens the editing only, since what was saved shows on every screen"]
related: [2026-10-26-churchsavvy-countdown-crawl.md, 2026-10-26-churchsavvy-slide-backgrounds.md, 2026-10-26-churchsavvy-timers.md]
---
The switch the three Sunday tools share: `worship_router.sunday_tools(user)`,
and `/worship/status` returns `sunday_tools`. The builds that follow update
this file.
