---
title: Chief keeps a short summary of a long conversation instead of dropping its start
date: 2026-11-25
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-24: "how are we storing the memory? can chief compact memory like you do when you need to?", then, on the three things I said I would add (a running summary inside a conversation, a tidy-up of memory notes, a short digest per person): "ok great. lets build this." This is the first of the three'
status: waiting on Kevin
prs: [kmj-intake-server (this PR)]
migrations: [supabase/APPLY-2026-11-25-chief-thread-summaries.sql (NOT APPLIED)]
left_undone:
  - "NOT APPLIED: supabase/APPLY-2026-11-25-chief-thread-summaries.sql. Until Kevin runs it nothing is summarised or stored and Chief works exactly as before"
  - "The other two of the three: a tidy-up of memory notes (merge near-duplicates, retire stale ones) and a short digest per person. Not started; each is its own change"
  - "Voice calls send no chat id (ChiefCallMode.tsx), so a long call is not summarised. The strategy coach is left out on purpose (its own persona and history)"
  - "A turn answered by the stream's quick first track never reaches chief_chat, so it neither reads the summary nor folds; the next full turn does both"
  - "Old rows are never cleared: one small row a chat. The table has an index on updated_at for a sweep; the sweep is not built"
  - "The summary is only as good as the small model's read of the messages. No live Chief eval was run, and no real conversation was summarised"
decisions:
  - "The app sends the last 30 messages of a chat (ChiefOfStaff.tsx MAX_API_HISTORY 30) and the server never sees the rest, so the state has to live on the server: one row a chat, keyed by business, login and the app's chat id (conversation_id, already sent with each turn)"
  - "Folded after the reply, off the request, in a thread: one background-lane call (Haiku 5.5 by default) once 6 of the oldest messages aren't in the summary. The newest 12 are never folded. So a long chat pays one small call about every three turns (a turn-by-turn run in the tests pins it), and a chat under 18 messages none"
  - "The row keeps fingerprints of the last messages folded in, not their text; the last three are an anchor that says where the summary ends in the next window the app sends. Not found (folds were missed), the summary is kept and the window is folded from its start: a message may be folded twice, never dropped. A row is always this chat's: the app makes a new id for every new chat and only brings one back with its own messages"
  - "Chief reads the summary in the turn's tail (never a cached segment), fenced as a record of the same conversation and not an instruction. The 2026-09-03 lesson: app-written text inside the user turn reads as an injection to the model, so it rides the system tail"
  - "The summary's writer is told to record what was said, never to address anyone, and to say when something was quoted from someone else; tag syntax is stripped on the way in and on the way out; it is one paragraph between a first and a last line that say what it is"
  - "After an independent review, which found the first version unfit to switch on. (1) It held any summary untrusted_text.detect_injection matched, and marked the messages folded: an honest church sentence ('asked Chief to send a text to all contacts') trips that check, and the messages were then gone for good. The hold is removed; why is in the module. (2) It folded on every turn once the window was full (67 calls in 68 turns); now about every three. (3) It threw the summary away whenever the window was short and the anchor missing, which canned replies made common; a row is never reset now. (4) The answer check was handed the summary as a business record; it is handed it as conversation. (5) The app's own sentinel messages were sent to the writer as the person's words; they are left out. (6) The same exchange twice in a window skipped what lay between; the anchor's earliest place is believed. (7) The table is out of the owner's export (it is keyed by sign-in ids), and goes with the business"
  - "units=0: the business's AI credits are not charged for housekeeping nobody asked for. It is metered to the business, so the daily spend cap sees it and stops it"
  - "Server-only table (RLS on, no policies, browser roles revoked). One login's summary is never read for another login: the owner does not read the team's through this"
  - "A write names the version it read, so two replicas folding the same chat can't both land"
related: [2026-11-24-chief-turns-saved-by-login.md, 2026-11-24-owner-reads-team-conversations.md]
---
Read both repos' work logs first; nothing open touches the chat history.

`chief_thread_summary.py` holds it: `block_for` before the reply, `after_turn`
after the turn is saved, both called from `chief_of_staff.chief_chat`.
`account_lifecycle` clears the table with a business. Tests:
`__tests__/test_chief_thread_summary.py` and, on a real Postgres,
`__tests__/chief_thread_summaries_db.mjs`.

Kevin applies the SQL by hand; its checks and rollback are in the file.
