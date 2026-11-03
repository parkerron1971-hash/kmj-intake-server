---
title: The reports and the books read every row, not the first 1,000
date: 2026-11-03
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03: "make sure to change every tab under reporting and come with a game plan to update them" then "go and start" (step 1 of the plan: check the books first)'
status: in review
prs: ["kmj-intake-server (this PR)"]
migrations: []
left_undone:
  - "Many other server reads still ask for more than 1,000 rows in one read (celebrations, church_news, church_groups_office and others); a sweep to sb_get_all_as_service is its own change"
  - "account_lifecycle._fetch_table pages by offset ordered by business_id, which isn't a stable order; worth moving to the keyset helper"
  - "Steps 2 to 5 of the reports plan (church words, server labels, four reports, walkthrough)"
decisions:
  - "Cause, checked live: Love City has 3,401 journal entries and 6,802 ledger lines, and all of them add up to a $0.00 difference (11 accounts). The trial balance read 1,000 lines (PostgREST's max-rows), saw 2 accounts and said Out of balance. No source is posted twice, anywhere"
  - "sb_clients.sb_get_all_as_service: pages by a unique key (key > the last one seen), in key order, 1,000 a page. None when the first page fails (like a single read), PartialRead when a later page fails or at the 500,000-row ceiling: never a quietly short list"
  - "Moved to it: the ledger and journal reads behind every GL report, backfill's already-posted set, the divergence checker's business list (it read 1,000 of 2,972 active entries platform-wide), the backfill sources (gifts, bills, expenses, bank rows, orders, bookings), the period counts, the source-table reports (P&L, AR, AP, expenses), the 1099 bills and the accountant export"
  - "Backfill's already-posted read now raises on a failed read: an empty set there would have posted every source a second time"
related: []
---
`sb_clients.py` (sb_get_all_as_service, PartialRead), `gl_reports.py`, `gl_engine.py`,
`reports_engine.py`, `reports_router.py`, `accountant_export.py`,
`__tests__/test_reads_every_row.py` (a stand-in with the 1,000-row cap).
