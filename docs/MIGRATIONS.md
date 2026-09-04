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
| `supabase/APPLY-2026-09-02-support-thread.sql` | The conversation on a ticket: `support_ticket_messages` (practitioner / support / system, tenant-READABLE by design) plus the practitioner-facing projection cached on the ticket — `stage`, `last_message_at`, `last_message_author`. Backfills each existing `admin_reply` as the first message of its thread, so an old ticket opens as a conversation rather than a blank page. | **applied 2026-09-02, verified.** Ran second, after the fix-queue file (it reads the `fix_state` that one introduces). Editor said "Success. No rows returned" and the confirming query DID run: `support_ticket_messages` exists, carries exactly **2** policies (the tenant SELECT and the owner ALL — no tenant INSERT, which is the point), and **0** of the 2 production tickets are left unprojected. **0 messages were backfilled, and that is correct**: neither ticket had ever been replied to. `0` replies were skipped for exceeding the 5000-char body cap, so that edge never existed here. Deliberately no CHECK on `stage`: the archetype CHECK went out of step with the app's own list in August and Postgres silently rejected writes the app had already called successful, so unknown stages fall back to a working badge instead. Writes are platform-owner only — a practitioner's own message goes through `POST /support/tickets/{id}/messages` (JWT + owner check), because sending one has to reopen the ticket and nudge the operator, and neither can hang off a PostgREST insert. Verify: `SELECT to_regclass('public.support_ticket_messages') IS NOT NULL;`, `SELECT policyname, cmd FROM pg_policies WHERE tablename='support_ticket_messages';` (expect a SELECT and an ALL, no tenant INSERT) and `SELECT count(*) FROM public.support_tickets WHERE last_message_at IS NULL;` (expect 0). |
| `supabase/APPLY-2026-09-02-support-fix-queue.sql` | The fix queue: `support_triage` (severity, fix_state, problem_key, the link to the `dev_tasks` row fixing it, and the operator-only note). Service-role only — RLS on, no policies — **because `support_tickets` is tenant-readable** and operator judgement must never sit on a row a practitioner can `select=*`. | **applied 2026-09-02, verified** — `support_triage` exists, RLS on, and **0** policies on it, which is the intended reachability (service-role only). Ran first. Nothing else regresses — the table is new and no existing column changes, so Mission Control's ticket panel and Help & Support are untouched either way. Verify: `SELECT to_regclass('public.support_triage') IS NOT NULL;` (expect t), `SELECT relrowsecurity FROM pg_class WHERE relname='support_triage';` (expect t) and `SELECT count(*) FROM pg_policies WHERE tablename='support_triage';` (expect 0). |
| `supabase/APPLY-2026-09-02-support-thread.sql` | The conversation on a ticket: `support_ticket_messages` (practitioner / support / system, tenant-READABLE by design) plus the practitioner-facing projection cached on the ticket — `stage`, `last_message_at`, `last_message_author`. Backfills each existing `admin_reply` as the first message of its thread, so an old ticket opens as a conversation rather than a blank page. | **PENDING — apply after merge, AFTER the fix-queue file above** (it reads the `fix_state` that one introduces). Deliberately no CHECK on `stage`: the archetype CHECK went out of step with the app's own list in August and Postgres silently rejected writes the app had already called successful, so unknown stages fall back to a working badge instead. Writes are platform-owner only — a practitioner's own message goes through `POST /support/tickets/{id}/messages` (JWT + owner check), because sending one has to reopen the ticket and nudge the operator, and neither can hang off a PostgREST insert. Verify: `SELECT to_regclass('public.support_ticket_messages') IS NOT NULL;`, `SELECT policyname, cmd FROM pg_policies WHERE tablename='support_ticket_messages';` (expect a SELECT and an ALL, no tenant INSERT) and `SELECT count(*) FROM public.support_tickets WHERE last_message_at IS NULL;` (expect 0). |
| `supabase/APPLY-2026-09-02-support-fix-queue.sql` | The fix queue: `support_triage` (severity, fix_state, problem_key, the link to the `dev_tasks` row fixing it, and the operator-only note). Service-role only — RLS on, no policies — **because `support_tickets` is tenant-readable** and operator judgement must never sit on a row a practitioner can `select=*`. | **PENDING — apply after merge.** The code half fails loud without it: `support_router` returns 502 naming this file on the first write. Nothing else regresses — the table is new and no existing column changes, so Mission Control's ticket panel and Help & Support are untouched either way. Verify: `SELECT to_regclass('public.support_triage') IS NOT NULL;` (expect t), `SELECT relrowsecurity FROM pg_class WHERE relname='support_triage';` (expect t) and `SELECT count(*) FROM pg_policies WHERE tablename='support_triage';` (expect 0). |
| `supabase/APPLY-2026-08-28-first-run-arc.sql` | Chief's first seven days: `first_run_arc`, one row per business recording when the trial actually began, whether the introduction has been delivered, and how far the practitioner has walked. Unique index on `business_id` (that IS the idempotency guarantee `first_run_arc.begin()` leans on) + a partial index for the daily-beat sweep. RLS on, **no policies** — service-role only, `dev_tasks` precedent. Touches one existing table, `businesses(id)` (uuid, verified against the FK in `APPLY-2026-07-12-credit-ledger.sql` and six others). | **pending** — apply after merge |
| `supabase/APPLY-2026-08-26-workspace-composer.sql` | Workspace composer phase one: `business_profiles.workspace_archetype` / `workspace_layout` / `workspace_terminology`, `sessions.assigned_to` + index, and the `business_metrics` view. | **applied 2026-08-26, verified** (3 columns, `assigned_to uuid`, index present, view returns 4 keys). Shipped BROKEN and was fixed before applying — see the note below. |
| `supabase/APPLY-2026-09-01-rls-advisor-errors.sql` | Closes all 11 Supabase Security Advisor **errors**: RLS on + grants revoked for `public.leads` and `public.discovery_submissions`, and `security_invoker = true` on the 8 SECURITY DEFINER views. | **PENDING — apply after merge.** Ships with the code half (`kmj_intake_automation` and three `public_site` write paths moved off the anon key); applying the SQL without that code would break nothing, but merging the code without the SQL leaves the tables open. `leads` is read by nothing in this repo and `discovery_submissions` is referenced nowhere at all, so neither gets a policy — RLS-on with no policy denies every role but service_role, which is the reachability both should have. Verify: `SELECT relname, relrowsecurity FROM pg_class WHERE relname IN ('leads','discovery_submissions');` (expect both `t`) and check `reloptions` carries `security_invoker=true` on the 8 views. |
| `supabase/APPLY-2026-08-31-client-actor-and-identity.sql` | The two-sided client layer's irreversible doors: `audit_log.actor_type` gains `'client'` (the CHECK went from 4 values to 5), and `business_customers` gains a nullable `platform_identity_id` + partial index. | **Reported applied 2026-09-01 by Kevin — NOT yet verified.** The editor showed the four statements and "Success. No rows returned", which is the expected DDL signal, but the confirming query never ran: the page wedged before it could. Do not upgrade this to "verified" without pasting the output of `SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='audit_log_actor_type_check';` (expect 5 values incl. `'client'`) **and** `SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid WHERE c.relname='audit_log' AND NOT t.tgisinternal;` — the second one matters because those append-only triggers are the whole basis of the ledger's tamper-evidence claim, and this migration swapped a constraint on that table. Rationale: both changes are cheap now and unrecoverable later — `audit_log` is append-only for real, so rows written under the 4-value CHECK can never be relabelled; `platform_identity_id` is written and read by nothing, and is explicitly NOT a cross-tenant email match. |
| `supabase/APPLY-2026-08-28-workspace-layout-variant.sql` | `business_profiles.workspace_layout_variant` + `_origin` — which DESK a business opens on within its archetype, and whether Chief or the practitioner chose it. | **applied 2026-08-28 by Kevin, verified** — both columns present, the origin CHECK live (`chief|user_override`), and 0 rows carrying a variant, which is correct: every business sits on its archetype default until Chief picks. Deliberately no CHECK on the variant: the archetype CHECK swallowed two presets silently on 2026-08-27 and variants change far more often. The app falls back to the default on anything unknown, so a stale value degrades to a working desk. |
| `supabase/APPLY-2026-08-27-workspace-archetype-widen.sql` | Widens the `business_profiles.workspace_archetype` CHECK from 5 values to the 7 presets that actually ship. | **applied 2026-08-27, verified** — constraint now lists all seven; a `therapist` and a `nonprofit` write both proved in a rollback transaction first. |
| `supabase/benchmarks/APPLY-2026-08-27-bench-<vertical>.sql` ×7 + `supabase/APPLY-2026-08-27-bench-aggregate.sql` | The benchmark VALUES, split into one view per vertical plus a stable aggregate that unions them. Supersedes the single `APPLY-2026-08-27-workspace-benchmark-values.sql`. | **applied 2026-08-27, verified** — all 7 per-vertical views live, aggregate returns the same 14 rows with identical values to the monolithic view it replaced. |
| ~~`supabase/APPLY-2026-08-27-workspace-benchmark-values.sql`~~ | The original single view. | applied 2026-08-26, **superseded 2026-08-27** by the split above. File removed. |
| `supabase/APPLY-2026-08-19-dev-bridge.sql` | Dev Bridge: `dev_tasks` (Mission Control → developer-side task list, local + cloud lanes) and `dev_bridge_devices` (Solution Space pairing). Service-role only. | applied 2026-08-19, verified (both tables, RLS on) |
| `../solutionist-studio/supabase/APPLY-2026-07-14-nonprofit-blueprint.sql` | the 5 nonprofit blueprint rows (donors, programs, grants, events, volunteers) | **applied 2026-08-11 — four weeks late.** The file was written 07-14 and `vertical_registry` recorded the vertical as "first-class end-to-end", but the rows were never applied: `business_type_module_blueprint` held **zero** nonprofit rows, so a nonprofit signup was provisioned nothing. Found by counting the table against the seed files (62 declared, 57 present). Verified after applying: 62 = 62. |
| `../solutionist-studio/supabase/APPLY-2026-08-11-blueprint-boards-sweep.sql` | kanban for every blueprint module whose status/stage select has ≥3 options (36 rows) | applied 2026-08-11, verified (32/57 rows carry a board; 76-row `module_inspect` sweep clean) |
| `../solutionist-studio/supabase/APPLY-2026-08-11-lawyer-matters-board.sql` + `-board-default.sql` | lawyer/matters gets the kanban its `work_pipeline` archetype implied, and opens on it | applied 2026-08-11, verified |
| `../solutionist-studio/supabase/APPLY-2026-08-11-matters-fixture-schema.sql` + `-mirrors-blueprint.sql` | the Vertical Test Lawyer fixture rendered a red panel (`schema` was `[]`); now mirrors the blueprint | applied 2026-08-11, verified |

> **2026-08-27 — the archetype CHECK allowed five values while seven
> presets shipped, and the mismatch was completely silent.** `therapist`
> and `nonprofit` are real layouts chosen by a real classifier. The
> app-layer validator accepted them — it checks
> `workspace_layouts.ARCHETYPES`, which has seven — and Postgres then
> rejected the write with 23514. But `sb_clients._sync_request` logs a
> warning and returns `None` on any 4xx, and `_persist` ignored the
> return value, so the practitioner got a success and nothing was saved.
> The next page load asked them to choose again. Forever. `nonprofit` is
> a live business type in this database, so this was not hypothetical.
>
> Two fixes, because widening the constraint alone would just wait to
> happen again. `__tests__/test_workspace_archetypes.py` now PARSES the
> migration and fails the build if its list disagrees with the preset
> folder, and walks every `businesses.type` present in production through
> the classifier to assert each lands somewhere savable. And `_persist`
> now reads the row back and raises if the archetype did not land — a
> write that cannot fail out loud is not a write, it is a hope.

> **2026-08-27 — the benchmark view was split one-per-vertical, on purpose.**
> Eight people are about to work on eight verticals at once. Appending
> UNION arms to one shared view guarantees merge conflicts, and a conflict
> resolved by guessing inside a SQL view puts one industry's number under
> another industry's sentence. Each vertical now owns
> `supabase/benchmarks/APPLY-*-bench-<vertical>.sql`; the aggregate unions
> a fixed list of seven and changes only when a whole vertical is added.
> Apply the seven per-vertical files before the aggregate — it depends on
> all of them. Verified identical: same 14 rows, same values, before and
> after.

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
| `supabase/APPLY-2026-09-04-events-agent-cursor.sql` | `events.agent_handled_at` + partial index — the standing agent's cursor (`chief_agent.py`): which events nobody has acted on yet. Stamped before planning; 24-hour window. Code is fail-soft without it (the tick fetch fails and logs the file name). | **applied** 2026-09-04 via the SQL editor; column + partial index verified |
| `supabase/APPLY-2026-09-04-rate-windows.sql` | `rate_windows` + `rate_take()` / `rate_purge()` — the rate limiter's window in Postgres, so the strict buckets (booking widget, checkout, waitlist, MCP, OAuth, agent site…) hold across web replicas instead of each replica having its own budget. Code falls back to per-process with a warning if the RPC is missing. | **applied** 2026-09-04 via the SQL editor; `rate_take('verify','x',2,60)` answered true, true, false |
| `supabase/APPLY-2026-09-04-chief-jobs-heartbeat.sql` | `chief_jobs.heartbeat_at` — the running worker stamps it on every progress ping, so the boot sweep and the 5-minute recovery tick can tell an orphaned build from a slow one across replicas. Code is fail-soft without it (stamping disables itself; the sweep falls back to `started_at` at 10 min), so apply before or after the deploy. | **applied** 2026-09-04 via the SQL editor; column + partial index verified |
| `supabase/APPLY-2026-09-04-chief-assignments.sql` | `chief_assignments` — an outcome the standing agent works over days (`chief_assignments.py`): a measurable target, a deadline, the moves log with reasoning written before each move, the tick's `next_check_at` cursor and the per-day think counter. Two indexes (the tick's due read; the card's per-business read). RLS on, **no policies** — service-role only, `first_run_arc` precedent; the app reads it through `GET /agents/chief/assignments` (owner check in code). Code is fail-soft without it (the tick logs this file name and does nothing; the chat verb says assignments are not set up yet). | **PENDING — apply after merge.** Verify: `SELECT to_regclass('public.chief_assignments') IS NOT NULL;` (t), `SELECT relrowsecurity FROM pg_class WHERE relname='chief_assignments';` (t), `SELECT count(*) FROM pg_policies WHERE tablename='chief_assignments';` (0). |
| `supabase/APPLY-2026-09-04-proposals-with-life.sql` | `agent_queue.expires_at` + `reminded_at`, `expired` added to the status CHECK (found by definition, not by name), and a partial index for the hourly sweep (`proposal_life.py`): a filed proposal nobody approves is let go after 48 hours, and reminded about once after 6. Code is fail-soft without it — it probes for the columns and files without an expiry; if the CHECK is not widened an overdue draft is dismissed with the reason in `ai_reasoning`. | **PENDING — apply after merge.** Verify: `SELECT column_name FROM information_schema.columns WHERE table_name='agent_queue' AND column_name IN ('expires_at','reminded_at');` (2 rows) and `SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='public.agent_queue'::regclass AND conname='agent_queue_status_check';` (includes `'expired'`). |
| `supabase/ROLLBACK-2026-09-03-kmj-site-manual.sql` | KMJ's hand-built site is NOT a migration: `site_sync.py` renders `sites/kmj-creative-solutions/` on every boot and writes it into the `business_sites` row when its hash changed (`html_source = manual`). The first install kept the composer page set under `site_config.manual_backup`; this file puts it back (set `SITE_SYNC=off` first). | rollback only — install is automatic on deploy |
| `supabase/APPLY-2026-09-03-sms-sent-by.sql` | `sms_messages.sent_by` — practitioner / chief / system, so the thread can mark who sent a text. Code writes it on every outbound; reads tolerate NULL. | **applied** 2026-09-03 via the SQL editor |
| `supabase/APPLY-2026-09-02-sms-numbers.sql` | Dedicated SMS numbers phase B — `sms_numbers` (one live number per business; inbound routes by `To`, outbound sends from it). Code reads it fail-soft, so it can go in before or after the deploy. | **applied** 2026-09-02 via the SQL editor (`applied \| 0`); indexes + owner policy verified |
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
