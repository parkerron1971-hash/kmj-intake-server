---
title: Local CPU business decision model prototype
date: 2026-10-12
agent: Codex (GPT-6)
asked: "ok create it and test it. don't spend to much money"
status: stopped
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

## Resume handoff — saved October 13, 2026

Kevin asked: "save this so we can pick this back up later". Work is paused at
his request; the local prototype is complete. Do not deploy or start paid
experiments just to resume the conversation. His standing preference is to keep
costs low. No Railway service, paid inference connection, or recurring job was
created for this prototype.

- Draft PR: https://github.com/parkerron1971-hash/kmj-intake-server/pull/1406
- Branch: `codex/business-decision-prototype-20261012`
- Local checkout: `C:\Users\kmccl\kmj-intake-server\output\business-decision-prototype`
- Start with `prototypes/business_decision/README.md` and `RESULTS.md`.
- Trained weights and raw evidence: `prototypes/business_decision/artifacts/`.
- Full repository CI **passed** on commit `276299fe73863a5f997ca94678ec406c1519e641`,
  run `38306523971`, confirmed October 13. The live paid evaluations and draft
  model-review workflow were skipped. This handoff changes documentation only.

From that checkout, run the existing demo without paid calls:

```powershell
python -m prototypes.business_decision demo
python -m unittest prototypes.business_decision.test_prototype -v
```

When Kevin resumes, first check the PR state and current worklogs: other work
continues in this repository. The original root checkout contains unrelated
user edits; keep working in the isolated checkout or a fresh worktree.

The next useful product step is to choose one actual business workflow and
evaluate the frozen model on new, independently authored/labeled scenarios.
Compare accepted-decision errors and coverage with the rules baseline. If
improving the model, use new development examples and preserve an untouched
evaluation set. The existing test set has already been inspected. Customer
training data is outside this prototype and conflicts with the current policy's
no-customer-training promise; fictional examples were used throughout.

Only after quality warrants it should a separate deployment decision consider
an authenticated internal Railway service and measured capacity. The earlier
"500 light users for $6-$10 extra/month" was a planning assumption, **not** a
validated Railway cost/capacity result. Local burst measurements and 20 correct
accepted synthetic examples must not be presented as production guarantees.
