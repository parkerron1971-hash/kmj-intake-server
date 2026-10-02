---
title: Agent findings readable on the Agents screen
date: 2026-10-02
agent: Claude Code (Claude Opus 5.5)
asked: 'where is the log where i can read each agent found and how to fix it?'
status: shipped
prs: [kmj-intake-server#1192, solutionist-studio#1093]
migrations: []
left_undone: []
decisions: ['findings stay in platform_changelog (agent=...); the screen reads GET /platform/agents?agent=&limit=']
related: [2026-10-02-hermes-says-it-once.md]
---
The Agents at work rebuild (FE #1092) dropped the old "Recent findings" list,
and even that list showed titles only: the detail (what is wrong, what to do)
was stored but shown nowhere. GET /platform/agents now takes ?agent= and
?limit= (max 100); the Agents screen gets a "What they found" section with
each finding's full write-up, a needs-you flag and an agent filter.
GitHub agents' findings stay where they are written: issue and PR comments,
reached by each card's Open link.
