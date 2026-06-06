-- ─────────────────────────────────────────────────────────────────
-- Phase VABI v1.5 — per-business terminology + intelligence overrides
-- ─────────────────────────────────────────────────────────────────
-- Run via:  Supabase Studio → SQL editor → paste + Run
-- Idempotent, forward-only, additive. Zero existing data touched.
--
-- Two new columns on business_profiles:
--
--   terminology_overrides jsonb DEFAULT '{}'
--     Practitioner-authored AND Chief-generated terminology overrides
--     for one business. Shape: { customer: "Patron", service: "Visit", ... }
--     Lookup priority chain (frontend + backend mirror each other):
--       business.terminology_overrides[k]
--       VERTICAL_TERMS[business_type][k]
--       BASE_TERMS[k]
--
--   vertical_intelligence_overrides jsonb DEFAULT '{}'
--     Same priority chain for the richer VABI intelligence
--     payloads (onboarding_questions, offering_suggestions,
--     invoice_line_templates, empty_state_nudges, module_suggestions,
--     email_voice). Partial overrides allowed: any key the
--     practitioner doesn't override falls through to the vertical
--     defaults from vertical_intelligence.py.
--
-- After this runs, the VABI v1.5 backend + frontend can be deployed.
-- ─────────────────────────────────────────────────────────────────

ALTER TABLE public.business_profiles
    ADD COLUMN IF NOT EXISTS terminology_overrides jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE public.business_profiles
    ADD COLUMN IF NOT EXISTS vertical_intelligence_overrides jsonb NOT NULL DEFAULT '{}'::jsonb;

-- Verify:
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema='public'
  AND table_name='business_profiles'
  AND column_name IN ('terminology_overrides', 'vertical_intelligence_overrides')
ORDER BY column_name;
