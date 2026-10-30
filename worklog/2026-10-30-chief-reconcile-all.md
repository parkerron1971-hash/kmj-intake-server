---
title: Chief reconciles the bank on request, lists every change, undoes the batch
date: 2026-10-30
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-30: "chief should be able to do pretty much all that i can do upon request except things that require my permission. so that way is someone say reconcile all the transaction it can and allow me to check what it done if I want." Then: "pick the best options for both questions"'
status: in review
prs: [kmj-intake-server#1653]
migrations: []
left_undone:
  - "Switched with CHIEF_BANK_SEARCH (owner until the Thursday flip), the same switch as the bank search"
  - "Deposits the bank calls transfers (PayPal and the like) aren't counted as income; Chief asks whether they're giving instead of relabelling. A 'mark these as giving' batch with the same undo is the natural next verb"
  - "Categorization proposals are still one at a time (chief_bookkeeping_actions); a confident-categorize batch could reuse this module's record-and-undo"
  - "Try lane (Kevin's 'pick the best'): clergy housing allowance next (a 2027 allowance must be designated by the board before Jan 1), then custom categories. Not filed in Mission Control from here: no owner session"
decisions:
  - "Kevin's pick (delegated): reconcile = only what's clear; anything unsure is left and listed; one batch, one undo"
  - "Clear means: a Stripe payout or sent transfer the existing matcher matches; a move between own accounts where both legs say transfer (an equal amount alone is a coincidence, not a transfer); a deposit that can't be a Stripe payout is settled 'ignored' with the reason on the row, as the screen's Ignore does. A deposit that says Stripe but matched nothing is left"
  - "Nothing decides what money IS: no income/giving relabelling"
  - "Class A, bulk (never unprompted, tag only); undo_reconcile_books is class A, NOT bulk, because it restores one recorded batch (test_action_inverse: no inverse is bulk)"
  - "Every write is guarded on the before-values and every undo on Chief's after-values, so a row changed meanwhile is never overwritten"
  - "Owner only, the Reconciliation screen's own write gate (plaid_router._require_owner, church money wall included)"
related: [2026-10-30-chief-bank-search.md, 2026-10-02-bookkeeping-redesign.md]
---
`chief_reconcile.py` adds `reconcile_books` and `undo_reconcile_books`. A
reconcile reads the unmatched deposits (200 per run, newest first), the
payments out in their date window, and settles only the clear rows. The result
is a show_view card ("What I reconciled") listing every row and what was done,
with a batch id and each row's before/after values, which the undo log keeps.
`undo_last` reaches it for a day. Asked by name, `undo_reconcile_books` works
for 30 days and skips any row changed since. A partial undo stays undoable so
asking again finishes it. Tests: `__tests__/test_chief_reconcile.py`.
