---
title: The church pricing page shows the price for every three months
date: 2026-11-16
agent: Claude Code (Claude Fable 5.2)
asked: "Kevin, 2026-11-16, after the 3-month term was switched on in Billing: \"need to be on the site as well because they may pay for three months...\" and \"no artifact needed. do straight on the site because of the meeting I have.\""
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "The business pricing cards (marketing_pages, marketing_home_v2/v3: the Monthly / Annual switch that shows a per-month figure) do not offer three months. Only the church section's switch does."
  - "On a phone the switch's three buttons wrap onto two rows. Nothing overflows; it could be tightened."
  - "The size picker's chip still reads 'Founding price, regular $249 a month' while the price above it reads every 3 months. True, but two terms in one card."
  - "Seen in a local render (file, no assets) at 1440 wide and a 390 phone. Not seen on the live site before this was written."
decisions:
  - "No mock first: Kevin said to go straight to the site. It is the same three-way switch he approved for Billing (Monthly, Every 3 months, Yearly), added to the switch the page already had."
  - "The page offers the term only when checkout can sell it: every church size has its 3-month Stripe price set, regular AND founding (church_site._church_quarter). Half a set shows nothing, because a founding church with no founding 3-month price would be refused at checkout."
  - "Three months' price, no discount, and no '% off' on the button. Yearly keeps '2 months free'."
  - "The cards carry the figure as data-q beside data-m and data-y; with the term not sold the page's HTML is what it was, byte for byte."
related: [2026-11-16-three-month-term.md]
---
`church_site.py`: `_quarter_sold`, `_church_quarter`, `_q`, the `Q_*` tokens,
`QUARTER_BUTTON`, `_saving_words` (`q`), `_plan_cards` and `_picker_data`.
`church_site/overview.html`: the middle button's slot, the switch's script
(three periods), and a wrap rule for narrow screens. `church_site/overview.js`:
the size picker follows the period.

Tests: `__tests__/test_church_site.py`, the last four.
