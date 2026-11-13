---
title: ChurchSavvy is included with Solutionist; ChurchSavvy-alone prices made in Stripe, billing on for the owner
date: 2026-11-13
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-13: "should I add the cost to churchsavvy in the system or have as no extra cost? we need to turn that on" then "Include" and "keep 20/15/29, go ahead"'
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio (PlanBilling wording)]
migrations: []
left_undone: ["Thursday 2026-11-19: CHURCHSAVVY_BILLING owner -> on (both services), after re-checking that no church on ChurchSavvy alone (settings.churchsavvy_only) would suddenly be asked to choose a plan", "Kevin's own end-to-end rehearsal of a ChurchSavvy-alone checkout while the switch is owner"]
decisions: ["no $10 add-on: a Solutionist church gets ChurchSavvy's screens and Planning at no extra cost (the code already opened everything; only the words promised $10)", "ChurchSavvy alone stays $20 / $15 / $29 a month", "the three live Stripe prices were made with the app's own bootstrap_prices narrowed to the STRIPE_PRICE_ID_CS_* entries (lookup keys churchsavvy_*_monthly); the ids are set on kmj-intake-server and kmj-intake-worker with CHURCHSAVVY_BILLING=owner"]
related: [2026-10-24-churchsavvy-billing.md, 2026-10-25-churchsavvy-site-v3.md]
---
The ChurchSavvy site said "$10 a month adds ChurchSavvy's screens to your
Solutionist plan" on its Pricing and With Solutionist pages, but nothing ever
charged it: `churchsavvy_billing.parts()` opens every part for a church that
isn't on ChurchSavvy alone. Kevin chose to keep it included, so the two lines
now say both parts come with every Solutionist church plan, and a test holds
both pages to it. The app's own Plan and billing page carried the same $10
line; the frontend PR changes it.

ChurchSavvy alone can now be bought by the owner only (CHURCHSAVVY_BILLING=owner).
Switching it on for every church is a Thursday step (see left_undone).
