-- ══════════════════════════════════════════════════════════════════
-- APPLY 2026-07-13 — Chief draft templates (draft→template residue)
--
-- Compounding intelligence, part 2: when a Chief-drafted message is good
-- enough to actually SEND (autopilot auto-sent it, or it was approved),
-- keep it as a reusable template keyed to the SITUATION. Next time a
-- similar situation comes up, Chief reuses that message's voice + shape
-- as an exemplar instead of generating from scratch — cheaper, and the
-- practitioner's proven voice stays consistent.
--
-- Situations are matched by MEANING (embedding), same mechanism as
-- semantic memory. Service-role only. Additive + idempotent. pgvector
-- already enabled.
-- ══════════════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS public.chief_templates (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id         uuid NOT NULL,
  kind                text NOT NULL,          -- 'check_in' | 'nurture' | 'email' | …
  situation           text NOT NULL,          -- the reason/context this message served
  situation_embedding vector(1536),
  body                text NOT NULL,          -- the message that worked
  uses                int  DEFAULT 1,         -- how many times reused/reinforced
  created_at          timestamptz DEFAULT now(),
  last_used_at        timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chief_templates_biz
  ON public.chief_templates (business_id, kind);
CREATE INDEX IF NOT EXISTS idx_chief_templates_embedding
  ON public.chief_templates USING ivfflat (situation_embedding vector_cosine_ops)
  WITH (lists = 100);

ALTER TABLE public.chief_templates ENABLE ROW LEVEL SECURITY;
-- service-role only (no policies on purpose — backend-mediated)

-- Business + kind scoped cosine match.
CREATE OR REPLACE FUNCTION public.match_chief_templates(
  p_business_id uuid,
  p_kind text,
  p_embedding vector(1536),
  p_threshold float DEFAULT 0.35,
  p_limit int DEFAULT 1
) RETURNS TABLE (id uuid, body text, situation text, uses int, similarity float)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT t.id, t.body, t.situation, t.uses,
         1 - (t.situation_embedding <=> p_embedding) AS similarity
  FROM public.chief_templates t
  WHERE t.business_id = p_business_id
    AND t.kind = p_kind
    AND t.situation_embedding IS NOT NULL
    AND 1 - (t.situation_embedding <=> p_embedding) >= p_threshold
  ORDER BY t.situation_embedding <=> p_embedding
  LIMIT p_limit;
$$;
REVOKE ALL ON FUNCTION public.match_chief_templates(uuid, text, vector, float, int)
  FROM PUBLIC, anon, authenticated;

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP FUNCTION IF EXISTS public.match_chief_templates(uuid, text, vector, float, int);
--   DROP TABLE IF EXISTS public.chief_templates;
