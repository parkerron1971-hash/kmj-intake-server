---
title: Giving as its own tick, the database half. Two server-only tables, a tick the money wall reads, and browser writes that take their own guard. With no holder one thing changes, a blind write that used to reach hidden money rows
date: 2026-11-18
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-18, on giving as its own tick on a person''s sheet: "yes build with C" (a holder asks, the owner taps yes). This is piece 2 of 7 of step three of One sheet per person: the migration, its rollback and the closed reads. No door on the server decides by the tick yet.'
status: waiting on Kevin
prs: []
migrations: [supabase/APPLY-2026-11-18-church-money-holders.sql]
left_undone:
  - "Not pushed: local commits on the branch church-money-holders, for the parent session to open as a PR."
  - "NOT APPLIED. Kevin runs supabase/APPLY-2026-11-18-church-money-holders.sql in the SQL editor (his word on 2026-11-18 was for the drafts table only). Run the file's 'Check before applying' block first (Q1 to Q7, read-only, expected answers beside each); apply with zero holders; the Check block at the foot says what to read back."
  - "NO DOOR ON THE SERVER DECIDES BY THE TICK. church_money_holders.money_holder and open_ask exist and are closed, and no route calls them. But the tick is live in the database the moment a row exists: every read and write the app makes with the person's own login (PostgREST, and server paths that run with the user's token) goes through these policies. The next PR adds the tick to church_money_gate behind the switch CHURCH_MONEY_TICKS, the sheet's money block, and the asks."
  - "The server must take a tick away when a login is revoked (business_users_router.hand_back_login) and LOWER IT TO SEE WHEN A SEAT IS LOWERED TO VIEWER. The database stops a Work holder writing the moment the seat is a Viewer, but raised back to a Member they write again without the owner: nothing in a row records that a seat went down and up. Recording the seat's role at the grant would not see a round trip either; only a trigger on business_users (a table this file must not touch) or the server can."
  - "A See holder cannot mark a money alert read. The app marks alerts read with the person's own login (PATCH chief_notifications), and changing a money alert now takes Work. Their bell keeps the dot on an invoice-paid or gift alert until the next PR marks those read on the server."
  - "No INSERT policy on events or chief_notifications. Any working seat can still insert an event or alert of a money kind (it could before; a tick changes nothing there). Closing that is its own change: a refused insert is an error, not a skipped row, and the app inserts invoice_sent and invoice_paid events from the browser."
  - "business_expenses is open to the signed-out role in production today (business_expenses_all, allow-all TO public). This file neither widens nor closes it: no restrictive money policy, old or new, is consulted for anon. A separate change drops that policy."
  - "A tick the owner gave keeps working if businesses.owner_id ever changes (no route transfers a business today)."
  - "An Admin can change businesses.type from the browser, and a church that stops being a church is no longer walled at all (the 2026-09-29 guard's own old hazard, found by the review; not this file's to fix)."
  - "Lead means nothing more than Work in the database. What Lead adds is the server's to say."
  - "stripe_payments_router (charges and refunds) and the payout doors are not in the database's wall at all: they are server routes on seat ladders, for the payouts-and-refunds piece."
  - "NOT VERIFIED IN PRODUCTION: the function body hashes (Q2), every caller of the wall (Q3), owners (Q4), column types (Q5) and double seats (Q6). The 14 restrictive policies and the permissive ones on bills and business_expenses were read from production on 2026-11-18 and the fixture mirrors them; the third and fourth permissive policies on the two bank tables are a guess."
  - "The database test takes about three minutes; it is the largest of CI's database checks."
decisions:
  - "THE OLD NAMES STAY NARROW. ministry_finance_access is not touched. The tick is read by five functions: two replaced bodies (ministry_finance_guard, its 2026-09-29 text plus one clause; ministry_giving_access) and three new ones. So running the 2026-09-29 file, the 2026-10-27 file or its rollback again can only take the tick's reach away. The first build widened ministry_finance_access itself, and the independent review showed a re-run of the 2026-10-27 file then let a See-only holder read who gave."
  - "NOTHING EXISTING IS DROPPED, AND NO EXISTING POLICY IS CHANGED. Restrictive policies AND together, so adding restrictive write policies beside the untouched FOR ALL one splits reading from writing with no drop."
  - "ONE DELIBERATE NARROWING AT ZERO HOLDERS. The review found that a See tick let a Member or Manager seat edit and delete money rows in events and chief_notifications (the policies that hide them are SELECT-only, and both tables are tenant_writer_write's), and that even today, with no holder, an unfiltered `delete from events` by a Member takes the hidden money rows with the rest. Four restrictive UPDATE and DELETE policies close both. Everyone who can see such a row today passes its write rule today, so the only change before a tick exists is to an unfiltered write by a login that cannot see the row."
  - "ministry_giving_access is replaced only while church_giving_open exists, and church_money_giving_write asks for it by name at run time: after the 2026-10-27 rollback both files still run, and a write on a giving row is not an error."
  - "A new column the plan did not have: church_money_holders.seat_id. The tick counts only while that business_users row is the person's active seat. A login taken off the team and invited again gets a new row, so an old tick never comes back with it."
  - "Work never on a Viewer seat, in the tick itself. On business_expenses that is what holds: its allow-all policy hands a Viewer the permissive half of a write."
  - "The business types are written four times in the file (the walled helper and the three guards, each in the 2026-09-29 guard's own shape: a nested call a row cost about a third more on the bank read). A test holds all four equal to the 2026-09-29 list, and the database test asks the three guards about fourteen spellings."
  - "church_money_grant, church_money_answer and church_money_ask are NOT security definer: only the service role may run them. grant and answer refuse anyone but businesses.owner_id before their first write; grant refuses an ask that is another person's or another church's. answer marks an ask that ran out as expired and says so; ask marks one first, so it does not hold the place of a new one (the one-open index cannot read the clock)."
  - "A missing table stops the file with nothing applied; it used to be skipped."
  - "Both tables are excluded from the export with a reason, like church_keepers and church_duty_holders."
  - "The server reads live in their own file, church_money_holders.py: the gate's table and its source scan stay as merged, and a test holds that nothing imports the reads yet."
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
caller, on their active seat only. `ministry_finance_guard` gains one clause,
"or any tick"; `ministry_giving_access` becomes "(the old three, or the
who-gave tick) and the Giving keeper". `ministry_finance_access` is not
touched. A browser write on any of the nine money tables now also takes
`ministry_finance_write_guard` (the old three, or a Work or Lead tick on a
seat that is not a Viewer); the two bank tables take
`ministry_finance_bank_guard`; changing or deleting a money event or a money
alert takes the write rule for its kind.

**Why the write guards.** `tenant_writer_write` (2026-07-31) lets every
Member, Manager and Admin seat write invoices, bills, expenses, bank
transactions, the customer ledger, events and alerts straight through
PostgREST. One restrictive policy, with one guard for reading and writing, was
all that stopped them on the money tables, and on events and alerts only a
SELECT policy did. Widening the read to a See tick would have handed a See
holder on a Manager seat every one of those writes. The database test drops
the write policies inside a transaction and watches exactly that happen, for a
bill and for a money event, then rolls back.

**With no holder, one thing changes.** The tick is `exists(... from
church_money_holders ...)`: with no rows it is false, each replaced function
reduces to its old body, and each policy added to the nine tables is the same
value as the one already there. The four policies on events and alerts are
the exception, on purpose: an unfiltered write (`delete from events`, no WHERE
and no RETURNING) by a Member or Manager seat used to take the money rows
that login cannot see, because Postgres never consults a SELECT-only policy
for a statement that reads no column. Those rows are now skipped, and an
unfiltered update that would turn a row into a money row is refused.
`__tests__/church_money_holders_db.mjs` (in CI's database checks) runs every
select, insert, update, delete, upsert, RETURNING, FOR UPDATE and move on
every money table, the gift row, the events and the alerts as an owner, an
Admin, the accountant, a Manager, a Member, a Viewer, a stranger, a shop's own
people, the signed-out role and a login with no id, before the file and after
it run twice, and holds the list of differences to exactly those eighteen
leaves by name.

**With a holder.** See reads the books and writes nothing: not a bill, not a
money event, not a money alert, by id, by business or with no WHERE. Who gave
and the bank each take their own tick. Work writes. The Giving keeper still
locks the gifts and the giving events. A revoked seat holds nothing at once;
invited again, still nothing; a deleted seat row takes its tick with it. Only
`church_money_grant` and `church_money_answer` make a holder, and each refuses
anyone but the church's owner. The browser's roles can read neither table and
run none of the server's functions.

**An older file run again only narrows.** With three holders in place the test
runs the 2026-09-29 block, the 2026-10-27 file and the 2026-10-27 rollback,
each on a fresh database, and holds every person to less or the same at every
leaf; then runs this file again and gets exactly the holders back. After the
2026-10-27 rollback this file and its own rollback each still run twice. Each
of the three older files now says so at its top.

**Stopping it.** `delete from public.church_money_holders;` puts every answer
back to the applied file with no holder. The rollback removes the added
policies and functions and restores the two bodies from their own files (the
test compares all six function hashes to the repo's files); it brings the
unfiltered write back, leaves the tables and their rows, and applying again
brings each tick back.

**Where it was run.** PGlite (a real Postgres engine), three times over: with
everything the superuser's, and with every table and function owned by a role
that is not a superuser, with and without BYPASSRLS; Supabase's default
privileges on; RLS and the June hotfix's policies on the three business
tables; the permissive policies production has on bills and business_expenses,
the allow-all TO public included.

Cost, measured on PGlite at 4,000 rows (relative only): an Admin's count of
the bank feed 173 ms before, 256 ms after; a count of bills unchanged; an
update of 4,000 bills 226 ms before, 453 ms after; an update of 4,000 events
197 ms before, 308 ms after.
