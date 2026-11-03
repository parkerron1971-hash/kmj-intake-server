---
title: Church leaders step 2, PR B2 — the migration (change log, setup sessions, template marks, unfinished departments)
date: 2026-11-05
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03: approved step 2 (design 4V41zJz1kEJGdeo4J9D2Ym, "Your two ideas"): church setup sessions on the Academy engine, a ready-made directory, Chief verbs with undo, the department sheet, drafts for new churches'
status: in progress
prs: [kmj-intake-server#1723]
migrations: [supabase/APPLY-2026-11-05-church-map-step2.sql (not yet applied; applied by hand after review, before B3a merges)]
left_undone:
  - "Apply supabase/APPLY-2026-11-05-church-map-step2.sql by hand after review and before B3a merges: run the ledger row's four checks first (the source check's name and values, the departments trigger, the rows the backfill will mark, neither table there yet), then its checks after, then mark the row APPLIED"
  - "If the pre-check lists a department someone saved as a draft on purpose (only possible by a hand-made API call today), clear its unfinished_at after applying"
  - "B3a: church_map_batch and the changes routes, reading church_map_changes behind church_map.step2_state()"
decisions:
  - "The source check's real name is church_role_defs_source_check (Postgres's name for the inline check in APPLY-2026-10-17-church-role-library.sql:50) and its values are catalog, custom, legacy and chief, as the spec guessed; the swap adds template and runs once (a second run finds template and leaves it), and any other check on source stops the file instead of leaving one that still refuses template"
  - "The unfinished_at backfill (the spec's predicate: an office draft with nothing hung from it) runs once, inside the block that adds the column; as the spec wrote it, it ran on every apply and would mark a draft saved on purpose after B3b"
  - "Every column add is a guarded DO block with a named constraint; set local lock_timeout 5s; notify pgrst"
  - "The jsonb length checks on parts and asks are CASEs, so a value that isn't a list is refused by its check rather than by jsonb_array_length's error"
  - "Added beyond §1.2: a partial index on church_map_changes.undoes (the self foreign key, so deleting a church's changes doesn't scan the table once a row)"
  - "account_lifecycle.py lists both new tables at the head of BUSINESS_CHILD_TABLES and in _IMPORT_SKIP (they cite people, roles and departments by id; a restored church starts its setup again): the one production Python change, required by test_export_import's list check"
related: [2026-11-04-church-step2-fixture.md, 2026-11-04-church-map-migration.md, 2026-11-04-church-map-writes.md]
---
The data for step 2 of the leaders map (`docs/CHURCH_LEADERS_STEP2.md` §1.2, §1.3, B2 in §7):
`template_key`/`template_version` on departments and roles, `unfinished_at` on departments, 'template' as a
role source, `seeded_as`/`confirmed_at`/`shape_key`/`shape_version` on the church settings, and two
server-only tables, `church_map_changes` and `church_setup_tracks`. It makes nothing for any church; every
church already seeded reads as confirmed, and nothing reads any of it until B3a and the switches.

`__tests__/church_map_step2_db.mjs` (PGlite, in CI) builds the church migrations and step 1, seeds Love City
(by its real id), Grace, New Hope and Riverside, runs the file twice and checks: every existing row of every
table unchanged by the columns it had; exactly the half-made office drafts marked, with their own
`updated_at`; the shape, constraints, foreign keys and indexes; the new values taken and wrong ones refused;
RLS on with the browser's roles refused (Supabase's default grants emulated); the second run changes no
schema or row, even after a draft saved on purpose; the ledger row's checks and the file's closing check run
as written; and the rollback refuses while a role says 'template', then leaves the schema as it found it.

Before building on it: B3a must probe `church_map_changes` (`step2_state()`) and answer 503 until this is
applied; B3b's failure path sets `unfinished_at` and its retry clears it.
