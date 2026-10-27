---
title: Paid sign-ups and help requests migrations applied to production
date: 2026-10-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-27: "you can apply everything that is need far as supabase and even railway."'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: ["supabase/APPLY-2026-10-27-church-event-signups.sql (APPLIED 10/27)", "supabase/APPLY-2026-10-27-church-help.sql (APPLIED 10/27)"]
left_undone: ["Railway unchanged: CHURCH_PAID_SIGNUPS and CHURCH_HELP stay at owner until the Thursday switch-on tasks on Plan"]
decisions: ["The help file's `drop trigger if exists` made the SQL editor ask for a confirmation (\"Potential issue detected\"); it only recreates the trigger on its own new table, so it was confirmed"]
related: [2026-10-27-church-migrations-applied.md]
---
Checked after applying: the three church_event_* tables and four
functions, and the three church_help_* tables, all with RLS on and 0
policies; the same-church trigger is on church_help_requests.
