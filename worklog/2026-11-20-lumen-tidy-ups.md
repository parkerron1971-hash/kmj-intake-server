---
title: "Member app new look (Look 5.1) tidy-ups: moments share through member_lumen_share; Loved by updates in place"
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: "Three small tidy-ups Kevin approved after Look 5.1 (#1985-#1994, #1999, #2010): the moments use the share helpers; 'Loved by' updates in place; 'Send to someone at church' in the share sheet. One PR each."
status: in progress
prs: [kmj-intake-server#2017, "kmj-intake-server (2 of 3: Loved by in place)"]
migrations: []
left_undone:
  - "Tidy-up 3 ('Send to someone at church') follows in its own PR."
  - "Love in a moment's viewer (a pastor's post, member_lumen_stories) is still today's RX_JS form: it doesn't turn the same post's heart or 'Loved by' in the feed below until the next page."
decisions:
  - "Moments: member_lumen_stories' hand-written share_link, events_on, event_shareable, event_picture, message_art, message_href, MOMENT_OF and EVENTS_HREF are gone. A moment's Share is member_lumen_stories.share(), which calls member_lumen_share.link('moment', ...) with the moment's icon and class: byte for byte the markup #1994 wrote (kind moment, data-share-id '<message|event>:<id>', aria-label Share). member_portal_lumen.render_home takes message_href, EVENTS_HREF, message_art, event_shareable and event_picture from member_lumen_share."
  - "member_lumen_share.attrs refuses a moment that doesn't name one of the church's own kinds ('<message|series|event>:<id>'), the guard the stories helper had. No moment without an id gets a Share."
  - "Event moments: upcoming_for has marked each occasion public since #1986, so a public event (and the service, when it is on the public events page) gets Share while the church's public events page is on. Pinned through the real upcoming_for: a public event shares, an invite-only one doesn't, none with the page off. Groups, members' posts and devotionals never."
  - "Loved by (#2: member_lumen_feed): Love and Praying on a feed card are the feed's own forms (lf-rxf, no longer nw-rxf), answered by the feed's script: the heart turns and the line is redrawn on the phone at once (likes(): 'you' added or taken away, the count moved, the server's own words: 'Loved by Ben and 6 others', 'Loved by you', 'N people', '· N praying'), then POST /my/news/react's JSON answer {ok, on, kind} is the truth; a refusal or a lost answer turns both back. Double-tap goes through the same form. No motion added."
  - "The line carries what the phone needs (data-n: loves without the member's own; data-p: praying without theirs; data-by: the newest lover who isn't them, already printed in the line). A post with nothing yet has no line; the script adds one under the icons."
  - "/my/news/react answers JSON when asked (Accept: application/json), the same checks as the form post (session, same-origin, the per-person limit: member_portal_church._signed_in/_allowed) and the same toggle; church_news.react fills `state['on']` from what it already knows (no read more). The form post without JSON is unchanged. Today's RX_JS (the old look, a moment's Love, Prayers only's I'm praying) is unchanged."
related: [2026-11-20-lumen-home-look-5-1.md, 2026-11-20-lumen-share.md, 2026-11-20-lumen-feed-look-5-1.md]
---
Moments now draw Share through `member_lumen_share` (#1986) instead of their own copy. No new read, no
route, no CSS. Checked: switch off and MEMBER_LUMEN=preview for a non-owner, 951 page x scene dumps (Home
harness 656, Bible harness 295) identical to main; switch on also identical (Watch's state clock aside).
Home with a public event moment (the share harness) identical to main. Reads per page identical
(Home harness 493 / 493 over 82 pages).

Loved by: no new read (the counts and the lover were already on the page; the route's answer comes from the
toggle it already did). Switch off and preview for a non-owner: identical to main (dumps below in the PR).
