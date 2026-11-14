---
title: The founding line says when the offer ends, not when the price does
date: 2026-11-14
agent: Claude Code (Claude Opus 5.5)
asked: "BE-5 flagged that 'keep the founding price for as long as they stay, until January 31' could read as the price ending January 31."
status: shipped
prs: [kmj-intake-server#TBD]
migrations: []
left_undone: []
decisions:
  - "The sample church's emails now say 'The first ten churches keep the founding price for as long as they stay. The offer ends January 31.' Two sentences, so the date is the offer's end. The live /churches band already says it that way, and the app's Start sheet gets the same fix in its own PR."
related: [2026-11-15-sample-church-be5.md]
---
A copy fix to `lifecycle_emails.founding_line`.
