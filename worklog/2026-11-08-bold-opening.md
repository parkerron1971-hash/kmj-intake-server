---
title: Signature and World pages open with poster-size type
date: 2026-11-08
agent: Claude Code (Claude Opus 5.5)
asked: "you can work on what is missing and need upgrading"
status: waiting on Kevin
prs: [kmj-intake-server#1773]
migrations: []
left_undone:
  - "Merged but switched off: SITE_BOLD_OPENING waits for a Thursday."
  - "No real build has run with it. A miss costs a section repair inside the look-fix cap, so watch the first builds for extra repair rounds."
decisions:
  - "The bar sits between the measured pages: 8vw on a computer, 12vw on a phone."
  - "Plain pages are exempt, so a law firm's first screen stays calm."
  - "Home page only, since that is the page the render measures."
  - "A ghost word doesn't count, because it is aria-hidden and faint. A library object's big name does."
related: [2026-11-08-site-scene-library.md]
---
Measured on four live pages, the biggest words on the first screen on a computer
are 201px and 196px on the hand-built pages, and 72px and 95px on the builder pages.
The type floor only set minimums for reading, so nothing asked for a bold opening.
The builder is now told the bar on Signature and World pages, and the render measures
it. A miss is a repair finding, never a fallback.
