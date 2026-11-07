---
title: A plan switch moves the one subscription and never makes a second
date: 2026-11-06
agent: Claude Code (Claude Opus 5.5)
asked: 'yes. go ahead with all 4'
status: shipped
prs: [kmj-intake-server#PENDING, solutionist-studio#1487]
migrations: []
---

/billing/checkout had no check for a running subscription, and Checkout always
makes a new one, so "Switch plan" could leave a business paying twice, with
the row following whichever Stripe wrote last and a later cancel of the old
one marking it canceled. Now a business with a running subscription gets no
Checkout: the plan item moves to the new price (`_switch_plan`), extra logins
stay on the subscription, a trial stays a trial, and the answer says
`switched`. A failed payment is fixed first. A no-card trial, or a subscription
that has ended (even if our row is behind), still goes to Checkout. This covers
every plan, not only churches. FE PR above adds the confirmation on the card.
