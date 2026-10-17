---
title: Asking a member to lead saves again — the leaders trigger refused every role and note
date: 2026-10-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "the ability to assign and save leaders with invite is not working. please check."'
status: shipped
prs: [kmj-intake-server#1475]
migrations: [supabase/APPLY-2026-10-17-church-leaders-trigger-fix.sql]
left_undone: []
decisions:
  - "Fixed in the database (a new APPLY file, applied live first): the backend and the office page were right; the trigger was the only fault"
  - "A real-Postgres check (PGlite) now runs both files in CI and proves the first one alone still fails, so the check can't quietly stop testing the fix"
related: [2026-10-17-church-leaders.md]
---
Kevin's "Send the invitation" on Leaders & roles came back 503 ("That
didn't save"). Railway showed POST /church/leaders 503 and no rows in
`church_leader_roles`. Replaying the insert in the database gave:
`record "new" has no field "leader_contact_id"`.

- **Cause:** the same-business trigger from #1473 had
  `if tg_table_name = 'church_follow_ups' and new.leader_contact_id is not null`.
  PL/pgSQL resolves every field the IF names before testing it, so the
  insert failed on `church_leader_roles` and `church_follow_up_notes`,
  which have no such column. No role could be asked or accepted and no
  note written; follow-ups themselves saved. The #1473 rollback probe ran
  the DDL only, never a row, and the Python tests fake the database.
- **Fix:** `APPLY-2026-10-17-church-leaders-trigger-fix.sql` reads each
  table's fields only inside an IF that has already picked the table.
  Rollback-probed on Love City's real rows (a role, saying yes, a
  follow-up with a leader, a note, another church refused), then applied.
  Nothing was lost: no follow-ups, notes or roles existed yet.
- **Guard:** `__tests__/church_leaders_db.mjs` (9 checks, in the CI
  PGlite step). Rehearsed: putting the combined IF back turned it red
  with the same error.
