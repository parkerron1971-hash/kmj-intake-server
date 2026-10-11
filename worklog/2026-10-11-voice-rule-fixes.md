---
title: Voice rules undo, name their text, stop re-proposing; standing instructions block fixed
date: 2026-10-11
agent: Claude Code (Claude Opus 5.5)
asked: "approved to build this... build the best path forward"
status: shipped
prs: [kmj-intake-server#1382, solutionist-studio#1204]
migrations: []
left_undone: ["voice rules fold into the business brain in Layer Two step 2 (business_operating_profiles + chief_proposals); this PR only fixes defects in today's flow"]
decisions: ["a revived STANDING INSTRUCTIONS block carries only the owner's own words (source user_stated); inferred ones stay assumptions in PRACTITIONER MEMORIES", "settings-screen voice-rule changes are audited on every business the owner has, because voice rules are per owner"]
related: []
---
Layer Two step 0 (the Phase 0 audit of the Layer Two handoff, artifact https://claude.ai/artifact/Qt8WBVSnfDvdfW1YiagT88). Fixed the voice-rule defects it found: undo never worked (inverse lacked `list`), removal by index could hit the wrong rule (now by text), the MCP propose tool had no arguments, the ledger kept "Added voice do" without the rule, the settings routes wrote no ledger row, and a chat add left observations so Chief re-proposed. The frontend PR clears observations on a decline too.

Also fixed STANDING INSTRUCTIONS, which had printed the standing permissions since 2026-09-04 because the variable was reused. Before building more here, read the Layer Two plan: voice rules move into the business brain in step 2, so don't extend `practitioner_profiles.voice_dos/donts`.
