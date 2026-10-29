---
title: ChurchSavvy on its own — a church's own colors and logo in its look
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: '"keep going with step 2 I want the entire thing built. also can you ahve access inside the system and access outside the system as well" (Kevin, 2026-10-19)'
status: in progress
prs: [kmj-intake-server#1516, solutionist-studio#1286, solutionist-studio#1287]
migrations: []
left_undone: ["the standalone app itself (solutionist-studio): /churchsavvy front door, sign-in, Name your church, the ChurchSavvy shell", "the ChurchSavvy price in Stripe and opening it to every church (Kevin)"]
decisions: ["a church that has no Solutionist brand kit sets its colors and logo on the Look page, stored in the look (look.brand); a brand kit, when there is one, always wins"]
related: [kmj-intake-server worklog/2026-10-19-churchsavvy-show.md]
---
A church on ChurchSavvy alone has no Brand Studio, so its screens had nothing to draw its colors and logo from, and the Look page's "Change in Brand Studio" would have been a dead end. The look now carries an optional `brand` (primary, accent and background colors, plus a logo link), checked in `worship_show.clean_look`. `worship_show_router._brand` uses it only when the church has no brand kit.

Checks: 2 new tests (engine, router); the show tests, 35 passed.
