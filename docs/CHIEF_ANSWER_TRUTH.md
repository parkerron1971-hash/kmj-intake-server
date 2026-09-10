# Chief answer checks

Chief now checks its final answer against the evidence available on the turn before returning it to chat, speech, or conversation history. Failed actions produce an execution-result reply. Unsupported answers and unavailable reviews produce an uncertainty response; successful write receipts can still report the actual result.

## Repairs in audit order

1. Fix `_compose_post_action_reply` to unpack `(actions, cleaned_text)` correctly. An empty correction falls back to execution results instead of the original optimistic draft.
2. Hold model prose during streaming. Server progress statuses still stream, followed by one checked answer delta and the same final response. Audio cannot speak an earlier draft that later gets corrected.
3. Add a final evidence check for ordinary answers, native writes, tag actions, coach replies, and fallback prose. The reviewer must cite supplied source IDs and exact excerpts; action claims require write receipts. Failed actions override prose deterministically. The old phrase detector remains a retry aid, not the factual verification boundary.
4. Derive legacy memory provenance from the authenticated owner's current words rather than the model's `source` field. Render source and historical dates, preserve unknown dates on semantic recall, and retain uncertainty in playbook summaries. Exact normalized deduplication preserves corrections involving negations or changed numbers. Existing rows are not rewritten.
5. Fetch exact contact and module counts through scoped PostgREST HEAD requests. Preserve the user's JWT and never retry a rejected user token as service role. Unknown counts stay unknown; fetched lists, status breakdowns, and truncated tool results are explicitly samples. Carry failed-source and retrieval metadata.
6. Preserve bounded evidence per turn, require source-backed factual answers, expose read tools in coach mode, and treat unavailable lookups explicitly. Recognize the audited instruction to falsify ledger totals. Retrieved content remains untrusted, including text sent to the reviewer. Raw business settings and profile rows are excluded from the review payload.
7. Add a factual evaluation separate from action selection, including nonexistent records, ambiguous names, missing data, conflicting memories, stale research, over-cap counts, injected instructions, failed sends, queued work, and missing receipts. Add regression coverage for the actual streaming and fallback boundaries.

## Verification and operation

Run offline regression tests with `python -m pytest -q __tests__ agents`. Run the 24 injected-output replay checks with `python scripts/chief_factual_eval.py --out chief-factual-report.json`. Replay checks validate known inputs and the enforcement contract; they do not measure model hallucination frequency.

For generated answers and real review, run `python scripts/chief_factual_eval.py --live --out chief-factual-report.json` with `ANTHROPIC_API_KEY` configured, or dispatch CI with `chief_eval=true`. The live factual harness uses synthetic evidence and does not access a business database or send messages. It measures answer generation and review, not the complete authenticated production conversation. The existing action evaluation remains separate. A scenario named `backup_unverified_claim` tests unverified fallback-style prose; it does not force a second provider outage.

The review is one tool-free, metered model call using the chat lane, subject to the spend guard and a 30-second outer timeout. Its input is bounded to 60,000 evidence characters plus a 16,000-character draft; review output is capped at 2,400 tokens. Chat timing now includes `actions` and `review`. The response includes `grounding.status` (`supported`, `receipts`, or `withheld`) and cited source IDs. Logs record status and citation counts without answer content.

There is additional model cost and a wait for review before conversational text or speech begins. Server progress remains available during the wait. Review outages withhold prose; they do not undo actions already performed. No database migration is required.

## Remaining limits

Exact source/quote and numeric checks reject fabricated provenance, but semantic agreement and full coverage of nonnumeric claims still depend on the reviewer model. A real quote can be irrelevant or misleading, and two models can make related mistakes. Missing evidence and strict review can also withhold an otherwise correct answer. Legacy memories remain historical and unverified until independently checked. These repairs reduce specific demonstrated risks; a lower numerical hallucination rating requires live evaluation and production observation.
