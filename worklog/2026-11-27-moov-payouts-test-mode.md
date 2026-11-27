---
title: Sending with Moov, test mode (a church pays its 1099 people from its own bank)
date: 2026-11-27
agent: Claude Code (Claude Opus 5.5)
asked: "M-6 step 3: let a church pay 1099 people through Moov from the church's own bank account; off by default, per-church opt-in; test mode only"
status: waiting on Kevin
prs: [kmj-intake-server (this PR)]
migrations: [supabase/APPLY-2026-11-27-moov-payouts.sql (not applied)]
left_undone:
  - "Kevin: create the Moov account, test keys, webhook URL, apply the migration (docs/MOOV_PAYOUTS.md, Go live)"
  - "the Pay people screen: W5's 'Send with Moov' hook calls the contract in docs/MOOV_PAYOUTS.md; no frontend in this PR"
  - "one real sandbox payout to settle amount.value vs amount.valueDecimal (MOOV_AMOUNT_SHAPE)"
  - "a daily pass over payouts stuck in pending; auto-matching the Moov debit in the bank feed to its bill"
  - "live mode: a reviewed PR flipping moov_client.LIVE_ALLOWED"
decisions:
  - "the church is its own Moov account and the source of every payout; the partner account can never be a source or be claimed"
  - "a bill exists from the moment of sending (scheduled) and is marked paid, paid_via 'moov', only when Moov says completed"
  - "Moov's webhook signs headers, not the body, so every status is read back from Moov's API"
  - "new gate part 'send' (see: owner/admin/accountant; work: owner/admin) and a new step-up scope 'pay' an Admin can confirm"
  - "W-9 stays the app's own capture; this build reads no TIN back from Moov"
  - "fees shown, not charged back; pricing left to Kevin ($500/month minimum)"
related: [2026-10-31-contractor-payout-lock.md]
---
Backend only, test mode only. `moov_client.py` is the one door to Moov: Basic auth, no keys or bodies in
logs, and live mode refused in code. `moov_payouts.py` covers the church's opt-in, Moov's hosted onboarding
for the church (KYB and bank) and for each payee, a quote with the fee per speed, the send (next-day by
default, idempotent, capped per payment and per day), and the books (one paid 1099 bill, which the
1099 summary counts once). Failures and returns put the bill back. The signed webhook only prompts a
read from Moov. The tests use a fake Moov, with no network. Read docs/MOOV_PAYOUTS.md before building the screen.
