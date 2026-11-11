---
title: A church's move request emails the platform owner
date: 2026-11-10
agent: Claude Code (Claude Fable 5.2)
asked: "yes to all" (the first paying church's rollout plan; fix 4 of 4)
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "No state after requested/paid exists for a move (in progress, done). The ticket is still closed by hand in Mission Control."
decisions: ["Best effort: the ticket stays the record, and a failed email never fails the request or the webhook."]
related: [2026-11-03-church-logins-and-move.md, 2026-11-10-giving-waits-for-stripe.md]
---
A move request (founding, or paid through Checkout) only wrote a "MOVE: ..."
support ticket, which sits in Mission Control until someone opens Today. The
first paying church is signing up this week and its first Sunday is days away,
so `church_billing._tell_owner` now sends one plain email to
`PLATFORM_OWNER_EMAIL` when the ticket is written: church, plan, where it's
moving from, and whether the move was free or paid. One email per ask (Resend
idempotency key per founding ask or per Checkout session). Tests in
`test_church_billing.py`.
