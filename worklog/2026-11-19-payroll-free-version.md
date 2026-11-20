---
title: Payroll, the free version, server half. Deposit calendar, pay statements (JSON, PDF, email), deposits marked sent, quarter and year-end worksheets, carried-over withholding, hourly reminders
date: 2026-11-19
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-19: "build the free version now and will think about the other option later." The church pays its people from its own bank and sends its own tax deposits; Solutionist prepares the numbers, the stubs, the calendar, the reminders and the year-end worksheets. Contract: payroll_free_contract.md (the app is built against it in parallel).'
status: in progress
prs: [kmj-intake-server#1973]
migrations: [supabase/APPLY-2026-11-19-payroll-deposits.sql (NOT applied; reviewed safe to apply)]
left_undone:
  - "Migration NOT applied. Until Kevin applies it the calendar reads 'no deposits marked' (deposits_ready: false), Mark sent and Undo answer 503 'Deposit tracking is being switched on. Try again shortly.', and the reminders skip."
  - "Housing with the housing allowance records switched off (HOUSING_ALLOWANCE=owner, so every church but the platform owner's): nothing can be checked, so the W-2 still leaves the housing out of Box 1 as if the board designated it in advance, and the row's note says so. With the records on, only what was designated in advance is left out."
  - "No route sets a person's paid_by. The statement reads employees.paid_by when that column exists, else 'direct_deposit' when direct-deposit consent is stamped, else null. No bank account number is stored or shown (the mock's 'Checking ending 2290' line is not drawn)."
  - "employees has no title column: Stub.employee.title and the W-2 list's title read employees.title when it exists, else null."
  - "The $100,000 next-day deposit rule and the 941 lookback that decides monthly vs semiweekly are not worked out: the church picks its schedule in the payroll settings."
  - "State holidays: a state's own deposit date rolls past weekends and Federal Reserve (bank) holidays, not that state's own holidays."
  - "No live send was made: the statement emails and the reminder alerts were checked with send_via_resend and push stood in."
decisions:
  - "Payroll and contractor READS need the giving tick at Work, not See (Kevin, 2026-11-19): church_money_gate.require_pay_records, asked first in payroll_router._access, contractors_router._access, and the 1099 summary, drafts and summary export in reports_router. With CHURCH_MONEY_TICKS off no tick is ever a standing, so nothing about who may see payroll changes (a test compares every login's answer with the switch off against no switch at all). Three existing tests that pinned the old call string were updated to the new one."
  - "Deposit due dates roll past IRS legal holidays, which are the District of Columbia's (Publication 15): the federal holidays plus DC Emancipation Day, with a Saturday holiday observed the Friday before. Approve-by days and the holidays shown use the Federal Reserve's schedule (a Saturday holiday closes no Friday). So April 15, 2023 rolled to April 18, July 3, 2026 is not an IRS business day but is a bank day."
  - "Semiweekly: the due date is the third business day after the semiweekly period closes (Publication 15: 'at least 3 business days', one more for each legal holiday among them). Identical to 'following Wednesday / Friday, rolled' except when a holiday falls inside the three days (payday Friday Jan 16, 2026, MLK Day Monday: due Thursday Jan 22, Publication 15's own example)."
  - "A statement of a run the login can't open (another church's, or a login without payroll) is a 404, never a 403. Sending statements first passes that 404 check, then needs the owner or an Admin (403)."
  - "941 line 6 includes 5d (Additional Medicare, 0.9% over $200,000), as the form does; lines 7 (fractions of cents, actual minus rates) and 12 (the months' total) are added so the monthly schedule reconciles."
  - "A line is a minister's for the 941 and W-2 when it had pay and no Medicare either half (how it WAS taxed), so someone who became a minister mid-year is counted right on both sides. Housing paid before the board's designation date stays in Box 1 (housing_allowance.figures' rule); housing paid over the designated amount gets a note, not a silent move."
  - "Reminders: a team alert at 3 or 2 days out (so a missed hour or a late approval still reaches them), the owner alone at 1 day; several dates at once are one alert; quiet hours 8 AM to 9 PM in the church's own time zone (outside_calendar.business_timezone); each (business, key, audience) is claimed in payroll_reminders_sent before it goes, so at most once."
  - "Carry-over: a line now records how the person was paid (calc_payload.pay); older lines are judged by whether their own hours on today's terms give the same gross. carried_from is the run id (a string), with carried_from_pay_date beside it for the app's 'carried over from Nov 13'. Typing a federal or state figure on the line drops the note."
related: [2026-10-31-minister-payroll.md, 2026-10-31-church-payroll-rules.md, 2026-11-18-church-payroll-behind-the-wall.md, 2026-11-18-church-money-ticks-server.md]
---
Before building, both repos' work logs were read: nothing in either had
started a payroll calendar, statements, worksheets or reminders. The related
work is the minister rules (10-31), payroll behind the church wall (11-18) and
the giving tick (11-18), which this builds on.

New modules, each with its own test file: `payroll_calendar.py` (bank and IRS
holidays, the deposit and filing rules, settings, the month view),
`payroll_deposits.py` (Mark sent / Undo and the reminders' memory, both
server-only tables), `payroll_carry.py`, `payroll_stubs.py` (the Stub JSON,
the reportlab PDF laid out like the mock PayStub.dc.html, and the emails),
`payroll_forms.py` (the 941 numbers by quarter, the W-2/W-3/1099-NEC year,
a CSV and two PDFs: worksheets only, never an official form's look, each
saying "For you or your accountant to file. Solutionist doesn't file.") and
`payroll_reminders.py` (hourly, registered beside the giving-request sweep).
`payroll_router.py` stays thin: the thirteen new doors call those modules.

Switches: `PAYROLL_STUB_EMAIL` and `PAYROLL_REMINDERS` (off | owner | on,
default on). The new table `payroll_deposits` is exported and deleted with a
business and skipped on import; `payroll_reminders_sent` is excluded from the
export with its reason.

Tests: the seven new files (`test_payroll_calendar.py`,
`test_payroll_deposits.py`, `test_payroll_carry.py`, `test_payroll_stubs.py`,
`test_payroll_forms.py`, `test_payroll_reminders.py`,
`test_payroll_free_routes.py`, on the shared stand-in
`__tests__/payroll_free_fake.py`), the existing payroll, contractor, gate,
export and housing suites, and the whole suite in CI's four parts with the
Supabase keys unset.

**After the independent review (PR #1973).** Must-fix: carried withholding
could leave an hourly check's take-home below zero and the run still
approved (80 hours carried onto a 4-hour check: net −$297.65). Now an hourly
line carries only when its pay equals the copied line's
(`payroll_carry.check`, with `calc_payload.carry_note` saying why not),
changing a carried hourly line's hours clears what was carried, and approve
refuses any line with take-home below zero, naming the person (409
`negative_net`). Also fixed: housing past the board's designated amount, or
with no designation in advance, is wages in W-2 Box 1 and on 941 line 2, Box
14 shows only what is left out, and the W-2 row and the 941 say how much
moved and why (Treas. Reg. 1.107-1(b)); IRS deposit lines and alerts say
EFTPS needs the payment by 8 p.m. Eastern the day before it's due
(Publication 15); the 1099-NEC line is the tax year's everywhere (one helper,
`form_1099.nec_threshold`: the 1099 summary, drafts, export column, summary
PDF, the accountant's cover email and the year worksheet); state due dates
roll on bank days, not DC holidays; `settings.payroll` is a server key (added
to the unapplied 11-17 settings guard file, and this migration rewrites the
guard's list when that file is already in); NaN and infinity are refused as
money; a statement's year-to-date taxes use each line's own Social Security
and Medicare; the year worksheet's contractors leave out Stripe-managed ones
as the drafts do; a long church name wraps on the PDF; statements after
mark-paid go in the background (`stubs: {queued, auto, sent: null,
skipped: []}`); the pay-records refusal no longer names the accountant
(payroll's ladder refuses a login with no seat); approve-by reminders go only
to the owner and Admins.

**After the second review.** A housing allowance record read that FAILS now
answers 503 "The housing allowance records couldn't be read. Try again
shortly." on every worksheet door (`payroll_forms.HousingUnreadable`), never
"not designated" with all the housing in Box 1. When more than one record
could be the minister's (`payroll_router._housing_match`: found, none or
ambiguous), the housing is left out of Box 1 as with the records off, the W-2
row says it couldn't tell which record is theirs, readiness asks to link the
right one, and the 941 page now says when it left housing unchecked (records
off or ambiguous). A carried line now records which figures were carried
(`calc_payload.carried_fields`); typing one leaves the other still marked,
and when the hours change on a carried hourly line every carried figure the
same PATCH doesn't type is cleared, with a note saying which still needs
typing (never the old check's state figure standing on the new one).
