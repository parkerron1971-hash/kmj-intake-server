---
title: Paid sign-ups for church events, with a waitlist (server; switched to the owner)
date: 2026-10-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Church Menu Gaps check (https://claude.ai/artifact/4oXF1Be46RddJxXnKAHodn, "The other doors", the Sunday card: RSVP has capacity and serving roles but no payment and no waitlist) → Kevin approved the build list, 2026-10-27: "ok continue"'
status: shipped, switched to the platform owner; migration waiting on Kevin
prs: [kmj-intake-server (this PR), solutionist-studio (the office's Sign-ups sheet, its own PR)]
migrations: ["supabase/APPLY-2026-10-27-church-event-signups.sql (NOT APPLIED: Kevin applies by hand)"]
left_undone:
  - "Apply supabase/APPLY-2026-10-27-church-event-signups.sql. Until then status says enabled false, the office routes answer 503, nothing can be priced, and free RSVP is unchanged"
  - "Switch-on: CHURCH_PAID_SIGNUPS=on on Railway on a Thursday (it defaults to owner), with the app's OPEN_TO_EVERYONE flip and a What's New entry"
  - "Refunds are made in the church's own Stripe dashboard (each paid sign-up links to its payment); the charge.refunded webhook brings them back. No refund button in the app yet"
  - "The office can't add a sign-up by hand (someone who paid cash at the door) or move someone off the waitlist out of order"
  - "Questions are per sign-up, not per person (one allergies answer for a family); Planning Center asks per attendee"
  - "No discount codes, no early-bird price, no sibling discount"
  - "A text when a waitlist place opens goes only to people who ticked the box and gave a phone; it rides send_sms_core, so a church on the no-card trial or a number that said STOP gets the email only"
  - "Stripe's checkout.session.expired isn't used (it may not be subscribed on the Connect endpoint); a hold runs out by its clock and the 5-minute sweep moves the waitlist"
  - "Chief has no sign-up actions (read who's coming, open sign-ups)"
decisions:
  - "Lane: Build, under the Build item 'Love City leaves Subsplash (M-1)'"
  - "Paid means the verified Connect webhook said so: record_checkout checks the sign-up's church owns the account the payment arrived on (the gift rule from #1418, not the booking/order/invoice pattern that trusts metadata), that metadata names the same church, and that the amount is at least what the server priced; it marks paid only from held, offered, expired or cancelled, so a repeat is a no-op (plus stripe_webhook_events dedupe). Any mismatch raises: the event is recorded as failed and the sign-up stays unpaid"
  - "The amount is worked out only by price_order from the event's own ticket types; the browser sends ticket counts, never money"
  - "Who gets a place is one locked step per event in Postgres (church_event_take / church_event_settle lock the setup row): paid and free sign-ups and unexpired holds and offers take places; the waitlist is strictly first come, first served, and a newcomer never jumps it"
  - "A hold is 40 minutes; Stripe's page closes at 31 (its minimum is 30), so a payment can't arrive long after the place went back. A payment that lands after its place went back (the hold ran out, or the office took it off while Stripe's page was open) is still recorded as paid, because the money moved: the office gets a notification and the Sign-ups sheet shows the event over its places, to refund in Stripe if they can't fit them. No automatic refund"
  - "Review fixes: the platform-owner check (an auth read) runs off the event loop in the async routes; a refund that can't be written raises, so Stripe retries it"
  - "Cards only on the Checkout page, so a held place never waits on a bank transfer"
  - "A waitlist offer lasts the event's offer_hours (24 by default, 2 to 72); its link carries a random token and only its sha256 is stored. A free place from the waitlist is simply confirmed"
  - "Free events with no setup are untouched: the public RSVP and the member app's I'm coming. An event with an open setup refuses the free 'attending' RSVP (409 / 'signup'), but serving in a role still works. A read that fails (or tables not made yet) blocks nothing"
  - "Switch CHURCH_PAID_SIGNUPS = off | owner | on, owner by default; owner = a church whose owner's sign-in address is the platform owner's (read from auth, fail-closed, cached 10 minutes). Off keeps setups asleep: the event says 'sign-ups aren't open online', never turns free"
  - "Office: owner, admins and managers in the Office area see sign-ups; owner and admins set prices, cancel and export. A paid sign-up is refunded in Stripe, not cancelled here"
  - "Tables are server-only (RLS on, no policies, browser roles revoked; functions execute for service_role only). A sign-up keeps its event id without a foreign key, so a paid sign-up outlives a deleted event; setups and ticket types cascade with the event"
  - "account_lifecycle: the three tables are exported and deleted with the church, skipped on import (they cite the event and the person by id)"
related: [2026-10-27-church-spaces.md, 2026-10-27-church-pledges-recurring.md]
---
Before building I read both repos' `worklog/`: nothing on paid sign-ups,
registrations or a waitlist. The nearest work is the public RSVP
(`events_rsvp_router.py`), the member app's Coming up
(`member_portal_church.py`) and online giving's Connect checkout and webhook.

- `church_event_signups.py` (new): the switch, the pure rules (ticket types,
  questions, answers, pricing, counts, the public view), the sign-up shared by
  the public page and the member app, the waitlist offer and the receipt, the
  webhook's `record_checkout` / `record_refund`, the 5-minute sweep, the
  emails (and a text when asked), and six office routes under
  `/church/events/signups` (the module docstring lists every route).
- `supabase/APPLY-2026-10-27-church-event-signups.sql` (new, NOT applied):
  three tables and four functions. Ledger row in `docs/MIGRATIONS.md`.
- `stripe_checkout_helpers.py` / `payments_core.py`: the sign-up's Checkout
  form and the adapter verb `create_event_signup_checkout`.
- `stripe_connect_router.py`: `checkout.session.completed` and
  `charge.refunded` for `source_type=event_signup`.
- `events_rsvp_router.py` / `public_site.py`: the public events page draws a
  sign-up card (price, places, deadline in one line; tickets with a running
  total; the questions; the waitlist and what happens next; the receipt after
  Stripe; the offer link's banner).
- `member_portal_church.py`: Coming up shows the sign-up where "I'm coming"
  was (a form post, no script), the member's own sign-up or waitlist place,
  and pay-for-an-offered-place.
- `rate_limit.py`: strict `event_signup` and `event_signup_read` buckets.
- `kmj_intake_automation.py`: the router (before the public catch-all) and the
  sweep job. `account_lifecycle.py`, `.env.example`, `ci.yml`.

Checks:
- `__tests__/test_event_signups.py`: 31 tests (free RSVP unchanged, also with
  no tables; server-side amounts; the webhook refusing a bad signature, the
  wrong account, another church's metadata and the wrong amount; a repeat
  processed once; holds running out; capacity and waitlist order; offers and
  their links; another church unreachable; the switch off and owner; rate
  limit first; refunds; the office; the CSV).
- I broke eight rules on purpose (the account check, the client's amount, the
  free-RSVP gate, the switch, a hold that never runs out, the rate limit after
  a read, a CSV formula, paid twice) and the tests caught seven; "paid twice"
  is held by two layers (the early return and the status filter on the
  write), and removing one leaves the other.
- `__tests__/church_event_signups_db.mjs`: 47 checks on PGlite (the functions
  as service_role; the browser roles refused).
- Events RSVP, member portal, online giving, payments core, export/import,
  route type hints, seat access, the access ratchet and the anonymous limiters
  pass.
