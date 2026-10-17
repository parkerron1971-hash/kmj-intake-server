---
title: The ownership sweep runs four times faster, and its billing tests share one pass
date: 2026-10-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "we need to speed up the process… small things like this shouldn''t take for ever to merge"; then "Yes, try it" to faster CI'
status: shipped
prs: [kmj-intake-server#1472]
migrations: []
left_undone: []
decisions:
  - "_segment reproduces ast.get_source_segment over lines split once per file, the way the parser splits them (only \\r\\n, \\r, \\n); proven equal on tricky input and five real files, and the whole sweep's output is identical"
  - "test_billing_surface_audit's three sweep() calls share one module-scoped result"
related: [2026-10-17-ci-parallel-tests.md]
---
With CI running in parallel (#1471), the slowest tests set the pace: the
three billing-audit tests (~80 s together, one file, one worker) and the
church care-counts guard test (31 s). Each called ownership_sweep.sweep().
Profiled, a quarter of a sweep was ast.get_source_segment re-splitting the
whole file for every one of ~12,000 functions. Splitting once per file
cut a full sweep from 36 s to 8.6 s locally, and the output over all 841
modules is identical (810 handlers, 46 unguarded). The billing tests now
share one sweep.
