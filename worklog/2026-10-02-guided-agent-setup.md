---
title: Guided agent connection setup
date: 2026-10-02
agent: Codex
asked: "Make agent setup easier before my meeting"
status: in progress
prs: [kmj-intake-server#1199, solutionist-studio#1100]
migrations: []
left_undone: [production deployment, real provider end-to-end check]
decisions: ["No schema migration", "No connection success from a saved profile", "Test sends a fixed greeting only", "Claude Code launcher is interactive, not a background worker"]
---
Added guided connection packaging and a fixed owner-requested assignment test. Existing business permissions and ask-first policy remain unchanged. Connection activity comes from token last-used timestamps and does not promise a running worker. The private ZIP uses a dedicated configuration instead of changing global settings. General ChatGPT pairing and always-on execution remain future work.

Validation: 144 targeted backend tests pass. Frontend live typecheck has zero errors, full-tree typecheck remains at the 14-error baseline, and production build passes. Local browser setup and waiting-for-reply state were checked. ZIP integrity and credential placement were checked with a dummy key. Native-provider execution and mobile visual verification remain unverified.
