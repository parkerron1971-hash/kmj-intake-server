---
title: Chief knows where each person left off when they start a new chat
date: 2026-11-25
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-24, on the three things I said I would add to Chief''s memory (a running summary inside a conversation, a tidy-up of memory notes, a short digest per person): "ok great. lets build this." This is the third'
status: waiting on Kevin
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Does nothing until supabase/APPLY-2026-11-24-chief-conversations-by-login.sql is applied (Kevin applies it): a login's turns aren't saved before that, so there is nothing to read"
  - "It is what a person last asked and what didn't go through. It is not 'how they like things done': a note per person needs chief_memories to know whose a note is (a column), and is not built"
  - "Not for the owner: the owner's turn already carries the nightly digest and the app's 'while you were away' note"
  - "Only the last 14 days, and only at the start of a chat (two messages or fewer)"
  - "No live Chief eval was run, and nobody's real conversation was read"
decisions:
  - "No model call and no new table: a few lines read off the login's own saved turns (chief_conversations, kept by login since 2026-11-24), at the start of a chat, in the turn's tail beside the 'who you are talking with' card"
  - "The login's own rows only, by the verified login in the filter, read as the server. Never the owner's or another login's"
  - "What didn't go through comes first (up to three), then the last things asked, newest first, five lines at most. A request that failed or was held is the thing most worth picking back up: Jessica's held assignment (2026-11-23) is the case"
  - "Chief's own replies are left out (they can quote other people); only what it did and whether it went through. Tag syntax is stripped from the saved text"
  - "Said to Chief as a record, not an instruction: don't recite it; it may offer once to finish something that didn't go through"
  - "A turn under ten minutes old is this chat's own, not 'last time'"
  - "CHIEF_LAST_TIME=off turns it off"
related: [2026-11-24-chief-turns-saved-by-login.md, 2026-11-25-chief-long-chat-summary.md, 2026-11-25-chief-notes-review.md]
---
Read both repos' work logs first; nothing open touches the start of a chat.

`chief_last_time.py` holds it; `chief_of_staff.chief_chat` reads it beside the
who-card, before the login's block. Tests: `__tests__/test_chief_last_time.py`.
