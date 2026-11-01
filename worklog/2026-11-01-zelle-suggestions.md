---
title: Zelle money from the bank, suggested as gifts in the week's service count
date: 2026-11-01
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-01: "yes build the sheet section and the zelle suggestions."'
status: in review
prs: ["kmj-intake-server (this PR)"]
migrations: []
left_undone:
  - "The screen (From the bank: Zelle, with Add) is the front end PR"
  - "Cash App reaches the bank as one transfer with no names: not suggested (its activity export would be a later import)"
  - "Switched with GIVING_SERVICES (owner until a Thursday flip)"
decisions:
  - "GET /giving/{id}/counts/{count}/bank: Zelle money in (the books' accounts, cleared, not filed as anything, never matched to a gift) during the open collecting count's online window, with the sender read from the bank words and matched to one person"
  - "A row added with bank_ref is checked against that bank row (this church's, Zelle money in, the same amount, not already a gift), dated the day the money arrived (so the Sunday match pairs it with that deposit), and its note names the bank row; a bank row is never recorded twice"
related: [2026-11-01-giving-services.md, 2026-10-31-giving-deposits.md]
---
`giving_services.py` (zelle_sender, who_is, bank_suggestions, the bank route, record_gifts
bank_ref). Tests: `__tests__/test_giving_services.py` (25).
