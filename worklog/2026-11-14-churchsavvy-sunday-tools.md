---
title: "ChurchSavvy Sunday tools: countdown for minutes and by itself, sermon notes as an outline, fonts and backgrounds"
date: 2026-11-14
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-14: countdown "we can set like 5 min or 15 min", started by a person or a pre-service clock, with background graphics; sermon notes with points and statements, better than Proclaim''s "--"; background and font choices. On the mock (canvas 3pdndYa6gYJCPy4W9EHRyi): "nice! build and merge everything", then "switch it on now, don''t wait for thursday when it''s done"'
status: shipped
prs: ["kmj-intake-server#1861 (the CHURCHSAVVY_SUNDAY_TOOLS switch)", "kmj-intake-server#1862 (two date-bound tests pinned)", "kmj-intake-server#1863 (countdown: designs, on the spot, starts by itself)", "kmj-intake-server#1864 (sermon notes as an outline)", "kmj-intake-server#1865 (fonts, background library, sermon series looks)", "solutionist-studio#1569 (sermon notes)", "solutionist-studio#1570 (countdown)", "solutionist-studio#1572 (fonts and backgrounds)", "solutionist-studio#1573 (What's New for all three)", "kmj-intake-server (this PR): this log"]
migrations: []
left_undone: ["the mock's soft shadow behind the words switch (not in the build list)"]
decisions: ["one switch for the three tools, owner by default; it opens the editing only, since what was saved shows on every screen", "CHURCHSAVVY_SUNDAY_TOOLS=on set on kmj-intake-server and kmj-intake-worker on 2026-11-14 (Saturday), at Kevin's word, ahead of the Thursday switch rule; owner puts it back to the owner only, off hides the new editing"]
related: [2026-10-26-churchsavvy-countdown-crawl.md, 2026-10-26-churchsavvy-slide-backgrounds.md, 2026-10-26-churchsavvy-timers.md, 2026-11-14-churchsavvy-fonts-backgrounds.md]
---
The switch the three Sunday tools share: `worship_router.sunday_tools(user)`,
and `/worship/status` returns `sunday_tools`. All three builds shipped the same
day (countdown #1863, sermon notes #1864, fonts and backgrounds #1865, with their
app halves) and the switch went to on for every church that night.
