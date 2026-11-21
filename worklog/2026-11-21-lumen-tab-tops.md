---
title: "Member app new look (Look 5.1): Watch, Connect and the Bible draw their own top bar, as the mock does"
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin compared the live member app with the approved Look 5.1 mock and saw cut corners. Watch, Connect and Bible keep the church top bar (logo, name, bell, chat, picture); in the mock they have none. Watch opens with a big title and a search icon, Connect with a big title, 'Your people at <church>' and the chat icon with the unread count, the Bible with its Read / Devotional / Plans / Saved control and search. Home keeps the church bar."
status: shipped
prs: ["kmj-intake-server (this PR)"]
migrations: []
left_undone:
  - "Watch's search button: the app has no message search (no ?q= on /my/sermons, nothing in member_portal_sermons or the public sermons page), so the button isn't drawn. Building a search was out of scope."
  - "On a computer (the sidebar layout) these three tabs now have no bell at the top either, as on the phone; the bell stays on Home and in the other pages' bars."
decisions:
  - "member_portal._shell takes lumen_top: a main tab's own top under the new look, drawn in place of the church's bar as <header class=\"mb-top lm-own lm-own-<tab>\">. It is the same sticky bar with the phone's safe area and the same scroll script, so it pins at the top as the mock's does. Only a main tab (no back link, not a conversation) uses it; today's look ignores it."
  - "Watch: the 'Watch' title (h1.lw-t1) moved from the page into the bar; Messages | Series opens the page, 4px under the bar as in the mock."
  - "Connect: the 'Connect' title and the message bubble are the bar (member_lumen_connect.top). The bubble is member_lumen_ui.bubble on member_portal_threads.BADGE, the count the church bar showed (member_portal_threads.counts, kept 15 s), shown only where Messages is on (member_portal_messaging.inbox_on, as the church bar). No read added. 'Your people at <church>' opens the page (member_lumen_connect.sub), 4px up under the bar as in the mock."
  - "The Bible: the segmented control and the search button (member_lumen_bible.seg) are the bar on Read, Devotional, Plans, Saved and Search, with the hairline under it always and the reader's line of how far you've read on its lower edge. SEG_JS no longer places the control under a bar (it is the bar); the old sticky rule went with it."
  - "CSS only through member_lumen_ui.templates(), order unchanged: the shared .mb-top.lm-own rules (60px, the 30px/800 title) in the foundation block, Watch's and Connect's and the Bible's own bits in their blocks. Every rule under .lm, tokens only."
related: [2026-11-20-lumen-bible-tabs.md, 2026-11-20-lumen-tidy-ups.md]
---
Watch, Connect and the Bible no longer wear the church bar under the new look; Home keeps it. No new read,
no route, no migration.

Checked: switch off and MEMBER_LUMEN=preview for a non-owner, 951 page x scene dumps each (Home harness 656,
Bible harness 295): same 951, differ 0 against main. Reads with the switch on, per page and table, in four
looks: Home harness 1984 / 1984 over 328 page-looks, Bible harness 1288 / 1288 over 236, no page differs.
Member suites: 1507 passed. Shots before and after (Chromium and WebKit, light and dark, 390x844 @2x) in the
session scratchpad's tabs-fix-shots/ (before-*, tabs-after-*).
