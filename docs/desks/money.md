# Desk: money

## 1. What it owns

Everything with a dollar sign, in plain words:

- **Plans and billing** — what a church or practitioner pays Solutionist: the
  Billing page, plan cards, monthly / every 3 months / yearly, founding church
  prices, extra office logins, extra texts on the next bill, credit packs,
  trials (businesses only; churches start on a plan), coupons.
- **Getting paid** — a practitioner's own Stripe (connect or "Set up Stripe
  here"), invoices, payment links, the store's checkout, booking payments,
  refunds, payouts, the Payments overview.
- **Giving** — a church's give page (embedded Checkout on the church's own
  Stripe), recorded gifts (cash, check, outside platforms), counts per service,
  pledges, recurring gifts, ways to give, giving statements, matching gifts to
  bank deposits, who in the office may see or work money (the giving tick).
- **Books** — the bank feed (Plaid, read only), statement uploads, filing bank
  rows to categories and lines, bills, funds for the year, housing allowance,
  the ledger, period close, reports and the accountant export.
- **Payroll, free version** — Solutionist prepares the numbers, stubs, forms and
  a deposit calendar; the employer pays from its own bank. Nothing moves money.
- **Mission Control → Money** (owner only) — the platform's own costs and
  "pay yourself" plan, Pricing & Stripe, Coupons, Subscriptions.

## 2. Where the code is

Backend (`kmj-intake-server`):

| Area | Files | Routes |
|---|---|---|
| Platform billing | `stripe_billing.py` (subscriptions, `/billing/webhook`, new-customer alert), `stripe_checkout_helpers.py`, `billing_limits.py`, `billing_context.py`, `billing_rehearsal.py`, `feature_gates.py` (plans, `plan_of`), `pricing_config.py` (every dial), `usage_metering.py`, `credit_ledger.py` | `/billing/*`, `/platform/billing/*` |
| Church plans | `church_billing.py` (logins, the move), `church_founding.py`, `churchsavvy_billing.py`, `church_texts.py` (text allowance bill) | `/billing/church/*`, `/churchsavvy-billing/*` |
| Trials | `no_card_trial.py`, `trial_expiry.py` | `/billing/trial/*` |
| Coupons | `stripe_discounts.py`, `discount_settlement.py`, `docs/STRIPE_COUPONS.md` | |
| Connected Stripe | `stripe_connect_router.py` (+ `/payments/stripe/webhook`), `stripe_connect_helpers.py`, `stripe_proxy.py` (`/stripe/*`, `/stripe/webhook`), `stripe_payments_router.py`, `stripe_data_proxy.py`, `payments_core.py` (`can_charge`), `payments_overview.py`, `payment_domains.py` (Apple/Google Pay domains), `checkout_guard.py`, `invoice_payment_links.py`, `customer_balances*.py`, `contractors_router.py` | `/payments/*`, `/balances/*` |
| Giving | `giving_router.py` (`/giving/{id}`, `/public/giving/{slug}/checkout`), `giving_records.py` (gifts = `invoices` with `is_gift`), `giving_*.py` (deposits, services, sheets, statements, ways, week, reports), `church_pledges.py`, `church_recurring_gifts.py` | `/giving*`, `/giving-deposits/*`, `/church/giving/*` |
| Who may touch money | `church_money_gate.py` (`require_money` / `may_money`, the one gate), `church_money_levels.py`, `church_money_holders.py`, `church_money_ticks.py` | `/church/*` |
| Bank + books | `plaid_router.py` (+ `/plaid/webhook`), `plaid_*.py`, `bank_statements.py`, `bank_money.py`, `bank_picks.py`, `expense_categories.py`, `expense_lines.py`, `bills_router.py`, `bill_payments.py`, `bill_words.py`, `funds.py`, `housing_allowance.py`, `gl_engine.py`, `gl_reports*.py`, `gl_router.py`, `period_lock.py`, `bookkeeping_close.py`, `bookkeeping_overview.py`, `reports_router.py`, `report_words.py`, `pdf_reports.py`, `accountant_export.py`, `receipts*.py` | `/plaid`, `/bank-statements`, `/expense-categories`, `/bills`, `/year-funds`, `/housing-allowance`, `/gl`, `/bookkeeping`, `/reports`, `/receipts` |
| Payroll | `payroll_router.py`, `payroll_calc.py` (SS/Medicare/FUTA only; income tax is typed), `payroll_*.py` | `/payroll/*` |
| Chief's money verbs | `chief_bookkeeping*.py`, `chief_bills.py`, `chief_file_bank.py`, `chief_transactions.py`, `chief_reconcile.py`, `chief_giving_*.py`, `chief_invoice_*.py`, `chief_expense_actions.py` | |
| Owner-only | `platform_money.py`, `money_auditor.py` (daily sense; registration is the system desk's) | `/platform/money/*` |

Main tables: `businesses` (plan, Stripe ids; `subscription_plan` = a Stripe PRICE id), `invoices`, `stripe_webhook_events`, `plaid_items`, `plaid_accounts`, `plaid_transactions`, `bank_statement_imports`, `category_rules`, `business_expenses`, `bills`, `business_funds`, `business_fund_items`, `gift_deposit_matches`, `gift_deposit_items`, `giving_counts`, `journal_entries`, `ledger_entries`, `gl_sync_queue`, `chart_of_accounts`, `accounting_periods`, `employees`, `pay_runs`, `pay_run_items`, `minister_housing_allowances`, `minister_housing_entries`, `chief_undo_log`.

Frontend (`solutionist-studio`), under `src/core/components/`: `BillingPanel.tsx`, `PlanTermSwitch.tsx`, `ChurchPlanExtras.tsx`, `GivingPanel.tsx`, `InvoicesPanel.tsx`, `PaymentsPanel.tsx`; folders `payments/` (incl. `overview/`, `payroll/`, `StripeSignupHere.tsx`), `bookkeeping/` (Transactions, Statements, Bills, Funds, Housing, `reports/`), `plaid/PlaidConnectButton.tsx`, `church/giving/`. Libs in `src/core/lib/`: `money.ts`, `givingDeposits.ts`, `yearFunds.ts`, `housingAllowance.ts`, `bankStatements.ts`, `expenseCategories.ts`, `expenseLines.ts`, `planLabels.ts`, `churchGivingOffice.ts`, `churchMoneyAsks.ts`. Mission Control in `src/modules/platform/pages/`: `MoneyPanel.tsx`, `MoneyWebsitePanel.tsx` (Pricing & Stripe), `CouponsPanel.tsx`, `SubscriptionsPanel.tsx`, `CostsPanel.tsx`.

Docs: `docs/BILLING_GO_LIVE.md`, `docs/FOUNDING_CHURCHES.md`, `docs/STRIPE_COUPONS.md`.

## 3. Rules that must not break

- **Never commit real figures.** No tenant's bank rows, gifts, balances or
  payroll in tests, fixtures, commits, PR text or worklogs. Use made-up numbers.
  A push was blocked once for exactly this.
- **Every Stripe webhook fails closed and verifies its signature:**
  `/billing/webhook` (`STRIPE_WEBHOOK_SECRET`), `/stripe/webhook`
  (`STRIPE_PAYMENTS_WEBHOOK_SECRET`, falls back to the first), and
  `/payments/stripe/webhook` (`verify_webhook_signature`). Plaid's webhook is
  verified too. Dedupe through `stripe_webhook_events`.
- **Who moves money:** giving, store and invoices are direct charges on the
  business's own Stripe account (platform fee zero, Stripe carries losses).
  Plaid is read only. Payroll moves nothing. The ONE exception, contractor
  payouts from the platform balance, is locked to the platform owner's
  businesses (`contractors_router._platform_money`). Never route a church's
  gifts through the platform's account; change the platform's payment-method
  config only with the owner's yes.
- **Every money door asks `church_money_gate.require_money`.** Don't write a
  new "is this the owner?" check for money; add a row to `RULES`.
- **`businesses` server columns and `settings` server keys** (`comp_tier`,
  `subscription_status`, `trial_ends_at`, `tier`, Stripe ids, `founding_church`…)
  are written by the service role only; the triggers refuse the app's logins
  (`docs/RLS_MODEL.md` Rule 4, `business_settings.SERVER_KEYS`). Write settings
  by key, never a whole-object copy.
- **The Android app must not sell Solutionist's own plans, credits or storage.**
  Gate any new buy button on `inAndroidApp()` (`src/core/lib/nativeApp.ts`). A
  church's own giving and a business's own sales are fine.
- `BILLING_ENFORCE` is ON by default since 2026-11-17; `off` is the emergency
  switch (every check says allowed; counters stay real). `docs/RUNBOOK.md` still
  calls enforcement dormant — trust `billing_limits.py`.
- **Paid AI reads** (statement PDFs, drafts) go through `spend_guard`, then
  `rate_limit.allow(...)`, then `billing_limits.require_units`, and log usage.
  Texts are metered in `api_usage` but kept out of the spend guard and credits.
- **No double counting:** a giving deposit is never filed as income where gifts
  are recorded; never let Chief create bills for things already paid from the
  bank unless matched (`bill_payments`); a fund holds bank rows only, never past
  a row's amount. Honor the period lock on every ledger write.
- **Read every ledger/report table with `sb_clients.sb_get_all_as_service`**
  (keyset pages). PostgREST caps a read at 1,000 rows and a short read must never
  read as zero.
- **Price raises follow `docs/FOUNDING_CHURCHES.md`:** move the outgoing list id
  into its `_FOUNDING` var (later: `STRIPE_PRICE_IDS_KEPT`) on BOTH Railway
  services before swapping, or founding churches resolve to no plan.
- Mock first, then build, for any money screen design (owner's rule). Features
  ride `off|owner|on` switches (`owner` = the platform owner's churches) and
  switch on on Thursdays, with a What's New entry at the flip.

## 4. Traps already hit

- `businesses.subscription_plan` holds the Stripe price id, not the plan key: use `feature_gates.plan_of` / `church_texts.church_plan_of`.
- Basil API removed `current_period_end` from Subscription; it wrote NULL for months. Reader handles both shapes; pinning `STRIPE_API_VERSION` is opt-in and a bad value 400s every call.
- Stripe dahlia renamed `ui_mode` `embedded` and `initEmbeddedCheckout`; embedded checkout pins an older version and the page calls whichever function exists.
- Without Payment Method Domains on the connected account, embedded Checkout shows no Apple Pay or Google Pay (`payment_domains.py`).
- Giving's Settings switch turned on for half-set-up Stripe accounts; now refused via `payments_core.can_charge` (only off-to-on, only on Stripe's explicit "can't charge").
- Cash App Pay is prohibited for religious MCCs; no switch fixes it. Don't promise it.
- A church was given the business no-card trial at signup; churches now never get a trial.
- Platform subscription receipts are a Stripe Dashboard setting, not code; our code sends none.
- Plaid Link closed itself every 45s: a token re-minted on parent re-render. Keep SDK session effects off callback identity (refs).
- Sonnet 5.5 400s on forced `tool_choice`; check `model_ladder.supports_forced_tool_choice` before forcing a tool.
- Statement rows stored as category `other` still count as waiting (`bank_money.needs_category`).
- "Filed" and "matched" differ: `reconciliation_status` only means tied to a payout/invoice/bill/deposit; a bank-paid bill stays unmatched.
- A bill plus its bank row booked the expense twice; `bill_settle` fixed it. An account switched out of bookkeeping still leaves a matched bill with no cash leg.
- Book choice must never hang on a read that can blip, or gifts re-post back and forth; a failed read raises and the row stays queued.
- "Out of balance" was a 1,000-row cap, not bad books.
- Mixed-key bulk inserts lose the whole chunk (PGRST102); FakeSB hides it. Prove write paths on the real database (kept test church), say "tests pass" and "proved live" separately.
- FakeDB ignores `order` and treats `offset` as a filter; month-hardcoded tests break at month boundaries.
- `ownership_sweep` only sees gates called directly; `asyncio.to_thread(_gate, ...)` failed the access ratchet. `rate_limit.allow_strict` fails CLOSED; practitioner surfaces use `allow`.
- Env vars are per Railway service: price ids go on both `kmj-intake-server` and `kmj-intake-worker`.
- The Billing page lives in a lazy chunk (`BusinessSettings-*.js`), not `main-*.js`; a live check grepping main sees nothing.
- The "Create Stripe catalog" button can create more prices than expected; compare env names before telling the owner a count.

## 5. How to check work

- Backend: `pytest -q __tests__/test_<area>.py` — `test_phasee_billing.py`, `test_church_billing.py`, `test_church_founding.py`, `test_no_card_trial.py`, `test_stripe_api_version.py`, `test_stripe_proxy_authz.py`, `test_stripe_connect_signup.py`, `test_online_giving.py`, `test_giving_deposits.py`, `test_one_money_gate.py`, `test_church_money_ticks.py`, `test_bank_statements.py`, `test_bill_payments.py`, `test_funds.py`, `test_housing_allowance.py`, `test_payroll_free_routes.py`, `test_payments_overview.py`, `test_platform_money.py`, `test_businesses_server_columns.py`, `test_settings_server_keys.py`, `test_plaid_webhook_signature.py`. CI runs all of it sharded (`pytest -n auto --dist loadfile`).
- Real Postgres (PGlite, CI job `test-db`, `PGLITE_MODULE` set): `node __tests__/church_money_holders_db.mjs`, `church_money_levels_db.mjs`, `settings_server_keys_db.mjs`, `businesses_server_columns_db.mjs`.
- Frontend: `npx tsc -p tsconfig.app.json --noEmit` (no new errors), `npx vite build`, `npm run check:giving`, `check:settings`, `check:owner`; jsdom checks `node scripts/check-money-room.mjs`, `check-pay-staff.mjs`, `check-payments-overview.mjs`, `check-giving-tick.mjs`, `check-church-giving-office.mjs`, `check-church-pays-today.mjs`, `check-church-plans.mjs` (all use `scripts/dev-desk-check.mjs`; install jsdom per the script header).
- Previews: `npx vite --config tests/<name>.vite.config.ts` for `church-plans`, `payments-overview`, `pay-staff`, `giving-tick`, `giving-deposits`, `statements`, `funds`, `housing-allowance`, `categories`, `money-room`.
- Live: read Stripe with the live key read-only; never pay, refund or change the
  platform's Stripe config without the owner's yes.

## 6. Edges

- **messaging** — `church_texts.py` counts texts that messaging sends and bills
  the extra; `giving_statement_mail.py` uses the email rails. Sending code is
  messaging's; the bill is ours.
- **church-office** — the giving tick on a person's sheet (`church_sheet`,
  `church_money_ticks`); help requests the treasurer pays (`church_help.py`).
- **member-app** — the member's give page (`member_lumen_give.py`) calls our
  checkout; we own the charge, they own the page.
- **websites** — public `/give` and the church pricing page
  (`church_site/overview.html`, `church_site.py` plan cards).
- **chief** — owns verb plumbing (`chief_of_staff.py`, `action_registry.py`);
  we own the money modules the verbs call.
- **system** — migrations, `AGENT_REGISTRY` for `money_auditor`, Railway env,
  RLS. **tickets** hands us billing and giving bugs with evidence.
