---
title: Church areas, step 2 — the Giving doors (who gave what, the bank and payouts need the keeper's key)
date: 2026-10-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-23: "if Pastor look at money another leader is notified and have to recieve a code from that person to get into money"; 2026-10-26: "go with your picks" (the lock binds the owner too; guarded at the start: giving names and bank, kids medical notes, pastors-only notes) and "go ahead, you build step 2 after the media fixes"'
status: in progress
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "The Kids and Care doors (the next server PR): medical and custody notes in kids_router and kids_checkin; pastors-only notes on the follow-up board and private_care's see-everything branch"
  - "The app: until Ask for a key lands, a locked page shows the server's message (Giving & money is locked. Ask its keeper for a key)"
  - "Chief's other reads and KAI's reads aren't behind the lock yet; only Chief's statement actions are"
  - "The database lock on the giving rows the app reads directly (invoices gift rows through ministry_finance_access)"
  - "Approval levels for money the system sends (contractor payments) and for money paid outside it"
decisions:
  - "Behind the Giving keeper, the owner and admins too: the gift records (read, record, correct), the mailed statements, Chief's statements, the donor report and its export, the giver list, a giver's statement (screen, export and email), the bank reconciliation and its export, the Stripe pages (charges, customers, refunds, payouts), and every bank read and write (plaid_router's two gates)"
  - "The books overview, review and month close read the bank feed through plaid_router's gates, so a church with a Giving keeper finds them behind the lock too"
  - "Totals stay open: the P&L, balance sheet, budgets, general ledger, 990 prep, the Reports pack and campaign totals. Revenue and profitability keep their totals and leave out the per-giver rows (givers_locked: true)"
  - "The church's outside accountant (a collaborator, no seat) sees who gave what, so the lock holds them too. They see Giving's keys, ask for Giving's key, are named to the keepers by their invited email and hear the answer by email; they never answer an ask and are never a keeper"
  - "Keepers can only be named at a church (404 anywhere else), so no other business ever has a lock. The lock never asks a business's type, because a church can change its own type to slip its keeper: each door reads the keepers (one indexed read, for every business), and a failed read is a 503, never an open door"
related: [2026-10-27-church-keys.md, 2026-10-23-church-areas-map.md]
---
- `church_keys.py`:
  - the outside accountant asks, sees Giving's keys and enters the code (`_member(..., accountant=True)`);
  - `_people` names and emails them;
  - `put_keeper` is church-only.
- The doors call `church_keys.wall` at the route or the route's gate:
  - `giving_router.py` (gift records);
  - `giving_statement_mail.py`;
  - `chief_giving_actions._authorize`;
  - `reports_router.py` (`_giving_wall`, plus `_givers_hidden` for revenue and profitability);
  - `stripe_data_proxy._require_owner_with_acct`;
  - `plaid_router._require_owner` / `_require_reader`.
- No shared reader is touched, so `church_my_week` and the Reports pack read as before.

Checks:
- `__tests__/test_church_key_doors.py`: 53 tests.
  - Every door refuses the pastor, an admin and the owner, with nothing written or sent first.
  - The keeper gets in, and so does a key for its hour.
  - Givers are left out of revenue and profitability.
  - With no keeper there's no lock, and another business is never locked.
  - A failed keepers read is a 503.
  - The accountant path is covered, and a church that changes its type stays locked.
- I removed each lock and accountant rule on purpose, and the tests caught all 31.
- The 55 suites that touch these modules pass (1,017 tests), including the access ratchet, giving, statements, the bank, Stripe and the books.
