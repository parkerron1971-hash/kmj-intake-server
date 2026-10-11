---
title: Metering fixes - unknown models loud, missing price rows, 1-hour cache writes at 2x
date: 2026-10-11
agent: Claude Code (Claude Opus 5.5)
asked: 'approved to build this (Layer Two plan, step 0a)'
status: shipped
prs: [kmj-intake-server#1379]
migrations: []
left_undone: ["confirm the Kimi K3 price ($3/$15 per MTok) against Moonshot's own page or an invoice", "confirm the GPT-5.4 price ($2.50/$15 per MTok) on openai.com or an invoice", "confirm whether ElevenLabs bills plan credits ($25 per 1M chars, what the Flash and Turbo rows use) or the public pay-as-you-go card ($50 per 1M); if the card, double both rows"]
decisions: ["a model with no price row is priced at the top current Claude list price (Fable, 1000/5000 cents per MTok) and printed once per process, never silently at another model's price", "direct provider cost rows (DALL-E, the GPT validator) are written with units=0 so they never charge credits"]
related: []
---
Layer Two step 0a. The Phase 0 audit found spend counted low or not at
all. Fixes: unknown models are priced at Fable rates and printed; rows
were added for eleven_flash_v2_5 (the default voice model, ~8x low before),
kimi-k3, gpt-5.4, claude-fable-5-1 and claude-mythos-5-1; 1-hour cache
writes are priced at 2x on the sync path (every llm_call seam row) and in
the route ledger; the GPT-5.4 decoration validator and DALL-E now write
api_usage cost rows the spend guard can see. Before adding a new model
anywhere, add its row in api_usage_logger.MODEL_PRICING_CENTS first.
