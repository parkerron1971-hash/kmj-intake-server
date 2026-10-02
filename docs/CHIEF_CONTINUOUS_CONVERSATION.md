# Chief continuous conversation — 2026-09-29

The fast and full models now share the same conversation personality, selected Chief tone, and recent conversation context. Voice lets the server own its opening and continuation; the local phrase remains the non-streaming fallback. The opener has room for a useful purpose sentence (up to 28 words), with the existing claim/action restrictions and bounded handoff.

The main writer starts without waiting for a separate headline call. Optional habit/relationship/mentor enrichment has a 750 ms deadline on active turns; prewarming still completes it in the background. Core business/financial reads retain their normal behavior. Failed optional sources are recorded as unavailable, never as proof of empty records.

Completed, locally verified sentences stream immediately. The first sentence the deterministic checker cannot prove can get a compact evidence check while generation/final review continue. There are at most two attempts, four seconds each, 256 output tokens each; no retry, repair, tools or unchecked early fallback. Citations still go through the existing provenance/figure validator. Completion claims and action tags never bypass the final action/receipt check. A rejected sentence holds its dependent continuation in order. All checks are cancelled before the final/history payload is assembled or when a turn exits. CHIEF_CONTINUOUS_STREAM=off restores the previous backend behavior.

Short completed voice sentences wait at most 180 ms for grouping instead of waiting indefinitely for another sentence or the final payload. Ordered TTS prefetch, backpressure and interruption remain intact.

[chief flow] logs request ID, first meaningful-content time and largest content gap separately from the first acknowledgment. No conversation text is logged by this metric; no database migration is required.

Validation includes stream-before-final, rejection, cancellation, truth provenance, personality/tenant isolation, context latency and headline bypass tests; voice tests cover short phrases, cancellation and duplicate prevention. The production frontend build and typecheck gates pass (0 live-app errors, unchanged 14 legacy errors).

An opt-in live model smoke test uses synthetic bookings and no business actions: python scripts/chief_stream_smoke.py with the existing provider environment. The successful pre-release sample returned opening words at 724 ms, accepted the supported sentence in 2282 ms and rejected the contradicted sentence in 1634 ms. These are provider-path fixture measurements, not end-to-end app p95 claims. Earlier full-review-shaped checks were too slow; the final implementation uses the compact evidence selector.

More complex operations still take real time. Existing full answer review remains, so the goal is earlier useful output and smaller gaps, not a guarantee that all tasks finish immediately.
