---
title: Contractor payouts are locked to the platform owner's own businesses
date: 2026-10-31
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-31, after asking whether Solutionist handles money and needs compliance: "go lock the contractor payouts"'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "The Pay tab (solutionist-studio PayTab.tsx) still shows Send onboarding and Pay to every business; another business now gets the plain 403 message after pressing them. Hiding the buttons is a small screen change"
  - "Rebuilding payouts so the business doing the paying is charged (destination charges or debiting its connected account), so Solutionist is never the payer on another business's 1099"
decisions:
  - "Payouts are sent from the PLATFORM's Stripe balance (the v1 funding model). For any business but the platform owner's, that is Solutionist's money paying their contractor, with Solutionist as the 1099 payer. So only the platform owner's businesses may open a payout (Express) account or send a payment"
  - "Checked twice: in each route before anything is recorded (no outbound_transfers row, no bill), and in _stripe_post for /transfers and /accounts just before Stripe is called. member_asks.platform_church answers it; a read that fails, or no business named, is a no"
  - "Contractor records, tax profiles, the transfer list and the 1099 summary stay open to every business: they're records, not money"
related: []
---
`contractors_router._platform_money`, called from `onboarding_link`, `pay` and
`_stripe_post`. Tests: `__tests__/test_f1_contractors.py` (four new),
`__tests__/test_financial_policy.py` (its contractor case is now the platform
owner's business, so the financial policy is still what it tests).
