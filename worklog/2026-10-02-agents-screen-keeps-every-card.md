---
title: Agents screen keeps every agent's last run
date: 2026-10-02
agent: Claude Code (Claude Opus 5.5)
asked: 'check it out'
status: shipped
prs: [kmj-intake-server#1188]
migrations: []
left_undone: []
decisions: ['every backend agent writes a platform_agent_runs row on every pass, found or not']
related: [2026-10-02-work-log-and-unfinished-work.md]
---
Found while checking Mission Control → Agents after the new GITHUB_TOKEN went
in. The screen read only the newest 200 run rows, and the support desk writes
288 a day, so by evening the once-a-day agents' cards read "not run yet" and
today's draft count came up short. Cards now fetch the latest run of any
agent the window missed, and drafts are counted by their own read. Trial
expiry only wrote when it ended a trial, so its card could never show a run;
it now records every hourly pass. A new backend agent must write a run row
every pass too, or its card stays "not run yet".
