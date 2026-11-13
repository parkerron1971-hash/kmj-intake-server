---
title: The first ten churches that pay keep their price (founding church prices)
date: 2026-11-13
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-13, after "I think 199 or any of the tier price is cheap for everything we are offering" and the advice to hold list prices and make today''s prices founding prices for the first 10 churches: "yes founding prices, keep 20/15/29, go ahead"'
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio (the plan card line)]
migrations: []
left_undone:
  - "Churches already paying before this merged are marked at their next renewal (the webhook sees every one), if a place is still left; none were paying as of 10-30"
  - "When a church price first goes up, follow docs/FOUNDING_CHURCHES.md: copy each outgoing list id into STRIPE_PRICE_ID_CHURCH_<SIZE>[_ANNUAL]_FOUNDING on both services before swapping"
decisions:
  - "Ten places, for the first PAID month on a church plan (webhook sees active); trials, comped churches and the platform owner's own churches take none; a place is never released"
  - "Separate from the free move: the 11-05 line tied the kept price to the five churches that move free. Now ten churches keep their price and the first five who ask move free; the move's lines drop the price clause and the price is its own line under the cards"
  - "Wording keeps Kevin's 11-05 phrase 'keep the price they start at, for as long as they stay' (honest about a church that leaves) rather than 'for good'"
  - "FOUNDING_CHURCHES on by default (Kevin approved it directly); off hides the line and stops open places getting the founding price, but a church holding a place keeps its price either way"
  - "price_to_plan learns the eight CHURCH_*_FOUNDING aliases and STRIPE_PRICE_IDS_KEPT (price=plan pairs) so a raise can never strand a church on a price that no longer means a plan"
  - "Asking checkout for a founding price without a place is a 409, never a quiet swap"
related: [2026-11-05-founding-price-line.md, 2026-11-06-founding-after-payment.md, 2026-11-03-church-plans-by-size.md]
---
`church_founding.py` holds the offer: places (`FOUNDING_CHURCH_SPOTS`, 10),
the switch, the count (`settings->founding_church`), `claim()` from
`stripe_billing._apply_subscription_state` on an active church plan, and
`checkout_price()` in `create_checkout` (so `_switch_plan` gets it too). Today
no `_FOUNDING` price is set, so every church pays the list price, which is the
founding price; the promise only needs work at the first raise.

The overview (mysolutionist.app/ and /churches) shows, under "Good to know":
"Founding price · The first ten churches keep the price they start at, for as
long as they stay. N of 10 left." The app reads `church_founding` from
`/billing/plans?for_type=church` and `founding_church` / `founding_price` from
`/billing/church/move`. Recipe for raising a price: docs/FOUNDING_CHURCHES.md.
