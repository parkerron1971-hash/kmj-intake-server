---
title: Chief knows the address, phone and hours the owner told the Design Coach
date: 2026-11-10
agent: Claude Code (Claude Opus 5.5)
asked: "go, fix the two gaps first and make it happen"
status: shipped
prs: [kmj-intake-server#1787]
migrations: []
left_undone:
  - "The business profile still doesn't learn the address from the Coach: the booking page, invoices and anything else reading the profile won't show it. Filling an empty profile field from the Coach's answer is the next step, if Kevin wants one source of truth."
  - "The page check is a heuristic: street number and name for an address, the last seven digits for a phone, a day name for hours."
decisions:
  - "The facts ride Chief's PRACTITIONER SITE lines, right under where the design stands, so the answer check reads the same lines Chief does."
  - "Chief is told to offer to put a missing fact on the page, never to ask for it."
related: [2026-11-09-coach-reads-the-ask.md, 2026-11-10-old-pick-meets-new-ask.md]
---
The live retest on the test shop: the owner gave the Design Coach the shop's
address, and its hours were on file. Minutes later, in the site editor, Chief said
"If you give me the shop address and hours, I can work them in." The site editor's
Chief is Chief itself (`/agents/chief/chat` with the design-studio tab), and those
answers lived only in the design dossier, which Chief's snapshot never read.

`chief_site_design.told_coach_lines` reads the dossier's truth (address, phone,
hours) from the site row Chief already loads, and `site_design_lines` puts it under
the blueprint line. When the site has a builder page, a second line names which of
those facts the live page doesn't show yet.
