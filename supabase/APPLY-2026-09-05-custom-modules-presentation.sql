-- ═══════════════════════════════════════════════════════════════════════
-- custom_modules.presentation — how a module FEELS (2026-09-05)
-- ═══════════════════════════════════════════════════════════════════════
-- The module generator now decides, from the practitioner's own words,
-- the sentence the empty state says, what the celebration says when a
-- goal is reached, a name for each milestone, and the surface's register
-- (calm / bold / warm / precise). The archetype components render it;
-- nothing here is code, a theme, or a layout.
--
-- jsonb with an empty-object default so every existing row and every
-- caller that does not know about the column (provisioning, structure
-- import, ensure_module) keeps working and renders the archetype's
-- honest defaults. The Pydantic model (module_spec_generator.Presentation)
-- is the shape's source of truth; the column is deliberately unchecked.
--
-- NON-DESTRUCTIVE. IDEMPOTENT.
-- ═══════════════════════════════════════════════════════════════════════

BEGIN;

ALTER TABLE public.custom_modules
  ADD COLUMN IF NOT EXISTS presentation jsonb NOT NULL DEFAULT '{}'::jsonb;

COMMIT;
