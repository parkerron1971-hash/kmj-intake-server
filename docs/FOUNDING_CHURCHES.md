# Founding churches

Kevin, 2026-11-13: *"yes founding prices"*. The first **10** churches that pay
for a Solutionist church plan keep the price they start at, for as long as they
stay. List prices go up later for new churches only.

Kevin, 2026-11-14: *"go with board C, Jan 31, build it"* (the canvas
APP35gJRsgVKuEqFmZPERx). The regular prices rose and the old ones became the
founding prices, shown as a deal while the offer is open:

| Plan | Founding | Regular | Credits (both) |
|---|---|---|---|
| Small | $99 (was $79) | $129 (was $99) | 3,000 |
| Growing | $199 | $249 | 7,500 |
| Established | $399 | $499 | 15,000 |
| Large | $699 | $899 | 27,500 |

Kevin, 2026-11-27: Small changes to **founding $99 / regular $129**, the
credits still 3,000; the other sizes stay. The church that took its founding
place at $79 keeps paying $79 (see "Raising a founding price" below).

- **One plan, two prices.** The credits are the same at both (Kevin: "so
  people don't think they get higher credits cheaper"), so "Save $50 a month"
  is the same plan for less.
- **The end.** The offer closes when ten churches hold a place or at the end of
  `FOUNDING_CHURCHES_UNTIL` (default `2027-01-31`, midnight US Eastern),
  whichever comes first. After that the site shows the regular price alone and
  checkout sells it to every new church. A church that holds a place keeps its
  price. `FOUNDING_CHURCHES_UNTIL=none` means no date.
- **Honest crossing-out.** The crossed-out number is always labelled "Regular
  price" and is the price church eleven pays (never "was"). A card shows it
  only when its founding price is below it (`church_founding.offer_prices`).

| | |
|---|---|
| Code | `church_founding.py` |
| Who | The first paid month on a church plan (the Stripe webhook sees `active`) while a place is left. A trial holds no place; a comped church and the platform owner's own churches never take one. Since 2026-11-13 a church plan has no free days (`pricing_config.church_free_week`, off): checkout charges the first month, so the place is taken at checkout. A church that was already on a carded trial still takes its place when that trial's first charge lands. |
| Record | `businesses.settings.founding_church = {n, at, plan, price_id}`, written once. Nothing releases a place: a founding church that cancels keeps its number. |
| Places | `FOUNDING_CHURCH_SPOTS` (default 10) |
| Switch | `FOUNDING_CHURCHES` = `on` (default) / `off`. Off hides the site line and stops open places getting the founding price. A church that already holds a place keeps its price either way. |
| Where it's said | On /churches while the offer is open: a band above the cards ("The first ten churches save up to $2,400 a year ... N of 10 founding places left") and each card's founding price under "Regular price ~~$249~~", with what it saves; the product pages' plan strip and the size picker say the founding price too. The count may lag five minutes. The app reads `church_founding` (`on, spots, left, ends, prices`) on `GET /billing/plans?for_type=church` and `founding_church` / `founding_price` on `GET /billing/church/move`. |
| Dials | Regular: `PRICE_TIER_CHURCH_<SIZE>_CENTS`. Founding: `PRICE_FOUNDING_CHURCH_<SIZE>_CENTS` (must match the Stripe price in `_FOUNDING`). Credits: `CREDITS_CHURCH_<SIZE>_CREDITS`. |

The free move is a separate offer: the first five churches that ask move free
(`FOUNDING_CHURCH_MOVES`, `church_billing.py`).

## Raising a church price (do this every time)

A church's plan is read from its Stripe price id (`feature_gates.price_to_plan`).
If the list id is swapped and the old one is forgotten, every church still on
the old price **loses its plan**. So, for each size and cadence you raise:

1. **Keep the outgoing list id meaning its plan**, on BOTH services
   (`kmj-intake-server` and `kmj-intake-worker`):
   - The first raise of a size (its `_FOUNDING` variable is empty): copy
     `STRIPE_PRICE_ID_CHURCH_<SIZE>[_ANNUAL]` into
     `STRIPE_PRICE_ID_CHURCH_<SIZE>[_ANNUAL]_FOUNDING`. That is the founding
     churches' price from then on. (The three-month prices, `_QUARTERLY`,
     were made on 2026-11-16 with their own `_QUARTERLY_FOUNDING` ids from
     the start, so there is nothing to copy for them; a later raise of a
     three-month price follows "any later raise" below.)
   - Any later raise: **never overwrite `_FOUNDING`**. Add the outgoing id to
     `STRIPE_PRICE_IDS_KEPT` instead (`price_x=church_growing`, comma
     separated), so the churches who started between raises keep their plan.
   Price ids are not secret, but read them from Railway, never from memory.
2. Make the new Stripe price and set its id as the list id on both services,
   plus the `PRICE_TIER_CHURCH_<SIZE>_CENTS` dial and a PR for the code
   default. The 2026-11-14 raise put the new prices on new lookup keys
   (`solutionist_church_<size>_<monthly|annual>_2026_11`) in
   `stripe_billing.BOOTSTRAP_CATALOG`, and kept the 2026-11-03 keys as the
   `_FOUNDING` entries, so a bootstrap run creates the new prices and prints
   both ids for every size.
3. Never move a founding church's subscription onto the new price, and don't
   archive the old price while anyone is on it.

### Raising a founding price (Small, 2026-11-27)

When the founding price itself goes up, `_FOUNDING` has to hold the new
founding price (that's what checkout sells to a church taking an open place),
so the outgoing founding id goes into `STRIPE_PRICE_IDS_KEPT` like an old list
id. Every outgoing id of that size goes there, list and founding, every term:

    STRIPE_PRICE_IDS_KEPT=price_old_list=church_small,price_old_founding=church_small,...

A church still on a kept price pays what that price charges, and the code
says so: `church_founding.kept_price` reads its amount from Stripe once (a
price's amount never changes), so the church's own card on Billing
(`/billing/plans` `price_plans[id].kept_cents`), its move
(`church_founding.price_cents_for`) and Mission Control's income
(`platform_money.monthly_price_cents`) all say the kept price, not today's
founding price. Order: merge the PR first (the code that reads the kept
amount), then set the env on both services in one go: the new list and
`_FOUNDING` ids, the `PRICE_TIER_` / `PRICE_FOUNDING_` dials if Railway sets
them, and `STRIPE_PRICE_IDS_KEPT`. `STRIPE_PRICE_IDS_KEPT` alone is safe at any
time: it only adds meanings.

The 2026-11-27 Small prices (lookup keys `*_2026_11b`): regular $129 / $387
every 3 months / $1,290 a year; founding $99 / $297 / $990.

After that, a founding church (or a church taking a place that's still open)
that changes size checks out at that size's `_FOUNDING` price, everyone else
at the list price. Asking checkout for a founding price without a place is
refused (409).
