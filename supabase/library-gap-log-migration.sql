-- ═══════════════════════════════════════════════════════════════════════
-- library_gap_log — track asks Chief couldn't satisfy (Phase C.1.3)
-- ═══════════════════════════════════════════════════════════════════════
-- Per NT8g: when a practitioner asks for something Chief doesn't have a
-- strong vertical pattern for AND doesn't have an archetype backing,
-- Chief replies honestly ("I don't have a strong way to build that yet
-- — here's what I can do nearby") AND stamps a row here so the team can
-- review what archetypes are owed next.
--
-- This table is FIRST-CLASS PRODUCT DATA per Kevin's NT8g ruling:
-- "library_gap_log is genuinely valuable data; treat it as a first-class
-- product surface for prioritizing future archetype work."
--
-- RLS: practitioner reads their OWN gaps (so they can see the "I asked
-- for X" history if they want); platform owner reads ALL gaps (the
-- product-prioritization surface). Anon: zero access.
--
-- NON-DESTRUCTIVE + IDEMPOTENT.
-- ═══════════════════════════════════════════════════════════════════════

BEGIN;

CREATE TABLE IF NOT EXISTS public.library_gap_log (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id       uuid REFERENCES public.businesses(id) ON DELETE SET NULL,
  business_type     text,                       -- snapshot at the time of gap (business type can change)
  -- The practitioner's words verbatim (or as close as we got via Chief's parser).
  intake_excerpt    text NOT NULL,
  -- Chief's own short explanation of what shape it would have wanted.
  rationale         text,
  -- The nearest archetype Chief offered as the "what I CAN do" alternative,
  -- if any. NULL when nothing nearby fit.
  nearest_archetype text,
  -- Did the practitioner accept the nearby alternative, decline, or just
  -- abandon? Captured for prioritization signal.
  outcome           text NOT NULL DEFAULT 'gap_logged',
  -- Free-form practitioner reply if they reacted.
  practitioner_note text,
  created_at        timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT library_gap_log_outcome_check CHECK (outcome IN
    ('gap_logged','accepted_nearest','declined_nearest','abandoned'))
);

CREATE INDEX IF NOT EXISTS library_gap_log_biz_type_idx
  ON public.library_gap_log(business_type, created_at DESC) WHERE business_type IS NOT NULL;

CREATE INDEX IF NOT EXISTS library_gap_log_recent_idx
  ON public.library_gap_log(created_at DESC);

ALTER TABLE public.library_gap_log ENABLE ROW LEVEL SECURITY;

-- Practitioner reads their OWN business's gaps (audit trail).
DROP POLICY IF EXISTS library_gap_log_owner_select ON public.library_gap_log;
CREATE POLICY library_gap_log_owner_select ON public.library_gap_log
  FOR SELECT TO authenticated
  USING (business_id IN (SELECT id FROM public.businesses WHERE owner_id = auth.uid()));

-- Service role writes (Chief inserts via _maybe_log_library_gap helper).
-- No practitioner-side INSERT/UPDATE policy — these rows are Chief-authored.
-- The platform-owner read surface uses service-role too (admin tool).

COMMIT;
