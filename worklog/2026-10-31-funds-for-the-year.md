---
title: Funds for the year, each bank transaction placed on one, and Chief can place them
date: 2026-10-31
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-31: "is there a way to have now if we created a fund for the year. we can place all what was paid out or sent out aligned with that. wether it is housing pay etc...", then "build that", wanting it "exactly based on transaction"'
status: in review
prs: [kmj-intake-server (this PR), solutionist-studio (the Funds tab)]
migrations: [supabase/APPLY-2026-10-31-funds-for-the-year.sql (applied 2026-10-31, verified: 2 tables, RLS on, 0 policies)]
left_undone:
  - "Typed-in expenses, bills and check requests aren't placed on funds: a fund holds bank transactions, so nothing is counted twice (a paid check request's expense and its cleared check are one payment). A cash payment that never reaches the bank has no fund yet"
  - "Gifts given through the app aren't counted on a fund by name; their payout is a deposit, placed as money in"
  - "The Check requests budget lines (church_check_settings.lines) stay as they are; a fund and a ministry's budget line can share a name, and aren't joined"
  - "What's New at the Thursday switch-on (FUNDS defaults to owner)"
decisions:
  - "A fund is one year's: a name, an optional budget, notes; one live fund of a name a year. Removing one removes its placements (the bank is untouched; the rows are free again)"
  - "A fund holds BANK transactions, all of one or a part, money out or in by the row's own sign (kept on the placement, so the figures never hang on the bank feed). Across funds a row is never placed past its amount, and once a fund. Kevin's ask was 'exactly based on transaction'; the bank is the one record of money that left, so nothing is counted twice"
  - "Figures: paid out, money in, left of the budget (or over it), balance (in less out). The server adds up; Chief and the screen quote it"
  - "Reading the bank is shared with the housing allowance (bank_picks.py: the books' accounts, cleared rows of a year, paged with a cap that fails rather than returns a part, descriptions, repeats). housing_allowance.py now reads through it; its 53 tests pass unchanged"
  - "Who: the Transactions screen's readers read (plaid_router._require_reader); the owner alone places or changes (plaid_router._require_owner), finder included. A payment tied to a housing allowance is tagged in the finder for the owner alone, and 'housing' picks only those"
  - "Chief, under Giving & money: fund_status and find_fund_payments (sensitive mid-turn reads), set_fund, place_fund_payments (bulk, class A; one undo, unplace_fund_payments, takes exactly the batch back). Chief places only what the owner confirmed; a budget is never suggested"
  - "Routes under /year-funds (reserved as a page id, so a church site's 'funds' page stays free)"
related: [2026-10-31-housing-from-the-bank.md]
---
`funds.py` (figures, describe, find_bank, place, unplace, report_csv,
summary, the routes, the Chief verbs), `bank_picks.py`; migration
`supabase/APPLY-2026-10-31-funds-for-the-year.sql`. Tests:
`__tests__/test_funds.py` (17).
