-- ═════════════════════════════════════════════════════════════════════
-- Arc 20 Phase B Part 9 — hybrid inference layer (semantic cache + gate)
-- ═════════════════════════════════════════════════════════════════════
-- pgvector semantic cache + gate-decision telemetry. Service-role only
-- (no practitioner-facing reads of raw cache — telemetry aggregates go
-- through the owner-gated endpoint).
--
-- Additive + idempotent. Clean rollback. Apply via Supabase Studio.
-- ═════════════════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS public.inference_cache (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id      uuid NOT NULL,
  surface          text NOT NULL,          -- 'chief_llm' | 'ai_proxy'
  task_type        text,
  prompt_hash      text NOT NULL,          -- sha256 of normalized request (exact fast path)
  embedding        vector(1536),
  request_preview  text,                   -- first ~300 chars (telemetry/debug)
  response         text NOT NULL,
  model            text,
  input_tokens     int DEFAULT 0,
  output_tokens    int DEFAULT 0,
  cost_cents_saved numeric(10,4) DEFAULT 0,
  hit_count        int DEFAULT 0,
  last_hit_at      timestamptz,
  created_at       timestamptz DEFAULT now(),
  -- 9.6 pattern-learning ready; UNUSED in v1 by design:
  cluster_id       uuid,
  outcome_weight   numeric(5,4)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_inference_cache_hash
  ON public.inference_cache (business_id, surface, prompt_hash);
CREATE INDEX IF NOT EXISTS idx_inference_cache_embedding
  ON public.inference_cache USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

ALTER TABLE public.inference_cache ENABLE ROW LEVEL SECURITY;
-- service-role only (no policies on purpose)

CREATE TABLE IF NOT EXISTS public.inference_gate_decisions (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id     uuid,
  surface         text,
  task_type       text,
  cache_hit       boolean NOT NULL DEFAULT false,
  confidence      numeric(5,4),
  fallback_reason text,        -- miss | stale | below_threshold | disabled | error
  cents_saved     numeric(10,4) DEFAULT 0,
  created_at      timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_gate_decisions_created
  ON public.inference_gate_decisions (created_at DESC);

ALTER TABLE public.inference_gate_decisions ENABLE ROW LEVEL SECURITY;
-- service-role only

-- RETENTION (surfaced): one decision row per AI call. Prune periodically:
--   DELETE FROM public.inference_gate_decisions WHERE created_at < now() - interval '90 days';

-- Business-scoped cosine match (PostgREST RPC).
CREATE OR REPLACE FUNCTION public.match_inference_cache(
  p_business_id uuid,
  p_surface text,
  p_embedding vector(1536),
  p_threshold float,
  p_max_age_days int DEFAULT 30
) RETURNS TABLE (id uuid, response text, similarity float, model text,
                 input_tokens int, output_tokens int)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT c.id, c.response,
         1 - (c.embedding <=> p_embedding) AS similarity,
         c.model, c.input_tokens, c.output_tokens
  FROM public.inference_cache c
  WHERE c.business_id = p_business_id
    AND c.surface = p_surface
    AND c.embedding IS NOT NULL
    AND c.created_at > now() - make_interval(days => p_max_age_days)
    AND 1 - (c.embedding <=> p_embedding) >= p_threshold
  ORDER BY c.embedding <=> p_embedding
  LIMIT 1;
$$;
REVOKE ALL ON FUNCTION public.match_inference_cache(uuid, text, vector, float, int) FROM PUBLIC, anon, authenticated;

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP FUNCTION IF EXISTS public.match_inference_cache(uuid, text, vector, float, int);
--   DROP TABLE IF EXISTS public.inference_gate_decisions;
--   DROP TABLE IF EXISTS public.inference_cache;

SELECT 'arc 20 inference layer ready' AS status;
