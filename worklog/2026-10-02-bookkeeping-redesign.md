---
title: Bookkeeping redesign (Overview, review queue, money_kind) and the ledger that stopped posting
date: 2026-10-02
agent: Claude Code (Claude Opus 5.5)
asked: '"look at the bookkeeping tab ... redesign of layout ui design ... top tier and easy navigation" / "Yes start building" / "Go ahead"'
status: in progress
prs: [kmj-intake-server#1182, kmj-intake-server#1183, kmj-intake-server#1184, kmj-intake-server#1190, solutionist-studio#1088, solutionist-studio#1089, solutionist-studio (review queue PR)]
migrations: [supabase/APPLY-2026-10-02-bank-money-kind.sql (pending, Kevin applies)]
left_undone: ["Close the month (Reconciliation + period close + bank recon as one checklist)", "Reports library grouped by question", "Settings: split Admin; move other businesses' GL cards to Mission Control; an in-app 'accounts linked twice' fix", "Phone categorize queue", "KMJ's doubled accounts: Kevin runs ~/bkfix.py --apply (the classifier blocked a production write)"]
decisions: ["design canvas first: https://claude.ai/artifact/AA5xYBhnDGyE7UTio1tqGe", "money_kind (income/owner/transfer, NULL = automatic) is the practitioner's answer; bank_money.py is the one rule set for the ledger, reports, counts and Chief", "a transfer posts through 1050 Transfers in Transit", "the overview is read-only and withholds claims about bank rows that didn't load"]
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

Before building more here, read the canvas and this file. The remaining
slices are listed under left_undone.
