---
title: "Member app new look (Look 5.1) tidy-ups: moments share through member_lumen_share"
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: "Three small tidy-ups Kevin approved after Look 5.1 (#1985-#1994, #1999, #2010): the moments use the share helpers; 'Loved by' updates in place; 'Send to someone at church' in the share sheet. One PR each."
status: in progress
prs: ["kmj-intake-server (1 of 3: moments share through member_lumen_share)"]
migrations: []
left_undone:
  - "Tidy-ups 2 ('Loved by' in place) and 3 ('Send to someone at church') follow in their own PRs."
decisions:
  - "Moments: member_lumen_stories' hand-written share_link, events_on, event_shareable, event_picture, message_art, message_href, MOMENT_OF and EVENTS_HREF are gone. A moment's Share is member_lumen_stories.share(), which calls member_lumen_share.link('moment', ...) with the moment's icon and class: byte for byte the markup #1994 wrote (kind moment, data-share-id '<message|event>:<id>', aria-label Share). member_portal_lumen.render_home takes message_href, EVENTS_HREF, message_art, event_shareable and event_picture from member_lumen_share."
  - "member_lumen_share.attrs refuses a moment that doesn't name one of the church's own kinds ('<message|series|event>:<id>'), the guard the stories helper had. No moment without an id gets a Share."
  - "Event moments: upcoming_for has marked each occasion public since #1986, so a public event (and the service, when it is on the public events page) gets Share while the church's public events page is on. Pinned through the real upcoming_for: a public event shares, an invite-only one doesn't, none with the page off. Groups, members' posts and devotionals never."
related: [2026-11-20-lumen-home-look-5-1.md, 2026-11-20-lumen-share.md]
---
Moments now draw Share through `member_lumen_share` (#1986) instead of their own copy. No new read, no
route, no CSS. Checked: switch off and MEMBER_LUMEN=preview for a non-owner, 951 page x scene dumps (Home
harness 656, Bible harness 295) identical to main; switch on also identical (Watch's state clock aside).
Home with a public event moment (the share harness) identical to main. Reads per page identical
(Home harness 493 / 493 over 82 pages).
