---
title: Platform Chief (Business Chief) on Sonnet 5.5
date: 2026-10-02
agent: Claude Code (Claude Opus 5.5)
asked: 'yes switch it to sonnet 5.5'
status: shipped
prs: [kmj-intake-server#1194]
migrations: []
left_undone: []
decisions: ['Business Chief stays on the API, not the subscription: $2/month, and a subscription login powering a server is a terms gray area', 'forced-tool creation turns and declines go to Sonnet 4.5']
related: [2026-10-02-agent-findings-on-screen.md]
---
Mission Control's Platform Chief ran on Sonnet 4.5 ($3/$15 per M tokens);
it now runs on Sonnet 5.5 ($2/$10), with temperature dropped and thinking
set to between_tools so it cannot eat the 4,200-token budget. Sonnet 5.5
rejects a forced tool_choice, so "create the flyer" turns go to
PLATFORM_CHIEF_FALLBACK_MODEL (Sonnet 4.5), and a refusal is asked once
more there. Env PLATFORM_CHIEF_MODEL still overrides.
