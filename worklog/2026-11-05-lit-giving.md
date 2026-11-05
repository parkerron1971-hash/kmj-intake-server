---
title: The Giving page becomes a lit room (and the lit rooms kit every product page will share)
date: 2026-11-05
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-04, on the Giving mock (claude.ai/artifact/NHKdhA7FbSsaaR788at2Zn): "the design is good! love it. let''s build it and do upgrades to others as well nice. show me the others too."'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "The other six product pages (people and care, kids and youth, groups and classes, member app, website and sermons, office and books) get their own lit mocks for Kevin to see first, then their own PRs on this kit"
  - "The overview's products grid still has the clipped second Member App phone; it gets fixed when the grid's tiles are relit"
decisions:
  - "A shared kit, church_site/lit.css + lit.js, inlined on any page whose template carries {{LIT_CSS}} / {{LIT_JS}}; the room's own parts sit beside its template (giving.css, giving.js) as {{ROOM_CSS}} / {{ROOM_JS}}. The kit never names a colour: it reads the room's --p/--pl/--pd/--pg from the page root, so one kit lights every room"
  - "Giving: the hero's devices are one scene at a readable size (the office's giving page and a member's phone in the room's green glass light; Ruth gives and the gift lands). 'Give in under a minute' becomes 'Follow one gift' (Sarah's $100: her phone, the church's own Stripe with a $0 cut, the Building fund, her January statement), a sticky story on desktop with each step's scene inline on phones. Monthly gifts loop a pause and a resume; funds are three glass jars; statements are paper with Chief's 'Send them'"
  - "Every claim on the page is one it already made (give page on the site and in the app, Stripe holds the card, no platform fee, fee cover, receipts, funds kept apart, the IRS form, a person presses send). The plan-by-size sections (FUNDS_LEDE, FUNDS_CLOSE, PREP_990) are kept as template sections"
  - "Complete at rest: the hero opens with the gift landed and the statements sent; scripts only loop scenes while they're on screen; reduced motion shows the end state and nothing moves"
  - ".pg's overflow:hidden (church.css) turns into overflow-x:clip on lit rooms; hidden makes .pg a scroller and sticky stops sticking"
related: [2026-10-23-church-site.md, 2026-11-04-church-first-home.md, 2026-11-05-kids-pickup-names.md]
---
The mocks were built from the live templates by a scratchpad builder (one module per room that rewrites its template; the same module wrote this template), so what Kevin approved is what renders.

Checked: `__tests__/test_lit_rooms.py` (8 new: the kit takes the room's colour, the kit and the room's parts are inlined with no marker left, both scripts parse, every "In this room" link lands, the page opens on its finished scenes with each step's scene inline for phones, sample labels and no names, the funds words follow the plans by size). Every site test file passes. Rendered at 1440 and 390 (the approved mock also at 1024): no page errors, no sideways scroll.
