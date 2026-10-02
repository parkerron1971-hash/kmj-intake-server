---
title: Reduce measured Chief conversation gaps
date: 2026-10-02
agent: Codex (GPT-6)
asked: "Fix those gaps; make every effort to fix those areas"
status: shipped
prs: [kmj-intake-server#1210]
migrations: []
left_undone: []
decisions: ["Preserve scoped conversation constraints", "Use existing action policy and owner checks", "No global model change", "Only checked card text is released early"]
related: [2026-10-02-chief-invoice-early-read.md, 2026-10-02-chief-invoice-direct-readout.md]
---
The live typed/read-aloud retest measured an approximately 7.9-second invoice
gap and a 21.6-second short-plan gap after the opening sentence. Provider audio
started about 0.17 seconds after text arrived; answer preparation was the bottleneck.

Self-contained invoice displays now use the existing scoped action door without
broad context or a model. Short two-day plans select grounded proposals with one
bounded fast-model request, retain a deterministic fallback, and speak the same
normalized steps shown on screen. The general plan path also avoids duplicate
composition and review when a validated proposal card supplies the entire reply.
General streamed turns overlap independent enrichment with the fresh context
snapshot. Checked invoice and plan speech is released before persistence finishes.

Four specialist agents implemented or independently reviewed these changes.
History, scoped-view and build constraints decline the narrow shortcuts. Rate,
billing, owner, UI policy, metering, audit and replay checks remain in place.
Focused request-level tests exercise denials, conversation constraints, cancellation,
stale warm context, one-execution replay and speech before a blocked archive.
Production speed claims remain pending deployment and a measured retest.

Code release: PR #1210. The production retest and measured results are recorded on the PR after deployment; the changes above do not by themselves establish a latency result.
Validation before release: 366 focused tests passed; full CI is the protected merge gate.
