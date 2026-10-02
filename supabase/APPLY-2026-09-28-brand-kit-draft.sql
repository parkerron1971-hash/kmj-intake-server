-- APPLY-2026-09-28-brand-kit-draft.sql
--
-- Brand Studio's draft: unsaved brand edits that survive leaving the page
-- until the owner presses Publish (brand_engine "THE DRAFT").
--
-- Two columns on businesses rather than a key inside settings: settings is
-- rewritten wholesale by save_brand_kit and other writers, and a draft
-- autosaves every few seconds. A column written alone can only overwrite
-- itself. Row access is the existing businesses RLS (owner-scoped), the same
-- door /brand/save already uses.
--
-- Idempotent. Nothing reads these columns but Brand Studio; a null draft is
-- the normal state.

ALTER TABLE public.businesses
  ADD COLUMN IF NOT EXISTS brand_kit_draft jsonb,
  ADD COLUMN IF NOT EXISTS brand_kit_draft_at timestamptz;

COMMENT ON COLUMN public.businesses.brand_kit_draft IS
  'Brand Studio edits not yet published. Never read by any renderer; Publish copies it into settings.brand_kit (via save_brand_kit) and clears it.';
COMMENT ON COLUMN public.businesses.brand_kit_draft_at IS
  'When brand_kit_draft was last autosaved.';
