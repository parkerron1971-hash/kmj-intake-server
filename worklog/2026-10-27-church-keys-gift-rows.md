---
title: Church areas, step 2, part 3 — the Giving keeper in the database (gift rows, giving alerts and the bank), and the gift amounts kept open
date: 2026-10-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-23: "if Pastor look at money another leader is notified and have to recieve a code from that person to get into money"; 2026-10-26: "go with your picks" (the lock binds the owner too; guarded at the start: giving names and bank) and "go ahead, you build step 2 after the media fixes"'
status: shipped (the SQL applied 2026-10-28 after solutionist-studio#1394 went live, and verified)
prs: ["kmj-intake-server#1624", "solutionist-studio#1394 (the app reads the amounts)"]
migrations: [supabase/APPLY-2026-10-27-church-keys-gift-rows.sql]
left_undone:
  - "Generic revenue cards (the status ribbon, the week card, Revenue) read invoices with the person's login, so for a locked owner they leave the gifts out, as they already do for a church's managers"
  - "Chief reads invoices with the person's login too, so a locked person's Chief no longer sees gift rows; its giving totals aren't given the amounts read yet"
  - "CHURCH_KEYS=off opens the server's doors but not this lock, which follows the keepers alone (remove the keepers or run the rollback)"
decisions:
  - "Why the database too: the server's doors read as the service role, but the app reads gift rows with the person's own login. The Bills page lists every invoice with its contact, so a gift showed its giver to an owner or admin the keeper hadn't let in"
  - "One rule, the server's: church_giving_open is false only while the church has an active Giving keeper (started, not ended) and this person neither keeps it nor holds an open key (status open, opens_until ahead), as church_keys.opened reads the same two tables. A change waiting its 7 days doesn't count; a keeper on the way out still does"
  - "No oracle: for someone who doesn't belong to the business it is a constant true (their own policies already refuse them), so the function tells a stranger nothing about another church's keepers"
  - "Behind it: gift rows (gift_row_privacy, with the relabel trigger), the giving events and the gift alerts (the bell), and the bank (a new restrictive church_giving_bank on plaid_transactions and plaid_accounts). Bills, other events and other alerts stay. Kids and Care notes need nothing here: those tables were never readable from the app"
  - "Totals stay open (the keeper guards the names, not the picture): GET /giving/{id}/amounts gives the finance roles (owner, admin, the outside accountant) each gift's date, amount, refund, fund and category, and whether it was recorded by hand, never the giver, the note or the number, and with no wall"
related: [2026-10-27-church-keys.md, 2026-10-27-church-key-doors-giving.md, 2026-10-27-church-key-doors-care.md]
---
Changes:
- `supabase/APPLY-2026-10-27-church-keys-gift-rows.sql` (new): `church_giving_open`, `ministry_giving_access`, and the policies above. Its rollback is `ROLLBACK-2026-10-27-church-keys-gift-rows.sql`.
- `giving_router.py`: `GET /giving/{business_id}/amounts?year=`.
- Tests:
  - `__tests__/church_keys_gift_rows_db.mjs` (new, on PGlite, in CI): 46 checks over the 2026-09-29 rule, taken from its own file.
  - `__tests__/test_church_key_doors.py`: the amounts read, and a failed read is a 503.
- `docs/MIGRATIONS.md`: the ledger row.
- The two door worklogs are marked shipped (#1621, #1622).

Checked:
- Each deliberate break failed a test:
  - the gift policy without the keeper;
  - a key that never ends;
  - the relabel trigger without the keeper;
  - the amounts carrying the giver;
  - the amounts behind the wall.
