---
title: Church leaders step 2, PR B3a — one change, one row (the leaders map's change log with Undo)
date: 2026-11-05
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03: approved step 2 (design 4V41zJz1kEJGdeo4J9D2Ym, "Your two ideas"): Chief verbs with undo, the department sheet, setup sessions, a ready-made directory, drafts for new churches'
status: in progress
prs: [kmj-intake-server#1725]
migrations: [supabase/APPLY-2026-11-05-church-map-step2.sql (applied 2026-11-03, B2)]
left_undone:
  - "B3b: people on drafts, the activation check, unfinished_at, ?with=choices, switch permissions on PATCH /church/roles (and logging role-switch saves through church_map_batch), role_name off team_leader"
  - "B5: Chief's map verbs on church_map_batch (change_map, undo_map_change, apply/discard), the full name resolver in place of B3a's ids-or-exact-names, action_inverse rows"
  - "F2: the sheet's Waiting for your yes and Recent changes, from GET /church/map/changes"
decisions:
  - "Check first = each part's own write run dry (a new dry= keyword on the six writes) against a copy of the map the earlier parts moved on, so a role part placed first lets the department part after it name that role's holder"
  - "Parts keep only the fields they change, plus label (the name when logged), done:false on what didn't go in, deleted:true on a draft an undo took out"
  - "A change of nothing logs nothing; a lone part that fails logs nothing and answers as its write does (step-1 messages unchanged); a failure after a part went in keeps the change failed, finished by POST /changes/{id}/apply"
  - "Applying a waiting or failed change: parts already in are passed over, a part reading as before (or already as after) is written, anything else is a 409"
  - "Money also covers can_board_yes (decision 3); undo, apply and discard of a money change are owner only; every batch call takes the caller's seat as role and refuses anyone but the owner or an admin"
  - "The change row is written after the parts (no transaction); a failed insert keeps the save, returns change null and prints a line"
related: [2026-11-05-church-step2-migration.md, 2026-11-04-church-map-writes.md, 2026-11-04-church-step2-fixture.md]
---
`church_map_batch.py` (docs/CHURCH_LEADERS_STEP2.md §4.1-§4.3, B3a in §7): `apply` (applied, or pending when
staged), `apply_pending`, `discard` and `undo` over `church_map_changes`, one row per change, each part with its
before and after. Undo is whole or not at all: 30 days, only while every touched field reads as the change left
it, a 409 naming what changed since. `church_map.step2_state()` probes the table: the new routes are a 503 until
B2's file is applied or when the probe fails.

Routes (behind CHURCH_MAP, so under `owner` only the platform owner): `GET /church/map/changes` (a manager seat
and up, plain words), `POST /church/map/changes/{id}/undo|apply|discard` (the owner or an admin; a money change
the owner). The step-1 routes (PUT departments, archive, PUT answers-to, PUT settings) log one change per save
with origin `office` once step 2 is there, and before it they run as they always have.

`__tests__/test_church_map_changes.py` covers every part kind applied then undone, drift, a partial failure
finished by a replay, money, waiting changes, the routes and 503s, and the step-1 logging. `church_three.build`
gains `migrated2`.
