---
title: ChurchSavvy's countdown you can grab, and the crawl (round 5, server)
date: 2026-10-26
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-25: "We need to create able to adjust count down clock for sure"; 2026-10-26 on the round 5 canvas: "these are a go. build it"'
status: in progress
prs: [kmj-intake-server (this PR), solutionist-studio (the booth's buttons, the looks and every screen, next)]
migrations: []
left_undone: ["timers from the plan, the service clock and the pastor asking for more time (board 24)", "the lobby on its own (board 26)"]
decisions: ["the countdown item keeps its look (big, picture, ring, plain), a welcome line, what happens at zero (next item, logo, count up on the stage) and a countdown video with its length; they ride on its slide", "the booth's grab is live state: count.to (what it counts to now) or count.held (the seconds it stopped at); no table", "the crawl is live state too: words up to 160, room and/or online, once, three times or until stopped, from `at`; saved lines live in the look (up to 10)", "'Over the loop' is the welcome loop's corner countdown (board 21), not a fifth look"]
related: [2026-10-26-churchsavvy-announcements-board.md]
---
`worship_show.py`: `_clean_countdown` (look, zero, picture_url, welcome, video_url + video_seconds, band_at, band_text), the countdown slide carrying them, `clean_live` taking `count` and `crawl`, and `clean_look`'s `crawls`. Canvas UZu4VsoY9KemkUGorz234j boards 22, 23 and 25. No migration: it all fits in the service's items, the live row's state and the look.
