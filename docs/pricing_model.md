> **Superseded 2026-09-04.** The ladder is now Starter $79 / 3,000 credits, Professional $149 / 7,500, Solutionist $299 / 17,500, and a Founder seat at $99 / 6,000 for the first fifty. Credit packs $12 / 650, $25 / 1,400, $50 / 2,800. The read-only connector is on every plan; the write key is Professional. Prices and tanks live in `pricing_config.py`; the numbers below are the history this was reasoned from.

# Solutionist Hybrid Pricing Model — Specification v1 (Phase A)

**Status:** Strategy spec for Kevin's review — NO code in this phase. Phase B (access control + enforcement) builds only after this is approved/adjusted.
**Author:** Claude Code, 2026-06-10.
**Basis:** Locked tier hypothesis ($79 / $199 / $399) + Kevin's hybrid subscription-floor + usage-overage framing. All numbers below grounded in the codebase's actual metering and the in-repo Anthropic price table (`api_usage_logger.py`, sourced anthropic.com/pricing as of 2026-05-25 — **Kevin: re-verify at https://www.anthropic.com/pricing before creating Stripe prices**).

---

## 1. Usage Unit Analysis — what's actually meterable

Audited every billable-event candidate against the codebase:

| Candidate | What it is | Typical volume | Variable cost to Solutionist | Meter it? |
|---|---|---|---|---|
| **Chief LLM interactions** | One logged AI call: Chief of Staff message (`/ai/proxy`, Sonnet, ≤1600 out), bookkeeping Chief (`chief_llm`, Haiku batch), GL analysis | Med–high (the activity heartbeat) | **$0.02–0.05/msg Sonnet; ~$0.005 Haiku** (real, scales with use) | **YES — primary unit.** Already metered end-to-end: `api_usage` rows carry business_id, tokens, model, cost_cents. |
| **AI site generations** | Composer hero/full-site builds (`compose_hero`, `run_build_loop`) — multi-call Sonnet bundles (enrich + designer + build + critique + refine) | Low frequency, **high unit cost** | ~$0.10–0.15 per hero compose; **~$0.50–2.00 per full build-with-loop** | **YES — but as a *weighted* count of the same unit** (see below), not a second meter. |
| Branded PDF reports | reportlab renders | Medium | ~$0 (CPU only) | No — unlimited. Metering free things reads as nickel-and-diming. |
| Customer bookings | Booking widget submissions | Med–high | ~$0 (a DB row + one email) | No — **never meter the practitioner's own revenue events.** Punishing success at the transaction level is the HoneyBook-resentment trap. |
| Contacts/clients managed | Rows + UI | Grows monotonically | ~$0 storage | No — a *tier limit* candidate someday, never a usage meter (can't go down; feels like rent on your own client list). |
| Plaid synced transactions | Bank sync volume | High for active books | Plaid bills **per connected Item/account ~$0.30–1.50/mo**, not per txn | No meter. Real cost is per-*connection* → a **tier limit** (e.g., Starter 2 connected accounts) is the honest shape — flagged as a tier-feature option, not v1. |
| Stripe payments processed | Practitioner's customer charges | Med | $0 to Solutionist (fees hit the practitioner's own Connect account per D.4) | No — not our cost, not our meter. |
| Outbound emails (Resend) | Invoices, statements, invites | Medium | ~$0.0004/email | No — rounding error; unlimited. |
| Storage (Supabase) | Assets, PDFs | Low | Cents/GB | No — revisit only if abuse appears. |
| Period closes / accountant exports | GL operations | Low (monthly/annual) | ~$0 | No — these are *tier features* (already gated Professional/Practice), not meters. |

**Recommendation — ONE practitioner-facing unit: the "Chief interaction."**
- 1 Chief message (any surface: Chief of Staff, bookkeeping Chief, Ask-Chief drawer) = **1 interaction**.
- 1 AI **site generation** = **25 interactions** (a full build-with-loop costs ~25–60× a chat message; weighting it into the same unit keeps ONE number for the practitioner while protecting the only genuinely expensive operation). Hero-only regenerations = 5.
- Everything else: included/unlimited.

Why one weighted unit beats a composite: practitioners can hold one number in their head ("I have 350 interactions"); the weighting is disclosed plainly ("site generations use 25"); and it's implementable today — `api_usage.endpoint`/`task_type` already distinguishes the call types, so the weight is a lookup at aggregation time, no schema change.

---

## 2. Tier Allotment Structure (recommended)

| Tier | Price | Included interactions/mo | Interpretation for the practitioner |
|---|---|---|---|
| Starter | $79 | **75** | ~3–4 Chief conversations/workday — real daily use, not a teaser |
| Professional | $199 | **350** | Chief as a true co-pilot + a couple of site regenerations |
| Practice | $399 | **1,000** | Team-scale usage (multi-seat tier) + heavy Chief automation |

*(Adjusts the Phase E v1.1 placeholder of 50 at Starter — 50 reads stingy against a $79 price; 75 is still ~$2.30 of COGS.)*

**Allotment math (Sonnet-dominant usage, ~$0.03 blended per interaction — see §4):**

| Tier | COGS at full allotment | Gross margin at full usage | Margin if usage is Haiku-heavy |
|---|---|---|---|
| Starter $79 | 75 × $0.03 ≈ **$2.25** | **~97%** | ~99% |
| Professional $199 | 350 × $0.03 ≈ **$10.50** | **~95%** | ~98% |
| Practice $399 | 1,000 × $0.03 ≈ **$30** | **~92%** | ~97% |

**Upgrade-pressure geometry** (with §3's per-tier overage rates): a Starter practitioner consistently burning ~375 interactions/mo pays $79 + 300×$0.40 = $199 — *exactly* the Professional price for half the allotment and none of the GL features. The spreadsheet does the selling. Same at the top: ~1,015 interactions on Professional ≈ $399. The tiers meet where the next tier starts — that's the "organic upgrade signal" Kevin asked for, made literal.

---

## 3. Overage Pricing Logic (recommended)

**Per-tier flat rate, capped so the total bill never exceeds 2× the plan price:**

| Tier | Overage rate | Overage margin (vs ~$0.03 COGS) | Max monthly bill (cap) |
|---|---|---|---|
| Starter | **$0.40**/interaction | ~92% | **$158** (then soft-block + upgrade prompt) |
| Professional | **$0.30** | ~90% | **$398** |
| Practice | **$0.25** | ~88% | **$798** (then "let's talk" — Network Enterprise lead) |

Why this over the alternatives:
- **Flat per-unit** ✓ (chosen, per-tier): one number per plan; the practitioner can do the math on a napkin. Per-tier rates (declining as you go up) bake in the volume reward WITHOUT in-month bracket complexity.
- **Tiered/declining brackets** ✗: rewards heavy users but nobody can predict their bill mid-month, and explaining brackets in a Chief drawer tooltip is a losing battle. The per-tier flat rate captures 90% of the same effect.
- **Uncapped** ✗: violates Goal #1 (no surprise bills). The **2×-total cap is the headline promise: "Your bill can never exceed twice your plan."** That sentence does more trust-building than any FAQ.
- At the cap: **soft-block** — Chief politely declines new AI interactions ("You've hit this month's ceiling — upgrade or I'm back on the 1st"), everything non-AI keeps working. Bookkeeping, bookings, invoices NEVER stop — only net-new AI spend pauses. A practitioner's business must never break because they talked to Chief too much.

---

## 4. Anthropic API Cost Reality Check

**Price basis** (in-repo `MODEL_PRICING_CENTS`, anthropic.com/pricing as of 2026-05-25 — re-verify; newer model generations may differ):
- Opus 4.x: $15 / $75 per MTok (in/out) · Sonnet 4.x: $3 / $15 · Haiku 4.x: $0.80 / $4.

**Per-interaction cost, from the actual code paths:**

| Path | Model | Typical tokens (in / out) | Cost |
|---|---|---|---|
| Chief of Staff message | Sonnet (`CHIEF_MODEL`, max 1600 out) | ~5–8k system+history / ~500–900 | **$0.022–0.038** |
| Bookkeeping Chief (ask/analyze-hard) | Haiku (≤700 out) | ~1.5–3k / ~300–700 | **$0.003–0.006** |
| Hero compose | Sonnet (4096 out budget) | ~6–10k / ~2–3k | **$0.06–0.12** |
| Full site build-with-loop | Sonnet ×4–8 calls | bundle | **$0.50–2.00** → hence weight 25 |

Blended planning number: **$0.03/interaction** (Sonnet-dominant mix). The 25× site-gen weight makes the worst real bundle (~$2.00) bill as 25 units — covered at every tier's overage rate.

**Starter margin honesty:** at $79/75 units, margins are healthy (~97%) — *no* need to (a) cut the allotment, (b) raise the price, or (c) force Haiku-only at Starter. The real risk isn't margin, it's positioning (see §7). Recommendation (c)-lite anyway as cost hygiene, not necessity: keep routing what's already Haiku on Haiku; don't promise model names in marketing — sell *outcomes* ("Chief"), which keeps the model-agnostic/future-proof goal: the unit is "an interaction," never "a token," so swapping providers or models never touches the pricing page.

**Anthropic price-rise cushion:** at these margins, a 30% API price increase moves Starter COGS from $2.25 → $2.93 (margin 96.3%); even a 3× increase keeps every tier above 88% at full allotment. The model absorbs provider volatility without re-pricing — Goal #4 satisfied with room to spare. The genuinely exposed line is *overage at heavy site-generation volume*, still ~3× covered at worst case.

---

## 5. Billing / Operational Considerations

**Metering infrastructure — sufficient, with three named gaps (Phase B work):**
- ✅ `api_usage` captures business_id, endpoint, task_type, model, tokens, cost_cents per call; `billing_limits.chief_messages_this_month()` already does calendar-month windowing (stateless reset).
- Gap 1: **unit weighting** — aggregation must apply the weight map (chat=1, hero=5, full build=25) keyed on endpoint/task_type. Lookup at read time; no schema change.
- Gap 2: **threshold notifications** — no 50/80/100% emails exist. Phase B: check on increment, one email per threshold per cycle (Resend, dedup via a small `usage_notifications` table or a jsonb on businesses).
- Gap 3: **Stripe usage reporting** — nothing reports to Stripe yet. Phase B: end-of-cycle job (the existing AsyncIOScheduler pattern) posts overage quantity to the metered subscription item.

**Usage transparency:** Settings → Billing UsageCard upgraded to "**234 / 350 interactions (67%)**" + progress bar + "estimated overage so far: $0.00"; Chief drawer keeps the Phase E v1.1 "X remaining" line (now allotment-aware). Site generations show their weight at the point of use ("This rebuild uses 25 interactions").

**Caps:** **soft cap default** (notify 50/80/100%, overage auto-charges) + **practitioner-set hard cap** in Settings ("never charge me overage — pause Chief instead"). Practitioner-friendly, and the hard cap is just "stop reporting usage + soft-block" — no Stripe complexity.

**Overage approval:** auto-charge at cycle end (standard SaaS; Stripe metered billing does this natively) with the threshold emails making it un-surprising. Per-cycle manual approval ✗ — turns every month into an invoice-chasing workflow and breaks the Stripe-native path.

---

## 6. Stripe Integration Map

1. **Subscriptions (the floor):** 3 Products × 2 Prices each (monthly + annual at ~17% off) on the **platform** Stripe account. Matches the shipped Phase E `STRIPE_PRICE_ID_{STARTER,PROFESSIONAL,PRACTICE}` env pattern (annual adds `_ANNUAL` variants — small Phase B extension).
2. **Usage (the scale):** one **metered Price per tier** (`usage_type=metered`, monthly aggregation `sum`, unit amounts $0.40/$0.30/$0.25), attached as a second subscription item on the same subscription. Solutionist reports **only the overage quantity** (max(0, weighted_usage − allotment), respecting the cap) via `subscription_items.usage_records.create()` at cycle end — keeping allotment logic OURS, not encoded in Stripe tiers (provider-agnostic, survives repricing).
3. **Cycle mechanics:** plan charges at cycle start; metered usage bills on the cycle-end invoice. Existing `/billing/webhook` (Phase E, prod `stripe_webhook_events` shape) already handles invoice events; `invoice.payment_failed` → existing past_due flow.
4. **Cap handling:** enforced **client-of-Stripe-side** — once the 2× cap or a practitioner hard cap is reached we stop counting reportable usage and soft-block; Stripe never even sees beyond-cap quantity. No Stripe config needed for caps.
5. **Connect separation (unchanged, important):** practitioner subscriptions + overage = **platform revenue on the platform account**. Practitioners' customer charges live on their own Connect accounts (D.4). The two streams never mix — exactly the Anthropic dual-stream shape Kevin described.

---

## 7. Risk Flags (honest)

1. **The 10,000-interaction Starter user doesn't exist — the cap makes them impossible.** Bill ceiling at Starter is $158. The real risk is inverted: a *capped* power user who won't upgrade churns instead. Mitigation: the cap message is an upgrade conversation (Chief literally says what the next tier costs), and Kevin sees cap-hitters in Mission Control before they churn.
2. **Positioning risk > margin risk at Starter.** $79 with 75 interactions must FEEL abundant, not metered. Mitigation: never show the meter until 50%; lead marketing with what's *unlimited* (bookings, invoicing, bookkeeping, reports) — the meter applies only to AI conversations.
3. **Competitive novelty cuts both ways.** HoneyBook/Dubsado/QuickBooks = flat tiers; AI devtools = pure usage. A hybrid is genuinely novel in the practitioner-OS category — differentiator AND education burden. The "never more than 2× your plan" promise is the one-sentence answer to "is this like a phone bill?". Register: competitors will copy this within a year of it working; the moat is Chief, not the pricing shape.
4. **Anthropic price increases:** absorbed to ~3× current pricing without re-pricing (§4). Re-visit tier allotments only if blended cost/interaction crosses ~$0.10.
5. **Year-1 conservatism (adopted in the numbers above):** 75/350/1,000 is deliberately lower than the generous instinct (100/500/1500). Raising allotments later is a gift announcement; cutting them is a crisis. Same for overage rates — start at $0.40/$0.30/$0.25; lowering later is good news.
6. **Weighted-unit honesty:** the 25× site-gen weight MUST be disclosed at the point of use, or the first practitioner who burns 100 units on four rebuilds writes the angry post. UI copy ships with the feature, not after.

---

## 8. Decision Sheet (one page, for Kevin)

| Decision | Recommendation |
|---|---|
| Metered unit | **Chief interactions** (weighted: chat = 1 · hero regen = 5 · full site build = 25; everything else unlimited) |
| Allotments | **Starter 75 · Professional 350 · Practice 1,000** per month |
| Overage | **Flat per tier: $0.40 / $0.30 / $0.25** per interaction |
| Ceiling | **Total bill capped at 2× plan price** ($158 / $398 / $798), then soft-block (AI pauses, business features never stop) + upgrade prompt |
| Caps UX | Soft cap default + practitioner-set hard cap; emails at 50/80/100% + each overage milestone; auto-charge at cycle end |
| Margin check | 92–97% at full allotment; absorbs ~3× Anthropic price increase without re-pricing |
| Model-agnostic | Unit = "interaction," never tokens/models — provider swaps never touch pricing |

**Kevin's Stripe setup (after approval — Phase B docs will walk through it):**
1. Create 3 Products; 2 recurring Prices each (monthly $79/$199/$399; annual $790/$1,990/$3,990 ≈ 17% off).
2. Create 3 metered Prices ($0.40/$0.30/$0.25, monthly, aggregate=sum) — overage items.
3. Set the 6 price-id env vars on Railway (+ 3 `_ANNUAL`, + 3 `_OVERAGE`).
4. Webhook endpoint → `/billing/webhook`, set `STRIPE_WEBHOOK_SECRET` (existing Phase E flow).
5. **Verify Anthropic pricing at anthropic.com/pricing** against §4's table before locking overage rates.

**Surfaced forks (recommendation made, Kevin can overrule):**
- **F-A1 Hybrid vs. pure-subscription vs. credit packs:** recommend **hybrid** as specced — pure subscription leaves scale-revenue on the table and re-opens the 10k-user problem; credit packs (prepaid bundles) are a fine *v2 add-on* for cap-hitters who hate overage, not a v1 foundation.
- **F-A2 Plaid connection limits as a tier feature** (Starter 2 accounts / Pro 5 / Practice unlimited): real COGS lives per-connection; recommend adding as *gate-ready feature limits* in Phase B (not a meter).
- **F-A3 Starter model routing:** no forced Haiku downgrade at Starter (margins don't need it; two-tier Chief quality risks the hero experience). Keep current routing.

*End of Phase A spec. Phase B (invite gate, grandfathering, backend-mediated creation, metering enforcement, BILLING_ENFORCE readiness) builds only after Kevin's review locks these numbers.*
