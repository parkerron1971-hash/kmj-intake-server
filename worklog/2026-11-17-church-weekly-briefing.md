---
title: A church's weekly briefing is about the church's week, in a church's words
date: 2026-11-17
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-17: "let''s work on those changes as well" (the church pages still in business words; the Briefing page''s letter is written here)'
status: in review
prs: [kmj-intake-server#1890]
migrations: []
left_undone:
  - "Giving is not in a church's letter: the Briefing page opens to office logins that never see giving, and one letter is kept for the whole church. Kevin's call if the pastor wants giving in his own letter (it would need a letter per reader, or the page gated)."
  - "Letters stored before this change keep their old business headings."
  - "No real model-written church letter has been read: tests use fakes, and live evals bill production."
decisions:
  - "A church's letter gets its own instructions and its own facts (church_weekly_briefing): Sunday counts, first-time guests, new people, follow-up, meetings, drafts waiting, places still open, the next seven days. Same model, same one call, endpoint auth and metering untouched."
  - "Every line about people is a count. No names, no health scores, no payments, in the prompt, the stored record or the endpoint's reply."
  - "The week in numbers, Places still open and Coming this week are printed under the letter as read, not by the model. A part that could not be read is said as not read this time, never zero."
  - "A church's check-in and meeting follow-up drafts are prompted without scores or the word session."
related: []
---
`growth_engine.run_growth_briefing` wrote every business the same letter: new
contacts, sessions, payments, at-risk clients by health score. A church got
that letter over numbers that mostly sat at zero.

- `church_weekly_briefing.py` (new): `week(biz)` reads the church's week with
  service-role reads held to a named table list; `system_prompt`, `facts`,
  `numbers_markdown`, `actions_markdown`, `fallback_body`; the church prompts
  for the check-in and meeting follow-up drafts.
- `growth_engine.py`: for a church only, the briefing uses the above; what it
  stores and hands back leaves out the payment lines and the names the
  business letter read. A business's prompt, data and stored numbers are
  unchanged (a test holds them).
- `__tests__/test_church_weekly_briefing.py`: 20 tests.

The page around the letter is the frontend's (solutionist-studio, the Home
pages pull request).
