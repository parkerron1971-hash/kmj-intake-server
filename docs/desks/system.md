# Desk: system

## 1. What it owns

The ground under every room. A pastor or practitioner sees this desk only when
it breaks: the app will not open, a save "works" but nothing is kept, one
church sees another's rows, Chief goes quiet because a guard tripped.

- The database: schema, hand-applied migrations, RLS, the migration ledger.
- Auth and tenant isolation: JWT verification, owner checks, role access, the
  service-role rule, webhook signature policy, spend and rate guards.
- Deploys and CI: Railway (backend), Vercel (frontend), GitHub workflows,
  uptime, on-call, backups.
- Background agents and the scheduler: the watchers, their registry, the
  single-leader lease, Mission Control's Agents and Systems rooms.
- Mission Control itself (owner-only) and Solution Space / the Dev Desk bridge
  (how KAI and its workers talk to the backend), plus the work log.

## 2. Where the code is

Backend (kmj-intake-server, trunk `main`, auto-deploys to Railway):
- `kmj_intake_automation.py`: app entry, mounts every router;
  `public_site_router` stays LAST. `PROCESS_ROLE` (web / worker / all) decides
  what a process runs.
- Auth: `auth_supabase.py` (`require_user`, `optional_user`,
  `require_user_session`); `lead_admin.require_owner` (platform owner by
  verified JWT email vs `PLATFORM_OWNER_EMAIL`); `business_access.py`
  (`business_access(min_role)`, `assert_access`) for owner/admin/member roles.
- DB access: `sb_clients.py` (`sb_*_as_service`, `sb_*_as_user`,
  `set_user_jwt`, `*_current_context`). `schema_probe.py` (send new columns
  only once the probe sees them).
- Guards: `spend_guard.py`, `rate_limit.py`, `api_usage_logger.py`,
  `webhook_guard.py` (one missing-secret policy for every inbound webhook),
  `ownership_sweep.py` (the measurement behind `test_business_access_ratchet`),
  `account_lifecycle.py` (`BUSINESS_CHILD_TABLES`, `EXPORT_EXCLUDED`,
  `USER_CHILD_TABLES`: export + delete coverage), `access_log_redaction.py`.
- Scheduler + agents: `scheduler_lock.py` (lease row `scheduler_lease`,
  `is_leader()`), `chief_scheduler.py`, `agents_live.py` (Agents at work:
  backend + GitHub agents on one screen), `platform_console.py`
  (`/platform/*`, `AGENT_REGISTRY`), `hermes_agent.py` (the watcher pattern:
  every run -> `platform_agent_runs`, findings -> `platform_changelog`),
  `platform_watchdog.py` (also `/telemetry/startup`), `db_health.py`
  (`/platform/db-health/*`), `platform_today.py`, `ops_desk.py` (lanes,
  rhythm, `/dev-bridge/ops/*` for KAI). Money auditor logic lives in
  `money_auditor.py` (money desk owns it; this desk owns its registry entry).
- Dev Desk bridge: `dev_bridge.py` (`/platform/dev-desk*` owner JWT;
  `/dev-bridge/*` device token via `_require_device`; tables `dev_tasks`,
  `dev_bridge_devices`), `dev_kai.py`, `dev_fleet.py`, `dev_relay.py`,
  `dev_cards.py`, `dev_alerts.py`, `dev_redact.py` (scrubs what KAI writes).
- Work log: `worklog.py`, `unfinished_work.py`, `worklog/` (format in
  `worklog/README.md`).
- Migrations: `supabase/APPLY-YYYY-MM-DD-*.sql` (+ some `ROLLBACK-*.sql`),
  older `__migrations__/YYYY_MM_DD_*.sql`.
- Docs: `docs/MIGRATIONS.md`, `docs/RLS_MODEL.md`, `docs/RUNBOOK.md`,
  `docs/OPERATIONS.md`, `docs/BETA_VERIFY_QUERIES.md`, `docs/RESTORE.md`,
  `docs/backup_and_restore.md`, `.env.example` (every var and what breaks).
- Workflows (`.github/workflows/`): `ci.yml` (`test-part` 1-4, `test-db`,
  aggregator `test`), `pr-review.yml`, `oncall.yml`, `uptime.yml` (every 10
  min), `deploy-check.yml`, `security-steward.yml`, `backup.yml`,
  `restore-drill.yml`, `chief-eval-weekly.yml`, `claude.yml`.
  `scripts/shard_tests.py` splits the suite.

Frontend (solutionist-studio, trunk `module-system`, Vercel):
- Mission Control: `src/modules/platform/` (`module.config.ts`, `rooms.ts`,
  `pages/` e.g. `TodayPanel`, `AgentsPanel`, `SystemHealthPanel`,
  `DatabasePanel`, `DevDeskPanel`, `PlanPanel`, `CostsPanel`;
  `components/McShell.tsx`, `McRoomShell.tsx`), styles
  `src/core/styles/mission-control.css` (prefix `mctl-`), deep links
  `src/core/lib/mcOpen.ts`.
- Boot: `index.html` + `public/startup.js` (the "Opening Solutionist" guard),
  `src/main.tsx`. Auth: `src/core/lib/supabaseClient.ts` (`authedFetch`).
- CI: `.github/workflows/ci.yml` job `gate`.

Solution Space (`C:\Users\kmccl\claude-bench`, Electron, NO git remote):
- `electron/bridge.js` (polls `/dev-bridge/queue`), `kai.js`,
  `kai-orchestrator.md`, `kaiPhone.js`, `fleetRelay.js`, `accounts.js`,
  `limits.js`, `charter.js`, `policy.js`, `worktree.js`, `redact.js`.

## 3. Rules that must not break

- Server code reads/writes with the service role; never the anon key. Rows the
  server owns (logs, ledgers, undo, runs) are written `*_as_service` even inside
  a chat that has a user JWT bound.
- Every write endpoint: `require_user` + an owner/role check in code. Platform
  surfaces (`/platform/*`, Mission Control, the build bridge): `require_owner`.
  `/dev-bridge/*`: device token only.
- RLS rules 0-4 in `docs/RLS_MODEL.md`: new views `security_invoker = true`;
  cross-table checks only through SECURITY DEFINER helpers (inline EXISTS =
  42P17 outage); no `USING (true)` policy on a tenant table (a build check now
  refuses one); app logins update only the owner columns of `businesses`.
- New tenant table: RLS on, one owner-scoped policy, service-role access, and
  listed in `BUSINESS_CHILD_TABLES` or `EXPORT_EXCLUDED` (test pins it).
- New `businesses` column: closed to app logins until granted; add to
  `OWNER_COLUMNS` in `__tests__/test_businesses_server_columns.py` or the
  server-columns trigger list.
- Migrations: idempotent, one ledger row in `docs/MIGRATIONS.md`, PR says
  "apply this migration after merge". The owner applies them by hand. Merge
  code first; code must work (fail soft, read as empty) before the table exists.
- Webhooks fail closed on a missing secret. Spend and rate guards fail open.
  Every paid call logs through `api_usage_logger`.
- Never change compute, Railway/Vercel secrets or deploy settings without the
  owner's yes. KAI never moves work into or out of Build.
- Solution Space: local branches only, never a PR; leave the checkout on the
  branch you found; never `npm run space` (overwrites the running app's `dist/`).

## 4. Traps already hit

- Several web replicas: state kept in process memory is lost on the next call.
- Python `logging` never reaches Railway logs; use `print(..., flush=True)` with a prefix.
- PostgREST keeps quotes on `col=eq."v"`; quote with `quote(str(v), safe='')`.
- A user-JWT write to a table with no INSERT policy returns None silently (42501).
- PostgREST bulk insert needs identical keys per row (PGRST102); `FakeSB` hides it.
- A fake is not proof for a write path; say "tests pass" and "proved on the database" separately.
- Allow-all policies sat next to scoped ones on twenty tables until 2026-11-18.
- `os.environ.setdefault` at test-module top leaks into other files in the shard ("Name or service not known" = leak, not flake).
- `git stash` is shared across worktrees (never stash); another session can switch the checkout, so check the branch in the same command as `git commit`.
- `core.autocrlf=true`: Edit/Write leave mixed endings and the diff balloons; normalize changed files to LF before `git add`.
- `Remove-Item` and `git worktree remove --force` follow a junction and empty the target.
- Heredoc Python mangles backslashes; Git Bash rewrites args starting with `/` (`MSYS_NO_PATHCONV=1`).
- No `jq` here: a watcher piping to jq is silently blind; use `gh --jq`.
- Frontend `gh pr merge --auto` merges at once (no required checks); backend auto-merge waits for `test`.
- The session's CLAUDE.md can be from a stale branch; read `origin/main:CLAUDE.md` (Lanes, work log).
- A var can exist in Railway even if no code greps for it; list names before asking the owner.
- `src/main.tsx` has no semicolons: a line starting with `(` glued onto the last call and crashed every load.
- Supabase SQL editor: long typed SQL wedges the tab; DROP scripts show a confirm; each editor load runs a heavy query (Disk IO).
- `docs/RUNBOOK.md` "Not yet built" predates `backup.yml` / `restore-drill.yml`; check the workflows.
- CI agents misdiagnose without evidence: gather it in shell first (on-call lesson).

## 5. How to check work

- `pytest -q -n auto --dist loadfile __tests__/<files>`; for this desk usually
  `test_business_access_ratchet.py test_businesses_server_columns.py
  test_settings_server_keys.py test_close_allow_all_policies.py
  test_export_import.py test_process_role.py test_scheduler_gate.py
  test_dev_bridge.py test_dev_kai.py test_dev_fleet.py test_dev_relay.py
  test_agents_live.py test_db_health.py test_ops_desk.py
  test_worklog_and_unfinished.py test_shared_rate_limit.py
  test_spend_guard_day_start.py test_inbound_webhook_signatures.py`.
- `python scripts/shard_tests.py --check` after adding test files; new
  `*_db.mjs` checks join the `test-db` job in `ci.yml`.
- Migrations: rehearse in a `*_db.mjs` (PGlite) check where one exists; after
  the owner applies, read back with the queries in `docs/MIGRATIONS.md` and
  `docs/RLS_MODEL.md` (`to_regclass`, `pg_policies`, `relrowsecurity`).
- Live: Railway HTTP logs (`railway logs --http --filter '@path:/x'`), commit
  statuses via `gh api repos/<repo>/commits/<sha>/status`, `/health` and
  `/health/ready`.
- Frontend: `npx tsc -p tsconfig.app.json --noEmit` (zero new errors over the
  baseline), `npx vite build`, `scripts/owner-gate-check.ts` (`npm run
  check:owner`), `scripts/check-db-health.mjs`, `scripts/dev-desk-check.mjs`,
  `scripts/check-startup.mjs`.
- Solution Space: `npm run typecheck`, `npm test`, a throwaway
  `npx vite build --outDir .tmp-x`.

## 6. Edges

- Every desk: its new tables and policies pass through this desk's rules;
  the desk that owns the feature writes the migration, this desk's checklist applies.
- chief: owns Chief's prompt, actions and lanes, including platform Chief;
  this desk owns spend/rate guards and the build bridge's owner gate plumbing.
- tickets: reads `/dev-bridge/tickets` (device token, in `support_router.py`)
  and diagnoses; incidents found here go to it or to the owning desk.
- money: owns `money_auditor.py` logic, billing enforcement, Stripe webhooks;
  this desk owns the webhook-guard policy and the agent registry entry.
- messaging: Resend/Twilio webhook signature checks follow `webhook_guard.py`.
- Shared files to coordinate on: `kmj_intake_automation.py` (router order),
  `platform_console.py`, `.github/workflows/ci.yml`, `docs/MIGRATIONS.md`,
  `account_lifecycle.py`.
