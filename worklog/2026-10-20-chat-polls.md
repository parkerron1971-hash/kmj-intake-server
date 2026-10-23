---
title: Polls in a group's chat
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-20: "let''s continue so we can finish up". From the approved canvas "Church Groups, Together" (board Chat: "Potluck theme for Nov 19? · Soul food 9 · Breakfast for dinner 4 · Taco bar 3 · 16 votes · closes Friday"; board Settings: "Photos and polls")'
status: shipped
prs: [kmj-intake-server#1545]
migrations: [supabase/APPLY-2026-10-20-chat-polls.sql (applied)]
left_undone: ["photos in the chat (next PR; the same groups.chat_extras switch will cover them and its label becomes Photos and polls)"]
decisions: ["anyone who can write in a group's chat, or the leaders' room, posts a poll from the composer's +: a question and 2-4 different choices (60 characters each); never in a private chat", "a poll is a message: the question is its text, the question and choices are checked together, a held poll is held whole and only its sender sees it", "everyone in the chat sees the counts, never who voted; one vote each, the same choice again takes it back, another changes it; voting closes a week after it's posted, shown in the church's time", "a group's leaders turn polls off on the People tab (groups.chat_extras, on by default); the office's chat switches still decide who writes", "the + also opens the group's prayer wall; a new message never reloads the page over a half-typed poll", "if the choices can't be saved the question is taken back down (status removed), never left as a bare message"]
related: [2026-10-20-group-chat.md]
---
`chat_polls.py` (new): `choices_from`, `attach`, `for_messages`, `vote`, `closes_text`, `card`, `form`, POLL_CSS. `member_portal_messaging`: send takes `poll=1` + `choice`; POST /my/messages/{tid}/vote; `group_chat_settings` reads chat_extras. `member_portal_groups`: poll cards, the + tray, the new-poll form (`?make=poll`), the People tab's Polls in the chat switch (POST /my/groups/extras). `member_portal_church`: the words. `account_lifecycle`: msg_polls + msg_poll_votes exported, never re-imported.

Checks: 17 tests in `test_chat_polls.py` (21 sabotages caught; a missing import on the leaders' room page was caught by one of them); `chat_polls_db.mjs` 19 checks on PGlite, in CI. Rollback probe on the live database (a poll and a vote through every trigger), then a second as service_role. Rendered at 390 and 1280.
