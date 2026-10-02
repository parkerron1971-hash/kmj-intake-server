---
title: Agents that run the platform, waves 1 and 2
date: 2026-10-01
agent: Claude Code (Claude Opus 5.5)
asked: "I need to develop agents that can help run this business ... map that out and get everything ready"
status: shipped
prs: [kmj-intake-server#1130, kmj-intake-server#1131, kmj-intake-server#1132, kmj-intake-server#1135, kmj-intake-server#1147, kmj-intake-server#1148, kmj-intake-server#1149, kmj-intake-server#1150, kmj-intake-server#1174, solutionist-studio#1064, solutionist-studio#1065, solutionist-studio#1066, solutionist-studio#1074]
migrations: [supabase/APPLY-2026-10-01-stripe-webhook-events-shape.sql (applied)]
left_undone: []
decisions: ["one brain, many senses: most agents are watchers with no AI", "code agents run on GitHub through the Claude app, not personal routines", "on-call diagnoses only and never merges", "Sentry errors only, no session replay"]
related: [kmj-intake-server worklog 2026-10-02-agent-operations-wave-3-and-more.md]
---
The plan is the "Solutionist Agent Operations" artifact
(https://claude.ai/artifact/995CQvhpmSPTNQUDAGU2ee). Wave 1: deploy checker
(backend /health reports its commit; both repos check every merge went live),
on-call (GitHub, diagnosis only, pre-gathered evidence, reads Sentry), the
watchdog files real failures as incidents, Sentry on in backend and app, and
the 28 nightly What's-New PRs folded into one rolling PR. Wave 2: the Money
auditor (daily, compares every subscription with Stripe), the PR reviewer in
both repos, and the Stripe webhook table fixed so events record and replays
are caught. Check the Agents page in Mission Control before adding another.
