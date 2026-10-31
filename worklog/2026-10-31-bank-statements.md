---
title: Bank statements fill in the months before the bank feed (CSV, OFX, or a PDF read by Claude)
date: 2026-10-31
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-31: "how about we upload all the statements that is missing so they can be added into the system itself. you want to put them inside the system yourself and then build a scanner or ability to upload?"'
status: shipped
prs: [kmj-intake-server#1663, kmj-intake-server#1664, kmj-intake-server#1665, kmj-intake-server (this PR), solutionist-studio#1423]
migrations: [supabase/APPLY-2026-10-31-bank-statements.sql (applied 2026-10-31, verified: 19 columns, the tag column, RLS on, 0 policies)]
left_undone:
  - "A bank that was never linked can't take statements: a statement's rows belong to an account in the books (plaid_accounts needs a Plaid item). Link first, then fill in before the feed"
  - "Statement rows come with no category (the bank gives none). They wait in the review queue like any uncategorized row; deposits aren't income until answered"
  - "Chief reads the coverage (bank_history) but can't add or remove a statement: a file comes through the screen"
  - "A bank re-linked later with longer history (Plaid days_requested) would bring the same months again on a new account id; remove the statements for those months first"
  - "What's New at the Thursday switch-on (BANK_STATEMENTS defaults to owner)"
  - "The review screen says 'matches the statement's own totals' even when the check passed on a summary split (totals_split); a line naming the bank's fee line apart is a small frontend follow-up"
  - "Love City's July statement has one row inside the bank feed's days that the feed lacks (an overdraft fee); feed days are never added, so it is Kevin's to look at"
decisions:
  - "Statement rows go INTO plaid_transactions, on the account they belong to, tagged statement_import_id (transaction_id stmt_ + a hash of account, date, amount, words and which of the day's same rows it is). Everything that reads the bank (Transactions, the ledger by its own insert trigger, reports, the housing allowance, funds, Chief's search) reads them with no change; removing a statement deletes its rows and the trigger reverses them"
  - "The scanner is Claude reading the PDF natively (a document block, a forced tool for the shape, thinking off, Sonnet 5.5, STATEMENT_READ_MODEL pins), metered at the llm_call seam with the business id and gated by billing_limits.require_units. A PDF locked against editing only is unlocked with pypdf; a password-locked one is refused; over 60 pages refused"
  - "CSV and OFX/QFX/QBO are read without AI: header detection (date, description, amount or debit/credit, balance, type, check number), newest-first files turned around, a running balance gives the opening and closing"
  - "The check: opening + in - out = closing to the cent, and a PDF's printed totals of deposits and withdrawals agree with its rows. One that doesn't add up is added only with accept_unbalanced. One balance or none is 'not checked', never 'balanced'; the owner can type the statement's balances on the screen to check it"
  - "Each row is reviewed server side on every call (the client is never trusted): new; already in (the same id); maybe in (same day and amount as a statement row already in, worded another way: left out unless ticked); in the feed (the feed's days, from FEED_DAYS=4 before its first row: matched one to one to a feed row of the same amount within 4 days, or flagged as missing from the feed). Feed days are never added"
  - "Removing a statement is refused while one of its rows is on a fund or a housing allowance"
  - "Coverage per account: the feed's first day (statement rows aside), the statements in (each one's check, and joins_previous: does it open where the one before closed), and the days of the year before the feed nothing covers"
  - "Who: readers see the coverage; the owner alone reads files, adds and removes (plaid_router gates). Routes under /bank-statements (reserved as a page id). Switch BANK_STATEMENTS off|owner|on, owner by default"
  - "Chief: bank_history, a sensitive mid-turn read under Giving & money; the funds and housing finders now say the months before the feed come in as statements"
related: [2026-10-31-funds-for-the-year.md, 2026-10-31-housing-from-the-bank.md]
---
`bank_statements.py` (parse_csv, parse_ofx, read_pdf, check, review, add,
remove, coverage, the routes, bank_history); migration
`supabase/APPLY-2026-10-31-bank-statements.sql` (`bank_statement_imports`,
`plaid_transactions.statement_import_id`). Wired: `chief_of_staff`,
`action_registry`, `chief_areas`, `chief_tool_loop`, `chief_prompt`,
`kmj_intake_automation`, `account_lifecycle` (erase order; not re-imported),
`site_page_helpers`. Tests: `__tests__/test_bank_statements.py` (25).

**Live, 2026-10-31.** Kevin's seven Huntington PDF statements (January to
July) went in through the screen, each checked before it was added; the
account's 2026 has no missing days now. Two fixes came out of it:
- #1664: Sonnet 5.5, the reader's model, answers a forced tool_choice with a
  400 (`model_ladder.supports_forced_tool_choice`); the prompt names the tool
  there instead. The first read failed in under a second because of it.
- #1665: Huntington prints Debits and Total Service Charges on lines of their
  own. The reader's printed totals now add fee and interest lines printed
  apart, and `check()` treats a one-sided mismatch with the balance tied to
  the cent as the bank's summary split (`totals_split`), never a missing row.
- This PR: `totals_split` is in every state's answer, so the shape is one.
