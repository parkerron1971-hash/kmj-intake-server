---
title: Every group has a leader, part 4 — Serve sign-ups go to the team's own leader; the old Team leader rows onto the team (M-8)
date: 2026-11-28
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin said GO on mission M-8: use the same team-leader idea as M-7; note the Linda Samuel launch risk"
status: waiting on Kevin
prs: [kmj-intake-server#2123]
migrations: []
left_undone:
  - "Kevin looks at GET /church/leaders/team-moves for each church and says which to move (the frontend shows it); nothing moves on its own"
  - "Linda Samuel (Love City, City Serve: outreach) is asked, not yes: she is listed as asked and never moved until she says yes and someone names her on the team"
decisions:
  - "A Serve card choice a serving team answers for (groups.serve_option, else the team's own name) goes to that team's lead first: the group's leader row, the Sunday hub's Team leader. With no leader there, today's routing exactly"
  - "team_leads is {} on any failed read, so a card is never held up by it; the leader row carries the church's team role key, so follow-ups read as before"
  - "The move list says lead, co_leader, already, asked (never moved) or no_team; applying adds the team's own leader row and keeps the role row; owner or admin only"
related: [2026-11-28-m8-group-leads.md, 2026-11-27-m7-sunday-hub-backend.md]
---
Part 4 of M-8. `church_follow_up.team_leads` and `choose(teams=)`, passed by
the card path and `guest_brief`. New `church_team_moves.py` (GET list, POST
apply) on church_router. `test_serve_to_team.py` (9); follow-up, guest, map
serve and three-church baselines (527) pass.
