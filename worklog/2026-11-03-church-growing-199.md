---
title: The Growing Church plan is $199 a month ($1,990 a year), up from $149
date: 2026-11-03
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03, after someone told him the church price was still too low: "yes make growing $199"'
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio (the What's New line)]
migrations: []
left_undone:
  - "PRICE_TIER_CHURCH_GROWING_CENTS=19900 is set on both Railway services, so the site and checkout agreed while this PR was in review. It now matches the code default and can be deleted"
  - "Small stays $79. Kevin asked about $99; the recommendation was to keep $79, and it's his call"
decisions:
  - "Changed the day the plans went on sale, while no church was on Growing, so no old price needs keeping"
  - "Stripe (live): new $199 monthly and $1,990 yearly prices on the same Growing Church product took over the lookup keys (transfer_lookup_key), so bootstrap_prices finds them. The $149 prices (price_1UXmzNRh4utPVrAs8uxegaAv, price_1UXmzNRh4utPVrAsqbq8zEYA) were archived after a check that no subscription used them"
  - "Railway: the two STRIPE_PRICE_ID_CHURCH_GROWING(_ANNUAL) ids are swapped on kmj-intake-server and kmj-intake-worker"
  - "Code: pricing_config's default, the bootstrap catalog's amounts, the comments, and the tests. The move fee follows the plan: three months of Growing is $597 now. The /churches cards, the product page strips, the FAQ and the app's plan cards all read the dial or Stripe, so nothing else changed"
related: [2026-11-03-church-plans-by-size.md, 2026-11-03-church-site-pricing-by-size.md, 2026-11-03-church-logins-and-move.md]
---
Before changing it I read `worklog/` in both repos. The plans (#1704), the
site (#1711) and the logins and the move (#1710) all read the Growing price
from `pricing_config.church_price_cents()`. The app reads it from
`/billing/plans`, so the only fixed $149 in the frontend was the What's New
line (#1458).

Why $199: Love City, with 148 people, pays Subsplash about $317 a month for
the app, website, giving and sermon tools, without the books, care or office
logins. Planning Center charges up to $265 a month at 250 people.

Checked: 278 tests pass across the church, pricing, site and home files.
