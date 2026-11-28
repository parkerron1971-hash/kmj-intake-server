---
title: Every group has a leader, part 1 — the group's lead, co-leaders and who it answers to (M-8)
date: 2026-11-28
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin said GO on mission M-8, Every group has a leader: naming a group's leader puts them straight in, with a note; the pastor, admins and office logins who manage groups name leaders; a leader adds their own co-leader and can't change who they answer to; answers to is ONE person per group"
status: waiting on Kevin
prs: [kmj-intake-server#2120]
migrations: [supabase/APPLY-2026-11-28-group-leads.sql (NOT APPLIED)]
left_undone:
  - "Apply supabase/APPLY-2026-11-28-group-leads.sql (until then the routes read ready: false and saving is a 503)"
  - "GROUP_LEADS defaults to owner (Love City). Set it to on, on BOTH Railway services, at the M-8 switch-on"
  - "The chain and the map reading the group's person are part 2; Everyone who leads is part 3; Serve sign-ups to the team's leader part 4; worship ministries' people part 5; the screens are the frontend PRs"
decisions:
  - "One record of who leads a group: group_members.role = 'leader' (the Sunday hub's team_leader reads the same). A co-leader keeps role leader with co_leader true, so every reader still counts them"
  - "A new lead takes the lead row; whoever led before stays on as a co-leader unless the save lists the co-leaders; leaving the co-leaders makes someone a member of the group again, never removes them"
  - "Who the group answers to must hold an active role here (the map's answers-to rule) and can't be one of its leaders"
  - "Office: owner, admin, or a login holding the groups duty (church_duties). The lead: co-leaders only, picked from the group's own people, from their login or the Lead tab's Your co-leaders"
  - "The note: a phone note (groups kind) and an email to an adult without a phone; only to people newly leading"
  - "Review fixes (account 2, 11-28): M1, the leader rows are read in one order (co_leader, created_at, contact_id), so the lead of a group with several plain leader rows is always the earliest; a save of only answers-to, a class or a Serve choice leaves every leader row alone. M2, the file's triggers let only the server (service_role, or the SQL editor) change who a group answers to, its class or its Serve choice, or name a co-leader; an office seat writing straight to the database is refused (PGlite: 35 checks)"
  - "Routes ride church_groups_office's router (no change to kmj_intake_automation.py, which M-7's open PRs edit)"
related: [2026-10-20-group-lead.md, 2026-11-04-church-map-chain.md, 2026-11-27-m7-sunday-hub-backend.md]
---
Part 1 of M-8 (the plan is in kai/reviews/leaders-roles-group-leaders.md). New
`church_group_leads.py`: `GET` and `PUT /church/groups/{id}/leads` (the lead,
co-leaders, who the group answers to, a class group's Course Studio class, a
team's Serve card choice), who may, the save, and the note "You now lead
Parking Team". The Lead tab (`group_lead`, `member_portal_lead`) gets Your
co-leaders for the group's lead. The migration adds columns only, checked on
PGlite (`group_leads_db.mjs`, 24); `test_group_leads.py` (18) runs at the
three-church fixture.

Launch risk, from the review: anyone a church made "Team leader" on Leaders &
roles for a Serve card name (church_leader_roles, scope text) is not a team
leader in the Sunday hub. At Love City that is only Linda Samuel (asked, not
yet yes). Part 4 moves those onto the team's own leader row after Kevin sees
the list.
