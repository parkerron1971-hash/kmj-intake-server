---
title: A church's payroll, contractors and period closes ask the money wall, as its ledger does
date: 2026-11-18
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-18: "yes fix and build what is needed." Found while building the one money gate: three books routers never asked the church wall.'
status: shipped
prs: []
migrations: []
left_undone:
  - "grants_router is left as it is: it reads the church's public funder profile and searches public federal opportunities, no money records."
  - "customer_balances_router is left as it is: it is the prepaid-balance card on a person's profile (Member and above), not the church's books."
  - "suppliers_router is left as it is: it feeds Supplies & equipment, which office logins work."
  - "The refusal uses the wall's existing words (the ledger's): 'Giving records require owner, admin, or accountant access.'"
decisions:
  - "The wall is asked FIRST in each _access, before the owner shortcut and the seat ladder, exactly as gl_router._access does. Any business that is not a church or nonprofit is not asked and keeps its ladder."
  - "In a church this takes payroll, contractors and period closes away from Manager, Member and Viewer logins through the server. The church menu already hid all three (Bookkeeping and Payments are money pages), so nobody loses a page they could open."
  - "The minister payroll tests used a Manager as the stand-in for 'someone who is not the owner'; that stand-in is now an Admin, and a new test pins that a Manager is refused outright."
related: [2026-11-18-one-money-gate.md]
---
`payroll_router._access`, `contractors_router._access` and
`accounting_periods_router._access` let any active seat on a church read
through the server, a Viewer included: employees and pay runs, contractors and
transfers, and the periods of the books. The ledger, the reports and the bank
refused the same login. A login that typed the address, or an old tab, got
what the menu had hidden.

Each now calls `giving_records.require_ministry_finance(biz, user, row)` (the
one money gate, "books" at "see") before anything else. For a church or
nonprofit that is the owner, an Admin or the accountant. `bookkeeping_close`
reaches the periods through the same function, so closing a church's books
follows.

Tests: `test_seat_access_routers.py` (a church refuses every seat below Admin
on all three, at read and at write; a business that is not a church keeps its
ladder; the wall sits before every other branch), `test_payroll_minister.py`.
