---
title: Chief's bank search tells filed from matched, and says a past answer by its line's name
date: 2026-11-03
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03, pasting a Chief chat about utilities and bills: "can you verfiy chief is doing things right and if there is needing to be a fix"'
status: in review
prs: ["kmj-intake-server (this PR)"]
migrations: []
left_undone:
  - "The recurring-bill finder missed DTE and Consumers Energy (monthly, but the amount changes and the bank's wording changed when the feed replaced the statements)"
  - "Feed rows since Jul 17 are filed as Ministry & operations with no Utilities label; the Spending report shows them under the line, not Utilities, until they're relabelled"
decisions:
  - "Verified on Love City (read only): 486 bank rows, 131 filed, 355 waiting (127 giving deposits, 17 other deposits, 211 payments all dated Jan 2-Jul 16, the statement months); Chief's 21-row batch of Oct 31 is there and undoable; the 9 utility and platform payments Chief listed as waiting are exactly the waiting ones, to the cent"
  - "What was wrong: Chief explained 'why are they still under All transactions' from the search card's Reconciled: No (reconciliation_status, a payout/bill/gifts tie) as if filing were half the job. All transactions is the whole bank list; filing takes a row out of To review"
  - "search_transactions: each row says what it's filed under (the business's line names, label, what the money is, or Waiting); totals count filed and waiting; the old column reads Matched with a dash for nothing to tie (not No); status takes waiting and filed; the tool text, the note and the prompt line say filed rows stay in All transactions and are never 'unreconciled'"
  - "bank_to_file: a payee's past answer carries its line's name (suggest.line), so Chief says Ministry & operations, never 'operating'"
related: []
---
`chief_transactions.py`, `chief_file_bank.py`, `chief_prompt.py` (the search tag's line),
`__tests__/test_chief_transactions.py`, `__tests__/test_chief_file_bank.py`, `__tests__/test_expense_categories.py`.
