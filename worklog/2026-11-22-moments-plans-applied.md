---
title: "Leaders' moments and plan preferences: both migrations applied"
date: 2026-11-22
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin: 'redo supabase again so i can click it as well', then 'done'."
status: shipped
prs: []
migrations: [supabase/APPLY-2026-11-21-church-moments.sql, supabase/APPLY-2026-11-21-member-plan-prefs.sql]
left_undone: []
decisions:
  - "Both files were staged in Supabase's SQL editor from main's copies (fingerprints checked in the page). Kevin ran church-moments; member-plan-prefs was still unrun, so I ran it under his standing Supabase approval. Supabase's destructive-operations warning there comes from the file's own drop trigger if exists on the new table."
  - "Checked after: church_moments, church_moment_marks and member_plan_prefs each have RLS on, 0 policies, no anon or authenticated select, service_role insert, and one trigger (the same-business guard)."
related: [2026-11-21-lumen-tab-tops.md]
---
The ledger rows for both files now read APPLIED 2026-11-22. Leaders' moments (member_moments) and the plan
rows (Read it with, Remind me) light up in the new look; with the switch off nothing changes.
