---
title: Prepare scheduling catalog reads while the owner is speaking
date: 2026-10-03
agent: Codex (GPT-6)
asked: "Start preparing Chief's request while I am still speaking"
status: in progress
prs: []
migrations: []
left_undone: [Integrated review and CI, coordinated backend and frontend release, live voice latency verification]
decisions: ["Unfinished speech performs only owner-scoped catalog reads", "Final availability always refreshes selected services and scheduling capacity", "Corrections and abandoned turns cannot restore stale preparation"]
related: [2026-10-03-chief-listening-availability.md]
---
Added an authenticated /agents/chief/listening endpoint with bounded partial text, turn UUID, monotonic revision, and explicit cancellation. It reads an active offering catalog only after the exact business and owner are verified under the user's JWT. It never executes actions, reserves appointments, calls a response model, or returns catalog data to the partial-speech client. Final handling may consume matching candidate-search input once; its existing authorization and fresh scheduling checks remain authoritative.

Entries expire after 30 seconds and are bounded to 500. Reads are throttled per user and limited to one active request per user and sixteen per process, with a three-second deadline. Growing partials reuse completed or in-flight catalog work without extending its lifetime. Corrections replace that lineage; cancellation and final consumption close it. Work finishing after a correction, cancellation, or final cannot restore the old entry. Different web workers safely miss this optional process-local cache.

Validation: 16 focused endpoint tests cover authentication, exact owner and business scope, bounded inputs, GET-only preparation, request-context reset, duplicate and corrected revisions, extending partials, cancellation/final races, TTL and entry bounds, request throttling, active-work bounds, timeout cleanup, and optional failures. Provider calls and live records are mocked. No production timing improvement is claimed before the coordinated live voice check.
