---
title: Chief keeps useful replies after verification and handles thinking pauses
date: 2026-10-02
agent: Codex (GPT-6)
asked: "Check the latest conversation and fix the remaining could-not-confirm wording"
status: shipped
prs: []
migrations: []
left_undone: ["Owner retest after deployment; no new end-to-end latency claim"]
decisions: ["Correct the reply path rather than hiding uncertainty around unsupported facts", "Read simple invoice displays from actual validated rows", "Recover only safe proposed steps or independently supported invoice reminders", "Exact voice hesitations do not search records or emit a waiting opener"]
related: [2026-10-02-chief-conversation-recovery.md, 2026-10-02-chief-invoice-direct-readout.md, 2026-10-02-chief-plan-recovery.md]
---
Reviewed the latest six authorized voice turns after the prior backend and frontend release. The weather answer was useful and interruption metrics reflected the actual outcomes. Remaining issues were a generated invoice self-retraction, a proposed plan withheld over an unrelated factual aside, and incomplete voice fragments prompting unnecessary business-record answers.

Pure invoice-display replies now use validated row data and skip composition/review model calls. Mixed requests keep normal review. Plan receipts prove only display/count, while recovery preserves bounded suggested steps without treating model-authored premises as records. Exact voice hesitations get brief acknowledgments without a model or actions; local waiting openers are suppressed for this feedback path. Scoped authorization and replay checks remain in place.

Four agents covered the three issue areas and independent review. Targeted suites and the final full CI are recorded in the release PR. The prior voice frontend remains deployed unchanged. No migrations or business-record mutations are part of this release; exact production commit and readiness are verified after protected merge.
