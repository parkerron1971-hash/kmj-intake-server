---
title: The eyes have room to finish, and words off the side of a phone are caught
date: 2026-11-09
agent: Claude Code (Claude Opus 5.5)
asked: "yes you can test it"
status: shipped
prs: []
migrations: []
left_undone: []
decisions:
  - "Marquees, swipe strips, off-canvas menus and anything animating are meant to run off, so they are not measured."
related: [2026-11-09-scenes-survive-the-builder.md]
---
Three real test builds found this. On the barbershop page the eyes ran out of tokens on
both looks, so the page shipped unseen, with a heading running off the side of the phone.
A page that hides sideways scroll passes a width check, so the render now measures words
past the edge directly. The marker object also wraps on a phone now.

This is live for every build: it is a fix, not a switched feature. A verdict that used
to come back cut off now finishes, which costs at most about $0.08 more per look.
