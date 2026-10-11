---
title: "A paid online booking is recorded as paid again"
date: 2026-10-11
agent: Claude Code (Claude Opus 5.5)
asked: "found while building refer-a-friend (step 3 of the approved Reach plan), which needs to know when a friend's visit is paid"
status: waiting on review
prs: [kmj-intake-server#1369]
migrations: []
left_undone: ["a booking paid online before this fix still shows unpaid here; any such payment is in Stripe (Payments), not on the booking, and is not backfilled"]
decisions: ["read the contact from the booking's data (contact_id:data->>contact_id), where the booking widget keeps it, so the rest of the handler is unchanged", "the test checks every field the read names against module_entries' live columns, so a read that names a missing column fails in CI, not silently in production"]
related: [2026-10-10-offers.md]
---
Stripe's webhook calls _mark_booking_paid when a client pays online for an
appointment. Its first read asked module_entries for a contact_id column,
which that table doesn't have (a booking keeps its contact in data).
PostgREST answered 400, the read came back empty, and the function returned
before recording anything: no paid_at, no deposit state, no tip, no card on
file for a no-show fee, no booking_paid event. Live, no booking has ever been
marked paid.

The read now takes the contact from data under the same name. Proved with
the anon key against live PostgREST: the old select answers 400 "column
module_entries.contact_id does not exist", the new one 200.
