---
title: Pure invoice displays skip context and model planning
date: 2026-10-02
agent: Codex (GPT-6)
asked: "Fix the measured conversation gaps"
status: shipped
prs: [kmj-intake-server#1210]
migrations: []
left_undone: []
decisions: ["Exact whole-message invoice display only", "Authenticated scoped business and owner IDs must match", "Existing admission, recurrence, action policy and replay checks remain"]
related: [2026-10-02-chief-invoice-direct-readout.md]
---
The prior deterministic readout still waited for broad business context and
model calls that selected the invoice display and narrated it. Pure invoice
display requests now translate directly to the existing show_view action after
rate/billing checks, recurring-invoice preparation, and the scoped business read.
The shortcut requires an exact business/owner match; collaborator seats, mixed
requests, analysis, images and coach modes retain the existing path.

Execution still passes through _execute_actions and its policy checks. The
reply uses the existing validated card readout, with deterministic failure
reporting and no fallback that could execute the display twice. Archive,
activity, audit and user-scoped stream replay remain intact. The branch returns
before global context and optional enrichment tasks are started.

Endpoint tests prove zero main-model/global-context calls for qualifying
requests and preserve billing/rate refusals, owner isolation, policy denial,
failed-read semantics, streamed step receipts and one-read replay. No private
records or model providers are used in the tests. Production timing improvement
requires the follow-up deployed voice test; no fabricated milliseconds are used.

Validation: 187 invoice shortcut/readout/recovery, call-feedback, replay and
display tests passed, including denial of cached replay after owner revocation.
