---
title: Preserve paged Chief responsibility evidence for answer verification
date: 2026-10-03
agent: Codex (GPT-6)
asked: "so are you going to fix it?"
status: in progress
prs: [kmj-intake-server#1249]
migrations: []
left_undone: [production deployment and signed-in KMJ report replay]
decisions: ["Keep every report page as read evidence", "Do not weaken the answer checker or turn reads into action receipts", "Distinguish page counts from source totals"]
related: [2026-10-03-chief-follow-through.md]
---
The KMJ owner clicked the shipped report shortcut. Six native report reads ran,
but the final answer was withheld: a draft count and a site-job progress number
could not be checked. All report reads shared one evidence key, so the last
page/filter replaced every earlier page before review. The earlier rollout
check used a smaller fixture business and missed this multi-page case.

Give responsibility evidence a source-and-offset key while leaving other read
replacement behavior intact. Return explicit scope, source counts and page
counts alongside the existing partial/unavailable flags. Read both repository
worklogs first; this change does not touch the parallel MySite work.

Regression coverage runs six reads through the real native dispatch and answer
evidence budget: earlier drafts, counts and job progress remain verifiable;
invented counts still fail; a failed later page preserves the earlier page;
new turns inherit no report evidence. No migration is required.

PR #1249 passed full CI (12,425 tests) and merged as 37a7563. The automatic
deployment did not start; manually deployed a clean git archive of that exact
commit to web and worker. Both running files match the archive's SHA-256 hashes;
readiness and the scheduler are healthy, and durable recovery remains enabled.
The signed-in KMJ replay returned a verified, explicitly partial answer instead
of the blanket error, but stopped at six of 32 items. This exposed a second
limit: small pages compete with the normal three available tool-reading rounds.

The follow-up uses bounded 16-item pages below the reviewer's per-source cap and
directs full reports to follow next_offset before answering. A 32-item regression
checks that all rows fit the native reading rounds and remain intact review
evidence. The normal tool budgets and unsupported-claim checks remain enforced.
