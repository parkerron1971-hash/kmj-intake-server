---
title: "Home's date and Today/Tomorrow wear the highlight (new look)"
date: 2026-11-22
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin found the highlight doesn't show where the office preview says it does (Home's date line and the Today kicker were grey)."
status: shipped
prs: []
migrations: []
left_undone: []
decisions:
  - "Home's date eyebrow (.lm-ey4) and This week's Today/Tonight/Tomorrow kickers (.lm-wkk.is-soon, on the pass and the cards) take var(--lm-gold): the gold-ink token, which is the readable ink (a deeper shade on white, the lit shade at night). The church's saved highlight therefore reaches them through the palette. Other days' kickers and the feed's event kickers (they name a date, never Today) stay grey."
  - "This changes the default new look slightly, to match the approved mock: the date and Today turn gold at every church on the new look."
  - "Save to page: PATCH /member-portal/{biz} writes settings and forgets member_cache's church on the copy that saved it, so that copy shows the change on the next page. Other server copies keep the church at most CHURCH_SECONDS (60 s). The colours are in the page's own <style> (no-store), not the hashed sheet."
related: [2026-11-22-member-page-colour-pictures.md]
---
The office preview and the app now agree on where the highlight shows.
