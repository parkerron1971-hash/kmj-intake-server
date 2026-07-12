# Solutionist Hybrid Pricing Model — Specification v2 (Prepaid Credits)

**Status:** Kevin-ruled 2026-07-12; supersedes `pricing_model.md` (v1, 2026-06-10).
**Rulings captured here:** (1) hybrid confirmed; (2) overage flips from postpaid
billing to **prepaid credits, Claude-style**; (3) allowances raised (75 was
starving engagement); (4) the **model ladder becomes a tier feature**
(Sonnet 5 → Opus 4.8 → Fable 5); (5) beta funding plan.
**Basis:** in-repo price table (`api_usage_logger.py`, verify at
anthropic.com/pricing before creating Stripe prices), live model lanes
(`chief_models.py`), Phase B metering machinery (dormant, shipped 2026-06-10).

---

## 1. Tiers & allowances

| | **Starter $79/mo** | **Professional $199/mo** | **Elite $399/mo** |
|---|---|---|---|
| Included units / month | **300** | **1,000** | **3,000** |
| Deep-thinking model | Sonnet 5 | **Opus 4.8** | **Fable 5** |
| Chat & voice model | Sonnet 5 | Sonnet 5 | Sonnet 5 |

**Unit weights** (one meter, honestly weighted — machinery already exists):

| Action | Units |
|---|---|
| Chief message (chat, voice, draft) | 1 |
| Deep analysis / weekly insight run | 5 |
| Site build or refine (composer run) | 25 |
| Free forever: bookings, PDFs, contacts, calendar, SMS receipt | 0 |

Rationale for the raise: a Chief message costs ~1–3¢ with prompt caching; v1's
75-unit allowance protected against a cost that barely exists while making the
product feel scarce (2.5 messages/day). Engagement IS the product — a
practitioner who talks to Chief daily does not churn. The expensive action
(site builds, $0.50–2.00) carries the weight instead.

**Customer language:** sell **"AI actions"** — never raw tokens. Tokens are
developer language, scary and unstable (model prices change; we'd be
repricing constantly). "300 AI actions a month" is legible to a barber.

## 2. Prepaid credits (the Claude-style top-up)

- Monthly units reset with the billing cycle. When they're exhausted, the
  practitioner **tops up a credit balance**: packs at **$10 / $25 / $50**
  (Stripe one-time payments — no metered invoicing).
- Draw-down order: monthly allowance first, then credits.
- **Credits never expire.** (Trust > breakage revenue. Expiring credits are
  the fastest way to make a small-business owner feel robbed.)
- Optional **auto-reload** ("top up $25 when my balance hits 0") — off by
  default, one toggle.
- Credit pricing ≈ 8–10¢/unit effective (e.g., $25 → 275 units) — above cost,
  below panic. Exact pack sizing at build time.
- **No overage invoices ever.** The balance IS the cap — v1's 2× bill-cap
  machinery is obsolete; running dry simply pauses AI actions with a friendly
  top-up prompt (nothing else in the product locks).

## 3. The model ladder as tier feature

Lanes today (`chief_models.py`): chat/voice/draft = Sonnet 5 · deep/insight =
Opus 4.8 · background = Haiku 4.5.

| Lane | Starter | Professional | Elite |
|---|---|---|---|
| chat / voice / draft | Sonnet 5 | Sonnet 5 | Sonnet 5 |
| deep / insight | **Sonnet 5** | **Opus 4.8** | **Fable 5** |
| background | Haiku 4.5 | Haiku 4.5 | Haiku 4.5 |

- Chat/voice stays Sonnet 5 for ALL tiers deliberately: it is the
  latency/quality sweet spot, and voice+chat share one per-model prompt cache
  (splitting doubles cache writes and cold-starts voice — documented in
  chief_models.py).
- The sellable line: *"Elite: your business advised by Anthropic's strongest
  model."* Deep/insight lanes are low-volume, so even premium Fable pricing
  stays cheap per customer.
- Build: `chief_models.model_for(lane)` gains a tier parameter (small change;
  env overrides keep working).
- ⚠ **Fable 5 is NOT in `api_usage_logger.MODEL_PRICING_CENTS`** — add it
  (verify price at anthropic.com/pricing) BEFORE Elite launches, or Fable
  usage logs wrong costs.

## 4. Economics (the "how much would I make" section)

Per-customer, monthly (typical ≈ half the allowance; costs from the in-repo
price table with prompt caching):

| | Starter | Professional | Elite |
|---|---|---|---|
| Revenue | $79 | $199 | $399 |
| Typical AI cost | ~$6 | ~$17 | ~$34 |
| Full-burn AI cost | ~$9 | ~$28 | ~$70 |
| **Margin (typical)** | **~$73 / 92%** | **~$182 / 91%** | **~$365 / 91%** |

At scale, assuming a 60/30/10 tier mix (blended $147/customer, ~$13 AI):

| Customers | MRR | ≈ Net after AI + infra + Stripe |
|---|---|---|
| 10 | $1,470 | ~$1,200/mo |
| 25 | $3,675 | ~$3,200/mo |
| 50 | $7,350 | ~$6,500/mo |
| 100 | $14,700 ($176K ARR) | ~$13,200/mo |
| 250 | $36,750 ($441K ARR) | ~$33,000/mo |

- Infra is ~flat (~$100/mo Railway+Supabase+Twilio base+Resend); Stripe ~3%.
  Break-even on all infrastructure ≈ **one customer**.
- Credit top-ups add ~5–15% revenue at near-100% margin (industry-typical for
  prepaid models).
- Caveats: tier mix is the biggest swing (a Professional-heavy mix lifts
  blended revenue ~35%); contribution margin ≠ net (time/marketing/support
  excluded); churn unmodeled — which is why allowances are generous; Fable
  pricing unverified.

## 5. Beta plan

- **Metering stays observational** during beta (machinery already counts
  silently); beta testers grandfathered — no enforcement, no charges.
- After ~30 days, calibrate the allowances against real `api_usage` data
  (Mission Control → Costs shows per-business burn) before locking numbers.
- **Ship the usage meter in Settings BEFORE any enforcement** — nobody should
  learn about limits from a paused Chief.
- **Funding:** ~$500 Anthropic + ~$100 OpenAI covers ~15 engaged testers for
  ~2 months (est. $8–20/tester/mo Anthropic + $2–5 OpenAI). Set console
  billing alerts at 50%/75%. The builder bridge rides Kevin's Max
  subscription — not this budget.

## 6. Build plan (Phase C — after spec approval)

1. **Credit ledger:** `credit_ledger` table (business_id, delta_units, kind:
   purchase|burn|grant, stripe_payment_id, balance snapshot) + migration.
2. **Stripe credit packs:** 3 one-time Products/Prices; webhook grants units
   on payment success (existing stripe_webhook_events rail).
3. **Draw-down:** integrate with the dormant weighted metering — allowance
   first, then ledger; expose balance on `billing_status`.
4. **Usage meter UI:** Settings → Plan & Usage — units used / remaining,
   balance, top-up buttons, auto-reload toggle.
5. **Tiered lanes:** tier param in `chief_models.model_for`; add Fable 5 to
   the price table (verified).
6. **Enforcement flip:** only after beta calibration + meter UI live +
   Kevin's explicit go.

**Kevin-side:** create the Stripe products; verify Sonnet 5 / Opus 4.8 /
Fable 5 pricing at anthropic.com/pricing; fund the beta budgets.

## 7. Rulings on the open questions (2026-07-12)

1. **Pack sizes RULED:** $10 → 100 units · $25 → 275 units · $50 → 600 units
   (10¢ / 9.1¢ / 8.3¢ effective — bigger packs visibly better value, all
   3–5× the weighted unit cost). Upgrade-cannibalization checked: a Starter
   user buying ~700 extra units/mo pays ~$139 total vs $199 Professional,
   and Professional still wins on the Opus ladder + 1,000 included units.
2. **Promo/referral credits RULED: same ledger.** kind='grant' with a source
   tag (referral | comp | goodwill) for analytics; ONE balance in the UI;
   grants never expire (same trust rule as purchases).
3. **Annual plans RULED: not at launch.** Monthly-only until allowances are
   calibrated and churn is understood (30–60 days of paid data); then
   introduce annual = 2 months free as an acquisition-phase cash-flow lever.
4. **Elite perks RULED:** model ladder + 3,000 units, PLUS priority support
   (Elite tickets answered first) and early feature access — both zero-cost
   at current scale. Priority build queueing deferred until a real queue
   exists (never promise a perk that can't be felt).
