---
title: A church's accountant reads payroll and contractors on the server (reads only) (M-6, review M1)
date: 2026-11-27
agent: Claude Code (Claude Opus 5.5)
asked: 'KAI, 2026-11-27, from the account-2 review of M-6 (M1): "Write a new backend PR so payroll_router._access lets the accountant through on viewer reads (passed.by == ACCOUNTANT) while every write stays refused. Do the same in contractors_router._access."'
status: in review
prs: [kmj-intake-server (this PR), solutionist-studio#1721 merges after this is live]
migrations: []
left_undone:
  - "solutionist-studio#1721 (the accountant's menu shows Pay staff) merges after this is live, on Thursday Dec 3 with the other M-6 features."
  - "Contractors joins the accountant's app menu later, once its Add button asks the login's role (after solutionist-studio#1719)."
decisions:
  - "payroll_router._access and contractors_router._access: when min_role is viewer and the church wall let the login in as the accountant (church_money_gate.ACCOUNTANT), the row is returned. An accountant collaborator holds no business_users seat, so the seat ladder refused every read before, though the wall (Kevin's 2026-11-19 ruling) lists the accountant for pay records. Every write asks manager, admin or owner and still meets the ladder, so all writes stay refused."
  - "What the accountant sees is what a viewer sees: people, runs, stubs (the Social Security number's last four, as on any stub), the calendar and the worksheets. The W-4 itself (GET tax-profile) stays the owner's."
  - "PAY_RECORDS_403 now names the accountant (to read)."
related: [2026-11-18-church-payroll-behind-the-wall.md, 2026-11-19-payroll-free-version.md]
---
`payroll_router.py`, `contractors_router.py`, `church_money_gate.py`
(PAY_RECORDS_403). Tests: `__tests__/test_payroll_free_routes.py`: the two
assertions that pinned the refusal flipped (the calendar, the refusal words),
the switch-off test's readers now include the accountant, and three new tests
(the accountant reads summary, people, runs, a run, stubs, a stub PDF, the
calendar, the quarter, the year and its CSV; is refused creating or changing a
person, the W-4, consent, creating, editing, approving, cancelling or marking
a run paid, sending stubs, settings and Mark sent; reads contractors and their
payments and can't add one). Rehearsed: without the change the read tests turn
red. Ran payroll, ticks, seat access, minister, contractors, the one money
gate, the access ratchet and the ownership sweep: 609 passed.
