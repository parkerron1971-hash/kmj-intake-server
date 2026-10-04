---
title: Reliable record-based Chief responsibility reports
date: 2026-10-03
agent: Codex (GPT-6)
asked: "so are you going to fix it?"
status: shipped
prs: [kmj-intake-server#1249, kmj-intake-server#1250, kmj-intake-server#1251]
migrations: []
left_undone: []
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

PR #1250 passed 12,426 tests and deployed as a clean ecb19dc archive. The live
account probe read all 32 items in two pages, but a second chat replay still
withheld the model summary over ungrounded date/ordinal claims. Preserving the
evidence alone is insufficient to make this fixed report dependable.

The final route renders the exact report shortcut directly from a fresh,
owner-scoped snapshot, following the existing scheduling-readout pattern.
It runs after admission and JWT binding but before recurrence, sweeps, general
context or a prose model. Typed record counts/statuses determine the answer;
missing sources, limits and next-check uncertainty remain explicit. Titles are
literal, bounded text; action-like/instruction-like titles are omitted. Normal
and mixed requests retain the ordinary model and answer checker. Stream replay
remains owner-scoped and the returned report is archived normally.

Validation: 91 integration/report/scheduling/invoice tests passed, including
cross-business denial before reads/replay, all 32 rows, partial/unavailable
sources, unsafe titles, no model/housekeeping/actions, and stream/final equality.
A read-only live-data probe produced all 32 KMJ rows in a 2,023-character report.

Final verification: #1251 passed full CI (12,437 tests, 17 skipped, one expected
failure, plus SQL checks) and merged as 873125a. Both Railway services deployed
the clean archive successfully. The running web files match that commit's
SHA-256 hashes; readiness and the scheduler lease are healthy. At 2026-10-04
00:39 UTC the actual signed-in KMJ shortcut returned all 32 work items (21
background records and 11 approvals), their statuses and no recorded next
checks. The direct route completed in 1,826ms with zero model tool calls and no
blanket verification error. No approvals, sends, retries or website work were
performed. Receipt: docs/CHIEF_REPORT_FIX_RELEASE.json. No runtime work remains.
