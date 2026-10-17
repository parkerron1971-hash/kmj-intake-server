---
title: CI runs the backend test suite across the runner's cores
date: 2026-10-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "we need to speed up the process… small things like this shouldn''t take for ever to merge"; then "Yes, try it" to running the backend tests in parallel'
status: shipped
prs: [kmj-intake-server#1471]
migrations: []
left_undone: []
decisions:
  - "pytest-xdist with -n auto (the public repo's ubuntu runner has 4 cores) and --dist loadfile, so each test file keeps its module fixtures and its own order on one worker"
  - "--durations=10 in the log, so the slowest tests are visible for the next cut"
related: [2026-10-17-cut-jpeg-flake.md]
---
The `test` job took about 7.5 minutes. Most of that was pytest: 16,448
tests in 344 s, one process at a time. Install took 26 s, Chromium 20 s
and the storage checks 39 s. The job now runs the suite with one worker
per core. Each test file stays on one worker, so a file's module fixtures
(the real app, the rendered site) build once and its tests keep the
order they were written in. The PR's own CI run is the measurement.
