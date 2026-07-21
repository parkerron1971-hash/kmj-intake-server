# Billing Go-Live Runbook — locked pricing (2026-07-21)

Kevin's pricing ruling: **Starter $79 · Professional $199 · Practice $399**,
annual = 2 months free, **Founding Member = Professional at $149/mo locked
for the life of the subscription, first 50 seats**. Nonprofit/ministry =
20% coupon code. Credit packs unchanged ($10/100 · $25/275 · $50/600 —
already live, no dashboard products needed).

---

## The fast path (one click, ~2 minutes)

1. Merge this PR (Railway deploys main) + the frontend PR.
2. Mission Control → **Money & Website** → press
   **"Create Stripe catalog (products + prices + MINISTRY20)"**.
   The server creates all 4 products, all 8 recurring prices, and the
   MINISTRY20 promo using its own Stripe key. Idempotent — pressing it
   twice reuses, never duplicates (prices carry lookup_keys).
3. The panel shows the exact env block — **Copy env block** → paste into
   Railway → Variables → save. Railway redeploys; pricing is live.
4. Verify per §4 below.

The manual dashboard path below does the same thing by hand — keep it as
the fallback/reference.

---

## 1. (Manual fallback) Create the products in the Stripe dashboard

Stripe dashboard → **Product catalog → + Add product**. Create THREE
products, each with a monthly and a yearly recurring price:

| Product name | Monthly price | Yearly price |
|---|---|---|
| Solutionist Starter | $79.00 / month | $790.00 / year |
| Solutionist Professional | $199.00 / month | $1,990.00 / year |
| Solutionist Practice | $399.00 / month | $3,990.00 / year |

Then ONE more product for the founder cohort (its own product so the
invoice line reads right):

| Product name | Monthly price | Yearly price (optional) |
|---|---|---|
| Solutionist Professional — Founding Member | $149.00 / month | $1,490.00 / year |

Every price: **Recurring**, USD. Copy each price id (`price_…`) as you go —
8 ids total (6 if you skip the founder-annual and starter-annual variants;
only the three monthly tier ids + founder monthly are required to launch).

## 2. Set the env vars on Railway

Railway → kmj-intake-server → Variables:

```
STRIPE_PRICE_ID_STARTER=price_…
STRIPE_PRICE_ID_PROFESSIONAL=price_…
STRIPE_PRICE_ID_PRACTICE=price_…
STRIPE_PRICE_ID_STARTER_ANNUAL=price_…
STRIPE_PRICE_ID_PROFESSIONAL_ANNUAL=price_…
STRIPE_PRICE_ID_PRACTICE_ANNUAL=price_…
STRIPE_PRICE_ID_FOUNDER=price_…
STRIPE_PRICE_ID_FOUNDER_ANNUAL=price_…
STRIPE_PRICE_ID_DEFAULT=<same id as STRIPE_PRICE_ID_PROFESSIONAL>
FOUNDER_SEAT_LIMIT=50
```

Railway redeploys on save. `BILLING_ENFORCE` stays **off** — beta accounts
keep free access; going live with prices does NOT lock anyone out.

## 3. Nonprofit / ministry coupon

Stripe dashboard → **Coupons → + Create coupon**:
- Name: `Ministry & Nonprofit`
- Type: **20% off, forever**
- Promotion code: `MINISTRY20` (shareable)

(Handed out manually to churches/nonprofits; applied at checkout.)

## 4. Verify (5 minutes)

1. `GET /billing/status` → `tiers_configured` all true, `founder.configured`
   true with `seats_left: 50`.
2. App → Settings → Billing & Plan → tier cards show real prices; the
   Founding Member card shows "0 of 50 seats taken"; Start Subscription
   enabled.
3. Optional smoke test: subscribe a test business to Founder monthly,
   confirm the businesses row gets `subscription_plan` = founder price id
   and the seat counter ticks to 1 of 50. Cancel via the portal after.

## 5. What the code does with these (already shipped)

- `feature_gates.PRICE_ENV_TO_PLAN` maps every variant price (annual,
  founder) to its base tier — entitlements identical, only price differs.
- `/billing/checkout` accepts `plan` = `starter` / `professional` /
  `practice` / `starter_annual` / `professional_annual` / `practice_annual`
  / `founder` / `founder_annual`.
- The founder cap is enforced at checkout creation against REAL
  subscription rows (active/trialing/past_due hold seats); the seat counts
  shown in the app come from the same query — the "X of 50" is never a
  marketing number.
- Beta/comped accounts: `comp_tier` still wins over Stripe (launch-ops),
  so existing testers see no change until enforcement day.

## 6. Enforcement day (later, separate decision)

When ready: `BILLING_ENFORCE=on`. Do NOT flip it the same day prices go
live — announce, give the beta cohort their founder-seat window first.
