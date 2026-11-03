---
title: A church can add an office login, and ask to be moved over
date: 2026-11-03
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03, approving the church-pricing plan (artifact Pdg8hF4pB5n6efoFQmzd8d), which included "One more login: $15 a month" and "The move: free for the five founding churches, then three months of the plan": "I agree with the plan. make the fixes and upgrade"'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Switch-on: bootstrap-prices now also creates the $15 extra-login price; paste STRIPE_PRICE_ID_EXTRA_LOGIN into Railway with the church prices"
  - "The app's buttons for both (Billing: add a login, ask for the move): a frontend follow-up after the church plan picker"
  - "The move itself is people work: the Mission Control ticket says what to bring over; the import tools (Subsplash script, Planning Center, Breeze) are the 10-30 build list"
decisions:
  - "Extra logins are a second item on the church's own subscription (Stripe prorates); the count lives in businesses.settings.extra_logins, written when set and again by the webhook from the subscription as Stripe holds it, 0 once it's cancelled"
  - "The webhook now takes the plan from the first subscription item whose price is one of our plans, not items[0] (a church's extra logins could come first); items[0] when none matches, as before"
  - "billing_limits.can_add_seat adds the extra logins to the plan's; a caller's row without settings is read fresh rather than counted as 0"
  - "The move: founding while fewer than 5 churches have a founding move in their settings (a race could make a sixth, accepted like the founder seats); after that a one-time Checkout of church_move_months x the plan's monthly price. An unreadable founding count is a 503, never a free move"
  - "Every move, founding or paid, writes businesses.settings.church_move and a billing support ticket (MOVE: <church> from <system> (founding church, no charge | paid $N)), so it lands in Mission Control's Today queue; a paid move is recorded once per Checkout session"
  - "Only the owner, only a church on a church plan (409 otherwise)"
related: [2026-11-03-church-plans-by-size.md]
---
Routes: POST /billing/church/extra-logins {business_id, count},
GET /billing/church/move?business_id=, POST /billing/church/move
{business_id, moving_from}. The webhook handles checkout.session.completed
and async_payment_succeeded with metadata.kind=church_move.

Tests: `__tests__/test_church_billing.py`, 26 cases. 428 passed across every
stripe, billing, seat, webhook, collaborator and access test file.
