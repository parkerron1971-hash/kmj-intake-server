---
title: The Bible marks database test no longer flips on a tied clock
date: 2026-10-19
agent: Claude Code (Claude Opus 5.5)
asked: '"yes fix it" (Kevin, 2026-10-19, the paste reader; this flaky test failed that PR''s CI)'
status: shipped
prs: [kmj-intake-server#1507]
migrations: []
left_undone: []
decisions: ["the test waits 5 ms before its newest mark, instead of changing what the newest-first list sorts by: the server's order is right; only the test's clock was too coarse"]
related: [kmj-intake-server worklog/2026-10-19-member-app-bible.md, kmj-intake-server#1506]
---
`__tests__/bible_marks_db.mjs` checks that the newest mark comes first in the Highlights & notes order (`updated_at DESC`). It saved two marks back to back. PGlite's `now()` ticks in whole milliseconds, with no part below that: a probe found 143 of 200 back-to-back statements on the same time. When the two saves tied, either could come first, and CI failed on #1506 with `'1CO' !== 'PSA'`. The test now waits 5 ms before saving the newest mark.

Checks:
- 15 local runs before: 2 failed.
- 15 local runs after: 0 failed.
