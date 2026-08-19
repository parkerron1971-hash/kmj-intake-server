# Migrations — the ledger

Supabase migrations here are **applied by hand** (no CLI, no
`schema_migrations` table). This doc is the source of truth for what
exists, the apply order, and how to check what's actually live.

## Where migrations live (three conventions)

| Location | Naming | Order signal |
|---|---|---|
| `__migrations__/` | `YYYY_MM_DD_name.sql` | date prefix = order |
| `supabase/` (this repo) | feature-named + newer `APPLY-YYYY-MM-DD-*` | date prefix on recent ones |
| `../solutionist-studio/supabase/` (frontend repo) | feature-named + `APPLY-YYYY-MM-DD-*` | date prefix on recent ones |

The `APPLY-YYYY-MM-DD-` prefix is the current convention — those are the
ones pending / recently applied. Older feature-named files may already
be live (some are "retroactive documentation" of tables that shipped
before the file). **The file set is not a faithful record of prod** —
verify against the live DB (below) before assuming.

## Standing rule

Every new schema change gets:
1. An `APPLY-YYYY-MM-DD-<name>.sql` file (idempotent: `IF EXISTS` /
   `IF NOT EXISTS` / `DROP POLICY IF EXISTS`).
2. A row in the "Recent / pending" table below.
3. A note in the PR description: **"apply this migration after merge."**

## How to check what's live (run in Supabase SQL Editor)

**Does a table exist?**
```sql
SELECT to_regclass('public.<table_name>') IS NOT NULL AS exists;
```

**Is RLS on + are the policies owner-scoped?** (see `docs/RLS_MODEL.md`)
```sql
SELECT relname, relrowsecurity FROM pg_class WHERE relname = '<table>';
SELECT policyname, cmd, qual FROM pg_policies WHERE tablename = '<table>';
```

**The beta gate queries** (RLS + migration presence) are in
`docs/BETA_VERIFY_QUERIES.md`.

## Recent / pending migrations (2026-08)

| File | What | Status |
|---|---|---|
| `supabase/APPLY-2026-08-19-dev-bridge.sql` | Dev Bridge: `dev_tasks` (Mission Control → developer-side task list, local + cloud lanes) and `dev_bridge_devices` (Solution Space pairing). Service-role only. | applied 2026-08-19, verified (both tables, RLS on) |
| `../solutionist-studio/supabase/APPLY-2026-07-14-nonprofit-blueprint.sql` | the 5 nonprofit blueprint rows (donors, programs, grants, events, volunteers) | **applied 2026-08-11 — four weeks late.** The file was written 07-14 and `vertical_registry` recorded the vertical as "first-class end-to-end", but the rows were never applied: `business_type_module_blueprint` held **zero** nonprofit rows, so a nonprofit signup was provisioned nothing. Found by counting the table against the seed files (62 declared, 57 present). Verified after applying: 62 = 62. |
| `../solutionist-studio/supabase/APPLY-2026-08-11-blueprint-boards-sweep.sql` | kanban for every blueprint module whose status/stage select has ≥3 options (36 rows) | applied 2026-08-11, verified (32/57 rows carry a board; 76-row `module_inspect` sweep clean) |
| `../solutionist-studio/supabase/APPLY-2026-08-11-lawyer-matters-board.sql` + `-board-default.sql` | lawyer/matters gets the kanban its `work_pipeline` archetype implied, and opens on it | applied 2026-08-11, verified |
| `../solutionist-studio/supabase/APPLY-2026-08-11-matters-fixture-schema.sql` + `-mirrors-blueprint.sql` | the Vertical Test Lawyer fixture rendered a red panel (`schema` was `[]`); now mirrors the blueprint | applied 2026-08-11, verified |

> **The lesson these four share:** writing a migration is not applying it, and a
> closure note that cites a file has only checked that the file exists. The cheap
> guard is the count — `SELECT count(*) FROM business_type_module_blueprint` against
> the rows the seed files declare. It disagreed for four weeks and nothing said so.

## Recent / pending migrations (2026-07)

| File | What | Status |
|---|---|---|
| `supabase/APPLY-2026-07-13-drop-permissive-policies.sql` | drop the `_all` `USING(true)` policies on invoices/social_accounts/email_replies/business_profiles (cross-tenant fix) | **applied** 2026-07-13 (deploy the paired anon→service code first) |
| `../solutionist-studio/supabase/APPLY-2026-07-13-insight-category.sql` | add `insight` to `chief_memories_category_check` + backfill | applied 2026-07-13 |
| `supabase/APPLY-2026-07-12-credit-ledger.sql` | prepaid credit_ledger (Pricing v2) | verify |
| `supabase/APPLY-2026-07-10-chief-scheduled-actions.sql` | Chief "schedule anything" | verify |
| `supabase/APPLY-2026-07-10-sms-missing-tables.sql` | sms_messages / sms_consents | verify |

> When you apply one, change its status here and note the date.

## Rollback

Most feature migrations ship a paired `*-rollback.sql` (grep the file's
header for `rollback`). RLS-policy changes: re-create the dropped policy
from `pg_policies` output captured before the change. There is no undo
for data deletions.
