---
title: The server writes a church's reports in church words, and every footnote in plain words
date: 2026-11-03
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03: "change every tab under reporting" then "go and start" (step 3 of the plan: church words from the server)'
status: in review
prs: ["kmj-intake-server (this PR)", "solutionist-studio #1454 (the words on screen)", "kmj-intake-server #1701 (the reports read every row)"]
migrations: []
left_undone:
  - "Step 4: Budget by the church's expense lines, a Funds report in place of Profitability, Giving & income by fund and by way given, one person's giving in place of the statement (the statement's activity still says Invoice issued)"
  - "Step 5: the walkthrough with Kevin, then a second What's New entry"
decisions:
  - "report_words.py is the server half of the screen's reportWords.ts: voice_of (vertical ministry is a church; vertical_family nonprofit-like is a nonprofit; else business, unchanged)"
  - "Account names a church reads (display only, codes unchanged so an accountant's import still matches): 4000 Contributions, 4100 Store & product sales, 1150 Online gifts on the way (Stripe clearing), 1160 Gifts to deposit, 3000 Opening balance (net assets), 3100 Unsorted deposits (net assets), 3200 Unsorted withdrawals (net assets), 3900 Net assets (prior years); 5000-5900 by the church's own line names (a renamed line keeps its name; one still on a standard name reads as the church's). Love City's books use 3100 for 101 unsorted deposits, 4000 for 719 gifts"
  - "Applied in the trial balance and general ledger (_account_meta), Giving & income and Spending by account, and the 990 packet"
  - "The journal reads Gift recorded / Gift received / Charge paid (one read of the page's invoices for is_gift), Paid from the bank, Deposit not sorted yet and the like for a church"
  - "Exports: a church's CSV and PDF rows and titles for Income & spending, Cash in and out, and What the church has and owes"
  - "Review: the year-end accountant ZIP reads in the church's words too (titles, CSV and PDF rows); its IIF keeps the chart's stored names because QuickBooks matches accounts by name. A failed gift lookup in the journal reads neutral (Payment received, Recorded), never Invoice, and logs"
  - "Every voice: the build-note footnotes are plain words (balance sheet, cash flow x2, forecast method, trust, givers, the 990 notes, bank reconciliation), and the PDF balance sheet no longer says Contact support"
related: [2026-11-03-reports-read-every-row.md]
---
`report_words.py` (new), `gl_reports.py`, `gl_reports_t2.py`, `gl_reports_t3.py`, `gl_reports_t4.py`,
`reports_engine.py`, `reports_router.py`, `pdf_reports.py`, `__tests__/test_report_words.py`.
