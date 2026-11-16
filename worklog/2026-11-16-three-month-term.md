---
title: Plans can be paid every three months (backend; nothing is sold until the prices exist)
date: 2026-11-16
agent: Claude Code (Claude Fable 5.2)
asked: "Kevin (Dev Desk), 2026-11-16: \"if I have people that like to pay 3 months at a time that would be good right it would function like monthly payment just every three months. Kinda like grammarly does it\"; then \"How about no discount since the price is already low for founding?\"; then, after the mock: \"Build it.\""
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio (the Billing page's switch)]
migrations: []
left_undone:
  - "The twelve 3-month prices are NOT in Stripe: Mission Control, Money, Website has the button that runs POST /billing/bootstrap-prices; the ids it hands back go on BOTH Railway services (kmj-intake-server and kmj-intake-worker). Until a plan's STRIPE_PRICE_ID_<PLAN>_QUARTERLY is set the Billing page does not offer the term for it. Switch-on is Kevin's, on a Thursday, with a What's New entry."
  - "The same button also makes the $150/yr extra-login price (STRIPE_PRICE_ID_EXTRA_LOGIN_ANNUAL) from the earlier PR, and the $45 3-month one."
  - "The paywall a new business chooses its plan on (AccessGate) and the public pricing pages offer monthly only, as they did for yearly. Only Billing offers the terms."
  - "Not tried on a live subscription. No church has paid yet."
  - "Founder seat, barber plans and ChurchSavvy alone have no 3-month price (only the plans sold today)."
  - "6-month and a commitment paid monthly were advised against and are not built."
decisions:
  - "Three months' price, no discount (Kevin: \"the price is already low for founding\"). A founding church keeps the price it starts at, so a 3-month discount would have been locked in for good; a discount is easier to add later than to take away."
  - "A term is part of the env var's name: STRIPE_PRICE_ID_<PLAN>_QUARTERLY and, for churches, _QUARTERLY_FOUNDING, as _ANNUAL already was. Checkout takes plan='<plan>_quarterly'."
  - "In Stripe a 3-month price is interval=month, interval_count=3. The catalog writes it as \"quarter\" (stripe_billing._recurring); a price under a 3-month key that bills monthly is stale and stays out of the env block."
  - "A plan entry carries quarterly_price_id only when the price is set AND Stripe can show its amount, so the page never offers a term with no figure."
  - "The extra office login gets a 3-month price too ($45), for the same reason it has a yearly one: Stripe holds one subscription to one billing term."
  - "The founding churches' rule is unchanged: a church with a place, or taking an open one, gets the founding price for the term it asked for; a founding price without a place is refused."
related: [2026-11-16-upgrades-paid-today-yearly-logins.md, 2026-11-13-founding-church-prices.md]
---
`feature_gates.PRICE_ENV_TO_PLAN` gains the `_QUARTERLY` names.
`church_founding`: `TERMS`, `_suffix`, `_term_of_price` (was `_is_annual`),
`offer_prices` adds `quarter_cents`. `church_billing`: `QUARTERLY`, the login's
3-month price and cents. `stripe_billing`: `_plan_entry` (quarterly id and
amount), `_price_plans` (`every: "quarter"`), `church_offer`
(`extra_login_quarter_cents`), `BOOTSTRAP_CATALOG` (twelve prices) and
`_recurring`. The Money room needs no change: it counts a subscription by its
plan's monthly price, and three months with no discount is that price.

Tests: `test_church_founding.py` (the last section), `test_one_subscription.py`
(section 8), `test_checkout_known_prices.py`, `test_church_billing.py`.
