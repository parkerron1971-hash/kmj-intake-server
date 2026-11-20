---
title: "Member app new look (Look 5.1) tidy-ups: moments share through member_lumen_share; Loved by updates in place; Send to someone at church"
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: "Three small tidy-ups Kevin approved after Look 5.1 (#1985-#1994, #1999, #2010): the moments use the share helpers; 'Loved by' updates in place; 'Send to someone at church' in the share sheet. One PR each."
status: shipped
prs: [kmj-intake-server#2017, kmj-intake-server#2021, "kmj-intake-server (3 of 3: Send to someone at church)"]
migrations: []
left_undone:
  - "Send to someone at church shows only where Messages' header count was read for the page (church threads open, and not the Kids space). A church with chats on but church threads closed never gets the row: no read was added to learn it there."
  - "The picker doesn't offer the church office, a chat request or Your teens; a note carried to a group whose chat is closed (notes only) isn't offered either."
  - "Love in a moment's viewer (a pastor's post, member_lumen_stories) is still today's RX_JS form: it doesn't turn the same post's heart or 'Loved by' in the feed below until the next page."
decisions:
  - "Moments: member_lumen_stories' hand-written share_link, events_on, event_shareable, event_picture, message_art, message_href, MOMENT_OF and EVENTS_HREF are gone. A moment's Share is member_lumen_stories.share(), which calls member_lumen_share.link('moment', ...) with the moment's icon and class: byte for byte the markup #1994 wrote (kind moment, data-share-id '<message|event>:<id>', aria-label Share). member_portal_lumen.render_home takes message_href, EVENTS_HREF, message_art, event_shareable and event_picture from member_lumen_share."
  - "member_lumen_share.attrs refuses a moment that doesn't name one of the church's own kinds ('<message|series|event>:<id>'), the guard the stories helper had. No moment without an id gets a Share."
  - "Event moments: upcoming_for has marked each occasion public since #1986, so a public event (and the service, when it is on the public events page) gets Share while the church's public events page is on. Pinned through the real upcoming_for: a public event shares, an invite-only one doesn't, none with the page off. Groups, members' posts and devotionals never."
  - "Loved by (#2: member_lumen_feed): Love and Praying on a feed card are the feed's own forms (lf-rxf, no longer nw-rxf), answered by the feed's script: the heart turns and the line is redrawn on the phone at once (likes(): 'you' added or taken away, the count moved, the server's own words: 'Loved by Ben and 6 others', 'Loved by you', 'N people', '· N praying'), then POST /my/news/react's JSON answer {ok, on, kind} is the truth; a refusal or a lost answer turns both back. Double-tap goes through the same form. No motion added."
  - "The line carries what the phone needs (data-n: loves without the member's own; data-p: praying without theirs; data-by: the newest lover who isn't them, already printed in the line). A post with nothing yet has no line; the script adds one under the icons."
  - "/my/news/react answers JSON when asked (Accept: application/json), the same checks as the form post (session, same-origin, the per-person limit: member_portal_church._signed_in/_allowed) and the same toggle; church_news.react fills `state['on']` from what it already knows (no read more). The form post without JSON is unchanged. Today's RX_JS (the old look, a moment's Love, Prayers only's I'm praying) is unchanged."
  - "Send to someone at church (#3: member_lumen_share): the sheet's last row, as the mock draws it (a round plane icon, 'Send to someone at church', 'Inside the app, to a member or a group', a chevron), drawn hidden. It shows when the page's script tag says data-send=1: member_lumen_share.send_open() reads Messages' own count for the page (member_portal_threads.counts, already read for the header, kept 15 s), which now marks 'chats' (the church's chats on and may_chat: a birthdate, the member's switch, the guidelines) from what it already checked. No read more; unknown is hidden. The sheet opens only on church content, so the row does too."
  - "The row goes to /my/messages?say=<title> <public link> (capped at 300 characters, the title cut first). The new-look inbox is then the picker (both inboxes: member_portal_threads._lumen_messages / lumen_inbox_page and member_portal_messaging.render_inbox): the note on top, 'Pick a person or a group. Your note waits in the box until you press Send.', Your chats (group chats while open, the leaders' room, private chats) and Start a chat, each carrying the note. Nothing more is read."
  - "Choosing someone opens the conversation with the note in the box, unsent: private chats already took say (/my/messages/to/<person>?say= and the chat page); group chats and the leaders' room (member_portal_groups._chat_body, new look) now do too. The member presses Send. The rules hold: startable's teen rules, a block refused at /my/messages/to/, the church's switch and a member who can't chat get the gate."
  - "say (member_portal_messaging.say_of / with_say): control characters and runs of space made one space, at most SAY_MAX (300), escaped on the page, quoted in links; only the content's title and public link."
related: [2026-11-20-lumen-home-look-5-1.md, 2026-11-20-lumen-share.md, 2026-11-20-lumen-feed-look-5-1.md]
---
Moments now draw Share through `member_lumen_share` (#1986) instead of their own copy. No new read, no
route, no CSS. Checked: switch off and MEMBER_LUMEN=preview for a non-owner, 951 page x scene dumps (Home
harness 656, Bible harness 295) identical to main; switch on also identical (Watch's state clock aside).
Home with a public event moment (the share harness) identical to main. Reads per page identical
(Home harness 493 / 493 over 82 pages).

Loved by: no new read (the counts and the lover were already on the page; the route's answer comes from the
toggle it already did). Switch off and preview for a non-owner: identical to main (dumps below in the PR).

Send to someone at church: no new read (the picker reads what the inbox reads: 29 in the harness), no route,
no write, no migration. Switch off and preview for a non-owner identical to main; switch on differs only by
the hashed file names and the script tag's data-send mark. Shots: the session scratchpad's tidy-shots/
(3-sheet-send, 4-picker, 5-conversation, Chromium and WebKit, light and dark).
