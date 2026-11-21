---
title: "A YouTube link's start time is kept, so a message can start at the sermon"
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: "sermons_public.video_embed_src drops any start time today. Keep it: YouTube t= (seconds, or 1h22m5s / 82m forms) or start= on watch, youtu.be, live and embed links, and add ?start=N to the nocookie embed. The member's own saved position, where the player resumes (member_lumen_watch _resume), still wins over the link's start. With this the church's team can paste a link with &t= to start at the sermon. Check every place that builds the embed or plays the video: the message page, the mini player, Watch's player script."
status: shipped
prs: ["kmj-intake-server (this PR)"]
migrations: []
left_undone:
  - "Love City's eight services are plain watch?v= links today, so nothing changes for them until someone pastes a link with &t= into the message."
  - "The live page's stream link goes through the same embed, so a live link carrying t= would start there too; a live link rarely carries one, so it is left as it is."
  - "Vimeo's own #t= in a pasted link is still dropped (asked for YouTube only)."
decisions:
  - "sermons_public.youtube_start(url): t= or start= in the query or after #, as whole seconds (95, 95s) or 1h22m5s / 82m / 1h, at most a day; 0 for anything else or a link that isn't YouTube. video_embed_src adds ?start=N to the youtube-nocookie embed. Pure, no read."
  - "This is every look: the public /sermons pages, today's member page (sermons_public.player_html) and the new look's message page all build their frame from video_embed_src. With the switch off a page changes only where a message's link carries a start time; the harness has none, so the dumps are the same, and with a start-time message added to the harness the only pages that change are that message's own (its frame's src)."
  - "New look: member_lumen_watch._with_start reads the link's start back out of the embed and writes one start, always last (&start=N): where the member left off (_resume, a few seconds back) when she has started it and not finished, else the link's start. Once she has watched it, it opens at the sermon again. The page's script, which swaps in the phone's own newer place, replaces '&start=N' at the end, so it keeps working and never leaves two starts."
  - "The mini player plays the message page's own frame (it never builds an embed of its own), so it starts wherever the page's frame does."
related: [2026-11-20-lumen-watch.md, 2026-11-21-watch-video-pictures.md]
---
A message whose YouTube link carries a start time (&t=1h2m, ?t=3725, start=) now opens at that second, in every look;
in the new look the member's own place still wins. No route, no read, no migration.

Checked: switch off and MEMBER_LUMEN=preview for a non-owner, 951 page x scene dumps each (Home harness 656, Bible
harness 295): same 951, differ 0 in both modes against main. With two YouTube messages added to the harness, one of them with t=1h2m5s: 688 pages each, same 672, differ 16 off and in preview, and all 16 are that message's own page (eight scenes, with and without ?listen=1), each differing only by its frame's ?start=3725.
Reads with the switch on, per page and table, in four looks: Home harness 1984 / 1984 over 328 page-looks (and with the YouTube messages, 1984 / 1984), no page differs; Bible harness every page that answers 200 the same, 1132 / 1132 over 224 (its Home is a harness crash on main and here alike, whose parallel reads vary run to run). Member suites: 1679 passed with the live tests (test_sermon_start_time: 38 new; the embed test now keeps t=10). Shots in
the session scratchpad's watch-fix-shots/ (start-*: the message page with a start-time link, and the frame's
address).
