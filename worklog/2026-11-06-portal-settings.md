---
title: Manage Subscription carries its own portal settings
date: 2026-11-06
agent: Claude Code (Claude Opus 5.5)
asked: 'yes. go ahead with all 4'
status: shipped
prs: [kmj-intake-server#1757]
migrations: []
---

While checking the Stripe account for the plan-switch fix: the live account has
no customer-portal settings at all, and Stripe refuses a portal session with
neither a saved default nor a configuration. So Manage Subscription, where a
church changes its card or cancels, had nothing to open with. Every session now
carries our own settings, made once and found by their mark: card, invoices,
email and address, cancel at the end of the paid period, and no plan changes,
which stay in the app. If Stripe won't answer, the session goes out as before.
Not yet proven on live: creating the settings from this machine was blocked, so
the first real press makes them. A failure there lands in the logs as
`portal configuration failed`.
