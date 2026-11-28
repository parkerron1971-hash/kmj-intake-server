---
title: Every group has a leader, on for every church (M-8 switch-on)
date: 2026-11-28
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin ran the group-leads SQL and says turn it ON FOR EVERYONE. Make the code default on, so the merge alone does it with no Railway step"
status: shipped on merge
prs: [kmj-intake-server (this PR)]
migrations: [supabase/APPLY-2026-11-28-group-leads.sql (APPLIED 2026-11-28; check after read 5 columns, 3 triggers, 0 co-leaders)]
left_undone: []
decisions:
  - "GROUP_LEADS now defaults to on (church_group_leads.mode() and church_follow_up.group_leads_open's fallback). Checked first, read-only: GROUP_LEADS is not set on either Railway service (kmj-intake-server, kmj-intake-worker), so this merge is the switch-on"
  - "Rollback: GROUP_LEADS=owner (Love City only) or off, on BOTH Railway services"
  - "The older tests keep owner through __tests__/conftest.py, as CHURCH_MAP does since #2121; test_unset_means_on_for_every_church holds the new default"
related: [2026-11-28-m8-group-leads.md, 2026-11-28-m8-serve-to-team.md, 2026-11-28-m8-map-person.md]
---
The switch-on for M-8. With the SQL applied and #2120 to #2124 merged, every
church's office can name a group's leader and co-leaders and who it answers
to, a lead adds their own co-leaders on the Lead tab, and a Serve sign-up for
a team's choice reaches that team's own leader. The leaders map (CHURCH_MAP)
went on for every church with #2121.
