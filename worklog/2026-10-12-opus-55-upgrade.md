---
title: Upgrade remaining Opus 4.7 and 4.8 workloads to Opus 5.5
date: 2026-10-12
agent: Codex (GPT-6)
asked: "jev uses gpu's? and ok update the models."
status: in progress
prs: []
migrations: []
left_undone: ["Merge after CI and verify production; update ATELIER_MODEL on web and worker"]
decisions: ["Medium effort for migrated design and proxy calls; high for Chief deep and insight", "Keep historical model pricing and explicit rollback overrides", "Do not change JEV or non-Opus provider selections"]
related: []
---
Migrates the remaining Opus defaults in Chief's heavy lanes and Professional
tier, composer specs, studio design/decorations, proxy builds, and the platform
build-model selector. Legacy proxy overrides map to 5.5. Thinking has output
room and effort reaches the pinned Anthropic SDK through extra_body; typed
text extraction is covered with thinking-first responses. The Moonshot
fallback preserves the requested Anthropic effort.

Validation: 107 focused tests passed against anthropic 0.34.2, followed by
six proxy tests including two new legacy-client migration checks. Historical
Opus pricing remains for past usage. No database migration.

Production preflight found ATELIER_MODEL=claude-opus-4-8 on both web and worker.
Builder, Director/spec-author and design-coach production overrides already
use 5.5. The isolated worktree protects the user's unrelated checkout edits.
