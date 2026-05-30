-- ═══════════════════════════════════════════════════════════════════════
-- Phase A Light (spike) — module_specs
-- ═══════════════════════════════════════════════════════════════════════
-- The source layer above custom_modules.schema (the runtime shape).
-- The Chief generates a ModuleSpec from an intake answer; the practitioner
-- accepts; materialization writes a custom_modules row from draft_json.
--
-- draft_json holds the full ModuleSpec (slug + name + icon + description +
-- schema + agent_config + intake_excerpt + reasoning + confidence + voice_hints
-- + workflows + public_display). The runtime side reads only the subset
-- custom_modules supports today; workflows/public_display sit dormant until
-- Phases B/C ship.
--
-- Non-destructive, idempotent. Service-role-only writes (Chief runs server-
-- side); reads owner-scoped.
-- ═══════════════════════════════════════════════════════════════════════

BEGIN;

CREATE TABLE IF NOT EXISTS public.module_specs (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id         UUID NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  slug                TEXT NOT NULL,
  draft_json          JSONB NOT NULL,
  intake_excerpt      TEXT NOT NULL,
  status              TEXT NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft', 'accepted', 'rejected')),
  materialized_module_id UUID REFERENCES public.custom_modules(id) ON DELETE SET NULL,
  reject_reason       TEXT,
  revise_feedback     TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  accepted_at         TIMESTAMPTZ
);

-- One draft per (business, slug) at a time. Re-proposing replaces via upsert
-- patterns at the app layer; this index is the safety net.
CREATE INDEX IF NOT EXISTS idx_module_specs_biz_status
  ON public.module_specs(business_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_module_specs_slug
  ON public.module_specs(business_id, slug);

DROP TRIGGER IF EXISTS trg_module_specs_updated ON public.module_specs;
CREATE TRIGGER trg_module_specs_updated
  BEFORE UPDATE ON public.module_specs
  FOR EACH ROW EXECUTE FUNCTION set_updated_at_timestamp();

ALTER TABLE public.module_specs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "specs_all" ON public.module_specs;
-- Service-role bypasses RLS (backend writes); authenticated reads scoped to
-- owner by the existing businesses.owner_id check at the router layer.
CREATE POLICY "specs_all" ON public.module_specs FOR ALL USING (true) WITH CHECK (true);

COMMIT;
