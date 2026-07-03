# Launch Plan — from private beta to paid launch

Companion to `LAUNCH_CHECKLIST.md` (env flips). This is the operating
plan: how the money machine works, how to run the beta program from
Mission Control, and the full backlog — including the things nobody
had written down yet. Updated 2026-07-03 (launch-ops PR).

## 1. Where we are

Built and live: product (all four sections + Chief), invite-only gate,
referrals, Stripe checkout/portal/webhooks, usage metering engine,
tier gates (dormant), PWA + push (keys pending), support tickets,
first-party analytics funnel, account export/deletion (PR #30),
bounce suppression (PR #30). The platform is feature-complete for a
paid beta; what remains is configuration, operations, and polish.

## 2. The money machine (tiers + pay-as-you-go)

**Model (docs/pricing_model.md):** subscription floor + metered overage.
- Starter $79/mo → 75 Chief interactions, overage $0.40/unit
- Professional $199/mo → 350 units, overage $0.30/unit
- Practice $399/mo → 1000 units, overage $0.25/unit
- 2× bill promise: overage can never exceed the tier price itself.
- Weighted units: chat = 1, hero compose = 5, full site build = 25.

**What this PR completed:** the overage price is now attached at
checkout (`stripe_billing.create_checkout`) — the last code gap
between "measures overage" and "bills overage". Real MRR now computes
in `/platform/subscriptions/summary`.

**To turn revenue ON (in order):**
1. Stripe dashboard: create 3 recurring prices + 3 METERED overage
   prices (usage type: metered, monthly).
2. Railway env: `STRIPE_PRICE_ID_{STARTER,PROFESSIONAL,PRACTICE}` and
   `..._OVERAGE` variants (readiness panel checks all six).
3. Existing subscribers (if any predate this): attach the overage item
   to their subscriptions once (Stripe dashboard or a one-time script).
4. Flip `BILLING_ENFORCE=on`. Trials/past-due now gate; usage caps arm;
   the daily `stripe_report_tick` starts reporting overage.
5. Watch `/access/readiness` — it preflights all of the above.

**Not built (don't market):** multi-seat collaboration
(`feature_gates.py` flags it NOT BUILT — the Practice tier sells
accountant collaboration, which IS built via TeamPanel invites).

## 3. Running the beta from Mission Control (this PR)

- **Shareable invite links:** Launch Console → create an invite with
  `max_uses` > 1 to mint ONE link you can post to a group (a barber
  Discord, a church leadership group). Label it. Every signup burns
  one use. Single-use email invites unchanged; resend button added.
- **Waitlist:** one-click Approve turns an entry into a sent invite.
- **Comp tiers:** `POST /access/business/{id}/tier` (Launch Console UI)
  — give a tester Professional for free without touching Stripe.
  Clear it later; Stripe-derived state resumes.
- **Token grants:** give any business bonus Chief interactions —
  one-month (`month: 'YYYY-MM'`) or recurring (no month). Grants top
  up the allotment AND lift the bill cap, so a grant can never cause
  a surprise charge.
- **Suggested beta shape:** comp_tier=professional + a recurring
  100-unit grant for founding testers; single-use invites for 1:1
  recruits; one labeled 25-use link per community you seed.

## 4. Platform money (your own Stripe + banking)

- **Stripe:** the platform's Stripe account is already "connected" —
  it IS the `STRIPE_SECRET_KEY` on Railway. Subscription revenue lands
  there. Practitioner charge money flows through their own Connect
  accounts and never commingles. Real MRR now shows in Mission
  Control → Subscriptions/Overview.
- **Banking:** recommendation — do NOT build platform-level banking.
  Run **KMJ Creative Solutions as a business inside Solutionist** and
  connect its bank via the existing Plaid integration: you get
  bookkeeping, P&L, and reconciliation for the platform itself with
  zero new code, and you dogfood the product you sell. A platform
  treasury dashboard is a v2 luxury.

## 5. The backlog you asked for (including the unconsidered)

**Before charging money** (highest stakes):
- [ ] Terms of Service update: billing terms, refund policy, overage
      language, cancellation (legal_content.py needs a billing section)
- [ ] Stripe Tax (or a decision to defer) — sales tax on SaaS varies
      by state; flip on Stripe Tax at checkout before real volume
- [ ] Dunning: past_due handling beyond the webhook status write —
      grace period + email sequence (Stripe Smart Retries + one email)
- [ ] Receipt/invoice branding in Stripe settings (logo, descriptor —
      "MYSOLUTIONIST" so cardholders recognize the charge)
- [ ] Refund runbook: who refunds, criteria, how it maps to comp_tier

**Before public launch** (trust + resilience):
- [ ] Backup verification: confirm Supabase PITR tier, run ONE restore
      drill to a scratch project, write down the steps
- [ ] Uptime monitor (UptimeRobot/BetterStack free tier) on `/` +
      `/health` + the marketing site, alerting your phone
- [ ] Incident runbook: what to do when Railway is down (status
      message, who to tell, rollback steps)
- [ ] Status page (even a simple static one) linked from the footer
- [ ] Frontend error reporting (Sentry browser SDK — backend is wired,
      the browser side is still blind)
- [ ] Staging environment: a second Railway service + Supabase branch
      so migrations get rehearsed before production
- [ ] Rate limiters → Postgres/Redis when you scale past one Railway
      instance (in-memory today; fine for now)
- [ ] Per-business customer token secrets (customer_token.py TODO —
      flagged "before first real launch")

**Growth machine** (after money is on):
- [ ] Email domain warmup: send volume ramps gradually; keep the
      suppression list clean (PR #30 handles the mechanics)
- [ ] Onboarding email sequence (welcome → day-2 tips → day-7 value
      check) — nothing sends today except the in-app welcome
- [ ] Referral double-sided rewards automation (referrals.py defers
      to manual application today)
- [ ] Churn instrumentation: exit survey on cancel + a Mission Control
      churn view fed by product_events
- [ ] App/Play store listings for the Capacitor wrapper (assets,
      privacy questionnaire, review timeline ~1-2 weeks)
- [ ] Demo/sandbox account with seeded data for prospects and for the
      marketing video to stay honest
- [ ] Help center: the tutorial exists in-app; written docs for the
      top 10 "how do I" questions cut support load

**Operating discipline** (cheap, compounding):
- [ ] Changelog surface (even a simple /changelog page) — you ship
      fast; make users feel it
- [ ] Feature flags convention: BILLING_ENFORCE is the model — prefer
      env-gated dormant ships over long branches
- [ ] Weekly Business Chief review ritual: MRR, funnel, churn risks,
      spend — the panels now exist; put 30 minutes on the calendar
- [ ] Security posture one-pager for bigger customers (auth model,
      RLS, data isolation, backups) — pre-answers procurement emails

## 6. Sequencing recommendation

1. **Now:** merge launch-ops PR + run migration → run the beta program
   properly (links, comps, grants).
2. **Next 2 weeks:** "before charging" list + Stripe prices created and
   readiness green — but keep `BILLING_ENFORCE=off`.
3. **Beta graduation:** when 10+ businesses are weekly-active and the
   funnel says activation holds, flip enforcement with founding-member
   comps already in place (they never hit a paywall — goodwill is
   cheap now, expensive later).
4. **Then:** public launch list, growth machine, stores.
