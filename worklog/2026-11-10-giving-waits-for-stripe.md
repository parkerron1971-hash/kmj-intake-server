---
title: Giving can't be switched on until Stripe has approved the church
date: 2026-11-10
agent: Claude Code (Claude Fable 5.2)
asked: "yes to all, on the first paying church's rollout plan (fix 3 of 4)"
status: shipped
prs: [kmj-intake-server#1790]
migrations: []
left_undone:
  - "giving_is_active still doesn't read charges_enabled: a church already switched on whose Stripe account later loses charges keeps a live give page. Left alone on purpose, so no live church's page could go dark from a stale flag."
  - "An account Stripe hasn't reported on yet (no settings.stripe flags) is let through, as payments_core.can_charge does everywhere."
decisions: ["Only the off-to-on switch is refused, and only on Stripe's explicit 'can't charge'. Off, and already-on, are never refused."]
related: [2026-11-05-lit-giving.md, 2026-11-03-church-logins-and-move.md]
---
The rollout check for the first paying church found that the Settings switch
(`PATCH /giving/{id}`) turned giving on for any church with a Stripe account
id, approved or not. A half-set-up account got a live give page and the gift
failed in front of the giver. Chief's `set_giving` already refused this; the
switch now does too, with the same rule (`payments_core.can_charge`). Tests in
`test_online_giving.py`.
