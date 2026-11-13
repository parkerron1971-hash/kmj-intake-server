---
title: CI runs the test suite in four parts side by side
date: 2026-11-13
agent: Claude Code (Claude Opus 5.5)
asked: 'is it possible to have more than one way to merge through github because it''s like agents are waiting on another to push through therefore the process seems to take much longer / yes do it'
status: in progress
prs: ["kmj-intake-server#1819"]
migrations: []
left_undone:
  - "The parts are weighed by how many tests each file defines, not by how long they take. If one part keeps finishing last, weigh by the --durations output instead."
decisions:
  - "Kevin turned off 'Require branches to be up to date before merging' on main's ruleset (he saved it himself, 2026-11-13). The required check is still `test`."
  - "The suite runs as four jobs (test-part, a matrix) on the same commands as before, each given its test files by scripts/shard_tests.py: every file in exactly one part (checked in each job), the heaviest files first to the lightest part. The four parts collect 21,900 tests together, the same as one full run."
  - "The database checks (the node *_db.mjs list) run in their own job beside the parts; they never needed Python."
  - "The job named `test`, which the ruleset requires, waits for every part and the database checks and passes only when all of them passed (if: always(), so a failed, cancelled or skipped part fails it)."
  - "Byte-compiling and the Chief computer sabotage check run once, in part 1."
  - "The script is shard_tests.py, not test_*.py, so a bare `pytest` never collects it."
related: [2026-11-13-church-mail-room.md]
---
Agents' PRs were waiting on each other: every merge put the others behind
main, and each then re-ran a 20-minute suite. Kevin turned off the "up to
date" requirement, and the suite now runs in four parts at once.
