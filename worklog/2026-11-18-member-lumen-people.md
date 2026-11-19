---
title: "Member app new look (Lumen) — the people pages: Messages, Prayer, Events, a group, Me, alerts, News"
date: 2026-11-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, on the approved "clean Lumen" mock (version 29, accent level 2): messages "look generic. it should feel like text messages area"; prayer, events and groups are "cool but there is no wow factor". Restyle Messages, Prayer, Events, a group''s page, Me (details, notifications) and News in the new look, in a few PRs.'
status: in review
prs: [kmj-intake-server#1962, kmj-intake-server#1963, "kmj-intake-server (a group, Me, alerts, News)"]
migrations: []
left_undone:
  - "Not checked on a real phone: Playwright Chromium and WebKit at 390x844 with reduced motion. The keyboard over the box (sticky at the foot) is untested on iOS."
decisions:
  - "Every page reads exactly what today's page reads (counted off and on, and against main, in the harness); off is byte for byte today's markup (81 page and scene dumps against main, all identical)."
  - "The inbox: the church's conversation pinned first on level 2's soft band ('From your church'), then one list newest first: groups, the leaders' room and private chats (today: separate Groups and Chats sections), each with its unread count; a chat request above with Accept and Ignore (messaging's own routes; 'Ignore', today's word, not the mock's 'Decline'); Start a chat and Your teens stay below."
  - "A group's row shows the group's initials on soft teal, not the mock's two faces: the inbox reads no member's photo for a group, and adding it would be a read of its own. A private chat shows the person's photo only where today's inbox does (member_photos.shown_to_members)."
  - "A conversation is a texting screen: its face and name in the bar (member_portal._shell lumen_head), no tab bar, bubbles (yours on the right in the church's colour), the box at the foot (sticky, with the round send button inside; dimmed while empty, CSS only). The church's notes and the office's replies are cards beside the church's mark, the replier's first name over the card."
  - "Instant send keeps its hooks: the same form, list, box and error ids; the bubble it draws while sending (li.mb-msg.mb-mine > .mb-msg-body, li.gc-m.mine > .gc-col > .gc-b) is the markup the new sheet styles; the JSON answer is drawn exactly as before (a POST never wears the new look). Tested in a browser (Chromium and WebKit, both looks): sent, refused (words back in the box) and held."
  - "Day lines: the church's conversation keeps the server's (church's clock). A private or group chat draws its own on the phone's clock from each message's time (data-at, new look only), again after each send: reading the church's clock there would be a read of its own."
  - "Read state is today's: unread counts and bold rows in the inbox, 'Sending…' then 'Sent' under a message on its way, 'Held for review'. No read receipts: when another member read a message is something members can't see today (privacy rules stay)."
  - "No times under your own bubbles (the mock has none); the church's notes and replies keep theirs. A group's chat names a person once per run of their messages (a gap of an hour, another person or a note starts a new run) and shows their face at its foot; names take one of four inks."
  - "A group's chat in the new look drops the group's hero and tabs: two of the group's faces (as its page shows them; the group's mark when none has a photo) and 'N people' in the bar, Back to where they came from (history), else the group. The chat's notices, 'Kind words only' and how you hear about it sit at the top."
  - "Coming up: each occasion a row with its day in the margin (weekday and month small in coral, the date in the serif), the same answers and forms as today's cards (I'm coming, You're coming, Serving: <role> with Just attend instead, Can't make it), Sign up to serve opening the open roles (a role is needed). An occasion has a day and no time: the line under it is where (and places left)."
  - "Prayer: the flame over 'How can we pray for you?', the request in the serif's italic, who prays with you as two cards over the same radio buttons (none chosen for them, as today: the mock pre-selected the team), Send to the pastors. The page answers on its own page ('Your pastors have it.' and who will see it): its form sends then=prayer and the route redirects to /my/prayer?done=prayer&s=...; today's form, without then, still goes Home."
  - "A group's page: no photo hero; its kind and who leads it in teal, its name in the serif, when and where, faces and the count (today's hero's rule: a member sees a few faces and how many, anyone else its leaders), and one segmented control for Home · Chat · Board · Prayer · Meet · People (Video while a meeting is open). Board posts as plain posts between lines; the Prayer and Meet tabs keep their own markup. Back is Connect."
  - "Me: the circle (the same photo form), the name in the serif, giving on the soft band (total and Give; months, each gift, statement, other years under it), one plain list of the same doors (no My classes: classes live on Connect). My details: the same form as quiet fields with labels over them."
  - "Your alerts: the bell list as built, its heading the new look's section with NEW while something is new; this phone keeps Turn on / Turn off buttons (the permission prompt needs a real tap), each kind a row with a switch (the same checkbox, CSS only) and Save."
  - "News: the heading in the serif, posts as plain stories between lines, filters as chips; Home's news card is untouched (scoped to the News page)."
  - "Class names kept clear of the other page sets: the composer row is .lm-cbox (.lm-crow is the foundation's), details are .lm-dform/.lm-dfield (.lm-field is the Bible's search)."
  - "The sheet: member_lumen_people.CSS_PEOPLE, a part of the hashed Lumen file through member_lumen_ui.templates() (member_app_ui.sheet builds the file from it), every rule under body.lm, nothing inline."
related: [2026-11-18-member-lumen.md, 2026-11-18-member-instant-send.md, 2026-11-18-member-alerts-list.md]
---
`member_lumen_people.py` holds the new look's people pages: the helpers (faces, inbox rows, a
conversation's bar, the send button, the day lines) and `CSS_PEOPLE`. The pages keep their
renderers and branch on `member_lumen.page()`: `member_portal_threads` (the inbox while church
threads are open, the church's conversation, a group's notes), `member_portal_messaging` (the
inbox while they're closed, a private chat), `member_portal_groups` (a group's chat, the leaders'
room, a group's page), `member_portal_church` (Coming up, Prayer, My details), `member_portal` (Me),
`member_push` and `member_alerts` (Your alerts), `member_portal_news` (News). Tests:
`__tests__/test_member_lumen_people.py`.

Measured locally (harness over the test fake, database time ~0; 30 warm requests, median
Server-Timing total, off / on): Messages 6.2 / 5.8 ms, the church's conversation 6.5 / 6.0, a
private chat 3.9 / 4.0, a group's chat 7.8 / 6.6 (main: 5.5 / 6.3, 5.3 / 6.2, 3.5 / 4.0,
6.4 / 7.4: noise). Coming up 1.7 / 1.7, Prayer 1.5 / 1.4, a group's page 3.8 / 3.0, Me 2.4 / 2.5,
My details 1.8 / 2.2, Your alerts 2.3 / 3.7, News 2.7 / 3.2 (main, on: 1.9, 1.4, 3.3, 3.1, 2.5, 3.0,
2.9: noise). Reads per page the same off and on and as main (Your alerts' two more under the new
look are the bell list's clock, as on main). A group's chat 70 KB → 53 KB, Me 18 KB → 14 KB.

Screenshots (mock beside build, Chromium and WebKit): the session scratchpad's
lumen-shots/people/side-by-side/.
