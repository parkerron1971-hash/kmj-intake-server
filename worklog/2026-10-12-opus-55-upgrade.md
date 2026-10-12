---
title: Upgrade remaining Opus 4.7 and 4.8 workloads to Opus 5.5
date: 2026-10-12
agent: Codex (GPT-6)
asked: "jev uses gpu's? and ok update the models."
status: shipped
prs: [kmj-intake-server#1404]
migrations: []
left_undone: []
decisions: ["Medium effort for migrated design and proxy calls; high for Chief deep and insight only on Opus 5.5", "Keep historical model pricing and explicit rollback overrides", "Do not change JEV or non-Opus provider selections"]
related: []
---
Migrates the remaining Opus defaults in Chief's heavy lanes and Professional
tier, composer specs, studio design/decorations, proxy builds, and the platform
build-model selector. Legacy proxy overrides map to 5.5. Thinking has output
room and effort reaches the pinned Anthropic SDK through extra_body; typed
text extraction is covered with thinking-first responses. The Moonshot
fallback preserves the requested Anthropic effort.

Validation: 121 focused tests passed against anthropic 0.34.2, including
legacy proxy clients and Starter/Professional/Practice effort/budget coverage.
Review caught a cross-tier effort change; only Opus 5.5 now gets the new high
default. The proxy retains its 8192-token total ceiling; large requests have
less room for text if the model spends more on thinking, and the existing
stop_reason reports truncation. These are compatibility tests, not a quality
benchmark. Historical Opus pricing remains for past usage. No database migration.

Production preflight found ATELIER_MODEL=claude-opus-4-8 on both web and worker;
both overrides were updated to claude-opus-5-5 and read back successfully,
without triggering an old-code deployment. They take effect with this release.
Builder, Director/spec-author and design-coach production overrides already
use 5.5. The isolated worktree protects the user's unrelated checkout edits.
