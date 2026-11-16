---
title: A dearer plan or an extra login is paid the day it is taken, and a yearly church buys its logins by the year
date: 2026-11-16
agent: Claude Code (Claude Fable 5.2)
asked: "Kevin (Dev Desk), 2026-11-16, asking about monthly, 3-month, 6-month and annual terms. The review found yearly already sold, with two gaps; I offered to fix them first and he said: \"Yes build.\""
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio (the Billing page's words)]
migrations: []
left_undone:
  - "STRIPE_PRICE_ID_EXTRA_LOGIN_ANNUAL is not set: the $150/yr login price has to be made in Stripe (POST /billing/bootstrap-prices, owner only) and its id put on both Railway services. Until then a church paying by the year is told to write in, before Stripe is asked."
  - "Not tried on a live subscription. Stripe's behaviour was read from its documentation (prorations, update a subscription, mixed interval subscriptions, 2026-11-16) and the code is tested against a stand-in. No church has paid yet, and nobody is known to be on a yearly plan."
  - "A card that needs its bank's confirmation for every charge (3-D Secure) cannot upgrade from the app: Stripe answers 402 and the person is told to write in. Handling that step in the app is its own piece of work."
  - "A change of term (monthly to yearly) is still left to Stripe's default: charged at once, and a card that fails leaves the subscription past due on the new plan. Not touched here."
  - "The 3-month term Kevin wants next is not built: it waits on his discount (5% suggested) and a mock of the Billing page with three choices. church_billing.LOGIN_PRICE_ENVS and stripe_billing._term_of already read a 3-month price."
  - "Refunds have no code: a refund made by hand in Stripe does not end access unless the subscription is cancelled too. No refund rule for yearly plans is written in the Terms beyond 'fees already paid are non-refundable'."
decisions:
  - "An upgrade is paid for the day it is taken, on every term. Stripe's default (create_prorations) puts the difference on the next bill; on a yearly plan that is the renewal, up to a year away, and a cancel before it means the difference is never paid. A dearer price on the same term, on an active subscription, is now proration_behavior=always_invoice."
  - "It only happens if the card takes it: payment_behavior=error_if_incomplete, so Stripe answers 402 and changes nothing. The person reads stripe_billing.CARD_REFUSED, never Stripe's own text."
  - "Cheaper plans and fewer logins are unchanged: the credit waits for the next bill. A trial is unchanged: nothing is charged."
  - "The price is read from Stripe at switch time (one GET). If it can't be read, the switch goes ahead as it did before this change; a read never stops a plan change."
  - "One subscription, one billing term (Stripe refuses mixed intervals outside flexible billing mode, and Checkout can't make them). So the extra office login has a price per term: the monthly $15 and a yearly one at ten months, as the plans are (STRIPE_PRICE_ID_EXTRA_LOGIN_ANNUAL, $150). A plan that changes term takes its logins to the matching price in the same call, or is refused before Stripe is asked."
  - "/billing/plans now carries price_plans: every plan price id, its plan and whether it bills by the month or year, from the env names (no Stripe call). Found while doing the page's words: the Billing page knew only each plan's regular ids, so a church on a FOUNDING price saw a raw price id where its plan's name belongs and no card marked as its own. The first paying church signs up on a founding price this week."
related: [2026-11-06-one-subscription.md, 2026-11-03-church-logins-and-move.md, 2026-11-13-founding-church-prices.md]
---
`stripe_billing._switch_plan` reads the new price (`_price`), compares terms
(`_term_of`) and amounts (`_costs_more`), and adds `PAID_TODAY` for a dearer
price on the same term. `church_billing` prices the login per term
(`LOGIN_PRICE_ENVS`, `extra_login_price(term)`, `plan_term`, `logins_for_term`)
and `set_extra_logins` charges an added login today. `church_offer` in
`/billing/plans` gains `extra_login_year_cents`; the answer gains
`price_plans`. `BOOTSTRAP_CATALOG` gains the yearly login price.

Tests: `test_one_subscription.py` (sections 6 and 7),
`test_church_billing.py` (section 6), `test_church_founding.py` (the last
test).

Overlap check: both work logs read. The plan switch is 2026-11-06 (#1756);
the logins are 2026-11-03 (#1710); nothing open touches either.
