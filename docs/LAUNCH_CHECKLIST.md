# Launch Checklist — env config + one-time setup

The business-readiness audit (2026-07-03) found that most "missing"
capabilities are actually **built and dormant** — they turn on with env
vars. This is the single list of what to set, where, and in what order.
Every item is safe to do independently; nothing here requires a deploy
beyond Railway's automatic restart on env change.

## 1. Railway env vars (kmj-intake-server)

### Error visibility (do first — takes 5 minutes)
| Var | Value | Effect |
|---|---|---|
| `SENTRY_DSN` | from sentry.io → new project (Python/FastAPI) | Backend exceptions become visible. Code is already wired (`kmj_intake_automation.py`); no-op until set. |

### Push notifications (Chief-in-your-pocket)
Generate once locally:
```
npx web-push generate-vapid-keys
```
| Var | Value |
|---|---|
| `VAPID_PUBLIC_KEY` | the generated public key |
| `VAPID_PRIVATE_KEY` | the generated private key |
| `VAPID_SUBJECT` | `mailto:kmjcreativesolution@gmail.com` |

Everything else (service worker, subscribe flow, morning brief) is
already live in both repos.

### Billing enforcement (when you decide to start charging)
Create the three products/prices in the Stripe dashboard first
(Starter $79 / Professional $199 / Agency $399 monthly), then:
| Var | Value |
|---|---|
| `STRIPE_PRICE_ID_STARTER` | `price_…` |
| `STRIPE_PRICE_ID_PROFESSIONAL` | `price_…` |
| `STRIPE_PRICE_ID_PRACTICE` | `price_…` |
| `BILLING_ENFORCE` | `on` — THE switch. Until then trials/past-due never block. |

⚠ `feature_gates.py` marks **multi_seat as NOT BUILT** — don't market
the Practice tier's collaboration until it ships.

### Webhook hardening (this PR)
| Var | Where to get it | Effect |
|---|---|---|
| `STRIPE_PAYMENTS_WEBHOOK_SECRET` | Stripe dashboard → the webhook endpoint pointed at `/stripe/webhook` → signing secret | Legacy payments webhook starts verifying signatures (until set: accepts unsigned + logs a warning, same as before). |
| `CORS_ALLOWED_ORIGINS` | optional | Default `*` is deliberate (bearer-token auth, public embeds). Set a comma-separated list only if you accept fencing the embeds. |

## 2. Resend dashboard (one-time)

Webhook → edit the existing `/email/webhook` webhook → **add events**
`email.bounced` and `email.complained` (keep `email.opened`). This
feeds the new suppression list so we stop sending to dead/hostile
addresses. Requires the `supabase/email-suppressions-migration.sql`
migration (below).

## 3. Supabase SQL editor (this PR's migrations)

Run once:
- `supabase/email-suppressions-migration.sql` — suppression table
  (service-role only). The send path fails open until it exists, so
  order doesn't matter.

## 4. Secret rotation (frontend `.env` — local machine)

`.env` is gitignored (never committed), but any **build made from this
machine** (desktop app bundles, manual deploys) shipped these into the
JavaScript where users can extract them. Rotate all four at their
dashboards, and don't put the new values back into `VITE_*` vars:

- `VITE_CANVA_CLIENT_SECRET` — rotate at canva.com developers
- `VITE_CLOUDINARY_API_SECRET` — rotate at cloudinary console
- `VITE_REMOVEBG_API_KEY` — rotate at remove.bg
- `VITE_APIFY_API_KEY` — rotate at apify console

These four are only used by the LEGACY workspace surfaces (old Content
Studio / Director / Discovery pages), which fail soft with a "key not
configured" message when the vars are absent. If you still use those
tools, say the word and we'll proxy them through the backend properly.
Also check the Vercel project's env vars — if any of these were copied
there, remove them (the live core app doesn't need them).

## 5. Supabase auth settings (worth confirming)

- Email confirmation ON/OFF is a project setting (Authentication →
  Providers → Email) — decide deliberately; there's no code-side gate.
- Redirect URLs for password recovery already documented in Arc 16.

## Done when

- Sentry shows a test exception, `/email/webhook` logs a SUPPRESS line
  on Resend's test bounce, `npx web-push` keys are set and a phone
  gets the test push, and (when you flip it) an expired-trial account
  hits the paywall.
