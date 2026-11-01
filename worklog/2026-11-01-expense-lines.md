---
title: A business names the lines of its books, and adds lines of its own (the server side)
date: 2026-11-01
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-01: "how can the roll up list can change?" then "yes build option 1 with church names as default but allow for them to be changed because other business would want different names also allow for there to be added more to this list."'
status: in review
prs: [kmj-intake-server (this PR), solutionist-studio (the card and every screen's names)]
migrations: [supabase/APPLY-2026-11-01-expense-lines.sql (before the code)]
left_undone:
  - "Switched with Chief's categories (CHIEF_BANK_SEARCH: owner until a Thursday flip); off, every business keeps the standard five names"
  - "The ledger's own account names (5000 Operating Expenses ...) and the trial balance stay standard: an accountant's view doesn't move"
  - "Bookkeeping overview's 'Where the money went' shows the five by their names; an added line stays inside its base there (the P&L splits it out)"
  - "No reordering of lines: each added line sits under the built-in line it counts as"
decisions:
  - "The five (operating, owner_pay, tax, savings, other) stay the books' accounts and the only values business_category takes; a business only names them. A church starts with Ministry & operations, Pastor & staff pay, Taxes, Reserves, Other"
  - "An added line counts as one of the five in the books (its base); a category placed on it (expense_categories.line) shows under it, and the P&L (reports screen, its PDF/email, the accountant package) shows it as its own section; totals never change (expense_lines.present)"
  - "Moving a category to a line on another base moves its rows' bucket with it, one batch; removing an added line sends its categories back to its base line; the five can't be removed; line names never clash, a built-in's standard name included"
  - "Chief: set_expense_line (rename / add / remove), one undo (undo_category_change); the categories lookup and bank_to_file give the lines by the business's names; set_expense_category takes 'line'"
  - "The card's routes: GET /expense-categories/lines (any screen that names a line) and POST /expense-categories/lines (owner, where on), logged in Chief's undo log"
related: [2026-10-31-expense-categories.md, 2026-11-01-categories-card.md]
---
`expense_lines.py` (new: the list, defaults, change, present), `expense_categories.py`
(categories on lines, the lines routes, Chief's verb), `reports_router.py` +
`accountant_export.py` + `bookkeeping_overview.py` (names in the P&L),
`chief_file_bank.py` (the names for Chief). Wired: `chief_of_staff`,
`action_registry`, `action_inverse`, `chief_areas`, `chief_prompt`,
`account_lifecycle`. Tests: `__tests__/test_expense_lines.py` (9).
