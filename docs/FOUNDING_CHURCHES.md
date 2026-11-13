# Founding churches

Kevin, 2026-11-13: *"yes founding prices"*. The first **10** churches that pay
for a Solutionist church plan keep the price they start at, for as long as they
stay. List prices go up later for new churches only.

| | |
|---|---|
| Code | `church_founding.py` |
| Who | The first paid month on a church plan (the Stripe webhook sees `active`) while a place is left. A trial holds no place; a comped church and the platform owner's own churches never take one. Since 2026-11-13 a church plan has no free days (`pricing_config.church_free_week`, off): checkout charges the first month, so the place is taken at checkout. A church that was already on a carded trial still takes its place when that trial's first charge lands. |
| Record | `businesses.settings.founding_church = {n, at, plan, price_id}`, written once. Nothing releases a place: a founding church that cancels keeps its number. |
| Places | `FOUNDING_CHURCH_SPOTS` (default 10) |
| Switch | `FOUNDING_CHURCHES` = `on` (default) / `off`. Off hides the site line and stops open places getting the founding price. A church that already holds a place keeps its price either way. |
| Where it's said | Under the price cards on mysolutionist.app/ and /churches ("Founding price ... N of 10 left"; the count may lag five minutes). The app reads `church_founding` on `GET /billing/plans?for_type=church` and `founding_church` / `founding_price` on `GET /billing/church/move`. |

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
     churches' price from then on.
   - Any later raise: **never overwrite `_FOUNDING`**. Add the outgoing id to
     `STRIPE_PRICE_IDS_KEPT` instead (`price_x=church_growing`, comma
     separated), so the churches who started between raises keep their plan.
   Price ids are not secret, but read them from Railway, never from memory.
2. Make the new Stripe price with `transfer_lookup_key` (the lookup key moves
   to it) and set its id as the list id on both services, plus the
   `PRICE_TIER_CHURCH_<SIZE>_CENTS` dial and a PR for the code default (the
   pattern from the 2026-11-03 raises).
3. Never move a founding church's subscription onto the new price, and don't
   archive the old price while anyone is on it.

After that, a founding church (or a church taking a place that's still open)
that changes size checks out at that size's `_FOUNDING` price, everyone else
at the list price. Asking checkout for a founding price without a place is
refused (409).
