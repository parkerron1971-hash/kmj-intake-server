---
title: Text delivery reports no longer lost
date: 2026-10-02
agent: Claude Code (Claude Opus 5.5)
asked: 'ok do it (look into the 13 texts never confirmed delivered)'
status: shipped
prs: [kmj-intake-server#PENDING]
migrations: []
left_undone: ['Hermes repeats the same unanswered-text finding into the operator log every hour; no dedupe yet']
decisions: ['a status report that finds no row retries for ~14s, then the hourly Hermes reconcile asks Twilio', 'a late sent never overwrites delivered or failed']
related: [2026-10-02-agents-screen-keeps-every-card.md]
---
Hermes flagged 13 outbound texts "never confirmed delivered". Twilio said 12
were delivered and 1 undelivered (30024). Twilio delivers within about a
second, so its status report often reached /webhooks/twilio/status before the
send path saved the row; the PATCH matched nothing and was dropped silently
(no Twilio alerts: we answered 204). Now the report retries in the
background, and Hermes' hourly pass calls twilio_sms.reconcile_sent, which
asks Twilio about anything still `sent` (5 min to 120 days old) and writes
the real outcome. The existing 13 are repaired on its first pass.
