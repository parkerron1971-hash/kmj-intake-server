---
title: "The nightly brain pass runs on the lane seam"
date: 2026-10-11
agent: Claude Code (Claude Opus 5.5)
asked: "awesome. continue (Kevin, 2026-10-11, after the Layer Two build)"
status: waiting on review
prs: [kmj-intake-server#1391]
migrations: []
left_undone: ["the background lane is not routed anywhere: that needs the replay bench (workstream G), a listed subprocessor (#1390) and Kevin's yes", "other background callers still call llm_call.post directly"]
decisions: ["the 3c per-run cap holds for the dearer of the routed model and the Claude fallback, and the failure names that model", "chief_reflection_runs.model and cost_cents name the model that actually answered"]
related: [2026-10-11-lane-registry.md, 2026-10-11-business-brain.md, 2026-10-11-lanes-only-to-listed-providers.md]
---
The nightly brain pass is the natural first candidate for a cheaper lane (no tools,
no caching, thinking off, JSON out). It now calls llm_call.post_lane("background"),
so moving it is a config change. With no lane configured, it is the same Haiku 5.5
call as before.
