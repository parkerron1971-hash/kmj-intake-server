---
title: Church leaders map, PR 5 — map writes and the /church/map routes
date: 2026-11-04
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03: take the leaders flow further, for every church that subscribes ("what i don''t want is what i build works for love city but is broken and messed up for other churches"); design 4V41zJz1kEJGdeo4J9D2Ym approved'
status: in review
prs: ["kmj-intake-server (this PR)"]
migrations: [supabase/APPLY-2026-11-04-church-map.sql (applied 2026-11-03 with PR 2; nothing new here)]
left_undone:
  - "Step 4: enter Love City's real department sheet through these routes once Kevin corrects it. Where a leader's role doesn't lead (the Intercessor leader, say), turn its can_lead on first"
  - "CHURCH_MAP defaults to owner (only the platform owner's login reaches /church/map). When it goes on, set it on BOTH Railway services; nothing was set here"
  - "PR 6: chain_for reads these departments and answers-to links; propose() is still a stub"
  - "Frontend (step 2): the department sheet on GET /church/map; the routes are its API"
decisions:
  - "A department's leader must hold a role that leads and its overseer one that can oversee; the fixture's Love City Intercessor leader and New Hope Deacons now have can_lead on (the room is unchanged)"
  - "Only the fields a request names are checked; the gaps list flags what has stopped qualifying since"
  - "Archiving deletes the department's units, so its things can hang elsewhere (the unique indexes span archived departments too)"
  - "A write the database refuses is re-read: a name or unit taken meanwhile is the same plain 400, else a 503; a new department never stays half made"
  - "Settings changes: only the owner changes a money level; each change prints a [church_map] settings line (was -> is) and stamps map_by/map_at; the same values again are no change"
  - "The writes and view refuse with a 503 when church_map.state() is False or None, never on ready() alone"
related: [2026-11-04-church-map-fixture.md, 2026-11-04-church-map-migration.md, 2026-11-04-church-map-core.md, 2026-11-04-church-map-switches.md]
---
`church_map.py` gains `save_department`, `archive_department`, `set_answers_to`, `save_settings` and
`view` (the map by name, each department's duty and who does it today, the switches, answers-to, the
settings and the gaps). `church_map_router.py` mounts them under `/church/map`, registered before the
`public_site_router` catch-all. A manager seat reads. The owner or an admin writes departments,
answers-to links and the role picks. Only the owner changes money levels.

`test_church_map_writes.py` enters each test church's `map_intent` through the routes and gets the same
tables as `church_three`'s direct write. Every baseline in `test_church_three_today.py` still holds, and
the scenario test's strict xfails are unchanged (5 pass, 7 xfail).
