---
title: Church leaders step 2, PR B4a — the ready-made catalog and its search (and two fixes from #1726's review)
date: 2026-11-05
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03: approved step 2 (design 4V41zJz1kEJGdeo4J9D2Ym, "Your two ideas"): a searchable ready-made directory'
status: in progress
prs: [kmj-intake-server#1727]
migrations: [supabase/APPLY-2026-11-05-church-map-step2.sql (applied 2026-11-03, B2)]
left_undone:
  - "B4b: POST /church/map/templates/adopt (a role, a department, a shape), built on church_templates.mine, SEATS and here()'s waits"
  - "F4: the Ready-made screen (search, cards, What this adds here, Add as a draft)"
decisions:
  - "Ready-mades are code (church_templates.py): 107 roles (the 101 TYPES rows built at import, plus six any.*), 14 departments, 6 shapes; VERSIONS pins each one's version and sha256"
  - "A department's leader and a shape's roles name a seat: each tradition's own row, else a stated fallback"
  - "Support duties: worship production_schedule, media stream, youth youth, children kids, prayer prayer, care care_visits, welcome first_guests, ushers serve_schedule, groups groups, facilities building; outreach, men's, women's and missions events"
  - "Search ranks an exact title, a word of its name, a word like one (WORDS), then a word in what it says, the church's own tradition first; one card per title and job"
  - "Already the church's own: the same template_key, the same title or name, or a role seeded from the same row on the same job (catalog_key)"
  - "Both GET routes are a manager seat's, behind CHURCH_MAP, a 503 before step 2's file, and read only (Riverside stays unseeded)"
  - "#1726 review: a role's job change is a switch change (an admin's; the owner's when it would take a board yes away), logged with the switches' before and after; a switch save is checked whole and written at once"
related: [2026-11-05-church-step2-drafts.md, 2026-11-05-church-step2-changes.md]
---
`church_templates.py` is the ready-made directory (docs/CHURCH_LEADERS_STEP2.md §1.1, §2.1-§2.3). Roles are
built at import from `church_roles.TYPES`, so each carries the backfill's switches, and six roles no tradition
names sit beside them. There are fourteen departments, each with an area, a support duty, a leader seat and
suggested units, and six shapes, each with its roles' flips, departments, overseers and picks. `search()` is a
lookup that decides nothing. `GET /church/map/templates` and `GET /church/map/templates/{kind}/{key}` (the
second with what adopting would add here) are in church_map_router.py.

Two fixes from #1726's review, in their own commit: `church_map_batch.switch_seat` counts a job change as a switch
change, and `save_role` checks the whole save first and then writes it at once. Details are in
docs/CHURCH_LEADERS_STEP2.md, "As built in B4a" (§2.5) and "Corrected in B4a" (§4.3).
