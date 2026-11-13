---
title: A church plan has no free days, its first month is charged the day it is chosen
date: 2026-11-13
agent: Claude Code (Claude Fable 5.2)
asked: "I am thinking we should remove the 7 days for free. thoughts ... yes build."
status: in review
prs: [kmj-intake-server#1824]
migrations: []
left_undone:
  - "A church still signs up without a card and has the same days and credits to look around with as any new business (no_card_trial). Only the free week AFTER a plan is chosen is gone. Taking the look-around away too would put a paywall in front of Chief's welcome and the Move-in list; that is a separate decision."
  - "The trial emails (trial ending soon, trial ended) still go to a church that has not chosen a plan, in the general words."
  - "No promise stands in the free week's place yet. Kevin turned down 'if you're not live on your first Sunday, your first month is on us' and asked for another idea."
  - "Not run with a real card: no church plan has ever been paid."
decisions:
  - "Church plans only. BILLING_TRIAL_DAYS is one dial for every business and the marketing site quotes it; every other plan keeps its free days."
  - "stripe_billing._pays_today(plan, asked): a church plan's checkout carries no trial_period_days and no trial_end, the same path as 'pay today' (skip_trial, 2026-09-04). A church still looking around without a card is charged the day it chooses, not on the date its look-around would have ended."
  - "PLAN_CHURCH_FREE_WEEK=1 brings the free week back with no deploy. A church already on a carded trial keeps its date either way: only new checkouts change."
  - "The church pages stop saying 'N days free': 'No card to sign up. Your first month starts the day you choose your plan.' The Start buttons still say 'Start free, no card', which is true of signing up. The coach section fills its pages from the same helper and keeps its trial wording (church=True is the church section's own)."
  - "/billing/plans church_offer carries free_week (0 or 1) and /access/open carries church_free_week, so the app's billing screen, bars and sign-up screen say what checkout will do."
  - "This fits the founding church price (church_founding): a place is held by the first PAID month, which now arrives at checkout."
related: [2026-11-13-founding-church-prices.md]
---
Kevin's offer to a founding church is "your first month, paid before the move starts". With the free week,
a church that added a card on a Monday was first charged the next Monday, the day after its first Sunday,
after a week of work done by hand. A church plan now charges at checkout.
