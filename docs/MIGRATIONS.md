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
| `supabase/APPLY-2026-08-26-workspace-composer.sql` | Workspace composer phase one: `business_profiles.workspace_archetype` / `workspace_layout` / `workspace_terminology`, `sessions.assigned_to` + index, and the `business_metrics` view. | **applied 2026-08-26, verified** (3 columns, `assigned_to uuid`, index present, view returns 4 keys). Shipped BROKEN and was fixed before applying — see the note below. |
| `supabase/APPLY-2026-08-27-workspace-benchmark-values.sql` | The `business_benchmark_values` view: the per-tenant VALUE half of the benchmark panel. Bands stay in `workspace_benchmarks.py`. | **applied 2026-08-26, verified** (view live, 5 keys returning values). Rewritten against the live schema first — see the note below. |
| `supabase/APPLY-2026-08-19-dev-bridge.sql` | Dev Bridge: `dev_tasks` (Mission Control → developer-side task list, local + cloud lanes) and `dev_bridge_devices` (Solution Space pairing). Service-role only. | applied 2026-08-19, verified (both tables, RLS on) |
| `../solutionist-studio/supabase/APPLY-2026-07-14-nonprofit-blueprint.sql` | the 5 nonprofit blueprint rows (donors, programs, grants, events, volunteers) | **applied 2026-08-11 — four weeks late.** The file was written 07-14 and `vertical_registry` recorded the vertical as "first-class end-to-end", but the rows were never applied: `business_type_module_blueprint` held **zero** nonprofit rows, so a nonprofit signup was provisioned nothing. Found by counting the table against the seed files (62 declared, 57 present). Verified after applying: 62 = 62. |
| `../solutionist-studio/supabase/APPLY-2026-08-11-blueprint-boards-sweep.sql` | kanban for every blueprint module whose status/stage select has ≥3 options (36 rows) | applied 2026-08-11, verified (32/57 rows carry a board; 76-row `module_inspect` sweep clean) |
| `../solutionist-studio/supabase/APPLY-2026-08-11-lawyer-matters-board.sql` + `-board-default.sql` | lawyer/matters gets the kanban its `work_pipeline` archetype implied, and opens on it | applied 2026-08-11, verified |
| `../solutionist-studio/supabase/APPLY-2026-08-11-matters-fixture-schema.sql` + `-mirrors-blueprint.sql` | the Vertical Test Lawyer fixture rendered a red panel (`schema` was `[]`); now mirrors the blueprint | applied 2026-08-11, verified |

> **2026-08-26 — both workspace migrations were written against columns that
> do not exist, and were caught by verifying before applying.** The first cut
> read `invoices.amount_due_cents`, `line_items`, `subtotal_cents`,
> `total_cents` and `amount_paid_cents`; the live table has `items`,
> `subtotal`, `tax_amount` and `total` — numeric, in DOLLARS — and **no
> paid-amount column at all**. It also filtered `invoices.status = 'open'`
> (the check constraint allows draft|sent|viewed|paid|overdue|cancelled) and
> `contacts.status` on `'first_time'` and `'donor'` (allowed: lead|active|
> inactive|churned|vip). `CREATE VIEW` would have failed outright — and the
> two `contacts.status` arms were *worse than a failure*, because they would
> have SUCCEEDED and returned nothing forever: a ministry would have been
> shown a guest-return rate of zero every Sunday.
>
> The `*_cents` names came from reading the CALLERS instead of the schema —
> they are Stripe payload keys, and they appear in the Python over a hundred
> times. `workspace_field_catalog.py` had inherited the same phantom columns
> for `invoices`, `business_users` (`display_name`), `contractors` (`trade`,
> `status`, `phone`) and `customer_balances` (`balance_cents`), and the trades
> preset bound one of them.
>
> **The cheap guard is the one this doc already states, applied literally:**
> query `information_schema.columns` for every table a migration touches
> before writing a line of it, and dry-run the whole file inside a
> transaction that ends in `ROLLBACK` before the one that ends in `COMMIT`.
> Both were done here; both migrations then applied first time.
>
> One incidental finding worth keeping: **`business_users` has no name column
> of any kind.** A seat carries an `invited_email` and a role, and the person
> lives in auth. That is the schema-level confirmation of why the salon board
> draws one undivided day rather than a lane per stylist.

> **The lesson these four share:** writing a migration is not applying it, and a
> closure note that cites a file has only checked that the file exists. The cheap
> guard is the count — `SELECT count(*) FROM business_type_module_blueprint` against
> the rows the seed files declare. It disagreed for four weeks and nothing said so.

## Recent / pending migrations (2026-07)

| File | What | Status |
|---|---|---|
| `APPLY-2026_08_22_signup_attribution.sql` | Growth arc Rung 1 — `attribution jsonb` on marketing_leads/waitlist/businesses + `data jsonb` on site_events (campaign params by channel) | **applied** 2026-08-22 |
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
