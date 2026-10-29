---
title: ChurchSavvy slides can have a background of their own (server)
date: 2026-10-26
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-26: "have where is a person wants to change the background of specifically the points or any slide for a certain background design, we should allow for that to happen so if there only want certain design background for certain slides it should be able to happen"'
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio (the Background choice on an item and on each sermon point; the screens draw it)]
migrations: []
left_undone: []
decisions: ["`bg` = {kind: color | image | video, color, url, dim}; nothing, {} or kind \"look\" follows the church's look", "songs, passages, sermon points and typed announcements carry one (the items whose words sit on the background); pictures, videos, countdowns, loops and the board's own designs draw their own way and drop it", "each sermon point may have its own, and it beats the item's", "compile_item copies it onto each slide as `bg`, so every screen (room, lobby, LED, the booth's thumbnails) gets it with the slide; no table, it lives in the service's items"]
related: [2026-10-26-churchsavvy-flyers.md]
---
`worship_show.py`: `clean_bg` (checked like the look's background: an https:// link, a #rrggbb color, darkening 0 to 0.85), `clean_item` keeps `bg` on the item and on each text slide, `compile_item` puts it on the slides. Tests: `__tests__/test_worship_show.py` (rehearsed red: without the copy onto the slides, the point-and-item test fails).
