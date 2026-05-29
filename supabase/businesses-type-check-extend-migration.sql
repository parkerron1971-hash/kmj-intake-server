-- ═══════════════════════════════════════════════════════════════════════
-- businesses.type CHECK extend — admit ministry + personal_services
-- ═══════════════════════════════════════════════════════════════════════
-- LGS Phase 0 made ministry + personal_services first-class business types
-- (archetypes in business_type_archetypes + module blueprints in
-- business_type_module_blueprint). But the businesses.type CHECK constraint
-- was never widened to admit them, so an onboarding INSERT with
-- type='ministry' or type='personal_services' fails (code 23514) — the
-- first-class work is invisible at the actual insert. This closes that gap.
--
-- NON-DESTRUCTIVE: the new value set is a strict SUPERSET of the current one
-- (15 existing values preserved verbatim + 2 added), so every existing row
-- still satisfies the constraint. No data is touched.
--
-- IDEMPOTENT: DROP CONSTRAINT IF EXISTS + re-ADD. Safe to re-run.
--
-- NOTE: this is the first migration kept in the backend repo's supabase/ dir
-- (the rest historically live in solutionist-studio/supabase/). Bundled into
-- the LGS Phases 2-5 backend PR so the first-class types ship with that work.
-- Apply via the Supabase SQL editor like the other migrations — backend
-- deploys do NOT auto-run migrations.
-- ═══════════════════════════════════════════════════════════════════════

BEGIN;

ALTER TABLE public.businesses DROP CONSTRAINT IF EXISTS businesses_type_check;

ALTER TABLE public.businesses ADD CONSTRAINT businesses_type_check
  CHECK (type = ANY (ARRAY[
    -- existing (preserved verbatim from the live constraint, 2026-05-29)
    'coach', 'consultant', 'creative', 'fitness_wellness', 'financial_educator',
    'course_creator', 'service_provider', 'custom', 'church', 'nonprofit',
    'agency', 'coaching', 'ecommerce', 'saas', 'general',
    -- LGS Phase 0 first-class types (added by this migration)
    'ministry', 'personal_services'
  ]::text[]));

COMMIT;

-- Rollback (if ever needed): re-run with the 15 existing values only,
-- AFTER confirming no rows use 'ministry' / 'personal_services'.
