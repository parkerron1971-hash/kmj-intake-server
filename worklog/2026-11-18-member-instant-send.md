---
title: Instant send in the member app — a message shows the moment a member taps Send
date: 2026-11-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-18: "the members app move slow when send messages in chat, switching from one tab to another… what is the problem and how can that be sped up?", then "yes build all four". This is fix 1 of 4 (instant send); the stopwatch + server caching and faster tab switching are other sessions.'
status: in review
prs: [kmj-intake-server#1945]
migrations: []
left_undone:
  - "The leader's desk on a computer (group_desk.script) injects the chat's script with x.textContent = '<script>…</script>', a syntax error that predates this; the desk's chat stays a plain post that reloads. Fix: run each <script>'s text, then check it in a browser."
  - "The old live page (LIVE_ROOM=off, the way back) keeps its post-then-poll; only the live room got instant send."
  - "A photo or a poll in a group chat is still the plain form post (multipart; they have their own forms)."
  - "A retry while the first send is still being checked on the server (a second or two) can still save twice; only a retry after the first was saved is caught."
decisions:
  - "Progressive: the same routes answer Accept: application/json with JSON, everything else with the same 303s. Same checks in the same order; the safety check still runs before the save, so nobody else sees an unchecked message."
  - "Sent: the bubble is swapped for the server's own (the page's renderer: member_portal_threads._bubble, member_portal_messaging._bubble, member_portal_groups._chat_item, now shared by the page and sent_item). Held and care: the page's own flash markup (member_portal_church.flash_html), shown above the box; care stays."
  - "Not sent: the bubble comes out, the words go back in the box, today's words say why, with Try again. A lost answer (offline, a proxy page) makes the same words a retry (retry=1); the route answers with the same words saved by the same person in that conversation in the last 10 minutes instead of saving twice. A church conversation row doesn't keep a crisis verdict, so a retry checks the words again (the crisis floor when the check is down) to show 988."
  - "Chats' polls: the feed adds `last` (newest id); a long chat's count stops at 80, so a new message there never reloaded the page before. The send answers count and fresh (nobody else wrote since the page's newest): fresh moves the poll's marks, else the next poll reloads. No poll while a message is on its way or while they type."
  - "MEMBER_INSTANT_SEND=off renders each page's old script (byte-identical group chat render checked)."
related: [2026-11-17-church-threads.md, 2026-11-17-one-messages.md]
---
Before: a member's send was a full form post (or a fetch that waited), the
safety check (Haiku, ~0.5–2 s), the save, a redirect and a reload of the whole
conversation, with the screen frozen. Now the bubble shows in under 10 ms of
the tap (measured in the page), marked "Sending…", the box clears and keeps the
keyboard up, and the answer swaps in the server's bubble ("Sent", then it
fades).

- `member_instant_send.py` (new): the switch, the JSON helpers, the retry
  window, and the one script every conversation uses (it adds its own styles).
- `member_portal_threads.py`: the church conversation's route answers JSON;
  `send_message(saved=, retry=)`; `church_script()`.
- `member_portal_messaging.py`: the send's JSON answer (`sent_json`), the retry
  lookup, `last` on the feed, `chat_script()` for a private chat.
- `member_portal_groups.py`: `_chat_item` (the per-message renderer, moved out
  of `_chat_body` unchanged), `sent_item`, `chat_script()`.
- `member_portal_live.py`: the live room shows the message at once and settles
  it by id; a retry finds it.
- `__tests__/test_member_instant_send.py`: 37 tests, each rehearsed red (26
  against main's routes; the 11 that pin unchanged refusals and the off
  switch, by a mutation each). Updated pins: the feed's shape
  (test_church_threads), the send's JSON (test_member_messaging, test_live).

Checked in Playwright on an iPhone-13-sized screen, Chromium and WebKit, over
the real pages and routes with the test fake and a 1.5 s safety check: sent,
held, care (the crisis words on screen above the box), too soon, check down,
offline, a lost answer, a double tap, a reply, someone else writing, the live
room. The fetch sends its real Origin (same-origin), not null.
