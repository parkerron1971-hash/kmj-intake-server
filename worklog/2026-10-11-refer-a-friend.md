---
title: "Refer a friend: give $10, get $10"
date: 2026-10-11
agent: Claude Code (Claude Opus 5.5)
asked: "go (Kevin, 2026-10-10, on default 3: the friend's code works on a first visit only, and the regular's code is sent when the friend's visit is paid); step 3 of the approved Reach plan"
status: waiting on review
prs: [kmj-intake-server#1370, solutionist-studio#1196]
migrations: [supabase/APPLY-2026-10-11-refer-a-friend.sql]
left_undone: ["the thank-you email's words are fixed (shown on the Offers card), not editable like a journey's", "a thank-you code has no end date", "texts wait for JOURNEY_TEXTS like every journey; until then the thank-you goes by email or the owner tells them at the counter", "Chief has no action to turn it on or make a client's link; it can open Offers"]
decisions: ["the program is the business's one offers row with source referral, so the friend's offer is checked, counted and taken off at checkout exactly like any offer", "each client gets one code (ANDRE-7K) made the first time it's needed, not a tracked short link per client; bookings through it are counted on the program", "the friend's visit counts as paid when it was paid in full online and its time has passed, when an invoice for the friend was marked paid after they booked, or when the owner says so; a booking paid online can be cancelled before the visit, so paying alone is not enough", "one thank-you per friend booking and per friend (unique), claimed before it is sent, in daytime on the business's clock", "the P.S. rides only on the rebook note (the board: 'add each regular's own link to their next rebook text, so nobody gets an extra message'), in words the owner sees on both the Offers card and the rebook card", "a thank-you code is used up by an active booking that used it, so a cancelled booking gives it back"]
related: [2026-10-10-offers.md, 2026-10-11-booking-paid-read.md, 2026-10-09-outreach-journeys.md]
---
The Reach plan's step 3, second part, on the approved Offers board's
"Refer a friend" card. Before: the only referral program was the platform's
own (referrals.py). Now a business turns on Refer a friend in Grow, Offers:
each client has their own code and link, a friend saves money on a first
visit, and once that visit is paid the client gets a THANKS code for their
next one by email. Each client's link can ride as a P.S. on their "Time for
your next visit?" note, and the owner can copy any client's link.

Found on the way: the Stripe webhook never recorded a paid booking
(2026-10-11-booking-paid-read.md, merged first), which this needs for
"paid online".

Live after merge: the migration is applied (2026-10-11 00:5x UTC, RLS on,
anon refused); then this backend, then the app.
