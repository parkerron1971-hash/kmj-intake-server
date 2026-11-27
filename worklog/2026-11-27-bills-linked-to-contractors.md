---
title: A bill can name its contractor, and a vendor's typed-in 1099 bills link to a contractor in one go (M-6 step 2, server half)
date: 2026-11-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, via KAI, 2026-11-27 (mission M-6 step 2): "1099 people linked to bills (a contractor picker on bills), W-9 and draft 1099, with the dead links fixed."'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "The app half (solutionist-studio, its own PR): the contractor picker on the bill form, and Link to a contractor / Add them as a contractor on the 1099 report's typed-in rows."
  - "Bank rows filed as honoraria still don't reach the 1099 summary; only bills do (by design: the summary reads bills)."
decisions:
  - "bills.contractor_id existed (2026-06-09) but only a Stripe payout ever set it, so a church that paid its guest speaker by check and entered a 1099 bill got a 'Manual 1099 needed' row that could never get a W-9 or a draft (the review's C2). POST and PATCH /bills now take contractor_id: checked to be this business's contractor (400 otherwise, 503 when the read fails, never a silent unlink); naming one makes the bill 1099-eligible; '' on PATCH unlinks. A recurring bill's copies carry it."
  - "POST /contractors/{id}/link-bills {business_id, vendor_name}: links every 1099-eligible bill of the business with no contractor whose vendor name is the same, ignoring case and spaces at the ends, read in full (strict: a partial read links nothing). Manager and up, through the contractor's own access (the church wall first). Amounts, dates and the books don't change. Twice is harmless."
  - "Review S3 (account 2): a contractor with a Stripe account (Stripe files their 1099, counting only Stripe transfers) can't be linked to a typed-in bill, by the bill picker or link-bills: 409 with a plain sentence. Such a payment stays typed in under their name, so the 1099 report keeps it as a manual row. Splitting a contractor's non-Stripe bills into their own row is the long-term fix, not done here."
related: [2026-10-31-lock-contractor-payouts.md]
---
`bills_router.py` (`_contractor_of`, contractor_id on create, patch and
recurring copies), `contractors_router.py` (`link_bills`). Tests:
`__tests__/test_f1_contractors.py` gains four (typed-in speaker bills link and
count for the 1099 under the contractor, others left alone; another business
and a blank name refused; a bill names only this business's contractor; a new
bill for a contractor is linked and 1099, and can be unlinked). Ran: the
contractor and bill suites (37), access ratchet, ownership sweep, seat access,
the one money gate and the financial policy (496).
