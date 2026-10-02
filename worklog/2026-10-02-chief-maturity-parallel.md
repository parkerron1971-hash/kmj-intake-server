---
title: Chief maturity cache misses load independent signals together
date: 2026-10-02
agent: Codex (GPT-6)
asked: "Fix the remaining measured gaps in Chief conversation latency"
status: in progress
prs: []
migrations: []
left_undone: [Independent review, full CI, production deployment and latency verification]
decisions: ["Bound maturity signal reads to five shared workers and join them before returning", "Keep six-hour cache, stage thresholds, business scopes, and settings writes unchanged"]
related: [2026-10-02-chief-conversation-gaps.md]
---
A slow post-deploy Chief context load included maturity-cache recomputation. Its five independent service-role reads now overlap through a shared bounded executor. Each read receives its own copy of the caller's request context. Unexpected errors still propagate after all submitted reads finish; missing rows still produce zero signals. Cache settings are reread and written only after complete signal collection, as before.

Validation: 22 focused tests pass across test_maturity_parallel_reads.py and test_lgs_phase2_maturity_voice.py. Synchronization barriers prove overlap without elapsed-time assertions. Tests cover exact business filters and results, caller context isolation, fresh-cache short circuit, settings preservation and write ordering, soft failures, exception drainage, and nonfatal cache-write failures. No live records or cache values were changed. This reduces serial read latency on cache misses; it does not establish a production timing improvement or alter other context loading.

