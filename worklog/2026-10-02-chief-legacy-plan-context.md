---
title: Resolve unrelated history before short Chief plans
date: 2026-10-02
agent: Codex (GPT-6)
asked: "Reduce the remaining legacy short-plan gap without ignoring conversation constraints"
status: in progress
prs: []
migrations: []
left_undone: ["Parent-managed integration and release", "Production legacy-plan timing retest"]
decisions: ["No broader current-request grammar", "Scope approval does not authorize actions", "Uncertain scope keeps the full path", "No assistant claims sent to scope model"]
related: [2026-10-02-chief-conversation-gaps.md, 2026-10-02-chief-plan-invoice-priority.md]
---
A bounded plan-only history classifier can clear unrelated prior invoice, weather
or email discussion for the existing checked proposal path. The exact current
request, mode, images, selected view and build exclusions remain. Fresh business
and owner scope precede the classifier, which runs at most once. Only one exact
approval sentinel is accepted; malformed output, incomplete history, spend denial,
errors and the 2.5-second total guard/provider timeout retain full context.
Standard provider metering records this optional call. Existing candidate selection
is a separate bounded call; this change does not claim a single shared call budget.

Explicit focus/topic/budget/time/exclusion constraints and instruction-like history
are rejected before inference, including in the synchronous eligibility path. Only
exact morning/afternoon/evening opening-control markers are omitted. A user yes to
a topical assistant scope question keeps full context even across intermediate
non-question assistant/debug output. Question shape is inspected locally; assistant
prose never becomes evidence or model input. Weather-retry acknowledgments remain
eligible for semantic classification. Classification is a model judgment about
read-only proposals, not proof that all possible conversational meanings are solved.

Plan-shaped turns defer speculative enrichment until the decision: accepted short
plans skip unused learned/source retrieval; declined scope starts the normal path.
Existing proposal normalization, action policy, audit and replay remain in use.

Validation: 124 focused context, quick-plan, request integration, scope and
preparation tests passed. Real fictional provider checks covered unrelated reads,
an old isolated time fragment, implicit client/topic/time restrictions, explicit
constraints, injection rejection, opening markers and scope acknowledgments.
The representative invoice/weather-retry/noise/email-visibility history was
accepted in 1.66 seconds; its explicit email-only-plan negative was blocked locally.
These were classifier-only checks with no customer records or business actions,
not an end-to-end production latency measurement. Parent owns review and release.

A final sync-route audit restricts the zero-classifier path to recognized plain
invoice/short-plan requests, known control markers, and acknowledgments. Unknown
history such as a truncated named qualifier must resolve or defer, even if an old
keyword guard did not recognize its topic. The live fictional "Please only Ada"
case deferred, while the representative unrelated-history case still cleared.
