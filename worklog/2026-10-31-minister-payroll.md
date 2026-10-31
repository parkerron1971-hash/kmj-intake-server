---
title: A minister in Pay your team (no FICA/FUTA, the housing part of each check, logged when paid)
date: 2026-10-31
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-31, on his housing allowance: "right now i am not recieving and payment through the system not to say it''s something in the future i want accounted for."'
status: in review
prs: [kmj-intake-server#1656, solutionist-studio#1418]
migrations: [supabase/APPLY-2026-10-31-minister-payroll.sql (applied 2026-10-31, verified)]
left_undone:
  - "The Pay your team screens (solutionist-studio): the owner's Minister switch and housing part on a person, the housing part on a draft line, and what mark-paid logged or couldn't (the API is here; the screens don't show it yet)"
  - "W-2s: nothing here makes a W-2 yet. When one does, Box 1 leaves out a minister's housing part and Box 14 shows it; Boxes 3-6 stay empty for a minister"
  - "A church's other staff: a 501(c)(3) owes no FUTA on anyone (IRC 3306(c)(8)); payroll_calc still charges it for non-ministers. Not changed here: a business doesn't record that it is a 501(c)(3)"
decisions:
  - "Minister = no Social Security, Medicare or FUTA, either half (IRC 3121(b)(8), 3306(c)(8)). Federal income tax stays typed in (0 unless they asked for withholding), so a line still needs it before approval"
  - "The minister setting, the per-check housing part and a line's housing part are the owner's alone (they change how pay is taxed); managers keep every other edit"
  - "Only a minister's line carries housing_allowance, never more than the check; everyone else's line is unchanged, so runs save before the migration"
  - "Marking a run paid logs each housing part to the minister's record for that year (linked by employee, else the one unlinked record whose name holds theirs word for word), source pay_run + the line id, so a retry counts once. It never fails the paid run (a failed read says so: failed on mark-paid, 503 on the retry); POST /payroll/runs/{id}/log-housing (owner) tries again"
  - "A line whose person is no longer a minister drops its housing part on the next recompute"
  - "An admin who marks a run paid writes its housing lines into the owner-only record, and sees only the names and amounts already on the run; costs and fair rental value stay the owner's"
  - "A run paying housing allowance with no designation on record gets a housing_notes line: the board designates it before it's paid, or the part is taxable"
  - "housing_allowance.NAV now names bkTab housing, so Chief's receipts open the screen (solutionist-studio#1418)"
related: [2026-10-30-housing-allowance.md]
---
`payroll_calc.statutory(..., minister=)` and `compute_item(..., housing_allowance=)`;
`run_totals` adds `housing_allowance`. `payroll_router`: `minister` and
`housing_allowance_per_period` on employees (owner only), `housing_allowance`
on a draft line (owner only, minister only, at most the gross), `housing_notes`
on a run, the housing log on mark-paid, and `POST /runs/{id}/log-housing`.
Tests: `__tests__/test_payroll_minister.py`.
