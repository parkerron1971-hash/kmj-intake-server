---
title: A housing allowance keeps its paper trail, and allowance paid before the board's vote is taxable
date: 2026-10-31
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-31, on what he and Love City need on paper for his housing allowance (the board votes first and in writing, he steps out of the vote, ordained / licensed / commissioned, self-employment tax, receipts and the rental value, the W-2): "fix the three and these things you talked about ... add these structure and rules in there as well"'
status: in review
prs: [kmj-intake-server (this PR), solutionist-studio (the screen)]
migrations: [supabase/APPLY-2026-10-31-housing-paper-trail.sql (applied 2026-10-31, verified: 11 columns)]
left_undone:
  - "A year-end statement (PDF) with the figures and the paper trail for the preparer"
  - "Reminders that reach the owner outside the screen (the bell, a text) before each quarterly estimate"
  - "Linking a pay run's minister_credential (payroll, #1658) to the allowance's: the two are typed separately today"
decisions:
  - "Allowance paid before the board's vote isn't housing allowance (Treas. Reg. 1.107-1(b): designated in advance of payment). figures() leaves it out of the paid limit and of Box 14 and counts it taxable; paid_before_designation says how much, and the paper trail warns with the amount and says it's Box 1. Housing COSTS before the vote are left as they are: the rule the regulation states is about payments"
  - "The paper trail is eight steps: board_vote, in_advance, independent, credential, se_tax, fair_rental, receipts, w2, each done / todo / warn / later, with plain words. Kevin's six items map onto them; the minister voting on their own allowance is a warning, not a gap"
  - "Owner-confirmed facts are stored as fields, never guessed: minister_recused, comparables_note, minister_credential, credential_detail, se_tax_plan, cash_salary, fair_rental_basis, receipts_kept_where, w2_checked_on"
  - "Self-employment tax: an estimate only once cash_salary is given: 92.35% of salary plus the allowance (designated, or paid if more), 12.4% up to the year's wage base (payroll_calc) plus 2.9%. Called 'about': no deduction for half of it, expenses or the 0.9% over $200,000. The next 1040-ES date skips weekends, Martin Luther King Day and DC Emancipation Day, the way the IRS moves them (pinned against 2022 and 2023's real dates)"
  - "Receipts: a photo or PDF on a housing cost (not on allowance paid), stored with church_checks' receipt handling (photo re-saved upright as JPEG, location tags dropped) in the private business-documents bucket under housing-receipts/, served only to the owner, never as a link. church_checks never serves a path outside its own folder, so the treasurer's screens can't reach these. Removing an entry, or replacing a receipt, deletes the old file"
  - "figures() also gives paid_since_designation (the paid limit), so the screen reads it rather than subtracting. When Chief logs allowance paid before the vote, its reply says it is taxable salary (W-2 Box 1) and counts only what was paid since the vote (review bot)"
  - "Chief: the status lookup ends each record with what's left on the paper trail; set_housing_allowance takes the trail fields (only as the owner says them), and with no name changes the year's only allowance"
related: [2026-10-30-housing-allowance.md, 2026-10-31-minister-payroll.md, 2026-10-31-church-payroll-rules.md]
---
`housing_allowance.paper_trail`, `open_steps`, `se_tax_estimate`,
`estimate_dates`, `next_estimate`, `attach_receipt`, `read_receipt`;
`POST/GET /housing-allowance/entries/{id}/receipt`. Tests:
`__tests__/test_housing_allowance.py` (ten new).
