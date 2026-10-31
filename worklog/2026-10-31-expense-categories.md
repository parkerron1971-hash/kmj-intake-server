---
title: Chief makes expense categories, suggests where a payment goes, and remembers a payee for next time
date: 2026-10-31
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-31: "can chief make expense catagories if i request it so transactions can go under there?" then "yes and also allow for chief to have suggestions on where things go ... hey, I noticed this transaction was to this particular business. Do you want me to add it to this category? ... do you want me to save this in my memory so I know to add this in the future"'
status: in review
prs: [kmj-intake-server (this PR), solutionist-studio (the category names on To review)]
migrations: [supabase/APPLY-2026-10-31-expense-categories.sql (before the code)]
left_undone:
  - "No screen to manage the list yet (make/rename/merge are Chief's; the To review box offers the saved names); a Categories card in Rules is a follow-up"
  - "Money in has no categories: its answers stay income / owner / transfer, and giving deposits belong to the Sunday match"
  - "Switched with the bank search (CHIEF_BANK_SEARCH: owner until a Thursday flip)"
decisions:
  - "A category is the label the P&L already breaks spending out by (business_subcategory) plus the bucket it rolls up to; expense_categories keeps one spelling per name (a unique index on lower(btrim(name)) among live ones, and key_of reads 'Utilities', 'utilities ', 'Utility' as one)"
  - "Make, rename, merge (set_expense_category): a rename or merge moves the bank rows filed as spending, the manual expenses and the rules with that name, each guarded on its values, one batch; merged, the old one is archived; undo_category_change puts it back, skipping a row changed since"
  - "Filing (file_bank_rows): an item may name a saved category (its line, bucket and spelling); 'refile' moves rows already filed as spending, by payee, rows or from_category, guarded the same way; only spending lines move, never income or a gift deposit"
  - "Suggestions: bank_to_file gives each money-out payee a 'suggest': a saved rule, or how the same payee was filed before (the most-used answer and how often); Chief proposes, asks, files what's confirmed. Chief's bookkeeping block tells it to offer when rows wait"
  - "Remembering (save_category_rule): an every-time rule kept by the payee's wording (payee key) as well as Plaid's merchant name (expense_categories.rule_for), so the bank feed's sync and a statement import both file that payee's next payments; one undo forgets it"
related: [2026-10-31-chief-files-the-bank.md, 2026-10-31-bank-statements.md]
---
`expense_categories.py` (the list, usage, picture, create, relabel,
set_category, suggest, history, remember, rule_for, undo, the routes, the Chief
verbs); `chief_file_bank` (suggestions, a saved category, refile, `spending`);
`plaid_router._tx_payload` and `bank_statements.add` (rules by payee);
`chief_bookkeeping` (the offer). Wired: `chief_of_staff`, `action_registry`,
`action_inverse`, `chief_areas`, `chief_tool_loop`, `chief_prompt`,
`kmj_intake_automation`, `account_lifecycle`, `site_page_helpers`. Tests:
`__tests__/test_expense_categories.py` (12).
