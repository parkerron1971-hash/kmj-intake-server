---
title: The treasurer hears when a count closes and when someone asks to be paid back
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: "yes go with the plan and make those small fixes as well (the money tells on Love City's connection map)"
status: in progress
prs: [kmj-intake-server (this PR; merges after #2038)]
migrations: []
left_undone:
  - "Rides CHURCH_TELLS (owner by default: Love City only); switch on for every church on a Thursday with the rest of the tells"
decisions:
  - "A count is told when it closed in the last 3 days and at least one of its gifts that rides a bank deposit (not card gifts) isn't in a deposit match yet; a count with no such gifts is never told"
  - "A pay-back is told while it is new, made in the last 3 days, undecided, and has no yes yet; once someone says yes, church_money_levels.tell_next asks for the next yes, so it isn't told twice"
  - "Never told to the doer: whoever closed the count; the office login that filed a request; a member whose email is one of the church's logins (the owner's too)"
  - "A guard read that fails (matched? a yes already?) holds the item for the next sweep rather than tell something that may be done"
  - "No amount, receipt or 'what it was for' on a lock screen: the service and its day, or the asker's first name and the ministry"
related: [2026-11-21-church-tells.md, 2026-10-27-church-checks.md, 2026-10-28-church-money-levels.md, 2026-11-01-giving-services.md]
---
`church_tells_money.py` holds two finders for the `church_tells` sweep.
`count_closed` reads `giving_counts` (closed, `closed_at` in the last 3 days),
their gifts in `invoices` (`giving_count_id`) and `gift_deposit_items`, and
tells the `deposit` duty "Nov 22 count is closed". `payback_asked` reads
`church_check_requests` (new, undecided, last 3 days) and
`church_check_approvals`, and tells the `pay` duty "Grace asked to be paid
back". Tests: `__tests__/test_church_tells_money.py`.
