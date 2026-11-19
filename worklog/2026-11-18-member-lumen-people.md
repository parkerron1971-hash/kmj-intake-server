---
title: "Member app new look (Lumen) — the people pages, step one: Messages (the inbox and a conversation)"
date: 2026-11-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, on the approved "clean Lumen" mock (version 29, accent level 2): messages "look generic. it should feel like text messages area"; prayer, events and groups are "cool but there is no wow factor". Restyle Messages, Prayer, Events, a group''s page, Me (details, notifications) and News in the new look, in a few PRs.'
status: in review
prs: ["kmj-intake-server (Messages)"]
migrations: []
left_undone:
  - "Next PRs, each from fresh main: Prayer and Events; then a group's page, Me (and My details), the notifications page and News."
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
  - "The sheet: member_lumen_people.CSS_PEOPLE, a part of the hashed Lumen file through member_lumen_ui.templates() (member_app_ui.sheet builds the file from it), every rule under body.lm, nothing inline."
related: [2026-11-18-member-lumen.md, 2026-11-18-member-instant-send.md, 2026-11-18-member-alerts-list.md]
---
`member_lumen_people.py` holds the new look's people pages: the helpers (faces, inbox rows, a
conversation's bar, the send button, the day lines) and `CSS_PEOPLE`. The pages keep their
renderers and branch on `member_lumen.page()`: `member_portal_threads` (the inbox while church
threads are open, the church's conversation, a group's notes), `member_portal_messaging` (the
inbox while they're closed, a private chat), `member_portal_groups` (a group's chat, the leaders'
room). Tests: `__tests__/test_member_lumen_people.py`.

Measured locally (harness over the test fake, database time ~0; 30 warm requests, median
Server-Timing total, off / on): Messages 6.2 / 5.8 ms, the church's conversation 6.5 / 6.0, a
private chat 3.9 / 4.0, a group's chat 7.8 / 6.6 (main: 5.5 / 6.3, 5.3 / 6.2, 3.5 / 4.0,
6.4 / 7.4: noise). Reads per page the same off and on and as main. A group's chat 70 KB → 53 KB.

Screenshots (mock beside build, Chromium and WebKit): the session scratchpad's
lumen-shots/people/side-by-side/.
