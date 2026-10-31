---
title: Chief files the waiting bank rows as income or expense, in one batch the owner confirmed, one undo
date: 2026-10-31
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-31, with Love City''s January to July statements just added: "NOW CAN I ASK CHIEF TO PLACE IN EXPENSE AND REVENUE ETC WOULD CHIEF DO THAT?"'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Only rows still waiting (To review) are filed; changing an answer already given stays on the Transactions screen"
  - "No 'do this every time' rule is made from chat; the screen's rules still do that"
  - "Switched with the bank search (CHIEF_BANK_SEARCH: owner until a Thursday flip)"
decisions:
  - "Under Kevin's 2026-10-30 rule (Chief does what he can, one batch he can check and undo); the proposals path stays one at a time, this is the owner's own answer given in chat"
  - "Read: bank_to_file is the To review queue itself (bookkeeping_overview.build_review), grouped by payee key (bank_picks.payee_key) and direction, money in positive, with the screen's suggestion where every row agrees. Readers may read"
  - "Write: file_bank_rows takes items by payee (every row of it still waiting) or by transaction_ids, with the screen's answers: income / owner / transfer (money_kind), operating / tax / owner_pay / savings (bucket), personal (excluded_from_books), and an optional label (business_subcategory). Money in can't be an expense, money out can't be income. Each write is guarded on the row's values from before, so an answer given meanwhile is left and counted. Owner only, bulk class A, at most 600 rows a batch"
  - "Undo: undo_file_bank_rows (action_inverse, so undo_last reaches it) puts the batch back guarded on what Chief wrote, skipping rows answered since; 30 days by name"
  - "The result is a display: table card (What I filed), which the app already draws for any verb"
  - "The prompt: propose per group and ask; for a church, giving through Tithe.ly, a giving app or the plate is income; never guess money in from a person or a payment app"
related: [2026-10-30-chief-reconcile-all.md, 2026-10-31-bank-statements.md]
---
`chief_file_bank.py` (queue, group, plan, file_rows, summarize, undo, the
handlers, TO_FILE_TOOL). Wired: `chief_of_staff`, `action_registry`,
`action_inverse`, `chief_areas` (Giving & money), `chief_tool_loop`,
`chief_prompt`. Tests: `__tests__/test_chief_file_bank.py` (11).
