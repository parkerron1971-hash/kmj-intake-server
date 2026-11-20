---
title: Giving tick follow-up before the switch goes on. Ids in one spelling, lowering with the switch off, tables_ready not yes for good, the bank tick on bank reads, Work to send, payroll checked, old gift thank-you events
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: "Giving tick, the follow-up before the switch goes on (backend, one PR): the seven fixes the reviews of #1931, #1933 and #1940 left before CHURCH_MONEY_TICKS can go on for any church."
status: waiting on Kevin
prs: [kmj-intake-server#1987]
migrations: [supabase/APPLY-2026-11-20-gift-thankyou-events.sql (NOT applied)]
left_undone:
  - "NOT APPLIED: supabase/APPLY-2026-11-20-gift-thankyou-events.sql. Kevin runs its Check before block, then the file, then Check after, before the switch goes on. Its rollback puts old givers' names back in the books' class: only with the switch off."
  - "The PR waits for an independent security review before merge; CHURCH_MONEY_TICKS stays unset (off)."
  - "Not changed, for Kevin to rule: the books' reports that are built from the bank stay with the books part, as the 2026-11-18 table opened them to any tick: /reports/balance-sheet (cash is the latest bank balance), cash-flow, cash-forecast, the P&L's bank lines, the general ledger and journal lines posted from bank rows, and /gl/verify (a Manager seat with Work) showing the bank's total balance beside the ledger's cash and up to 20 bank transaction ids that aren't in dollars."
  - "Outside the sweep's list (giving_services, bank_*, church_*, gl_*) and not checked for the bank tick: bookkeeping_close, bookkeeping_overview, funds, bill_payments, housing_allowance, room_card, expense_categories, plaid_reconciliation, setup_plan."
  - "The trust doors take the bank part only, not the Giving keeper as /reports/bank-reconciliation does (_bank_wall): adding the keeper would change who gets in with the switch off."
decisions:
  - "Every hook filters by the id in its one spelling (church_money_holders._id: uuid.UUID after a check that the text is a spelling Postgres reads). An id that isn't a uuid is refused (False: the sheet's save stops with a 503, a revoke counts it in failed), never read as no id. A seat id given that isn't one never drops the seat filter."
  - "seat_gone, seat_lowered_to_viewer and role_lowered run whatever CHURCH_MONEY_TICKS says, whenever the tables are there. Giving stays behind the switch."
  - "tables_ready keeps a yes ten minutes, a no five. A read of either table, or the probe after a hook's write fails, that PostgREST answers 404, PGRST205 or 42P01 flips it to no at once. With the tables gone the hooks return True. A probe that fails any other way (a timeout) is 'couldn't tell': not kept, and the hook returns False, so a lowering is never skipped on a guess."
  - "The bank part (require_money(.., 'see', 'bank'), refusal words church_money_gate.BANK_403) on: the Zelle senders (GET /giving/{id}/counts/{count}/bank), recording a gift from a bank row (POST .../gifts with a bank_ref: the whole press is refused), /gl/trust-status, /reports/trust-reconciliation and its export."
  - "POST /reports/accountant/send and /reports/customer-statement/send ask require_ministry_finance(.., need='work') before anything is built or sent."
  - "Payroll and contractors: every route reaches require_pay_records (a scan test holds it); nothing to fix."
  - "The SQL marks each moved event (data.retyped_from) so its rollback moves back exactly those rows, never a gift thank-you the code wrote as giving since #1940."
related: [2026-11-18-church-money-ticks-server.md, 2026-11-18-church-money-holders.md, 2026-11-18-one-money-gate.md, 2026-11-19-payroll-free-version.md]
---
Before building, both repos' work logs were read: the giving tick's server
piece (11-18), the holders tables (11-18), the one money gate (11-18) and
payroll's free version (11-19) are the work this finishes; nothing else had
started these fixes.

What changed: `church_money_holders.py` (ids in one spelling; the tables'
readiness, flipped by its reads), `church_money_ticks.py` (the hooks, the
probe), `giving_services.py`, `gl_router.py`, `reports_router.py` (the bank
part, Work to send), `church_money_gate.py` (BANK_403), and
`supabase/APPLY-` / `ROLLBACK-2026-11-20-gift-thankyou-events.sql` with
`__tests__/gift_thankyou_events_db.mjs` (PGlite, in CI's database checks).

Tests: `__tests__/test_church_money_ticks_follow_up.py` (new), three tests in
`test_church_money_ticks.py` brought up to the new rules (off now lowers; a
non-uuid id is refused; a missing table is what PostgREST says),
`test_giving_services.py`'s fixture stands in for the bank part as it does
for the giving gate.
