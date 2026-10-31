---
title: A housing allowance's payments are tied to the bank payments they were, and the year comes out as a report
date: 2026-10-31
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-31: "there are already payout that occured this year for housing and i need reports on that but it matching transaction because i want to know exactly based on transaction how much has been paid out. so i was going to go through transaction or better yet ask chief to go through the transaction and help me find what was paid out and attach it to the housing payouts or payments"'
status: in review
prs: [kmj-intake-server (this PR), solutionist-studio (the screen, next)]
migrations: []
left_undone:
  - "The screen: Find in the bank, the bank row beside each payment, the report download (solutionist-studio, next PR)"
  - "Bank history before the connection: Plaid gave Love City 90 days (its rows start 2026-07-17), so January to mid-July can't be tied here. Link tokens ask for nothing more (no transactions.days_requested); asking for two years going forward is its own PR, and the months already missed need a statement import or the payments typed in from the statement"
  - "The fund for the year (Kevin's ask just before this one): every payment out, payroll and housing included, against a yearly fund. Its own PRs after this"
decisions:
  - "No migration: minister_housing_entries already had source = bank and source_id = the Plaid transaction_id, counted once per allowance (the unique index). Nothing ever filled them"
  - "Find reads the accounts in the books (the Transactions screen's own, as search_transactions does): cleared payments out (amount > 0, not pending) in the allowance's tax year, paged, a failure past 10,000 rather than a part passed off as the whole. The server counts and totals; Chief quotes them"
  - "Love City's descriptions never say 'Kevin', 'housing', 'parsonage' or 'pastor' (a count on production, 2026-10-31: 0 of 106 payments out), so find leads with REPEATS: the same amount and the same description once reference numbers are dropped. Words and an exact amount narrow it. They are candidates, never proof; Chief ties only what the owner confirms"
  - "Attach is all or none and never adds up past the bank row: a payment already on this allowance is a 409; what a row pays across allowances can't pass its amount (a paycheck transfer can be split, the housing part on the allowance). A typed-in payment of the same amount within 7 days is the same payment: it is tied (source manual to bank, its date to the bank's), not counted twice"
  - "One batch, one undo, the reconcile_books shape: attach_housing_payments is bulk and class A; its result lists the entries it added and the typed-in ones it tied with their old dates, and detach_housing_payments (class A, not bulk) takes exactly that back. Detach never touches a typed-in or pay run entry"
  - "The record shows each bank-tied payment's bank date, description and amount (a failed bank read leaves them off and says so, never fails the screen), paid by where it came from (tied to the bank, from a pay run, typed in only), and where the bank history starts. Chief's status says the same"
  - "The report is a CSV for the tax preparer: every entry beside its bank row, before-the-vote and receipt columns, then the figures and the bank history line. A cell that starts with = + - @ is quoted so a spreadsheet never runs a bank description as a formula"
  - "Also fixed: a failed delete was reported as done (sb_delete_as_service returns False, not None)"
related: [2026-10-30-housing-allowance.md, 2026-10-31-housing-paper-trail.md, 2026-10-31-minister-payroll.md]
---
`housing_allowance.find_bank_payments`, `attach_bank_payments`,
`detach_bank_payments`, `sources`, `report_csv`, `bank_history_starts`;
routes `GET/POST /housing-allowance/{id}/bank`,
`POST /housing-allowance/bank/detach`, `GET /housing-allowance/{id}/report.csv`;
Chief verbs `find_housing_payments` (a sensitive mid-turn read),
`attach_housing_payments`, `detach_housing_payments`. Tests:
`__tests__/test_housing_allowance.py` (12 new).
