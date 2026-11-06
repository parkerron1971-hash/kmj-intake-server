---
title: The founding churches keep the price they start at
date: 2026-11-05
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-05, after asking whether the church price is still too low (my answer: not for now; keep the first churches at today''s price, raise for new churches later): "yes do the run-through and add the founding price line"'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "The app's Billing card (ChurchPlanExtras, the move) doesn't say it yet; the site does"
  - "If a founding church changes plan after a price rise, which price it gets is decided then"
decisions:
  - "The line rides on the same dial as the free move (FOUNDING_CHURCH_MOVES): the first five churches move free and keep the price they start at, for as long as they stay. With no founding churches left, neither line shows"
  - "Nothing has to run for the promise to hold: a price rise is a new Stripe price that takes the lookup key, and every subscription stays on the price it has. pricing_config.founding_church_moves says never to move a founding church onto the new price"
  - "Said twice, where the move is already said: the Moving over box and the Good to know note under the price cards"
related: [2026-11-03-church-pricing-by-size.md]
---
The overview (mysolutionist.app/ and /churches) now says the founding churches keep their price. In the Moving over box: "The first five churches move free. They also keep the price they start at, for as long as they stay." Under the price cards: "...and the first five churches move free and keep the price they start at, for as long as they stay."
