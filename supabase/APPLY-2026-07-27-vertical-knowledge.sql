-- ══════════════════════════════════════════════════════════════════
-- APPLY 2026-07-27 — vertical_knowledge (Feed 1 + Feed 2)
--
-- LAYER_TWO_ARCHITECTURE.md §6 describes three feeds of vertical
-- intelligence. Two of them had nowhere to live:
--
--   Feed 1 — seeded per-vertical knowledge. Exists, but as Python
--            literals in vertical_intelligence.py, so it can only grow
--            by editing a file and shipping a deploy.
--   Feed 2 — what real usage teaches. Did not exist at all. Every
--            memory in the system is business_id-scoped, so no salon's
--            experience has ever reached the next salon.
--
-- This table is where both land. Rows are keyed by VERTICAL, not by
-- business — that is the whole point, and it is also the entire risk,
-- so read the isolation notes before touching it.
--
-- ─── What may be written here ────────────────────────────────────────
-- PATTERNS ONLY. "Rebooking reminders sent the same evening get more
-- replies than next-morning ones" is a pattern. Anything naming a
-- business, a customer, an amount, a date, or quoting a real message is
-- NOT, and must never reach this table.
--
-- Three structural defences, in the writer (vertical_distill.py):
--   1. k-anonymity — a learned row needs evidence from at least
--      MIN_BUSINESSES distinct businesses. A pattern only one business
--      exhibits cannot be written, so a row cannot encode one tenant's
--      specifics even by accident.
--   2. No business_id column. Not "we don't populate it" — the column
--      does not exist, so provenance cannot be reconstructed from a row.
--   3. Contribution is per-business and revocable (settings.feed2 —
--      on by default, Kevin's ruling 2026-07-27).
--
-- Additive + idempotent. pgvector already enabled (arc20 inference
-- layer). Service-role only, like chief_templates.
-- ══════════════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS public.vertical_knowledge (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  vertical       text NOT NULL,          -- canonical key from vertical_registry
  kind           text NOT NULL,          -- 'voice' | 'workflow' | 'offering' | 'pattern' | …
  content        text NOT NULL,          -- the knowledge, one self-contained sentence
  embedding      vector(1536),
  source         text NOT NULL DEFAULT 'seed'
                 CHECK (source IN ('seed', 'learned', 'curated')),
  confidence     real NOT NULL DEFAULT 0.5
                 CHECK (confidence >= 0 AND confidence <= 1),
  -- How many DISTINCT businesses' evidence supports this row. Seeds carry
  -- 0 (they are asserted, not observed). Learned rows must clear the
  -- k-anonymity floor before they are written at all; this column is what
  -- makes that auditable after the fact.
  evidence_count int NOT NULL DEFAULT 0,
  curated_by     text,                   -- who vouched for it, when human
  is_active      boolean NOT NULL DEFAULT true,
  created_at     timestamptz DEFAULT now(),
  updated_at     timestamptz DEFAULT now()
  -- DELIBERATELY NO business_id. See defence 2 above.
);

CREATE INDEX IF NOT EXISTS idx_vertical_knowledge_lookup
  ON public.vertical_knowledge (vertical, kind, is_active);
CREATE INDEX IF NOT EXISTS idx_vertical_knowledge_embedding
  ON public.vertical_knowledge USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

-- One row per (vertical, kind, content): re-running the seed loader or the
-- distiller reinforces rather than duplicates.
CREATE UNIQUE INDEX IF NOT EXISTS uq_vertical_knowledge_content
  ON public.vertical_knowledge (vertical, kind, md5(content));

ALTER TABLE public.vertical_knowledge ENABLE ROW LEVEL SECURITY;
-- No policies, on purpose. Anon and authenticated cannot read this table
-- at all; it is reachable only through the service role, which means only
-- through backend code that has been through review.

-- ─── Retrieval ───────────────────────────────────────────────────────
-- Vertical-scoped cosine match. Note what is NOT a parameter: there is no
-- business_id, because knowledge here belongs to the vertical. The caller
-- decides which vertical the asking business is, and gets that vertical's
-- knowledge and nothing else.
CREATE OR REPLACE FUNCTION public.match_vertical_knowledge(
  p_vertical text,
  p_embedding vector(1536),
  p_threshold float DEFAULT 0.30,
  p_limit int DEFAULT 6
) RETURNS TABLE (id uuid, content text, kind text, source text,
                 confidence real, evidence_count int, similarity float)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT k.id, k.content, k.kind, k.source, k.confidence, k.evidence_count,
         1 - (k.embedding <=> p_embedding) AS similarity
  FROM public.vertical_knowledge k
  WHERE k.vertical = p_vertical
    AND k.is_active = true
    AND k.embedding IS NOT NULL
    AND 1 - (k.embedding <=> p_embedding) >= p_threshold
  ORDER BY k.embedding <=> p_embedding
  LIMIT p_limit;
$$;
REVOKE ALL ON FUNCTION public.match_vertical_knowledge(text, vector, float, int)
  FROM PUBLIC, anon, authenticated;

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP FUNCTION IF EXISTS public.match_vertical_knowledge(text, vector, float, int);
--   DROP TABLE IF EXISTS public.vertical_knowledge;
