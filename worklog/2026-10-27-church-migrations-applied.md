---
title: Rooms & spaces and pledges & campaigns migrations applied to production
date: 2026-10-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-27: "you can apply everything that is need far as supabase and even railway."'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: ["supabase/APPLY-2026-10-27-church-spaces.sql (APPLIED 10/27)", "supabase/APPLY-2026-10-27-church-pledges.sql (APPLIED 10/27)"]
left_undone: ["Railway: nothing changed. CHURCH_SPACES and CHURCH_PLEDGES stay at their default (owner) until the Thursday switch-on tasks on Plan"]
decisions: ["Both ran in the production SQL editor (project kmj-solutionist-studio, ref brqjgbpzackdihgjsorf), verified by schema first (audit_log, business_customers, businesses present)"]
related: [2026-10-27-church-spaces.md, 2026-10-27-church-pledges.md]
---
Checked after applying: church_spaces, church_space_bookings,
church_campaigns and church_pledges exist with RLS on and 0 policies,
and the exclusion constraint church_space_bookings_no_clash is in place.
docs/MIGRATIONS.md now says APPLIED for both.
