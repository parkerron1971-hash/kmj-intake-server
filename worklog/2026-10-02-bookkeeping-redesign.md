---
title: Bookkeeping redesign (Overview, review queue, money_kind) and the ledger that stopped posting
date: 2026-10-02
agent: Claude Code (Claude Opus 5.5)
asked: '"look at the bookkeeping tab ... redesign of layout ui design ... top tier and easy navigation" / "Yes start building" / "Go ahead"'
status: in progress
prs: [kmj-intake-server#1182, kmj-intake-server#1183, kmj-intake-server#1184, kmj-intake-server#1190, kmj-intake-server#1193, kmj-intake-server#1201, kmj-intake-server#1203, solutionist-studio#1088, solutionist-studio#1089, solutionist-studio#1095, solutionist-studio#1096, solutionist-studio#1098, solutionist-studio#1103]
migrations: [supabase/APPLY-2026-10-02-bank-money-kind.sql (pending, Kevin applies), supabase/APPLY-2026-10-02-close-checklist.sql (pending, Kevin applies)]
left_undone: ["Phone categorize queue", "KMJ's doubled accounts: Kevin clicks Take the old copy out in Settings → Connections (or runs ~/bkfix.py --apply)", "A deposit matched to a Stripe payout still counts as needing a category (bank_money.needs_category + the SQL filter); its own PR"]
decisions: ["design canvas first: https://claude.ai/artifact/AA5xYBhnDGyE7UTio1tqGe", "money_kind (income/owner/transfer, NULL = automatic) is the practitioner's answer; bank_money.py is the one rule set for the ledger, reports, counts and Chief", "a transfer posts through 1050 Transfers in Transit", "the overview is read-only and withholds claims about bank rows that didn't load", "close checklist answers (statements, looked over) are written only if accounting_periods.updated_at still matches what the merge read; three misses is a 409, never an overwrite", "saving close answers takes the same period_close plan gate as the lock", "a refused lock (checks open, no with_open) writes nothing, not even the period row"]
related: []
---
Kevin asked for a top-tier Bookkeeping tab. The canvas came first, then the
build.

Shipped so far:
- One room header and an Overview fed by GET /bookkeeping/overview (#1182,
  FE #1088/#1089).
- The GL queue: it had posted nothing for any business since the 2026-06-10
  deploy. A raw '+' timestamp in the claim URL was rejected and read as
  "nothing to do". Fixed in #1183; 252 rows posted overnight.
- "Uncategorized" means what its count means (#1184).
- money_kind (#1190), so deposits can be answered and transfer pairs
  confirmed. It needs the migration above.
- The review queue in Transactions (FE).
- Reports library and Settings (FE #1096/#1098); the in-app fix for a
  bank linked twice (#1193).
- Close the month: GET /bookkeeping/close (bookkeeping_close.py), six
  checks per month, statement balances and "looked over" kept on
  accounting_periods.close_checklist (migration above). The lock goes
  through the same close as Settings → Months, and close/reopen now fail
  loudly when their write is rejected.

Before building more here, read the canvas and this file. The remaining
slices are listed under left_undone.

Close the month follow-up (#1203, after review): two saves at once can't
drop one (conditional updated_at write, re-read and re-merge, 409 after
three tries), a refused lock writes nothing, answers take the plan gate,
and the failure paths (rejected write 502, unread rows 503, two-signature
close) have tests.
