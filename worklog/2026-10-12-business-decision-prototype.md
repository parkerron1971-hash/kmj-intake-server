---
title: Local CPU business decision model prototype
date: 2026-10-12
agent: Codex (GPT-6)
asked: "ok create it and test it. don't spend to much money"
status: in progress
prs: [kmj-intake-server#1406]
migrations: []
left_undone: ["Production integration is outside this local prototype; independently evaluate representative examples before considering rollout"]
decisions: ["No paid API calls or Railway deployment", "Standard-library Naive Bayes model trained only on fictional examples", "Scores are not calibrated confidence", "Return recommendations only; never send, book, cancel or charge", "Keep existing Chief business memory and provider routing unchanged"]
related: [2026-10-11-business-brain.md, 2026-10-11-lane-registry.md, 2026-10-12-privacy-says-how-chief-learns.md]
---
Built and tested the requested prototype in prototypes/business_decision:
trained JSON weights, typed decision engine, CLI, loopback HTTP demo, reproducible
training/validation/test splits, keyword baseline, functional tests and a bounded
CPU/memory/HTTP benchmark. Backend and frontend worklogs showed existing business
memory/rules work, so this tests a separate local learned classifier rather than
rebuilding those features. No customer data or production integration.

20 functional tests passed. On 60 held-out fictional messages the model handled
20 locally with no incorrect local decisions, deferring 40 (11 unnecessarily).
Overall route/intent accuracy was 49/60, below the baseline's 51/60; the baseline
made four incorrect local decisions. Same-author synthetic data is not a customer
accuracy or savings claim. About 38 MiB process memory; 1,500 local HTTP requests,
including 25 concurrent requests, completed with zero errors. Full evidence and
limitations are in RESULTS.md and the artifact reports.

Prototype work is complete locally; retained as a draft PR for review, not merged
or deployed. Paid model/API and added hosting spend for this work: $0.
