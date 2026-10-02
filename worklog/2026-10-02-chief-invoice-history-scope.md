---
title: Preserve invoice scope without long conversation preparation
date: 2026-10-02
agent: Codex (GPT-6)
asked: "Fix the remaining conversation gaps after retesting"
status: in progress
prs: []
migrations: []
left_undone: ["Integration and production retest", "Complex plan history remains on the general path"]
decisions: ["Read-only exact invoice displays only", "Preserve explicit owner scope", "Hard constraints defer before paid work", "Owner and replay checks precede model work"]
related: [2026-10-02-chief-conversation-gaps.md, 2026-10-02-chief-invoice-early-read.md]
---
The existing fresh-conversation invoice shortcut was already deployed. Its conservative history guard forced repeated displays through the full model path, and a plain earlier all-invoices request could lose its scope. A bounded fast-lane scope check now preserves supported owner filter/form choices across unrelated conversation. It can select only the existing invoice view; unsupported client, date, amount, negated or ambiguous scope defers to the general path. Actual rows still come through the scoped action handler and checked readout.

The 2.5-second deadline includes spend checking and the provider. Invalid, contradictory, capped or timed-out output never guesses a scope. Exact owner and completed replay checks run first. Known opening-greeting markers carry no scope authority; other internal markers defer. Accepted assistant scope questions and truncated qualifier follow-ups cannot bypass preflight. Other meaningful unclassified owner history must pass the bounded resolver even if the old direct shortcut appears eligible.

Validation: 144 focused tests passed. Three fictional live configured-fast-model cases preserved prior all/list (1477 ms), explicit current open/list (515 ms), and prior paid/chart (464 ms). Named-client and truncated-qualifier cases deferred before a provider call. These are scope timings, not end-to-end voice measurements. No customer records were changed; live provider usage used standard metering.

Follow-up review covered the complete descriptive email-visibility discussion and the exact read-only short-plan request between invoice displays. The guard recognizes only complete email permission clauses or the existing whole quick-plan grammar as separate operations; qualifiers in another clause still defer. The full fictional history resolved all/list in 1457 ms, and retained all/list after the read-only plan in 435 ms. Explicit current open resolved in 539 ms. Request-level regressions verify these sequences avoid broad context and the main model while preserving invoice scope.
