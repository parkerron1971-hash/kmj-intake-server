---
title: A church's treasurer (an Admin seat) can do the money week, and a locked-out treasurer can ask for a key
date: 2026-11-01
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin approved: Love City's treasurer holds an Admin seat and must be able to do the money week (match the deposit, the bank matching, reconcile, categories, bills, store orders); and the Keys dead end, where someone the Giving keeper locked out couldn't even ask for a key"
status: waiting on Kevin
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "The screens: giving deposits and the categories card now answer can_change true for a church's Admin; any front-end check that hides a button from a non-owner (Bills, Transactions, Reconciliation, store orders) still needs the same rule"
  - "Still owner-only, not part of this ask: matching a bill to the bank (bill_payments, which reads bank rows outside the Giving wall), placing bank rows on funds (funds.py), bank statements (bank_statements.py), and Bookkeeping's transfer pairs and duplicate-account clean-up (bookkeeping_overview). Open them through plaid_router._require_money_writer / bills_router._writer if Kevin wants them in the treasurer's week"
  - "Chief's bills lookup (chief_bills) reads bank rows for its 'could be bills' suggestions without the Giving wall, as before; the owner's bill-to-bank match does too"
  - "church_checks counts an office login with the Giving & money area as the treasurer; this gate counts only the owner and an Admin seat"
decisions:
  - "One gate, church_money_gate.require_money_writer: the owner, or in a church (church_follow_up.is_church) an active Admin seat. A Manager seat, a stranger and every non-church seat get the same 403 as before; a church that changes its type holds its Admins to the owner rule"
  - "The Giving wall stays where it was: the bank's doors (plaid_router._require_money_writer, giving deposits, Chief's bank verbs) call church_keys.wall after the gate, so a named Giving keeper still locks the treasurer out until a key. Bills and store orders were never behind the wall and still aren't"
  - "Opened: plaid sync, a bank row's edit, bulk categorize and exclude, category rules (add, delete), the payout match/unmatch/ignore/run; the Sunday match and unmatch; the categories card (add, change, lines, undo); bills (add, edit, mark paid, delete); store orders (list, fulfill, ship); Chief's reconcile, file the bank, categories, the Sunday match, add and remove bills"
  - "Kept owner-only: linking a bank (link token, public-token exchange, relink), unlinking (item removal), which accounts count in the books (the account toggle and account removal), and the church's payout and Stripe accounts (untouched)"
  - "A church's bills list: the owner, an Admin or the outside accountant (any seat read it before); every other business's list as before"
  - "Only the owner is shown a bank payment that fits a new bill from Chief's add_bill, since only they match bills to the bank"
  - "CHURCH_KEYS=owner (the default) opens the key routes to the logins and accountants of the platform owner's own churches (businesses.owner_id == chief_of_staff.PLATFORM_OWNER_ID), not only the platform owner's email; anyone else's church stays closed, and off still closes them"
related: [2026-10-31-giving-deposits.md, 2026-11-01-categories-card.md, 2026-10-28-church-money-levels.md]
---
`church_money_gate.py` (new: `require_money_writer`, `standing`, `can_write`);
`plaid_router` (`_require_money_writer`, `_require_money_writer_for_tx`; the
owner gate kept on linking and accounts); `giving_deposits`,
`expense_categories`, `chief_reconcile`, `chief_file_bank` (writes through
the new plaid gate; can_change from the gate); `bills_router` (`_writer`,
`_writer_for_bill`; a church's list narrowed; `_owner` kept for
bill_payments); `chief_bills` (adds and removes through `_writer`);
`store_router` (`_require_order_keeper`); `church_keys` (`platform_church`,
`_gate(user, business_id)`; `is_open`/`opened`/`wall` unchanged). Tests:
`__tests__/test_treasurer_money_week.py`, with neighbouring fixtures patched
for the renamed gates. The giving-deposits log's "a finance seat matching is
a later ruling" is this ruling. Before building more here, check the front
end's owner-only button checks.
