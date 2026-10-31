---
title: The Sunday match, recorded gifts matched to the bank deposits that carried them, never twice
date: 2026-10-31
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-31: everybody gives on Sunday (cash, check, card, Cash App), each gift recorded by person, the money deposited over Sunday to Tuesday; the gifts that tally to $650 should meet the deposits that make $650 and Chief should recognize it. Then: "yes build it but also make sure that chief can either do it for people, match what the person does or verify. make sure that there is no duplicates."'
status: shipped
prs: [kmj-intake-server#1669, solutionist-studio#1424]
migrations: [supabase/APPLY-2026-10-31-giving-deposits.sql (applied 2026-10-31, verified), supabase/APPLY-2026-10-31-giving-deposits-repost.sql (applied 2026-10-31 for the platform owner's churches; again for every church at the switch-on)]
left_undone:
  - "Card gifts through the app stay with the Stripe payout matcher; gifts through another platform than Subsplash (Tithe.ly, Pushpay) aren't recorded per person, so their payouts aren't matched here"
  - "A deposit that doesn't add up to its gifts (a counting error) can't be matched until the gifts or the deposit are corrected; the screen says by how much"
  - "Switched with GIVING_DEPOSITS (owner until a Thursday flip); What's New at the flip. The ledger books 1160 only where it's on (giving_deposits.ledger_gifts_wait, asked once per business per drain, and a read it can't make leaves the rows queued), so at the flip the repost SQL runs again for every church, and again if it's ever switched off"
  - "Treasurer seats: matching is owner-only like every bank write; a finance seat matching is a later ruling"
decisions:
  - "The books: a church's gift not given by card books into 1160 Gifts to Deposit (nonprofit chart), not Cash; a matched deposit is money_kind 'gifts' and books Dr Cash, Cr 1160 for the deposit plus any fee the platform kept (gift_match_fee); the fee is its own business_expenses row (Operating, 'Giving platform fees'), so the ledger and the H.3a reports agree and cash nets to the bank. Revenue still comes from the gift, once. This also ends 'other' gifts (Cash App) sitting in 1150 Stripe Clearing, which no payout ever cleared"
  - "No duplicates is the database's rule: gift_deposit_items' primary key (business, side, ref); the code checks first and says which gift or deposit is already matched"
  - "The clear matches (Chief, or the screen's Match all): a day's cash and check in one to three deposits from the day before to six days after; two Sundays in one deposit; Subsplash gifts less the fee written on each, in one payout within a week or a run of days; a transfer gift to the one deposit of its amount within three days, or two to four in one deposit. Anything with two possible answers is left for a person"
  - "A person's match (the screen, or Chief on the owner's word): exactly the gifts and deposits named, checked: the deposits must add to the gifts, an online payout may be less by a fee up to 10%; otherwise it says by how much and what may be missing"
  - "Verify (Chief's giving_deposits, the screen's top line): every match, whoever made it, against the gifts and deposits now: an edited or refunded gift, a deposit given another answer or gone, a missing fee row"
  - "Every write is guarded: a deposit answered meanwhile or in a closed month leaves nothing behind; unmatching puts the deposits back to waiting and removes the fee row. The screen can't set or change 'gifts' on a bank row (plaid_router), reconcile skips gift deposits, and the To review queue never shows them"
  - "Chief: giving_deposits (sensitive read), match_giving_deposits (bulk class A: the clear ones, or items the owner named), unmatch_giving_deposits (the inverse, one batch)"
related: [2026-10-31-chief-files-the-bank.md, 2026-10-31-bank-statements.md]
---
`giving_deposits.py` (gifts, deposits, matches, plan, check_match,
write_match, unmatch, verify, status, match_clear, match_named, the routes,
the Chief verbs); `gl_engine` (1160, `_gift_waits`, the 'gifts' deposit);
`bank_money` ('gifts', MATCHED_ONLY); `plaid_router` (the screen can't set or
change it); `chief_reconcile` (skips gift deposits). Wired: `chief_of_staff`,
`action_registry`, `action_inverse`, `chief_areas`, `chief_tool_loop`,
`chief_prompt`, `kmj_intake_automation`, `account_lifecycle`,
`site_page_helpers`. Tests: `__tests__/test_giving_deposits.py` (17).

**Live, 2026-10-31.** Merged #1669 (after the review's fixes: 1160 only where
the switch is on, a partial batch keeps its undo, verify reads a match's own
rows) and solutionist-studio#1424. Schema applied before the code; the repost
queued Love City's 718 non-card gifts after it deployed, and the ledger drained
them into 1160 at about a hundred a run. Love City's ledger has had an active
divergence alarm since 2026-10-14 (revenue, cash, and a trial balance off),
from before this work; not touched here.

