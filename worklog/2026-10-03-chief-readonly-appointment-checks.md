---
title: Deterministic read-only appointment availability checks
date: 2026-10-03
agent: Codex (GPT-6)
asked: "Prepare while speaking and eliminate scheduling repair loops"
status: in progress
prs: []
migrations: []
left_undone: ["Protected release and production voice retest"]
decisions: ["No model calls or booking writes", "Use canonical joint capacity rules", "Fresh calendar and offering validation at final check", "Unknown historical constraints defer"]
related: [2026-10-02-chief-invoice-history-scope.md]
---
A bounded appointment checker recognizes explicit read-only requests, computes relative dates in the business timezone, disambiguates service names, and checks proposed appointments together against the canonical scheduling engine. Results include saved business hours, lead time, capacity, booking durations, and outside-calendar busy blocks. All database calls are GETs. Missing, malformed, incomplete, or timed-out evidence cannot become a free-slot claim.

Listening preparation supplies only a short-lived candidate catalog. Final reads revalidate current matching names, selected IDs, active state, and duration, including newly ambiguous services. The full read group has a six-second deadline and drains concurrent tasks. Exact morning/meridiem and service-choice replies can continue deterministic clarification chains without losing the original request. Arbitrary prior constraints, extra tasks, and unsupported wording remain on the full conversation path. CHIEF_AVAILABILITY_CHECK=off disables this route.

Validation:94 focused availability, independent pagination, listening, and canonical-engine checks passed. Cases cover joint proposed overlap, existing occupancy, outside-calendar conflicts, invalid saved data, timezone/date and DST ambiguity, fresh service changes, no writes, cancellation, and safe clarification continuations. Live read-only schema checking identified and removed an obsolete booking duration column from this new query. Production end-to-end voice timing is measured separately by the integrating session.
