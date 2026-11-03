---
title: Trends PDF and CSV name each month, read in a church's words, and say which twelve months
date: 2026-11-03
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03: "yes fix the pdf too" (after the screen got named months, FE #1459)'
status: in review
prs: ["kmj-intake-server (this PR)", "solutionist-studio #1459 (the screen, merged)"]
migrations: []
left_undone:
  - "Trends is still the last 12 months only; there's no This year choice (gl_reports_t3.trends takes no period)"
decisions:
  - "PDF: months by name with their year (Dec 2025), the month still going marked (so far), a 12-month total, the section heading carries the range, and momentum names its months (Aug–Oct vs May–Jul) in words (up 22.5%; Helvetica has no arrows)"
  - "PDF header: Last 12 months: Dec 2025 – Nov 2026 (as of Nov 3, 2026), in place of As of 2026-11-03"
  - "The columns were Revenue / Expenses / Net for everyone; a church reads Giving & income / Spending / Left over (a nonprofit: Contributions & income), via new report_words rows money_in / money_out / left_over. A business reads what it did"
  - "CSV: the same month names and column words; no total row (a spreadsheet sums its own, and a total would double-count)"
  - "report_words.month_label / day_label / month_span carry the month words; anything that isn't a month comes back as it was"
related: [2026-11-03-reports-church-labels.md]
---
`report_words.py`, `pdf_reports.py` (`_trends_body`, `_x`, `_change`), `reports_router.py` (`_period_label`, `_csv_rows`),
`__tests__/test_trends_exports.py` (sample numbers only).
