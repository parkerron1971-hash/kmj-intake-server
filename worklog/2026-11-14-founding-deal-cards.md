---
title: The church plans' regular prices rise, and the first ten churches see the founding price as a deal until January 31
date: 2026-11-14
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-14: "go with board C, Jan 31, build it", then "show a reduction of credits ... so people don''t think they get higher credits cheaper"'
status: shipped
prs: [kmj-intake-server#TBD]
migrations: []
left_undone:
  - "The app's plan cards (solutionist-studio) show the deal from the new /billing/plans fields: a separate FE PR"
  - "MRR in usage_metering counts every church plan at its regular price, so a founding church reads $50 high there"
decisions:
  - "Regular prices Small $99, Growing $249, Established $499, Large $899 (yearly 10x). Founding prices are the 2026-11-03 prices: $79 / $199 / $399 / $699"
  - "Credits did NOT change: 3,000 / 7,500 / 15,000 / 27,500 at both prices. One plan, two prices, so 'Save $50 a month' is the same plan for less. A full tank is about 36% of the founding price and 29% of the regular (under the 40% line)"
  - "The offer ends when ten churches hold a place or at the end of FOUNDING_CHURCHES_UNTIL (default 2027-01-31, midnight US Eastern), whichever comes first. Past it: no band, regular price alone, checkout sells the regular price, and a place goes only to a church already paying a founding price"
  - "The crossed-out number is labelled 'Regular price' (never 'was') and is shown only where the founding price is below it (church_founding.offer_prices)"
  - "The first payment and the move (three months of the plan) are priced at what the church pays: church_founding.price_cents_for"
  - "Stripe: new lookup keys solutionist_church_<size>_<cadence>_2026_11 for the regular prices; the 2026-11-03 keys stay in BOOTSTRAP_CATALOG as the _FOUNDING entries, so one bootstrap run prints every id"
related: [2026-11-13-founding-church-prices.md]
---
Board C from the canvas (APP35gJRsgVKuEqFmZPERx), built into /churches:

- A dark band above the four cards: "The first ten churches save up to $2,400
  a year, for as long as they stay. The offer ends when ten churches have
  joined or on January 31, whichever comes first. After that, every new church
  pays the regular price." with the ten places drawn as dots.
- Each card: a "Founding price" chip, "Regular price ~~$249~~", the founding
  price large, "Save $50 a month · $600 a year" (yearly: "Save $500 a year"),
  "Your price stays locked for as long as you stay.", and "Claim a founding
  place". The yearly switch moves every number.
- The product pages' plan strip and the size picker say the founding price
  with the regular one named.
- /billing/plans `church_founding` gains `ends` and `prices` for the app.

Stripe: eight new regular prices were made with the app's own bootstrap code,
narrowed to the church entries; the eight founding ids it read back are the
list ids that were live (checked one by one). The env swap on both services
follows docs/FOUNDING_CHURCHES.md: the old list ids into `_FOUNDING`, the new
ids as the list ids, and the `PRICE_TIER_CHURCH_<SIZE>_CENTS` dials moved.
