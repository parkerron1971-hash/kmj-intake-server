---
title: Find my best clips is announced (plan cards and the compare table)
date: 2026-10-05
agent: Claude Code (Claude Opus 5.5)
asked: "to the questions, I would say tighten the checker but don't have it so tight nothing is produced. you can go."
status: done
prs: [kmj-intake-server announce-find-my-best-clips, solutionist-studio announce-best-clips]
migrations: []
left_undone: ["Posting a clip with its cover through Post for Me is not built"]
decisions: ["ai_clips is sold on the Solutionist plan only, as it was gated", "The compare row sits under Your presence, next to publishing", "The FE label merges first so a card never shows the raw key"]
related: [2026-10-05-clip-covers.md, 2026-10-05-remember-this-style.md]
---
Kevin opened Find my best clips to every business after the live Church proof
(upload, four clips, covers, saved style) and then said "you can go" to the
announcement. ai_clips leaves UNANNOUNCED_FEATURES (now empty) so
/billing/plans lists it on the Solutionist card, and leaves _NOT_A_ROW, so it
gets a compare row under Your presence. The row's "ten hours a month" is
pinned to clip_finder.INCLUDED_SECONDS by test. The industry plans (solo,
booked, boss) still do not carry it.
