---
title: Every group has a leader, part 3 — Everyone who leads, in one place (M-8)
date: 2026-11-28
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin said GO on mission M-8: one place to see every leader and who they answer to; the Worship part shows as worship team leaders; a class group points to its Course Studio class and the teacher shows once, with both"
status: waiting on Kevin
prs: [kmj-intake-server#TBD]
migrations: []
left_undone:
  - "The group-leads columns come from part 1's file (#2120); before it is applied the list is whole, with no co-leaders, group answers-to, class links or Serve choices"
  - "Leaders & roles' Everyone who leads list and the Team leader chips as real teams are the frontend PR"
decisions:
  - "One row a person a thing they lead, from the church's own records: role holders (active and asked), group leads and co-leaders by kind, the Worship part, Course Studio teachers, Kids check-in leaders"
  - "Answers to: the person on the holder row or the group, else the fallback in words: the role's answers-to (whoever holds it), the group's department's leader, or the leaders map"
  - "A Course Studio teacher who leads the class group pointing at that class shows once, on the group's row with teaches; teachers and Worship-part people are matched to the church's people by email, and an address two people share names nobody"
  - "The Worship part names the church's worship team the way the Sunday hub does (a Sunday team, ChurchSavvy's, named worship/praise/band/choir/music/singers), once, unless they already lead it"
  - "Same seat as Leaders & roles (manager and up); every read pages past 1,000; a failed read is a 503, never a short list"
related: [2026-11-28-m8-group-leads.md, 2026-11-28-m8-map-person.md]
---
Part 3 of M-8. New `church_leaders_all.py`: `GET /church/leaders/everyone`
(rows, teams, gaps, counts), mounted on church_router. Tests:
`test_church_leaders_all.py` (11) at the three-church fixture.
