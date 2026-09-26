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

2026-09-07 media follow-up: `APPLY-2026-09-07-ledger-after-erasure.sql` is
**APPLIED**, explicitly approved and rollback-tested. It includes documented
erased sequence ranges when bounding the ledger tip, without permitting
backward or unsupported forward changes. Live staff rehearsal and cleanup passed.
`APPLY-2026-09-07-media-library.sql` is **APPLIED**; rollback tests passed for
private storage, queue concurrency and immutable media review, and production
RLS/browser revocations were verified. Drive configuration remains a prerequisite.

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
| `supabase/APPLY-2026-09-26-chief-build-lanes.sql` | Chief's background jobs run side by side when they touch different things: `chief_build_claim` serializes per business AND lane (`chief_build_lane`: site / image / plan) instead of per business. Same signature; replayable. | **PENDING.** Requires the 2026-09-18 builds migration. The code works before and after it (before it, jobs queue per business as they always have). CI check: `scripts/chief-build-lanes-db-check.mjs`. Verify after applying: `select chief_build_lane('flyer'), chief_build_lane('plan'), chief_build_lane('event_setup')` returns `image, plan, site`, and `has_function_privilege('authenticated','chief_build_claim(uuid,uuid)','EXECUTE')` is false. |
| `supabase/APPLY-2026-09-26-marketing-campaigns.sql` | Owner campaign briefs, revision/audit history, bounded plan requests, stable post relationships and Buffer metric snapshots. | **APPLIED 2026-09-26 15:35 UTC**, with the Chief local-work migration in one transaction through the Supabase Management API, explicitly authorized by Kevin. RLS/grants and rollback-only campaign audit/revision checks passed. Automatic metrics refresh remains unchanged. |
| `supabase/APPLY-2026-09-25-voice-turn-log.sql` | `voice_turn_log`: one row per spoken call turn, measured by the app (time to first audio vs its 1s budget, first reply audio, where the time went, barge-in, underruns, TTS cache hits). Joins `model_route_log` on `request_id`. Service-role only: RLS on, no policies, no anon/authenticated grants. | **APPLIED 2026-09-25 via the SQL editor, after #1041 merged.** Verified: RLS on, 0 policies, anon/authenticated SELECT denied, service_role INSERT granted, 21 columns, 3 indexes; PostgREST sees it (service GET returns `[]`). |
| `supabase/APPLY-2026-09-25-model-route-log.sql` | `model_route_log`: one row per streamed Chief request from the two-track reply (lane, complexity, model, escalation, time to first token vs its budget, total time, cost across every model call). Service-role only: RLS on, no policies, no anon/authenticated grants. | **APPLIED 2026-09-25 via the SQL editor, after #1040/#1041 merged** (same batch as voice_turn_log). Verified: RLS on, 0 policies, anon/authenticated SELECT denied, service_role INSERT granted, 34 columns, 3 indexes; PostgREST sees it (service GET returns `[]`). |
| `supabase/APPLY-2026-09-25-lane-saved-links.sql` | `lane_saved_links`: owner-saved Lane merchant links (page, name, account), application-encrypted, keyed-hash unique per page and account, 20 per owner; `lane_link_save/list/delete`. | **APPLIED 2026-09-25 via the Management API, before the code.** Verified: RLS on, 3 functions, no anon/authenticated table or function access, service_role executes. A rolled-back `DO` probe saved and listed a row on the live database; 0 rows after. |
| `supabase/APPLY-2026-09-24-lane-wallet.sql` | Encrypted owner-bound purchase journal, revision leases and permanent checkout claims. | **APPLIED 2026-09-24.** Production RLS and service-only table/function permissions verified. Checkout remains disabled. See docs/LANE_PILOT_SETUP.md. |
| `supabase/APPLY-2026-09-23-link-wallet.sql` | Customer-owned encrypted Link OAuth sessions, callback-state lookup and fenced writes. | **APPLIED 2026-09-24.** Production RLS and service-only table/function permissions verified. Customer OAuth remains unconfigured; no live spending is enabled. See docs/LINK_WALLET.md. |
| `supabase/APPLY-2026-09-24-dev-desk-agents.sql` | `dev_tasks.agent` (`claude` default, or `codex`; CHECK) so a Solution Space task names its coding agent; `dev_bridge_devices.agents` (what each device's build can open, written on every queue poll); the agent joins the authorized scope the `dev_task_authority_immutable` trigger guards. | **APPLIED 2026-09-24 via the Management API, before the code.** Rehearsed first in a rolled-back `DO` block (existing rows read `claude`, a Codex insert passes, an unknown agent is refused, status still moves on an authorized task, the agent cannot be changed). Verified: both columns, the constraint, the trigger naming `new.agent`, 10/10 rows `claude`. |
| `supabase/APPLY-2026-09-18-chief-builds.sql` | Durable build identities, fenced worker leases, versioned approval/resume, owner-scoped image reservation. | **APPLIED** (date not recorded; the first build row is 2026-09-19, and `CHIEF_BUILDS=on` in production). Verified live 2026-09-26: the lease and revision columns are present, and a test workshop build in Vertical Test Coach ran end to end through the claim, renew and save functions. Requires chief_jobs and the 2026-09-08 image studio migration. |
| `supabase/APPLY-2026-09-15-platform-marketing.sql` | Owner-only Buffer channel selection, immutable marketing exports, versioned calendar, atomic batch review, durable delivery claims and audit events. | **APPLIED 2026-09-15.** Production rollback rehearsal and schema verification passed: four RLS-protected tables, export bucket, atomic review/claim and audit. Calendar remains paused with no posts. |
| `supabase/APPLY-2026-09-13-platform-inbox-sent.sql` | `platform_emails.direction` (`inbound` default / `sent`) + `resend_id`, so mail composed from Mission Control's inbox is recorded next to the mail that came in and listed under a Sent folder. Code is fail-soft without it: the inbox list retries without the direction filter, compose still sends but reports `recorded: false`. | **applied 2026-09-13 via the SQL editor, verified** — `columns_ok = 2`, `sent_rows = 0` right after apply; #952 merged first. |
| `supabase/APPLY-2026-09-12-chief-computer-completion.sql` | Service-only confirmed-order reconciliation: inventory, supplier note, one expense, planned-cancellation undo, replay claim. | **PENDING. Apply after PR5 merge.** Production dependency columns verified with zero-row reads. Local PostgreSQL role, retry and closed-period probes passed. Execution stays off. |
| `supabase/APPLY-2026-09-12-chief-computer-runtime.sql` | Service-only atomic plan, approval/job insertion, state/hold transitions, ordered events and settings merge. | **APPLIED 2026-09-12 (UTC)** after PR937 merged. Production runtime transaction and role rollback probe passed. Keep execution disabled until all six arc PRs are integrated. |
| `supabase/APPLY-2026-09-12-chief-computer.sql` | Chief errand/event foundation and service-only encrypted login vault. | **APPLIED 2026-09-12 (UTC)** after PR935 merged. Production transactional role probe passed: RLS enabled, browser writes denied, zero vault policies, authenticated/anonymous ciphertext SELECT denied. Service API schema and backend health verified. Vault key and saved cards remain disabled. See `docs/CHIEF_COMPUTER.md`. |
| `supabase/APPLY-2026-09-11-agent-coordination.sql` | Owner-configured bot profiles, scoped assignment inbox, atomic claims, revision guards and service-only access. | **APPLIED 2026-09-11** to production before the feature release. Both tables have RLS enabled; anonymous reads and authenticated writes are denied; service access and the enabled assignment guard were verified. |
| `supabase/APPLY-2026-09-11-connected-ai.sql` | Service-only device pairing, credential hashes, durable Chief job leases and single-send approval transitions. | **PENDING. Apply this migration after merge**, with `CONNECTED_AI_ENABLED=off`. Requires existing contacts, agent_queue, chief_jobs and invoices, plus `APPLY-2026-09-09-invoice-archive.sql`. Local PostgreSQL lifecycle and idempotency checks passed; live application is not claimed. See `docs/CONNECTED_AI_PILOT.md`. |
| `supabase/APPLY-2026-09-09-academy-live.sql` | Live sessions, persistent participant controls, signed-webhook attendance, and caller-scoped class access. | **PENDING**. Apply after the September 8 academy-school migration, then release Railway and frontend changes. No LiveKit secrets go in Supabase. |
| Frontend `supabase/APPLY-2026-09-08-course-learning.sql`, then `APPLY-2026-09-08-academy-authoring.sql`, then `APPLY-2026-09-08-academy-school.sql` | Rich lessons, protected student submissions, atomic Chief course authoring, verified school access, course teachers and grading. | **APPLIED 2026-09-08**, after a successful production rollback rehearsal. Anonymous school/authoring access and browser access to the authoring log are denied. Enable `ACADEMY_CLASSROOM_V2=on` only once the frontend is live. Do not reapply the older learning migration after the school migration. |
| `supabase/APPLY-2026-09-09-image-upload-policy.sql` | Qualifies the storage object path so the owner policy does not read `businesses.name`. | **APPLIED 2026-09-09 UTC** during the upload repair. Owner storage insertion and gallery/conversation reads passed a production rollback check. |
| `supabase/APPLY-2026-09-08-image-studio.sql` | Private image gallery, generation reservations, publication deduplication and atomic post preparation. | **APPLIED 2026-09-09 UTC** during the upload repair; tables, private bucket, policies and reservation function verified. Storage policy correction above also applied. |
| `supabase/APPLY-2026-09-08-conversation-desk.sql` | Chief conversation metadata for saved Image Studio threads, with business-owner RLS. | **APPLIED 2026-09-09 UTC** with the Image Studio setup. Metadata column and owner reads verified. |
| `supabase/APPLY-2026-09-07-restricted-entry-boundary.sql` | Restrictive browser policy and service-write trigger keep restricted readings out of the ordinary module store. | **APPLIED 2026-09-07.** Preflight found zero affected rows. Rollback checks verified ordinary-store rejection and protected-store access. No rows deleted. |
| `supabase/APPLY-2026-09-07-program-outcomes.sql` | Service-only immutable snapshots and atomic report approval. | **APPLIED 2026-09-07.** RLS and browser revocations verified; rollback tests rejected stale approval and approved-snapshot mutation. |
| `supabase/APPLY-2026-09-07-financial-policy.sql` | Service-only financial policies, historical account bindings, atomic owner changes and change history; database connection guard. | **APPLIED 2026-09-07.** Permissions, atomic policy change and locked-connection rejection verified. Existing provider arrangements require separate review; no tenant lock enabled. |
| `supabase/APPLY-2026-09-07-business-learning.sql` | Private operating profiles, revision history and atomic compare-and-save RPC. Service role only; no shared vertical writes. | **PENDING. Apply before deploying the business-learning backend.** See `docs/BUSINESS_LEARNING.md` for verification and smoke test. |
| `supabase/APPLY-2026-09-06-growth-intelligence.sql` | Service-only Growth records, contact interaction/status history, unique campaign credit, and per-business reporting preferences. | **Applied during the 2026-09-06 release, verified.** Both tables have RLS; both triggers exist; zero businesses lack preferences; zero anon/authenticated table grants; all three unique indexes exist. |
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
| `supabase/APPLY-2026-09-04-chief-assignments.sql` | `chief_assignments` — an outcome the standing agent works over days (`chief_assignments.py`): a measurable target, a deadline, the moves log with reasoning written before each move, the tick's `next_check_at` cursor and the per-day think counter. Two indexes (the tick's due read; the card's per-business read). RLS on, **no policies** — service-role only, `first_run_arc` precedent; the app reads it through `GET /agents/chief/assignments` (owner check in code). Code is fail-soft without it (the tick logs this file name and does nothing; the chat verb says assignments are not set up yet). | **applied 2026-09-04 via the SQL editor, verified** — table present, RLS on, 0 policies (the three 09-04 files ran as one batch; the confirming SELECT returned assignments=t, moves=t, queue_cols=2, status_check incl. 'expired', policies=0). |
| `supabase/APPLY-2026-09-04-proposals-with-life.sql` | `agent_queue.expires_at` + `reminded_at`, `expired` added to the status CHECK (found by definition, not by name), and a partial index for the hourly sweep (`proposal_life.py`): a filed proposal nobody approves is let go after 48 hours, and reminded about once after 6. Code is fail-soft without it — it probes for the columns and files without an expiry; if the CHECK is not widened an overdue draft is dismissed with the reason in `ai_reasoning`. | **applied 2026-09-04 via the SQL editor, verified** — both columns present; `agent_queue_status_check` now reads `draft, approved, sent, dismissed, failed, expired`. |
| `supabase/APPLY-2026-09-04-chief-moves.sql` | `chief_moves` — one row per move Chief made on its own (`outcome_ledger.py`) with the ids it produced, and the outcome the six-hourly reconciler fills in from plain reads (approved / dismissed / expired / replied / completed / ignored / met / missed). Feeds the digest in every prompt, the retire rule, and the weekly report. RLS on, **no policies** — service-role only. Code is fail-soft without it (recording returns nothing, the tick logs this file). | **applied 2026-09-04 via the SQL editor, verified** — table present, RLS on, 0 policies. |
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

## Chief subscription work (2026-09-26)

`supabase/APPLY-2026-09-26-chief-local-work.sql` - **APPLIED 2026-09-26 15:35 UTC**.
Kevin explicitly authorized the assistant to apply both migrations, overriding
the manual-application rule for this operation. All prerequisites were verified.
Six new tables have RLS with no browser-role access; all seven new RPCs are
service-role only. Rollback-only service-role checks passed for both agents:
atomic claims, duplicate-request/reply handling, note acknowledgements and
report-key rotation. No test campaigns, work, tasks or devices remain.
The API health and readiness endpoints returned HTTP 200 after application.
Requires Dev Bridge, September 16 authority, September 24 agents and September 26
marketing campaigns. Service-only conversations and atomic create/claim/reply/ack
RPCs. See `docs/CHIEF_LOCAL_WORK.md` for the paired desktop/frontend release.

## Rollback

Most feature migrations ship a paired `*-rollback.sql` (grep the file's
header for `rollback`). RLS-policy changes: re-create the dropped policy
from `pg_policies` output captured before the change. There is no undo
for data deletions.
