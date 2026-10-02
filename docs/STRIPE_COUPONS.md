# Stripe coupons

## Operator workflow

Mission Control → Money & Website → Coupons & discounts manages the platform's
Stripe promotion codes. Create a percentage or fixed-amount code, choose its
subscription duration, and optionally set expiration and maximum redemptions.
Copy the code for a new subscriber to enter on Stripe Checkout, or select an
existing subscriber and apply it to eligible future invoices. Applying a code
does not create an immediate charge, refund, or proration. Existing discounts
are not overwritten. Stripe enforces redemption and eligibility restrictions.

Business owners use Operate → Payments → Coupons after connecting Stripe.
Their codes belong to their connected account, separate from platform billing.
Business codes apply once per purchase. Customers redeem them on Stripe's
hosted online-store checkout and on full-service booking payments that have no
deposit or tip. Invoices, deposits, tips, no-show fees, donations, credit packs,
and offline counter sales retain their existing payment behavior.

Both panels read Stripe directly, including codes created in the Stripe
dashboard. Refresh retrieves current usage and status. Deactivation stops new
redemptions; it does not remove discounts already attached to subscriptions.
Create/apply retries keep an idempotency key. Test-mode codes are visibly labeled.

## Payment records

Store shipping uses a native Stripe shipping rate, outside the merchandise
discount. The configured store tax percentage is passed as a Stripe tax rate,
so Stripe calculates tax after discount. This preserves the store's existing
tax policy; it does not enable Stripe Tax or introduce jurisdiction selection.
Free-shipping qualification is still calculated from the original cart subtotal.

New coupon-capable Checkout Sessions carry `discount_checkout_v1=true` on the
session and PaymentIntent. The session's final verified totals update order
subtotal, tax, shipping, and total before receipts, stock fulfillment, or the
ledger sees a paid order. Receipts derive the discount from original line
prices minus the net subtotal. Booking data records `amount_paid_cents`,
`discount_cents`, and `price_before_discount`; its price fields reflect the
paid service amount, including zero when fully discounted.

PaymentIntent success waits for Checkout settlement, preserving saved-card
references without posting gross revenue early. Checkout completion and
asynchronous payment success are supported, as are fully discounted sessions
with `payment_status=no_payment_required`. New settlement events must match
the source business's connected account. Failed handlers return HTTP 500 so
Stripe retries them.

## Release

No new environment variables or database migrations are required. Existing
Stripe keys, Connect setup, financial-policy tables, and verified webhooks
must already be operational. Deploy the backend before the frontend.

In the connected-account webhook destination, ensure the subscribed events
include `checkout.session.completed`, `checkout.session.async_payment_succeeded`,
and `payment_intent.succeeded`, alongside the existing payment/refund events.
The coupon catalog reads Stripe on demand and needs no coupon webhook subscription.

Before live use, run a Stripe test-mode purchase with a percentage code, a fixed
amount code, an expired code, and a 100% code. Check the Stripe total against the
order, receipt, and ledger; repeat a webhook delivery and confirm stock is not
decremented again. Verify an existing subscription receives the intended duration
and discount without an immediate charge. Automated tests mock Stripe; they do
not claim a live Stripe charge or deployment occurred.

## Implementation and checks

- `stripe_discounts.py`: owner-gated platform/business management and subscription application.
- `discount_settlement.py`: source-account and store-total validation.
- `__tests__/test_stripe_discounts.py`: validation, authorization, retry/version handling, and settlement tests.
- Frontend: `src/core/components/payments/DiscountsPanel.tsx`, mounted in Money & Website and Payments.
- Frontend browser fixture: `tests/vite.discounts.config.ts` and `tests/discounts-preview.*`.
- `scripts/check_discount_ui.py`: mocked create/retry/apply/deactivate, business scope, and desktop/mobile checks.

The isolated frontend checkout is `output/coupons-frontend`; its browser fixture
builds to the sibling `coupons-qa/build`. Run `python scripts/check_discount_ui.py`
from the original backend workspace after building that fixture. The script
does not use production credentials or make Stripe calls.
