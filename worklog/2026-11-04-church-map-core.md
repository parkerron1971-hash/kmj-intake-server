---
title: Church leaders map, PR 3 — church_map read core, and the role switches as data
date: 2026-11-04
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03: take the leaders flow further, for every church that subscribes ("what i don''t want is what i build works for love city but is broken and messed up for other churches"); design 4V41zJz1kEJGdeo4J9D2Ym approved'
status: in review
prs: ["kmj-intake-server (this PR)"]
migrations: [supabase/APPLY-2026-11-04-church-map.sql (applied 2026-11-03 with PR 2; nothing new here)]
left_undone:
  - "CHURCH_MAP is new and defaults to owner (Love City only). When it goes on, set it on BOTH Railway services (server and worker); nothing was set here"
  - "PR 4: switches replace words (shepherding's role_rows, choose's made_for tie-break, the leaders room's can_lead, keeping its answers-to seat rule)"
  - "PR 5: map writes and /church/map routes (save_department, archive_department, set_answers_to, save_settings); propose() is still a stub returning {}"
  - "PR 6: chain_for on Map's led_by / overseen_by / department_of / answers_to"
  - "PR 9: drop church_role_defs_switches' insert fill and church_role_switches_today (every insert names the switches now; the made_for trim stays)"
decisions:
  - "Every role insert names all six switch columns once ready(); a pastoral null with all else off and no made_for is saved false, since the live insert trigger would read it as none said (the fake runs that trigger)"
  - "A job change starts the can_* switches again from the new job's defaults unless the same request sets them; made_for is trimmed to the new handles; the server now refuses a job change while anyone holds the role, as the page already did"
  - "A new custom role's made_for is suggested once from its key and title (today's tie-break), then stored; can_shepherd follows decision 2 (pastoral shepherds)"
  - "can_shepherd null (follows Ministers) is kept only on a pastoral role"
  - "An office catalog row fills office_overseer_roles only while it is null; create_role never adds one"
  - "chief_lines says the switches only where church_open and ready; library carries them whenever ready"
  - "The fixture's Love City Prophets is made with can_shepherd false (it predates the map); build(migrated=False) is the database before the file, and the baselines run that way too"
related: [2026-11-04-church-map-fixture.md, 2026-11-04-church-map-migration.md]
---
New `church_map.py` holds the switch (`mode`/`open_to`/`church_open`), `ready()`, `load(biz) -> Map | None`
(five reads of its own; None on any failed one), `can(m, role)` (the seven switches) and a `propose` stub.
`church_roles.py` gives each job its switches; every catalog row now carries them, pinned equal to
the backfill vectors. `ensure_library`, `set_type`, `create_role` and `update_role` write them, but
only once `ready()`. `_FIELDS` and `_RoleDef` take them, and `library`/`chief_lines` show them.
`church_three.build` now writes `db.map_intent` into the map's tables.

Nothing reads a switch to decide anything yet. Every baseline in `test_church_three_today.py` holds
with the map closed, open and empty, and open on a database without the migration. The scenario
tests are still 4 passing and 8 strict xfails, as before.
