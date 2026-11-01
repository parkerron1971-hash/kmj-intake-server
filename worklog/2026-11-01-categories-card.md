---
title: The categories card on screen (the server side)
date: 2026-11-01
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-01: "build the categories card on screen"'
status: in review
prs: [kmj-intake-server (this PR), solutionist-studio (the card)]
migrations: []
left_undone:
  - "Categories for money in (income) still don't exist; the card is spending only"
  - "Switched with Chief's categories (CHIEF_BANK_SEARCH: owner until a Thursday flip); the GET says so as `card`"
decisions:
  - "The card changes through the same code as Chief's verb: set_category is now the gate plus change(); undo is the gate plus take_back(). The card's routes gate as the owner (plaid_router._require_owner, the church money wall included) and the switch"
  - "POST /expense-categories/change (rename, new bucket, merge) and /undo; a card change is written to chief_undo_log as set_expense_category by the person who clicked, so the card's Undo button and 'Chief, undo that' both take it back"
  - "A merge may now start from a label in use that isn't on the list ('Utility bills' into 'Utilities'): its rows and rules move, nothing is archived, and a label with nothing filed is refused"
  - "Chief's categories link (NAV) opens Transactions → Rules, where the card is"
related: [2026-10-31-expense-categories.md]
---
`expense_categories.py` (change, take_back, the card routes, `card` on the
GET, NAV, wording that reads for both Chief and the screen). Tests:
`__tests__/test_expense_categories.py` (19; 3 new for the card).
