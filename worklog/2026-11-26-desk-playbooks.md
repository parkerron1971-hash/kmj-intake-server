---
title: Desk playbooks for KAI's workers
date: 2026-11-26
agent: Claude Code (Claude Opus 5.5)
asked: "specialist desks: KAI attaches a desk's playbook to every worker it opens in that area"
status: waiting on Kevin
prs: [kmj-intake-server#2094]
migrations: []
left_undone: ["Solution Space attaches docs/desks/<id>.md from origin/main to a worker's brief on the local claude-bench branch kai-desks-and-phone; live once Kevin runs that branch"]
decisions: ["nine fixed desk ids: member-app, church-office, chief, websites, money, messaging, live-media, system, tickets", "the playbooks are knowledge, not policy: CLAUDE.md and AGENTS.md win where they disagree", "tickets diagnoses and hands off; it never fixes code itself"]
related: []
---
Docs only. `docs/desks/README.md` is the map (id, what it owns, routing
keywords, repos) and how KAI uses it; one playbook per desk under
`docs/desks/`: what it owns, where the code is in both repos, the rules
that must not break, the traps already hit, how to check work, and the
edges with other desks. Every path in them was checked against the repos
on the day they were written. A worker that finds a playbook wrong fixes
it in the PR that found it out.
