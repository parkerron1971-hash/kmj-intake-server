---
title: The business pricing cards show paying every three months
date: 2026-11-16
agent: Claude Code (Claude Fable 5.2)
asked: "Kevin, 2026-11-16, after the church pricing page got the 3-month price: \"do the business pricing cards too\"."
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Only the live business page (marketing_home_v3, served at /business) was changed. The two older editions kept for rollback (marketing_pages' pricing section and marketing_home_v2) still offer Monthly and Annual only; they show only if HOME_EDITION is rolled back."
  - "The compare table's column heads stay on the price a month, which is the same for three months."
  - "'Start with Professional' still goes to /start?plan=professional: the plan is carried to Choose your plan, the way of paying is picked there on Billing's switch."
  - "Seen in a local render (file, no assets) at 1440 wide and a 390 phone. Not seen on the live site before this was written."
decisions:
  - "No mock first, as for the church page: Kevin said to go straight to the site, and it is the three-way switch he approved for Billing."
  - "These cards lead with the price a month. Three months is three months' price, so that figure does not move; the line under it says the real charge ('$447 billed every 3 months'), as the annual line says '$1,490 a year, billed once'."
  - "The button names no saving. Annual keeps '2 months free'."
  - "Offered only while all three plans have their 3-month Stripe price set (marketing_home_v3._quarter_sold), so the page never shows a way of paying checkout would refuse. Without it the page's HTML is what it was."
  - "The switch wraps on a narrow screen (three buttons do not fit a phone in one row)."
related: [2026-11-16-three-months-on-the-church-page.md, 2026-11-16-three-month-term.md]
---
`marketing_home_v3.py`: `_quarter_sold`, `_QUARTER_BTN`, `data-quarterly` on
each card's billed line, the `{{QUARTER_BTN}}` slot. `marketing_home_v3.html`:
the slot in the switch, `setPeriod(period)` for three periods, and the wrap
rule. Tests: `__tests__/test_home_v3.py`, the last two.
