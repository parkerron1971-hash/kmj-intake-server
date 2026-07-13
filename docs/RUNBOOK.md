# Runbook — deploy, rollback, incidents

Operating the Solutionist System backend + frontend. Written so someone
other than Kevin can keep it running.

## Deploy

| Repo | Trunk | Deploys to | Trigger |
|---|---|---|---|
| kmj-intake-server (backend) | `main` | Railway | push / merge to `main` |
| solutionist-studio (frontend) | `module-system` | Vercel | push / merge to `module-system` |

Both are auto-deploy on merge. No manual deploy step. Backend deploy
takes ~1–2 min on Railway; frontend ~2–3 min on Vercel.

Migrations do **not** deploy automatically — apply them by hand in the
Supabase SQL Editor (see `MIGRATIONS.md`). Merge the code first, then
apply the migration, unless a PR says otherwise.

## Rollback

- **Bad backend deploy:** Railway dashboard → the service → Deployments →
  pick the last-good deploy → "Redeploy". Or `git revert` the merge on
  `main` and push (auto-redeploys).
- **Bad frontend deploy:** Vercel dashboard → Deployments → promote the
  last-good build. Or revert on `module-system`.
- **Bad migration:** run its paired `*-rollback.sql` (see MIGRATIONS.md).
  Data deletions have no undo.
- **Billing emergency:** `BILLING_ENFORCE=off` (env) makes access checks
  fail open. Enforcement is dormant by default anyway.
- **AI spend emergency:** `SPEND_GUARD` trips automatically at
  `DAILY_SPEND_CAP_USD`. To force-stop AI: set `CHIEF_LLM=off` /
  `CHIEF_INSIGHTS=off`, or lower `DAILY_SPEND_CAP_USD`.

## "Something is down" — first checks

1. **Whole backend 500s / won't boot:** check the Railway deploy log.
   Usual cause = a missing load-bearing env var
   (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON`). The
   Anthropic client is lazy now, so a missing `ANTHROPIC_API_KEY` only
   kills AI, not the whole app.
2. **App loads but Chief is silent:** `ANTHROPIC_API_KEY` missing/rotated,
   or the daily spend cap tripped (check Mission Control / the
   platform_changelog alert), or a Claude API outage.
3. **Frontend white screen:** the ErrorBoundary should catch it and show
   a Reload card; the crash is beaconed to the watchdog stream
   (Mission Control → System Health → Recent errors).
4. **Emails not sending:** `RESEND_API_KEY` unset (fails silently), the
   recipient is on the suppression list, or the domain isn't verified in
   Resend.
5. **Invoices not auto-marking paid:** the Stripe webhook secret is wrong
   or the payment events go to a different Stripe endpoint than the one
   `STRIPE_PAYMENTS_WEBHOOK_SECRET` / `STRIPE_WEBHOOK_SECRET` belongs to.

## Observability

- **Mission Control** (owner-only, in-app) → System Health: connected
  services, watchdog findings, recent client + server errors, builder
  controls. Watchdog runs hourly and pushes the owner on trouble.
- **Costs**: `api_usage` table drives it; `spend_guard` sums it daily.
- **Sentry**: on only if `SENTRY_DSN` is set (PII off).

## Not yet built (known gaps)

Staging environment, automated backups/restore drill, and a formal
on-call rotation don't exist. Supabase keeps automatic backups on its
plan — verify the retention in the Supabase dashboard before relying on
it. These are tracked in `LAUNCH_PLAN.md`.
