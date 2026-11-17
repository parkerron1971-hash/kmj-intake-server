---
title: Kevin is told when a new customer subscribes and its payment goes through
date: 2026-11-16
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-16, after asking me to check that the first church''s payment arrived: "can we build notification on through mission control that will let me know when someone new subscribe and payment went through"'
status: in review
prs: [kmj-intake-server#TBD, solutionist-studio#TBD]
migrations: []
left_undone:
  - "Receipts: Stripe has NOT emailed customers a receipt (the first church's charge has receipt_number null). The switch is in Stripe's Dashboard (Settings, Customer emails, Successful payments), not in our code. Kevin's call, asked 11-16."
  - "Not proved on a real payment: no production write, no push sent. The next new subscription shows as a 'New customers' alert in the Dev Desk inbox and on Today. On a failure Railway prints '[billing] new customer alert failed for <invoice>'."
decisions:
  - "One alert per new subscription, from invoice.paid on the platform webhook (/billing/webhook; it already receives invoice.paid). 'paid': billing_reason subscription_create with money. 'first': any later paid invoice with money when Stripe shows no earlier paid invoice with money (a trial ending). 'started': subscription_create with nothing charged (free days or a full discount), with the first charge's date. Renewals, upgrades, logins and one-off invoices never alert. If Stripe can't be read, it says nothing rather than call a renewal new."
  - "It rides the owner alert inbox (dev_alerts, new server source 'customers', push by default): his phone push, quiet hours, morning digest, rate limits and the inbox in the Dev Desk all come with it. No new table, no migration (dev_alerts.source has no CHECK). The alert opens Mission Control, Subscriptions (dev_alerts.OTHER_NAV, the only page outside the Dev Desk an alert may open)."
  - "Once per event: a redelivered Stripe event (already in stripe_webhook_events) is skipped, and the alert's key is the invoice id (30-minute dedupe). It runs in the background, so the webhook's answer never waits on a push or fails because of one."
  - "Today (platform_today) shows each 'customers' alert from the last three days as a gold people/money item: Open Subscriptions, or Draft a welcome with Chief."
  - "Shipped on, not held for a Thursday: it is owner-only and Kevin asked for it now. He turns it off under Dev Desk, alert settings, New customers."
related: [2026-11-16-churches-no-trial.md]
---
The first church paid today, and Kevin had to ask me whether the money
arrived. From this PR a new subscription tells him itself: "New church:
Elevation of Grace paid $199", "Growing Church plan, monthly. They
subscribed and the first payment went through." It goes to his phone and
the alert inbox, and stays on Today for three days. The frontend PR gives
the source its name and switch in the alert settings.
