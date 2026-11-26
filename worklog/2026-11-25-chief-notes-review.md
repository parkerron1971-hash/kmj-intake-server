---
title: Chief can go through its notes with the owner, and says when some aren't being carried
date: 2026-11-25
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-24, on the three things I said I would add to Chief''s memory (a running summary inside a conversation, a tidy-up of memory notes, a short digest per person): "ok great. lets build this." This is the second'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Nothing tidies by itself. I told Kevin 'every so often, merge near-duplicates and retire stale ones'; what is built is a read the owner asks for (or Chief reaches for when its notes block says some aren't carried), and the owner picks. Why is in the decisions"
  - "How many notes real businesses keep was not looked at (no production read was asked for). If none is near 50, the 'not carried' part does nothing yet"
  - "The third of the three (a short digest per person) is not started"
  - "The outside-agent surface's forget still takes a phrase only"
  - "No live Chief eval was run"
decisions:
  - "A read, review_memories, that changes nothing: how many notes are kept and how many a reply carries (the top 50, picked the way the turn picks them), which are not carried, which look alike, which nothing has used in 180 days"
  - "No automatic merging. The write path's own dedup matched on shared words until it erased a correction ('do not take Friday calls' read as 'take Friday calls'; chief_of_staff._find_duplicate_memory). Two notes that share their words are grouped and, when they differ by a not, a number, a day or an amount, marked may_disagree: Chief shows both and asks which is true"
  - "No retiring by age. A note nobody has used in a year may be the one that matters next week. Old notes are listed for the owner, never dropped"
  - "forget takes a note's own id (memory_id), checked against this business's active notes: of two look-alikes, a phrase can pick the wrong one"
  - "Under its notes Chief now reads one line when more are kept than it carries, so it looks before saying it doesn't have something. Nothing is added for a business whose notes all fit (nearly all)"
  - "The owner's in a church lane (as remember and forget are), and Chief's alone: not on the outside-agent surface"
related: [2026-11-25-chief-long-chat-summary.md]
---
Read both repos' work logs first; nothing open touches Chief's notes.

`chief_memory_review.py` holds the read; wired in `action_registry`,
`chief_areas`, `chief_tool_loop`, `chief_of_staff` (handler, phrase, the line
under the notes, forget by id) and `chief_prompt`. Tests:
`__tests__/test_chief_memory_review.py`.
