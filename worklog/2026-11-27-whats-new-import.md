---
title: What's New, the old list into the new table (the import)
date: 2026-11-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Through KAI, after the account-2 cross-review (kai/reviews/whats-new-rework-review.md): Kevin said yes to writing the import first; imported rows don''t count as new for anyone; fix "done for this week" per business if that''s what the design meant'
status: in progress
prs: []
migrations: []
left_undone: ["run it: POST /platform/updates/sync-ledger once APPLY-2026-11-27-whats-new.sql is applied (the 15-minute job does it on its own too), then read one practitioner's /updates/for-me", "solutionist-studio#1726 goes after this is live", "step 4 retires the file; until then the sync keeps adding what PRs append"]
decisions: ["read whatsNew.ts from GitHub (module-system) with the server's GITHUB_TOKEN, parse it, add what the table lacks; never overwrite (Mission Control edits win)", "old news stays old: a ledger row dated on or before WHATS_NEW_LEDGER_NEW_AFTER (default 2026-11-27) is never new, so the cut-over shows 0 new instead of 124 at a church / 52 at a coach; entries PRs add after that day are new as usual (a blanket 'ledger is never new' would have hidden every M-6 update until step 4)", "every 15 minutes, kill switch WHATS_NEW_LEDGER_SYNC=off; owner's run-now route", "a failed news-draft write is 503, not 404 (review nit)"]
related: [2026-11-27-whats-new-ledger.md, solutionist-studio:docs/whats-new-rework-plan.md]
---
`whats_new_ledger.py`: a small parser for the file's real shapes ('…', "…",
`…` without ${}, lists, comments, \u escapes and surrogate pairs) that refuses
anything else with the line it was on. On the real 699-entry file it matches
the TypeScript module's own export field by field, 0 differences. Each entry
becomes a published `source='ledger'` row with its first sentence as the card's
one line. `platform_updates.is_new` holds the "old news" rule. Checks:
`__tests__/test_whats_new_ledger.py` (13; the old-news rule broken on purpose
and caught) and the existing 16.
