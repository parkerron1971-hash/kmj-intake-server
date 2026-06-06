-- ─────────────────────────────────────────────────────────────────
-- Path C Phase 1 — 1f Replace businesses.type CHECK with FK
-- ─────────────────────────────────────────────────────────────────
-- Replaces the hand-maintained CHECK (type IN [...]) constraint on
-- public.businesses with a FOREIGN KEY to
-- public.business_type_archetypes.business_type. Once applied, the
-- archetype table becomes the single source of truth — adding a new
-- archetype row automatically allows that value on businesses.
--
-- PRE-REQUISITES (must pass before this runs):
--   1. Run 2026_06_07_pathc_phase1_diagnostic.sql.
--      Q5 (businesses.type values missing from archetypes) MUST
--      return ZERO rows.
--   2. Run 2026_06_07_pathc_phase1_seed_archetypes.sql.
--      Re-run Q5; verify it returns ZERO rows.
--
-- If Q5 still returns rows, STOP — those values would violate the new
-- FK. Add archetype rows for them in seed_archetypes.sql before
-- re-attempting this migration.
--
-- DATA SAFETY:
--   - DROP CONSTRAINT IF EXISTS for both names (current and FK).
--   - ADD CONSTRAINT inside a single transaction — if the constraint
--     would reject any existing row, the entire migration rolls back
--     leaving the database exactly as before.
--   - No data is touched.
--
-- ─────────────────────────────────────────────────────────────────
-- business_profiles.business_type FK is INTENTIONALLY DEFERRED to
-- Phase 2. The diagnostic (Q6) surfaces drift on that field that
-- Kevin rules on first (Phase 2 question 2b). Phase 2 will add (or
-- skip) the parallel FK based on the ruling.
-- ─────────────────────────────────────────────────────────────────

BEGIN;

-- 1. Drop the existing CHECK constraint (if present). Safe re-run.
ALTER TABLE public.businesses
    DROP CONSTRAINT IF EXISTS businesses_type_check;

-- 2. Drop any prior FK by name (idempotent re-run).
ALTER TABLE public.businesses
    DROP CONSTRAINT IF EXISTS businesses_type_fk;

-- 3. Add the FK. ON DELETE / ON UPDATE: NO ACTION (the default) —
--    archetype rows shouldn't be deleted while businesses reference
--    them; if a rename is ever needed it's a manual two-step.
ALTER TABLE public.businesses
    ADD CONSTRAINT businesses_type_fk
    FOREIGN KEY (type)
    REFERENCES public.business_type_archetypes(business_type);

COMMIT;

-- ─── Verify ─────────────────────────────────────────────────────
-- Confirm the FK is in place and no businesses violate it.

SELECT
    conname     AS constraint_name,
    contype     AS constraint_type,
    pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'public.businesses'::regclass
  AND conname IN ('businesses_type_check', 'businesses_type_fk');

-- Should be zero — FK guarantees this, but verify defensively.
SELECT COUNT(*) AS businesses_with_invalid_type
FROM public.businesses b
WHERE b.type IS NOT NULL
  AND b.type NOT IN (
    SELECT business_type FROM public.business_type_archetypes
  );

-- ─── Rollback recipe (for emergencies) ──────────────────────────
-- If the FK introduces a real problem (e.g. an INSERT path the seed
-- missed), restore the CHECK constraint:
--
--   BEGIN;
--   ALTER TABLE public.businesses DROP CONSTRAINT businesses_type_fk;
--   ALTER TABLE public.businesses ADD CONSTRAINT businesses_type_check
--     CHECK (type = ANY (ARRAY[
--       'coach', 'consultant', 'creative', 'fitness_wellness',
--       'financial_educator', 'course_creator', 'service_provider',
--       'custom', 'church', 'nonprofit', 'agency', 'coaching',
--       'ecommerce', 'saas', 'general', 'ministry',
--       'personal_services', 'lawyer'
--     ]::text[]));
--   COMMIT;
