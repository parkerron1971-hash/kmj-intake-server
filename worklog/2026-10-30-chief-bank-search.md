---
title: Chief searches and totals bank transactions (search_transactions)
date: 2026-10-30
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-30: Chief couldn''t total what was "given to kmj paypal kmj ministries kevin" this year: "can chief look at transactions that is not reconciled? ... build it now"'
status: in review
prs: [kmj-intake-server#1649]
migrations: []
left_undone:
  - "CHIEF_BANK_SEARCH is owner (Kevin's businesses only) until a Thursday flip to on (Railway, both services)"
  - "Kevin's wider rule, same day: Chief does anything he can do on request except what needs his permission, then shows what it did. First case: 'reconcile all the transactions' as one reviewable, undoable batch. Separate PR; it reverses chief_bookkeeping_actions' 'bulk approval is deliberately not offered'"
  - "Custom categories and clergy housing allowance: surveyed, not built (findings in the PR thread / session summary)"
decisions:
  - "A Chief-only, sensitive read: bank rows never go out on the agent (MCP/KAI) surface"
  - "Gate = the Transactions screen's own reader gate (plaid_router._require_reader), checked as the person talking; no person, no rows"
  - "The server sums every match (paged, 5,000 cap, past it the search refuses); the card shows 25. Pending and excluded matches are reported, never counted"
  - "One payload: mid-turn a lookup, as an [ACTION:] tag a show_view card (view transactions) the app already draws; no frontend change"
  - "direction both by default: 'given to' is ambiguous, so in and out are reported apart instead of guessed"
related: [2026-10-02-bookkeeping-redesign.md]
---
Chief's prompt carried bookkeeping counts only (how many deposits were
unreconciled, and their sum), and no tool read a single bank row, so Chief said "let me
search" and then sent Kevin to the Transactions screen. `chief_transactions.py`
adds `search_transactions`: words (any match on the bank description or
merchant), in/out/both, dates (Jan 1 to today by default), and reconciled /
unreconciled / all. It returns exact totals (in and out apart, by status, by
word) and the 25 most recent rows. Placed in the church money lane
(`chief_areas.MONEY`). The bookkeeping block now tells Chief to call it, or,
where it's switched off, to say at once that it can't. Tests:
`__tests__/test_chief_transactions.py`.
