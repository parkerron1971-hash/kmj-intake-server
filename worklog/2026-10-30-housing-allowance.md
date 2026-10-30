---
title: A minister's housing allowance in the system (designation, paid, housing costs, year-end figures)
date: 2026-10-30
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-30: "I do have a housing allowance setup. so we need structure for this setup in the system". Paid: "Both / not sure". Who sees it: "Owner only"'
status: in review
prs: [kmj-intake-server#1655]
migrations: [supabase/APPLY-2026-10-30-housing-allowance.sql (applied 2026-10-30, verified)]
left_undone:
  - "Payroll (next PR): a minister flag on employees so Pay your team withholds no Social Security/Medicare (payroll_calc computes FICA and FUTA for everyone today), a housing part per pay run, and that part logged as 'paid' (source pay_run) when a run is marked paid"
  - "The app screen (solutionist-studio): Housing allowance under the owner's money area; Chief's receipts point at Bookkeeping (housing_allowance.NAV) until it exists"
  - "Picking a bank row as a payment works by API (source bank, source_id = transaction_id); the screen's picker comes with the app screen"
  - "A year-end statement PDF for the minister (the figures and Box 14 are in GET /housing-allowance today)"
  - "HOUSING_ALLOWANCE is owner (Kevin's businesses) until a Thursday flip"
decisions:
  - "Owner only (Kevin's pick): a minister's housing costs are personal records; the board's amount already lives in its own Board decision, which the allowance links to"
  - "Excludable = least of designated, paid, spent, fair rental value; paid above it is taxable; Box 14 = paid. Every summary says the tax preparer confirms it and that the allowance still counts for self-employment tax"
  - "Chief records only the board's own amount and date (it asks when they aren't said, never suggests one); its lookup quotes server figures"
  - "Server-only tables; set is not undoable (no before-values kept); a logged entry is, by delete"
related: [2026-10-30-chief-reconcile-all.md, 2026-10-27-church-board.md]
---
`housing_allowance.py`: two tables, owner-only routes under `/housing-allowance`
(list with figures and reminders, create, change, archive, add and delete
entries), and four Chief verbs: `housing_allowance_status` (a sensitive,
Chief-only lookup), `set_housing_allowance`, `log_housing_entry` (undone by
`delete_housing_entry`). From November it reminds that next year's allowance
must be designated before Jan 1. Tests: `__tests__/test_housing_allowance.py`.
