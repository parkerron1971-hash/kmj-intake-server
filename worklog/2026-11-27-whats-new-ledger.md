---
title: What's New from the database (step 1 of the rework, the backend)
date: 2026-11-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Through KAI, Kevin: "yes to all" on the What''s New rework plan; build it in the plan''s order, one PR a step, the backend first, the migration as an APPLY file Kevin applies'
status: in progress
prs: []
migrations: [supabase/APPLY-2026-11-27-whats-new.sql (NOT APPLIED; staged in Kevin's SQL editor)]
left_undone: ["the merged-PR ingest (a PR's whats-new block becomes a draft) and drafts for merged PRs without one", "news drafts written from published updates", "Chief's whats_new tool", "importing the old ledger and the open sweep / news PRs' entries once the file is applied", "the frontend steps (card, bell, Show me, listen, Mission Control queue)"]
decisions: ["three server-only tables; the app reads them only through /updates/for-me and /updates/seen", "seen-state per login and business; something counts as new for 30 days", "roles is new: an owner-only update (the plan and bill) never reaches a seat", "a group_key folds one feature shipped over several PRs into its newest row", "a church reads church_title/line/body when an update has them; Mission Control warns about business words a church would read and church words a business would read"]
related: [solutionist-studio:docs/whats-new-rework-plan.md, solutionist-studio:worklog/2026-11-27-whats-new-rework-mockups.md]
---
Read both repos' work logs: nothing earlier keeps updates in the database
(`platform_changelog` is Kevin's operator log, a different thing). This PR adds
`platform_updates.py` and its tables: who an update is for (kinds, church areas,
the new roles, the day the login joined), how the card ranks (made for them,
their area or role, a page they opened lately, big over small, newest), a
church's own words, seen-state per login, and the platform owner's queue and
news drafts with wording warnings. Checks: `__tests__/test_platform_updates.py`
(15; two rules broken on purpose and caught) and `__tests__/whats_new_db.mjs`
(21, PGlite, in CI). Until the file is applied the routes answer an empty list,
and the app keeps the list it has built in.
