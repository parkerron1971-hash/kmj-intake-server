---
title: Giving as its own tick, the database half. Two server-only tables, a tick the money wall reads, and browser writes that take their own guard. With no holder nothing changes
date: 2026-11-18
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-18, on giving as its own tick on a person''s sheet: "yes build with C" (a holder asks, the owner taps yes). This is piece 2 of 7 of step three of One sheet per person: the migration, its rollback and the closed reads. Nothing decides by the tick yet.'
status: waiting on Kevin
prs: []
migrations: [supabase/APPLY-2026-11-18-church-money-holders.sql]
left_undone:
  - "Not pushed: local commits on the branch church-money-holders, for the parent session to open as a PR after an independent review."
  - "NOT APPLIED. Kevin runs supabase/APPLY-2026-11-18-church-money-holders.sql in the SQL editor (his word on 2026-11-18 was for the drafts table only). Apply with zero holders; the Check block at the foot of the file says what to read back."
  - "NOTHING ON THE SERVER READS THE TICK. church_money_holders.money_holder and open_ask exist and are closed, and no door calls them. The next PR adds the tick as one more standing in church_money_gate behind the switch CHURCH_MONEY_TICKS, the sheet's money block, and the asks."
  - "The server must still take a tick away when a login is revoked (business_users_router.hand_back_login). The database already ignores it (the tick counts only on the active seat it was given to, and a login invited again is a new seat), but the row should not linger."
  - "An ask that ran out keeps status asked until the server marks it expired: church_money_answer refuses it, open_ask does not show it, and the one-open-ask index holds its place until then. The next PR sweeps them."
  - "Lead means nothing more than Work in the database. What Lead adds is the server's to say."
  - "stripe_payments_router (charges and refunds) and the payout doors are not in the database's wall at all: they are server routes on seat ladders, for the payouts-and-refunds piece."
  - "NOT VERIFIED: production's own catalog. The file was run on PGlite (a real Postgres engine) over the repo's copies of the 2026-07-31, 2026-09-29 and 2026-10-27 files. If production carries a policy or function on these tables that no file in the repo made, this did not see it. The Check block's policy counts (9, 9, 9, 9, 2, 2, 1) would show a difference."
decisions:
  - "NOTHING EXISTING IS DROPPED OR CHANGED BUT TWO FUNCTION BODIES. The plan said to split ministry_financial_privacy and gift_row_privacy into a select policy and a write policy. Restrictive policies AND together, so adding three restrictive write policies beside the untouched FOR ALL one gives the same split with no drop: a write must pass the old guard AND the write guard. The rollback is then only removals."
  - "gift_row_privacy needed no split. A gift row is an invoices row, so a browser write on it already takes the write guard (Work) AND gift_row_privacy (who gave, and the Giving keeper)."
  - "ministry_giving_access is rebuilt on the base, not on ministry_finance_access. It was `ministry_finance_access AND church_giving_open`; left alone, widening the access would have shown every holder who gave."
  - "A new column the plan did not have: church_money_holders.seat_id. The tick counts only while that business_users row is the person's active seat. A login taken off the team and invited again gets a new row (business_users_router.make_invite_row), so an old tick never comes back with it, and no clock is compared. Deleting the seat row deletes the tick."
  - "Work never on a Viewer seat, in the tick itself, not only through tenant_writer_write: the write guard says no to a Work row on a Viewer seat."
  - "The two new guards carry the not-walled branch (a shop's seats keep writing their own invoices). The business types are written once in the new file (ministry_finance_walled); a test holds that list equal to the one ministry_finance_guard carries in the 2026-09-29 file, and the database test asks all three guards about fourteen spellings."
  - "The bank takes its own restrictive policy (church_money_bank) on plaid_transactions and plaid_accounts: without it a See holder would read the bank through the widened guard."
  - "church_money_grant and church_money_answer are NOT security definer. Only the service role may run them, and it reads and writes these tables itself; a role handed EXECUTE by mistake still could not touch a row. Each refuses anyone but businesses.owner_id before its first write."
  - "church_money_grant takes a seventh, optional argument (the ask it answers) and a null level takes the tick away. It refuses a business that is not a church or nonprofit, a person with no active seat, the owner, and Work or Lead for a Viewer."
  - "church_money_asks has reminded_at for the 48-hour reminder Kevin agreed to, so that reminder needs no later migration."
  - "Both tables are excluded from the export with a reason (sign-in user ids and a seat row that mean nothing in another business), like church_keepers and church_duty_holders. They go with the business by cascade."
  - "The server reads live in their own file, church_money_holders.py, not in church_money_gate.py: the gate's table and its source scan stay exactly as merged, and a test holds that nothing imports the reads yet."
related: [2026-11-18-one-money-gate.md, 2026-11-18-sheet-login-level.md]
---
The money rows opened for three kinds of person: the owner, an active Admin
seat, the outside accountant (`ministry_finance_access`, 2026-09-29). Love
City's treasurer could only be let in by making her an Admin, which opens the
whole church. This is the database's half of a fourth kind: an office login
the owner has ticked.

**What the file adds.** `church_money_holders` (one row a login a church:
`level` see, work or lead; `who_gave`; `bank`; the seat it was given to) and
`church_money_asks` (a request waiting for the owner; seven days; never for
yourself; one open a login). `church_money_tick(b, part)` answers for the
caller, on their active seat only. `ministry_finance_access` becomes "the old
three, or any tick"; `ministry_giving_access` becomes "(the old three, or the
who-gave tick) and the Giving keeper". A browser write on any of the nine
money tables now also takes `ministry_finance_write_guard` (the old three, or
a Work or Lead tick on a seat that is not a Viewer), and the two bank tables
take `ministry_finance_bank_guard`.

**Why the write guard.** `tenant_writer_write` (2026-07-31) lets every Member,
Manager and Admin seat write invoices, bills, expenses, bank transactions and
the customer ledger straight through PostgREST. One restrictive policy, with
one guard for reading and writing, was all that stopped them. Widening that
guard to a See tick would have handed a See holder on a Manager seat every one
of those writes. The database test drops the three write policies inside a
transaction and watches exactly that happen, then rolls back.

**With no holder nothing changes.** The tick is `exists(... from
church_money_holders ...)`: with no rows it is false, each replaced function
reduces to its old body, and each added policy is the same value as the one
already there. `__tests__/church_money_holders_db.mjs` (209 checks, in CI's
database checks) runs every select, insert, update and delete on every money
table, the gift row, the giving events and the gift alerts as an owner, an
Admin, the accountant, a Manager, a Member, a Viewer, a stranger and a shop's
own people, before the file and after it run twice, and compares the lot.

**With a holder.** See reads the books and writes nothing. Who gave and the
bank each take their own tick. Work writes. The Giving keeper still locks the
gifts. A revoked seat holds nothing at once; invited again, still nothing; a
deleted seat row takes its tick with it. Only `church_money_grant` and
`church_money_answer` make a holder, and each refuses anyone but the church's
owner. The browser's roles can read neither table and run neither function.

**Stopping it.** `delete from public.church_money_holders;` puts every answer
back at once. `ROLLBACK-2026-11-18-church-money-holders.sql` removes the added
policies and functions and restores the two bodies from their own files (the
test compares them to those files word for word); it leaves the tables and
their rows, and applying again brings each tick back.

Checked: the database test above, and eight deliberate breaks of the migration
(giving on the widened access, a seat that need not be active, any seat row
instead of the one ticked, Work on a Viewer, the write guard on any tick, the
bank guard on any tick, a grant with no owner check, a Manager in the base),
each of which made it fail. `__tests__/test_church_money_holders.py` (61):
the file's shape, the copies, the rights, the rollback, and the closed reads.
