# kmj-intake-server — the Solutionist System backend

FastAPI (Python) backend for the Solutionist System. Powers Chief (the
AI chief-of-staff), the composer/site builder, billing, SMS/email, and
all the practitioner-facing data actions.

## Deploy & trunk

- **Trunk = `main`.** Pushing to `main` auto-deploys to **Railway**.
- Live URL: `https://kmj-intake-server-production.up.railway.app` (the
  frontend calls this host).
- **FOOTGUN:** `solutionist-studio/railway/` in the *frontend* repo is a
  dead 2026-05-02 snapshot. This repo is the live backend. Edit Chief
  and every backend behavior **here**, or it doesn't deploy.
- Entry point: `kmj_intake_automation.py` (mounts ~70 routers). The
  `public_site_router` catch-all MUST stay registered last.

## Database (Supabase)

- **Migrations are applied by Kevin, by hand.** New schema changes ship
  as `supabase/APPLY-YYYY-MM-DD-*.sql` (or `__migrations__/YYYY_MM_DD_*`).
  See `docs/MIGRATIONS.md` for the ledger, apply order, and the queries
  that tell you what's live.
- **Server code uses the SERVICE-ROLE key** (`SUPABASE_SERVICE_ROLE_KEY`),
  which bypasses RLS. NEVER use the anon key (`SUPABASE_ANON`) for
  server-side DB access — it ships in the client bundle, and the RLS
  policies are owner-scoped, so anon writes will be blocked. The
  canonical helpers are `sb_clients.sb_*_as_service`.
- Tenant isolation is enforced by RLS **and** by app-layer owner checks.
  See `docs/RLS_MODEL.md` — including the 42P17 recursion rule (a naive
  cross-table policy re-causes a production outage) and the
  permissive-policy trap.

## Security invariants (do not regress)

- **Every write endpoint requires auth + an owner check.** The pattern:
  `user: AuthedUser = Depends(require_user)` + `_require_owner(business_id, user)`
  (service-role read of `businesses.owner_id` vs the JWT user id;
  independent of RLS). Canonical example: `contacts_router.py`.
- **Owner-gated platform surfaces** use `require_owner` (checks the
  verified-JWT email == `PLATFORM_OWNER_EMAIL`). Mission Control, the
  build bridge, and all `/platform/*` are owner-only.
- **Webhooks fail closed** — Stripe (`stripe_billing` + `stripe_proxy`),
  Resend (`email_sender`) verify signatures; a missing secret rejects
  the event.
- **Spend + rate guards:** `spend_guard.py` (daily $ circuit breaker,
  `DAILY_SPEND_CAP_USD`) and `rate_limit.py` (per-caller) sit in front of
  the paid AI endpoints. Both fail OPEN.
- Metering: every paid API call should log via `api_usage_logger`
  (`log_api_usage` / `_sync`), which feeds the spend guard + Costs view.

## Chief (chief_of_staff.py)

- 113 `ACTION_HANDLERS`. Every handler returns `{result, label}`; a
  missing `result` blanks the app (toLowerCase crash) — always return
  both. Actions are emitted by the model as `[ACTION:{"type":...}]` tags.
- 3-segment prompt cache: `[[CHIEF_GLOBAL_SPLIT]]` (universal, cached once
  globally) → `[[CHIEF_CACHE_SPLIT]]` (per-business stable) → dynamic
  tail. A segment under the model's 1024-token min silently won't cache.
- Model lanes live in `chief_models.py` (`model_for(lane, plan)`); env
  `CHIEF_MODEL_<LANE>` overrides. Deep/insight lanes scale by plan tier.
- **The build bridge** (`handle_queue_build_request`): owner-gated,
  fail-closed. Owner → files a GitHub `@claude` issue; non-owner → a
  support ticket. Practitioners must NEVER see builder/GitHub/Claude Code
  language — Chief mirrors the action-result wording.

## Env

~94 env vars, most fail SOFT (the feature goes quiet, no crash) — which
is harder to debug than a hard failure. See `.env.example` for the full
list with what breaks without each. The load-bearing ones:
`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON`,
`ANTHROPIC_API_KEY`, `PLATFORM_OWNER_EMAIL`.

## Conventions

- End commit messages with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- One PR per change; never stack PRs (Kevin merges fast — after a merge
  link is handed over, the branch is dead; follow-ups get a fresh branch).
  Always `git fetch` + check PR state before branching from / pushing to
  anything.
- `git push` from a workflow context needs the gh credential helper.
