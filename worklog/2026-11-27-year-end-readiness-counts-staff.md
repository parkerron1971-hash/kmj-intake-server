---
title: The year-end readiness check counts staff not paid yet, flags a housing allowance kept only on Bookkeeping, and the Form 4361 wording (M-6 step 2)
date: 2026-11-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, via KAI, 2026-11-27 (mission M-6 step 2): "an honest year-end check that counts active staff; the self-employment tax wording fixed for Form 4361."'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Nothing in the app changes: Quarters and year-end already counts whatever the server marks not ready."
  - "The minister setup on the employee form (so the pastor is paid as a minister and the Housing record links to them) is its own M-6 step 2 PR; until then this check is what tells a church its W-2 won't carry the housing allowance."
decisions:
  - "payroll_forms.year's readiness read only people with paid lines, so a church that had added staff but not run payroll saw 'Ready for February 1, 6 of 6, everything the W-2s need is here' with no W-4, address or Social Security number on file (Love City, 2026-11-27 review). Now active employees with no line in the year count too: for this year or a later one, hired by the year's end (no start date counts). They get no W-2 row (no pay); their missing W-4, address or SSN shows on the readiness lines. An earlier year is unchanged."
  - "No one on staff reads 'No one on staff yet', not 'W-4s on file for all 0 people'."
  - "When no line in the year was paid as a minister's but the year's housing allowance records (housing_allowance.list_allowances, switched on) name a minister, the housing line is not ready: 'Bookkeeping, Housing has a {yr} housing allowance for X, but no pay run here pays them as a minister, so no W-2 from here will show it', with the fix (mark them a minister and pay through pay runs, or the accountant prepares their W-2 with Box 14). It used to say 'No minister's pay this year, so no housing designation is needed'. A records read that fails raises HousingUnreadable (the door's 503), never 'nothing needed'."
  - "housing_allowance.CARE (the Housing page's footer and Chief's housing receipts) and the matching Chief prompt line now say the allowance is still counted for self-employment tax 'unless the minister has an approved Form 4361': the page said both 'exempt (Form 4361)' and 'still counted' before."
related: [2026-11-19-payroll-free-version.md, 2026-11-27-contractor-payouts-explicit-list.md]
---
`payroll_forms.py` (`_unpaid_staff`, `_housing_without_pay`, the readiness
lines), `housing_allowance.CARE`, `chief_prompt.py` (one line). Tests:
`__tests__/test_payroll_forms.py` gains six (staff not paid yet counted, then
ready once on file with the count; an earlier year, a later hire and someone
no longer on staff left out; no one on staff; a housing allowance kept
elsewhere flagged; no records still reads as nothing needed; an unreadable
read is never nothing needed). Rehearsed: turning either rule off turns its
tests red. Ran the payroll, housing and Chief prompt shape suites: 219 passed.
