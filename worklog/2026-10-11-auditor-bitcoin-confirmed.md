---
title: Auditor portal shows Bitcoin-confirmed anchors as confirmed
date: 2026-10-11
agent: Claude Code (Claude Opus 5.5)
asked: "approved to build this. great plan"
status: shipped
prs: [kmj-intake-server#1380]
migrations: []
left_undone: ["the rest of Layer Two: pricing/metering fixes, voice-rule bugs, turn id + ledger fields, business brain, nightly brain pass, brain in the cache, routing seam, document checks (review artifact https://claude.ai/artifact/Qt8WBVSnfDvdfW1YiagT88)", "the auditor portal still cannot hand over the .ots proof file; only the owner can download it"]
decisions: ["a failed upgrade-cache read marks an anchor 'unchecked', never 'waiting for its block'", "a block link is shown as a block page, with a note that the full check is the .ots file and ots verify"]
related: []
---
Layer Two step 0, from the Phase 0 audit Kevin approved on 2026-10-11. The
auditor portal read only the `.ots` bytes stored at submission. Those never
learn about their own Bitcoin confirmation, which lives in
`ledger_anchor_upgrades`. So auditors were told Bitcoin-confirmed anchors were
"NOT on a durable public network". `_anchor_summary` now reads that cache
through `ledger_anchor.upgrades_for_strict`, which answers None on a failed
read. The page names the block, says "waiting" only when the cache was
actually read, and says "could not be read just now" otherwise.

The same PR brings docs/ACTION_LEDGER.md up to date (Stage 5 is built), adds
the ledger and auditor env vars to `.env.example`, and corrects the
`recall_conversation` MCP description, which claimed meaning-based search; it
is substring search over the last 7 days.
