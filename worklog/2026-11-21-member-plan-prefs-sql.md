---
title: "Plans: the table for reading with your group and a reminder (APPLY file, not applied)"
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: "Read it with your group + reminders: storage will likely need a table; ship it as supabase/APPLY-YYYY-MM-DD-*.sql (Kevin applies these by hand): RLS on, no policies, revoked from anon/authenticated, service_role granted, idempotent, same-business triggers; the shape of APPLY-2026-11-21-church-moments.sql. The SQL file can be its own PR before the feature PR."
status: shipped
prs: ["kmj-intake-server (this PR)"]
migrations: ["supabase/APPLY-2026-11-21-member-plan-prefs.sql (NOT APPLIED)"]
left_undone:
  - "Applying it: Kevin runs the file in the Supabase SQL editor when he's ready. Nothing reads the table until the feature PR lands, and the feature stays quietly absent until the file is applied."
decisions:
  - "One table, member_plan_prefs, one row a member a plan, for both choices: the group they read it with (null = on my own; a deleted group lets the choice go, on delete set null) and a reminder time on a quarter hour (null = none), plus reminded_on, the reminder sweep's once-a-day claim."
  - "The plan is named exactly as member_plan_starts names it ('reading:<key>' for a reading or topic plan, 'devotional:<uuid>'), with the same check."
  - "Server-only, as church_moments: RLS on, no policies, public/anon/authenticated revoked, service_role granted; a trigger keeps the member and the group inside the row's own church; one transaction, lock_timeout 5s, safe twice, ends with NOTIFY pgrst; checks and rollback in the file."
  - "account_lifecycle.EXPORT_EXCLUDED gets it with its reason (like member_plan_starts: keyed to devotional ids an import re-mints)."
related: [2026-11-21-lumen-plan-group.md]
---
The table for reading a plan with your group and a reminder at your hour. Not applied: Kevin runs it by hand.

Checked: PGlite check __tests__/member_plan_prefs_db.mjs, 24 checks (applied twice; the plan's name, the quarter hour, the
claim once a day, every row inside its church, a deleted group lets go, a member who leaves takes their rows, no
browser read or write). test_export_import passes with the table listed.
