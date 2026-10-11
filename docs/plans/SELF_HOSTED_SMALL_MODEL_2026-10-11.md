# Self-hosted small model: design note and trigger

Layer Two workstream E, 2026-10-11. **Design only. Nothing here is built or
deployed, and no GPU spend is approved.** The question: when would running an
open-weight small model on our own pay-per-use GPU be cheaper than renting the
small lanes from a provider, without losing quality?

## The answer today

Not for a long time. The lanes a small model could take already run on the
cheapest rented model, and they cost under a dollar a month for the whole
platform. Self-hosting has a floor cost in the hundreds of dollars a month.
The meter puts the crossover thousands of times away.

## Candidate lanes

Low-judgment work where a small model could plausibly hold quality:

| Lane | Today | 30-day metered spend (probe, 2026-10-11) |
|---|---|---|
| Opening line (`opener`) | Haiku 5.5 | 210 calls, $0.36 |
| Headline sentence (`fast`) | Haiku 5.5 | 25 calls, $0.09 |
| Router tie-breaker (`route`) | Haiku 5.5 | 14 calls, $0.01 |
| Background helpers, nightly brain pass (`background`) | Haiku 5.5 | new; about 0.1¢ per business per night |
| Embeddings (memories, inference cache) | OpenAI text-embedding-3-small | negligible ($0.02 per MTok) |
| Transcription (recap voice memos) | gpt-4o-mini-transcribe | small, per minute |

Not candidates yet: Chief's main reasoning, the answer check (it decides what
the owner is told; it stays on Sonnet per the 2026-10-07 replay bench), vision,
and anything that writes words a client reads.

Source: `C:/Users/kmccl/chief-eval-tools/l2_cache_probe.py` (read-only, totals
only). Whole-platform Chief spend over the same 30 days was $83, across 7
businesses.

## The floor of self-hosting

Typical list prices; verify before acting on them.

- **Always on.** One mid-size GPU (L4 / A10G class) at roughly $0.70–1.10 an
  hour is about **$500–800 a month**, before redundancy, monitoring and the
  engineer time to keep it patched.
- **Scale to zero.** Pay-per-second serverless GPUs avoid the idle cost, but
  a cold start takes seconds to tens of seconds. That breaks the opener's
  500 ms first-word target (docs/MODEL_ROUTER.md). It could fit the nightly
  pass, which isn't latency-bound, but that lane costs about two dollars a
  month.

## The trigger

Move a lane off a rented model only when **all three** hold:

1. **Spend.** The candidate lanes' metered spend is at least **2× the
   always-on floor (about $1,000–1,600 a month) for three months in a row.**
   Read it from `api_usage` grouped by lane (the `lane` column from the Layer
   Two migration).
2. **Quality.** The self-hosted model matches the current model on the
   lane's replay bench (record real calls, replay them, grade them). This is
   the Layer Two lane-graduation step (workstream G), run offline, never on
   customers.
3. **Seam.** The lane can point at an OpenAI-compatible endpoint through the
   `llm_call` lane registry (workstream D) with a fallback to the rented
   model. Then the move is a config change you can undo.

Today the spend test is about 2,000× short. Even at 1,000 active businesses
with today's usage per business, the candidate lanes would cost tens of
dollars a month.

## What would change the math

- A new high-volume, low-judgment lane, such as bulk extraction from documents
  or receipts at scale. Re-run the probe when one ships.
- Rented small-model prices rising. They have only fallen, and each new cheap
  model pushes the trigger further out.
- A privacy requirement no provider can meet. That is a reason to self-host
  regardless of cost, and it would be decided as a product decision, not by
  this meter.

## Later, mention only

- **Per-vertical adapters (LoRA)** on a small open model, trained only on
  de-identified data from the interaction record (workstream C). This needs
  consent language that covers improvement (not in the 2026-08-23 policy) and
  a separate de-identification pipeline. Never per business, never on raw
  tenant data, never therapist data.
- **On-device transcription** for recap voice memos (Whisper-class models
  in the browser via WebAssembly; no GPU). Mainly a privacy feature for
  sensitive verticals: audio never leaves the device. Expect slower,
  somewhat less accurate transcripts on older phones.

## Where independence actually comes from

None of this needs a GPU:

- **The brain we own:** owner rules, the nightly digest and versioned brains
  (`business_brain.py`, `chief_brain_pass.py`). A better rented model reads
  the same brain and gets better for free.
- **Capabilities:** tested, deterministic tools that do work no model is paid
  for (`docs/LAYER_TWO_CAPABILITIES.md`, the booking rehearsal).
- **The routing seam:** any lane can switch provider by config.
- **The ledger:** proof of which brain and model acted, anchored publicly.

Review this note quarterly by re-running the probe.
