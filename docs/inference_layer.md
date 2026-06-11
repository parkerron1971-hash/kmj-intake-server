# Hybrid Inference Layer — Design + Phase B Implementation (Arc 20B Part 9)

**Status:** 9.1 design (this doc) + 9.2–9.4 SHIPPED (semantic cache, routing gate, telemetry). 9.5 local hosting assessed and **deferred** (see §6 — Railway cannot host it; alternatives named). 9.6 pattern learning acknowledged as Phase C+ (schema is ready for it).
**Budget posture:** v1 ships at **$0–5/month incremental infra** (pgvector rides the existing Supabase; embeddings are ~$0.02/1M tokens) — far inside the $50–100 ceiling, leaving the whole budget for the local-model phase when the data justifies it.

---

## 1. Audit — every place Anthropic gets called

| Call site | Surface | Frequency | Cacheable? |
|---|---|---|---|
| `chief_of_staff._call_claude` (`/agents/chief/chat`) | Main Chief conversation | Highest | **NO in v1** — answers are state-dependent (books, bookings, history). Caching conversational replies returns stale business state — the one unforgivable failure mode. Cost here is attacked by PR1's prompt-cache split instead. |
| `ai_proxy` (`/ai/proxy`) | Frontend task calls (`task_type`: plan/build/score/draft/volume/briefing) | High | **YES, per task_type allow-list** — scoring/classification tasks repeat heavily. |
| `chief_llm._call_claude` | Bookkeeping Chief (ask-transaction, analyze-hard) | Medium | **YES** — "what is this Adobe charge" repeats across months and (eventually) tenants. |
| `hero_composer._call` / Director loop | Site generation | Low | **NEVER** — creative work must not converge (anti-convergence is a DRL requirement; a cache here would fight it). Excluded by design. |
| `notification_engine`, agents/* | Briefings, drafts | Low-medium | Later — same gate slots in. |

**Gate insertion point (the lean confirmed):** inside `ai_proxy` and `chief_llm._call_claude`, immediately **after** `usage_metering.can_interact()` passes and **before** the Anthropic HTTP call. One function call at each site; no pipeline refactor needed (stop condition: not tripped).

## 2. Cache design (9.2 — shipped)

- **Store:** Supabase **pgvector** (`create extension vector`) — available on Supabase, zero new infra, RLS-able, and the data sits next to everything else. External vector stores (Pinecone etc.) rejected for v1: new vendor + egress + secrets for no capability we need at this scale. *(Fork documented: if cache rows exceed ~500k, revisit.)*
- **Table `inference_cache`:** business_id, surface, task_type, prompt_hash (sha256 fast path), embedding `vector(1536)`, request_preview, response, model, tokens, `cost_cents_saved`, `hit_count`, `last_hit_at` — plus **`cluster_id` + `outcome_weight`, unused in v1** (9.6 pattern-learning ready, per the scope).
- **Scoping:** **per-business by default.** Platform-shared cache is the obvious v2 win (the same bookkeeping questions repeat across tenants) but it's a *privacy decision* — cached responses can embed business specifics. Deferred behind validation + a redaction pass. *(Fork surfaced; recommend per-business v1, shared-with-redaction v2.)*
- **Embeddings:** **OpenAI `text-embedding-3-small`** ($0.02/1M tokens), per the lean. Anthropic has no first-party embeddings API (it partners with Voyage); Voyage is a fine alternative at similar cost — the embedder is one function, swappable. Requires `OPENAI_API_KEY` on Railway (Kevin setup, ~$1/month at realistic volume). **Fail-open:** no key → gate disabled → everything routes to Claude exactly as today.
- **Match logic:** exact `prompt_hash` hit first (free, instant) → else cosine similarity via a SQL function (`match_inference_cache` RPC, business-scoped, threshold + top-1). **Default threshold 0.92 conservative** (the scope's 0.85 floor respected — per-surface tunable via env `INFERENCE_GATE_THRESHOLD`; we start stricter because a wrong cache hit costs trust, a miss costs $0.03). **Freshness:** entries older than `INFERENCE_CACHE_TTL_DAYS` (default 30) are skipped-but-kept (re-validated by the next Claude answer overwriting them).

## 3. Routing gate (9.3 — shipped)

`inference_gate.py` — decision order, fail-open at every step:
1. Gate disabled (`INFERENCE_GATE=off` or no embedding key) → **Claude**.
2. Surface/task_type not in the cacheable allow-list → **Claude**.
3. Exact hash hit (fresh) → **cached** (confidence 1.0).
4. Vector hit ≥ threshold (fresh) → **cached**.
5. Anything else (miss, stale, error) → **Claude**, then **store** the answer.

Every decision logs to `inference_gate_decisions` (surface, cache_hit, confidence, fallback_reason, est. cents saved). **Retention surfaced:** decisions are one row per AI call — prune >90 days (manual/cron note in migration; telemetry aggregates don't need raw rows forever).

## 4. Telemetry (9.4 — shipped)
`GET /inference/stats` (platform-owner) + **Inference Layer panel** in Bookkeeping → Admin (self-hides for non-owners): hit rate, calls saved, est. $ saved, cache size, top cached requests, per-surface breakdown.

## 5. Metering interaction (important, deliberate)
**Cache hits still count as weighted Chief interactions.** The practitioner bought an answer, not an Anthropic invoice line — metering measures value delivered, and this keeps the unit model stable whether an answer came from cache, Claude, or (later) a local model. This is exactly the "pricing survives swapping providers" goal. Cost savings accrue to the platform margin, which is the point of Layer 2.

## 6. Local model hosting — honest assessment (9.5 → DEFERRED)
**Railway cannot host this within budget: it has no GPU offering.** CPU-only small models (Llama 3.2 3B-class via Ollama) on Railway would cost ~$20–40/mo for 5–15s latencies and quality far below what "Chief" must feel like — a worse product to save cents the cache already saves. **Recommendation: defer local inference to a dedicated arc, triggered by data** — when telemetry shows ≥30% of escalated (non-cached) traffic is *classification-shaped* (the local-model sweet spot), revisit with **serverless GPU (RunPod serverless / Modal)**: pay-per-second, scale-to-zero, fits the $50–100 ceiling, and the gate already has the "try local first" slot (decision step 4.5). The routing gate + cache ARE the layer-2 foundation; the local model is an optimization plugged into a proven gate, not a prerequisite.

## 7. Phased plan (within ceiling)
| Phase | What | Incremental cost |
|---|---|---|
| **B (now, shipped)** | pgvector cache + gate + telemetry on chief_llm + ai_proxy allow-listed task_types | ~$1–5/mo (embeddings) |
| C | Cacheable-surface expansion (notifications, briefings) + platform-shared cache w/ redaction (fork ruling) | ~$5/mo |
| C+ | Serverless-GPU local model behind the gate's local-first step, IF telemetry justifies | ~$30–80/mo |
| Later | Pattern learning (cluster_id/outcome_weight come alive) | — |

**Kevin setup for v1:** add `OPENAI_API_KEY` to Railway (any funded OpenAI account; embeddings only) + apply the migration. Without the key everything behaves exactly as today.
