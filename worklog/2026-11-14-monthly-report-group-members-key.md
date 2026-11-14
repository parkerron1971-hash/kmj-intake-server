---
title: The monthly report reads Sunday teams again (group_members has no id)
date: 2026-11-14
agent: Claude Code (Claude Opus 5.5)
asked: "Found by the sample-church seed work (BE-2): church_monthly_report selected and ordered group_members by id, a column that table doesn't have."
status: shipped
prs: [kmj-intake-server#TBD]
migrations: []
left_undone: []
decisions:
  - "group_members' key is (group_id, contact_id) (supabase/APPLY-2026-09-30-groups.sql). The Sunday-teams read now selects group_id,contact_id,joined_on and pages in that order. Before, PostgREST refused the read and every church's monthly report said Sunday teams couldn't be read (the 'People new to a Sunday team' line)."
  - "The test fake had given group_members rows an id, which hid it; the fake now mirrors the real table, and a new test pins the columns and the paging order. It fails on the old code."
related: [2026-11-15-sample-church-be2.md]
---
A small fix, Fix lane.
