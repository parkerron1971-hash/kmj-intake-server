---
title: Every group has a leader, part 5 — worship ministries' leaders are the church's people (M-8)
date: 2026-11-28
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin said GO on mission M-8: YES, now: worship ministries' typed leaders become real people from the members list. Match by email and name, and list any that don't match"
status: waiting on Kevin
prs: [kmj-intake-server#2124]
migrations: ["supabase/APPLY-2026-11-28-group-leads.sql (from part 1, kmj-intake-server#2120: worship_ministries.leader_contact_id)"]
left_undone:
  - "Run the match at each church once part 1's file is applied: GET /worship/ministries/leader-matches lists it, the frontend shows it, and Link them applies"
decisions:
  - "Picking a person fills the typed name and email the ministry's link and emails already read; letting go keeps the typed words"
  - "Matching is by email (exactly one person has it), else by the whole name (exactly one person has it); two people with the same email or name are never guessed; the rest are listed with why"
  - "Applying links only a ministry with no person yet, and only the matches; same seat as the ministries (the plan's part)"
related: [2026-11-28-m8-group-leads.md]
---
Part 5 of M-8. `worship_ministries.py`: `leader_contact_id` on POST/PUT and in
the list (once the column answers), `leader_matches`, `GET` and
`POST /worship/ministries/leader-matches[/apply]`.
`test_worship_ministry_leaders.py` (4); the worship suites (107) pass.
