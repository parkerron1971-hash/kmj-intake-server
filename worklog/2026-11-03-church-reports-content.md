---
title: The reports a church needs, on the server - Funds, gifts by fund and way, one person's giving, the budget in its lines
date: 2026-11-03
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03: step 4 of the reports plan, and on the Funds report "go wth a" (match a giving fund to the year fund of the same name)'
status: in review
prs: ["kmj-intake-server (this PR)", "solutionist-studio (the screens, next)"]
migrations: []
left_undone:
  - "The screens: the Funds report, One person's giving, the two new Giving & income sections (front end PR)"
  - "A line a church added (like Missions) has no budget of its own: business_budgets.category allows only the six built-ins, so it counts in the line it sits under"
decisions:
  - "giving_reports.py. Funds: every configured giving fund plus any fund on a gift, given = the period's net gifts to it; spent = bank payments placed (out) on the year fund whose name matches (Youth = Youth Fund = youth, the word Fund and case ignored), left = given - spent. Year funds no giving fund matches are listed apart with what was spent. Year funds switched off: given only"
  - "A gift with no fund is the general fund; designated per giving_router.is_designated (tithes and offerings are general)"
  - "Giving & income for a church or nonprofit adds by_fund and by_way (giving_ways.method_label: Online, Cash, Check, Cash App...). Totals without names, so outside the Giving lock like the other totals"
  - "GET /reports/funds, /reports/givers?year, /reports/giver-history?contact_id&year: the Givers gates (require_finance, _owner_or_reader, the Giving & money keeper). A failed Funds-tab read is a 503, never no spending"
  - "Budget for a church or nonprofit: rows in its own line names (report_words.line_names, shared with the account names), income as Giving & income; no Profit First amounts made up from a business allocator. A business is unchanged"
  - "Funds exports as CSV and PDF (its own PDF table); the Giving & income PDF gains the two gift tables and church headings"
related: [2026-11-03-reports-church-labels.md, 2026-10-31-funds-for-the-year.md]
---
`giving_reports.py` (new), `reports_router.py` (three routes, revenue by fund and way, the Funds export),
`gl_reports_t3.py` (budget), `report_words.py` (line_names), `pdf_reports.py`, `__tests__/test_giving_reports.py`.
