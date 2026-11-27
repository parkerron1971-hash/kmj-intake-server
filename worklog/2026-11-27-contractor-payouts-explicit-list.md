---
title: Contractor payouts from the platform's Stripe balance are locked to an explicit list, never a church (M-6 step 1)
date: 2026-11-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, via KAI, 2026-11-27 (mission M-6, the Pay staff review''s b+ direction, step 1, urgent): "contractor Stripe payouts must never spend Solutionist''s balance on behalf of a church. Lock _platform_money to the actual platform business id(s) (an explicit setting, not the owner''s email), and make the church Contractors page stop offering Pay contractors via Stripe, Send onboarding and Pay."'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "CONTRACTOR_PAYOUT_BUSINESS_IDS is unset everywhere, so after this merges NO business can send a Stripe contractor payout (fail closed, on purpose). If Kevin wants the platform's own business (or KMJ Creative Solutions) to keep paying contractors from the platform balance, he sets its businesses.id on the web service (kmj-intake-server; the worker never sends payouts). A church or nonprofit is refused even if listed."
  - "The app half (solutionist-studio, its own PR): the church Contractors page becomes records only and reads GET /contractors `payouts.stripe` before showing Send onboarding or Pay."
  - "Not checked: whether any outbound_transfers exist live. Nothing here touches past rows; it only refuses new payouts."
decisions:
  - "The old lock asked member_asks.platform_church(biz): is this business's OWNER the platform owner. That is true for every business Kevin runs, Love City Church included, so LCC's Contractors page could spend Solutionist's Stripe balance with Solutionist as the 1099 payer (found in the Pay staff review, 2026-11-27). The owner's email no longer counts at all."
  - "New rule, both must hold: the business is named in CONTRACTOR_PAYOUT_BUSINESS_IDS (comma or space separated; UUIDs compared case-blind), AND it is not nonprofit-like (vertical_family.is_nonprofit_like: church, ministry, nonprofit), read from the businesses row. A failed or empty read of that row is a 503 'nothing was sent', never a yes."
  - "A dedicated setting rather than PLATFORM_BUSINESS_ID: that one names Solutionist's marketing-suite business and is validated for that purpose; which businesses may spend the platform balance is a separate money decision Kevin makes explicitly."
  - "Review S4 (account 2): 'never a church' also refuses anything vertical_registry resolves to ministry or nonprofit, so the alias `pastor` (a church everywhere else, but not on vertical_family's list) is refused too; the test covers it."
  - "GET /contractors now returns payouts: {stripe: bool}, so the app shows no button the server would refuse. It is a map so M-6 step 3 (Moov payouts from the business's own account, another worker) adds its own key without changing this one."
  - "The check still runs twice: in each route before anything is recorded, and in _stripe_post for /transfers and /accounts just before Stripe."
  - "test_financial_policy's contractor case now names its business in the new setting (and gets a guard test), so the financial policy, not the payout lock, is still what stops it. Rehearsed: removing require_operational_write turns that case red; making _payout_verdict always yes turns 12 of the contractor tests red."
related: [2026-10-31-lock-contractor-payouts.md]
---
`contractors_router`: `CONTRACTOR_PAYOUT_BUSINESS_IDS`, `payout_business_ids`,
`_payout_verdict`, `payouts_open`, `_platform_money` (403, or 503 when the
business can't be read), and `payouts` on `GET /contractors`. Documented in
`.env.example` and the money desk playbook (`docs/desks/money.md`, "Who moves
money").

Tests: `__tests__/test_f1_contractors.py` (the fixture names its business in
the new setting; new: the owner being the platform owner is not enough, a
church/ministry/nonprofit refused even when named at every door, unset or empty
means nobody, ids in any case and separator, an unreadable business is a no, a
named business still pays) and `__tests__/test_financial_policy.py`. Ran
locally: those two plus test_seat_access_routers, test_payments_overview,
test_payroll_free_routes, test_payroll_minister, test_business_access_ratchet,
test_ownership_sweep_segments (171 passed). CI runs the whole suite.
