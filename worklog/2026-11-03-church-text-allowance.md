---
title: A church plan's texts are counted, the church hears at 80% and 100%, and extra texts go on the next bill
date: 2026-11-03
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03, approving the church-pricing plan (artifact Pdg8hF4pB5n6efoFQmzd8d), which included each plan''s texts a month and "$20 per 1,000 extra": "I agree with the plan. make the fixes and upgrade"'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "The app: the Billing page's texts line (GET /billing/usage now returns `texts`) and the announcement composer's 'this will use N of your M texts' (GET /sms/broadcast/reach now returns `texts`): frontend follow-up"
  - "What's New entry at switch-on, with the church plans"
  - "The 1.25-cent cost per segment (sms_usage) still hasn't been checked against a real Twilio invoice; the price (2 cents a text) leaves room either way"
decisions:
  - "Nothing ever stops a text. The heads-up is sent after a broadcast, and by the daily tick, never before a send. A test checks that no sending module reads the allowance"
  - "Sign-in codes don't count toward the plan: they're how members get into the app. Every other text does, kids pickup codes included. Texts, not segments"
  - "Extra texts are priced per text (the $20-per-1,000 dial / 1,000 = 2 cents), not per started thousand: 40 texts over is 80 cents, not $20"
  - "A month under CHURCH_TEXT_BILL_MIN_CENTS ($1, 50 texts) isn't billed. It's recorded as 'none'"
  - "Billed at month close by a daily tick (09:15 UTC, leader only), so a church that fails on the 1st is retried on the 2nd. Only active or past-due subscriptions; trials and comped churches are never billed"
  - "One Stripe invoice item on the church's subscription, so it lands on the next invoice. Once per month: the month is claimed in settings.church_texts_bill with a write filtered on the record it read, the Stripe call carries an idempotency key, and a run that finds its own unfinished claim first looks for the item it already made (including one an invoice already took) before making one"
  - "A count that can't be read sends no heads-up and bills nothing (tried again tomorrow)"
  - "CHURCH_TEXT_BILLING=off stops the bill; the count and heads-up keep going"
related: [2026-11-03-church-plans-by-size.md, 2026-11-03-sms-metering.md]
---
`church_texts.py`: `summary`, `check_allowance`, `bill_month`, `bill_tick`.
Wired in: the scheduler (`church_texts` job), `GET /billing/usage` (`texts`),
`GET /sms/broadcast/reach` (`texts`), and `sms_routing.announce` (heads-up
after a send).

Tests: `__tests__/test_church_texts.py` (59). `test_bulletin_said_yes` now
expects the reach's `texts` key. 531 passed across the SMS, billing, Stripe,
usage and church plan files; 214 across the scheduler files.
