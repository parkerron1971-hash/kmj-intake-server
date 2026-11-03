---
title: Church leaders map, PR 2 — the migration (role switches, answers-to, church settings, departments)
date: 2026-11-04
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03: take the leaders flow further, for every church that subscribes ("what i don''t want is what i build works for love city but is broken and messed up for other churches"); design 4V41zJz1kEJGdeo4J9D2Ym approved'
status: waiting on Kevin
prs: ["kmj-intake-server (this PR)"]
migrations: [supabase/APPLY-2026-11-04-church-map.sql (not yet applied; applied by hand after review, before PR 3 merges)]
left_undone:
  - "Apply supabase/APPLY-2026-11-04-church-map.sql by hand after review and before PR 3 merges; run the ledger row's before/after checks, then mark the row APPLIED"
  - "BLOCKS THIS PR (CI): account_lifecycle.py must list church_departments and church_department_units, or test_export_import.py::TestTheListCannotRot fails (every business_id table is exported or excluded with a reason). Proposed: both at the head of BUSINESS_CHILD_TABLES (units, then departments: before the boards, ministries, groups, roles and contacts they cite) and both in _IMPORT_SKIP beside church_role_defs (they cite people, groups, roles, boards and ministries by id). Held because PR 2's brief allows no production Python"
  - "PR 3: update_role leaves the switches alone when a role's job changes; decide whether a job change writes the new job's defaults (until PR 4 the leaders room still reads the job, so a role re-jobbed in between drifts at PR 4)"
  - "PR 9: drop church_role_defs_switches' insert fill and church_role_switches_today once every write names the switches (the trim of made_for stays)"
decisions:
  - "The guard's real name is church_role_defs_guard (APPLY-2026-10-17-church-role-library.sql:102-104); it is disabled only for the one backfill update, inside the block, under the ALTER's lock"
  - "Today's rule lives in one SQL function, church_role_switches_today(job, key, title, handles), used by the backfill and by a new insert trigger; test_church_map_vectors.py pins its literals to SHEPHERD_TITLE, MINISTER_TITLE, LEADER_JOBS and the Executive Pastor key"
  - "Added beyond §1: a role inserted with none of the switches said gets today's rule (otherwise a library filled between this migration and PR 3 gets can_shepherd null and can_lead false), and made_for is trimmed to handles on every write (otherwise the check refuses today's role edits that drop a stream)"
  - "Every column add is a guarded DO block with named constraints, so a second run adds no duplicate constraint; set local lock_timeout 5s"
  - "office_overseer_roles is filled only where null (the spec's insert ... on conflict ... where null), so a re-run fills only a church never set; a church with an active Executive Pastor role and no settings row gets a row carrying only that (seeded_at null, so its library still fills)"
  - "church_role_settings_guard checks only the role ids a write adds, so a role deleted later never blocks the church's next settings save"
  - "church_map_same_business also refuses moving a department or unit to another church; the label-uniqueness index covers only the kinds a label names (serve option, space, check line)"
related: [2026-11-04-church-map-fixture.md, 2026-10-17-church-leaders.md, 2026-11-01-church-duties.md]
---
The data for step 1 of the leaders map (`docs/CHURCH_LEADERS_MAP.md` §1, §2, PR 2 in §5): six switches on each
role (`can_shepherd`, `can_oversee`, `can_lead`, `can_board_yes`, `can_see_all`, `made_for`) backfilled once from
today's rules, `church_leader_roles.answers_to_contact_id`, the church's money levels and role picks on
`church_role_settings`, `church_departments` and `church_department_units`, and `church_area_places.by`/`word`.
Nothing is created for any church beyond today's rule, and nothing reads it until PR 3/4 and `CHURCH_MAP`.

Pinned three ways: `__tests__/test_church_map_vectors.py` computes every switch for the eight church types'
rows, the legacy four, the three test churches' libraries and some edges with today's Python and holds it to
`__tests__/fixtures/church_map_backfill_vectors.json`; `__tests__/church_map_db.mjs` (PGlite, in CI) seeds
those rows, runs the file twice and gets the same values, with holders, shepherds, follow-ups and the
shepherding settings unchanged byte for byte, and also runs the file's closing check, the ledger's Love City
query and the rollback block (which must leave the schema as it found it).

Before building more here: read the ledger row for the pre-apply trigger check, and remember that the
switches are stored data from the moment this is applied, so a role's title or job changing afterwards no
longer moves them (rule a).
