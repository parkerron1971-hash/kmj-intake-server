---
title: Chief says members and guests to a church, not clients and leads
date: 2026-10-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-27: Office "stuff is missing… what need to be reworded" → "lets start building this"'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone: []
decisions: ["Lane: Fix. The app's church word list (FE #1375) maps client, lead, prospect and offering; the server's didn't, so Chief kept the business words", "Same words as the app: client(s) → Member(s), lead(s) and prospect(s) → Guest(s), offering → Item, offerings → Store"]
related: []
---
`vertical_terminology.py`: the ministry entry gains client(s), lead(s),
prospect(s) and offering(s). `__tests__/test_church_words.py` pins them
and checks other businesses keep Client and Lead. The related
terminology and church test files pass (563 tests).
