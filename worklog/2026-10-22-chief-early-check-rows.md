---
title: Chief's early sentence check works on a business with real records
date: 2026-10-22
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "pull the slow turns" then "yes start with #1" (after a TikTok tip about chunking words; the slow-turn breakdown said the early check never ran)'
status: shipped
prs: [kmj-intake-server#TBD]
migrations: []
left_undone:
  - "Measure live after deploy: `[chief prefix review]` lines should show dispatch/accepted instead of evidence_budget, and `[voice flow]` first_answer_text_ms should drop on turns that open with a one-record fact. Logs are per deployment: railway deployment list, then railway logs <id> --lines 5000"
  - "#2 from the slow-turn list, not built: the final check's trim loop chased 'draft number 10,18 has no reviewed claim' three times (about 10 s) and then withheld the reply (2 of 13 turns on 2026-10-20)"
  - "#3, not built: billing gates (1-3.5 s) and record gathering (1-7 s) run one after the other before the main call starts"
  - "FOUND, NOT FIXED: on a turn that reads with a tool, the second Sonnet call's text arrives in one burst at its end (first_text_ms within 20 ms of end_ms, 2026-10-20), so no sentence can stream before that call finishes"
  - "FOUND, deliberate: an uncited sentence that addresses the owner or starts with a capital ('Hey, good to hear from you.', 'Fair question') is always held by the early check's guard, and a held sentence stops the early stream. Loosening that is Kevin's call"
decisions:
  - "A list source is matched row by row: every row that shares a word or carries a warning is kept, a row is never cut, a cut-off last row is kept verbatim when it matches, and a list the sentence names stays whole. A narrowed list says rows_omitted and is never complete"
  - "Everyday words (hey, good, hear, question, step...) no longer pull records in; a record noun, state word or standing-claim word is never one of them"
  - "Limit 14,000 -> 24,000 characters: Haiku 5.5 answered in 0.74 s median, 1.4 s p90 on KMJ's records (the streamer allows 4 s), about $0.0007 a check"
  - "Every name in an early sentence must sit in the record item the quote came from. Haiku approved 'Monica Walton's invoice INV-2026-013 is for $55' (Demetrio's invoice) in 4 of 8 live runs; the name check held all 3 that ran after it was added. This also closes the hole for small businesses, where all records always fit"
  - "Rollback is the existing CHIEF_CONTINUOUS_STREAM=off (turns the whole early check off)"
related: [2026-10-18-chief-tone-notes.md]
---
On 2026-10-20 Kevin's voice turns waited 10-33 s for the first real
answer; the early sentence check (`chief_truth._stream_review_sources`)
gave up on 12 of 13 turns because one shared word anywhere in a 10,000-
character list (memories, modules, events) brought the whole list in.
Replayed offline on 31 real sentences with KMJ's records, 1 fit the old
14k limit; with row matching 9 fit at 14k and 17 at 24k. Live on Haiku
with true and planted-false sentences from KMJ's records: 24 of 27 true
passed (the 3 held name the whole contact list, too big to check early),
0 of 33 plants passed. Tests: `__tests__/test_chief_early_check_rows.py`;
`test_chief_connected_stream.py` fixtures now size against the limit.
