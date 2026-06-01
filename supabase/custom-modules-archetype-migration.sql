-- ═══════════════════════════════════════════════════════════════════════
-- custom_modules — archetype columns (Phase C.1)
-- ═══════════════════════════════════════════════════════════════════════
-- Adds the archetype dispatch fields to custom_modules so the frontend
-- ArchetypeDispatch wrapper can route each materialized module to the
-- right hand-written component instead of always rendering DynamicModule.
--
-- C1 / C4 ruling:
--   - archetype: closed-enum string, source of truth in the backend
--     (module_spec_generator.ArchetypeEnum). DEFAULT 'fallback_generic'
--     so existing rows keep working (C15: existing modules stay as
--     fallback_generic until practitioner regenerates).
--   - archetype_params: jsonb for per-archetype typed config
--     (e.g. {primary_date_field: 'booking_date'} for booking_calendar).
--   - archetype_fallback_reason: required when archetype = 'fallback_generic'.
--     The LLM populates this when no archetype fits — every fallback is a
--     marker that a new archetype is owed.
--
-- NON-DESTRUCTIVE: ADD COLUMN IF NOT EXISTS. Existing rows get
-- 'fallback_generic' as their archetype (C15 — they keep rendering through
-- DynamicModule until regenerated).
-- IDEMPOTENT.
-- ═══════════════════════════════════════════════════════════════════════

BEGIN;

ALTER TABLE public.custom_modules
  ADD COLUMN IF NOT EXISTS archetype text NOT NULL DEFAULT 'fallback_generic';

ALTER TABLE public.custom_modules
  ADD COLUMN IF NOT EXISTS archetype_params jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE public.custom_modules
  ADD COLUMN IF NOT EXISTS archetype_fallback_reason text;

-- Index for fast lookup by archetype (used by booking_widget_router's
-- _bookings_module helper + future archetype-specific queries).
CREATE INDEX IF NOT EXISTS custom_modules_archetype_idx
  ON public.custom_modules(business_id, archetype) WHERE is_active = true;

COMMIT;
