-- ══════════════════════════════════════════════════════════════════
-- APPLY 2026-07-13 — semantic memory for Chief (pgvector on chief_memories)
--
-- Compounding API-free intelligence: today Chief pulls memories by
-- importance + recency only, so the memory most RELEVANT to the current
-- message competes on age, not meaning. This adds an embedding column +
-- a business-scoped cosine-match RPC so retrieval can surface the
-- memories that actually relate to what the practitioner just said.
--
-- Embeddings are computed ONCE at write time (OpenAI text-embedding-3-
-- small, 1536 dims — the same client the inference gate already uses).
-- Retrieval is then pure DB math: free, instant, and it works even
-- during an Anthropic/OpenAI outage.
--
-- Additive + idempotent. pgvector is already enabled (arc20 inference
-- layer). Backfill of existing rows happens lazily via a backend sweep.
-- ══════════════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE public.chief_memories
  ADD COLUMN IF NOT EXISTS embedding vector(1536);

-- ivfflat cosine index. (Rows with NULL embedding are simply not matched
-- until the backfill fills them.)
CREATE INDEX IF NOT EXISTS idx_chief_memories_embedding
  ON public.chief_memories USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

-- Business-scoped semantic match (PostgREST RPC). SECURITY DEFINER so it
-- runs with owner privileges, but REVOKEd from anon/authenticated — only
-- the backend service role calls it, and it hard-filters by business_id.
CREATE OR REPLACE FUNCTION public.match_chief_memories(
  p_business_id uuid,
  p_embedding vector(1536),
  p_threshold float DEFAULT 0.30,
  p_limit int DEFAULT 12
) RETURNS TABLE (id uuid, content text, category text, importance int,
                 similarity float)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT m.id, m.content, m.category, m.importance,
         1 - (m.embedding <=> p_embedding) AS similarity
  FROM public.chief_memories m
  WHERE m.business_id = p_business_id
    AND m.is_active = true
    AND m.embedding IS NOT NULL
    AND 1 - (m.embedding <=> p_embedding) >= p_threshold
  ORDER BY m.embedding <=> p_embedding
  LIMIT p_limit;
$$;
REVOKE ALL ON FUNCTION public.match_chief_memories(uuid, vector, float, int)
  FROM PUBLIC, anon, authenticated;

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP FUNCTION IF EXISTS public.match_chief_memories(uuid, vector, float, int);
--   DROP INDEX IF EXISTS public.idx_chief_memories_embedding;
--   ALTER TABLE public.chief_memories DROP COLUMN IF EXISTS embedding;
