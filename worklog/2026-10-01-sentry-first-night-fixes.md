---
title: Bugs Sentry found on its first night, and the Stripe event-order bug
date: 2026-10-01
agent: Claude Code (Claude Opus 5.5)
asked: "make the changes so we can keep building"
status: shipped
prs: [kmj-intake-server#1139, kmj-intake-server#1140, kmj-intake-server#1141, kmj-intake-server#1142, kmj-intake-server#1172]
migrations: [supabase/APPLY-2026-10-01-agent-queue-data.sql (applied)]
left_undone: []
decisions: ["billing events apply the subscription as Stripe holds it now, never the event order"]
---
The double-booking guard passed every slot ('+' in URL timestamps), the
booking session sync did nothing, agent_queue.data never existed (autopilot,
bookkeeping inbox and payment escalation broken), five scheduled jobs blocked
the event loop, and the ledger vocabulary was lost on every boot. Separately,
a cancelled subscription (Creative Genius) stayed past_due because two
same-second Stripe events applied out of order. Before building near billing
or bookings, read these PRs' descriptions.
