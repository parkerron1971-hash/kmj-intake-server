---
title: Giving and the home page say only what the product does
date: 2026-11-06
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-06: "I want to make sure this is properly ready"'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "'keep the price for as long as they stay' is a promise no code enforces: it holds because a Stripe subscription stays on its price. 'Stay with you to your first Sunday' is a promise Kevin keeps by hand"
  - "'Set list shared Tuesday' couldn't be confirmed either way"
decisions:
  - "A review of the six new rooms found about 28 false lines, so Giving and the home page, built the same way, got the same review"
  - "The card fee is 2.9% + 30c on the gift, so covering it on $100 is $3.30, not $3.20, and the gift is recorded at $103.30 everywhere it shows. A new test reads covered_fee_cents, so the page can't drift from the code"
  - "'the building fund never pays the light bill' is gone: nothing stops spending from a fund, every designated fund shares account 4200, and spending by fund is FUNDS (owner). Now 'each gift stays counted in it', and restricted gifts post apart from General"
  - "Shepherds hear on Monday morning; only group leaders get a drafted note. The note scene is a group leader's now"
  - "Bank matching says Stripe payouts, since the Sunday match is GIVING_DEPOSITS (owner)"
  - "The footer called a church a small business on all seven rooms; it now uses the home page's line. Chief's strip says what earned permission does"
  - "Checked in production: CHURCH_AREAS, CHURCH_BOARD, CHURCH_CHECKS, CHURCH_REPORTS, CHURCH_SERVING are on, and the extra-login and annual prices are set, so those lines stand"
related: [2026-11-06-lit-rooms.md]
---
Same reason as the rooms: a sample scene is a promise once it's on the site. The fee maths was wrong on the money page, and the funds line promised a wall the books don't have.
