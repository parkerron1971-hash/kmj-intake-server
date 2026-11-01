---
title: Ways to give, and gifts by card or bank (never pay-later) — giving by service, step 1 server
date: 2026-11-01
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-01: "the giving type needs to be updated. it only has cash check bank transfer and other. allow for all the ways a person give to show. like online needs to be on there and others should have prefills like cash app paypal etc..." then, after the Stripe check: "yes. let''s do that. sounds like a great plan. build everything"'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "STRIPE_GIVING_PMC: the platform's giving payment set must be made in the Solutionist Stripe account (Settings → Connect → Payment methods → Add new configuration: Cards, Apple Pay, Google Pay, Link, ACH Direct Debit on; the rest off) and its pmc_ id set in Railway. Until then: card and Link only (no Klarna), no bank choice"
  - "Google Pay is off in the platform's default Connect set (every business); a one-click change in the Solutionist Stripe account. The API change was refused from the agent"
  - "Switched with GIVING_SERVICES (owner until a Thursday flip)"
  - "The settings screen and the treasurer's menu are the front end PR"
decisions:
  - "Stripe can't take Cash App (religious organizations are a prohibited category: Love City shows Ineligible), PayPal (Europe only, no direct charges) or Venmo/Zelle (not on Stripe). Those are the church's own accounts: shown as Other ways to give, recorded by the treasurer, matched at the bank"
  - "One list (settings.giving.ways) feeds both the give page (ways with a handle the church chose to show) and the treasurer's menu (Cash, Check, the ways, Bank transfer, Other)"
  - "A way's token is the gift's payment_method: cashapp/zelle/venmo/paypal match as transfers, Subsplash as 'subsplash bank payout', an app named under Other as 'other' with its name in the note. gl_engine now books paypal and other as non-Stripe money (1000), never 1150"
  - "Gift checkouts filter Stripe's dynamic set with allowed_payment_method_types (card + link, or us_bank_account) instead of payment_method_types (which current Stripe refuses for Checkout); a filter Stripe refuses by name is retried without it, so a gift is never stopped"
  - "Cover the fee is worked out for the way chosen: card 2.9% + 30c, bank 0.8% at most $5. Bank needs the church's ACH capability, checked with Stripe when the church turns it on"
  - "Cash App and PayPal.Me links carry the chosen amount; Zelle has no link, so its email or phone has a Copy button"
related: [2026-10-31-sunday-match.md]
---
`giving_ways.py` (new). Wired: `giving_router` (settings, give page and embed,
checkout, the treasurer's menu `GET /giving/{id}/ways`, recorded gifts),
`stripe_checkout_helpers.create_giving_checkout(extra_form)`, `gl_engine`
hints. Tests: `__tests__/test_giving_ways.py` (37).
