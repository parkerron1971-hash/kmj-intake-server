-- APPLY-2026-07-29-restricted-min-role.sql
-- RUN ONCE in the Supabase SQL Editor (whole file).
--
-- Lets a business DELEGATE access to a restricted module without handing
-- over ownership.
--
-- THE SEAM THIS CLOSES
--   restricted_modules._authorize has carried this comment since Fork 25:
--
--     "25b SEAM: replace the `owner_id == user.id` check below with a
--      role-permission lookup (business_members) when multi-staff lands."
--
--   Multi-staff landed. business_users.role is already viewer/member/
--   manager/admin and public.business_role() already exists. The seam was
--   simply never closed, so a church with a bookkeeper still had exactly one
--   person who could open Giving: the owner.
--
--   (For the record: the vertical readiness audit reported roles as "only
--   admin/member + accountant, too coarse". That was read off an older
--   migration file rather than the live database and was wrong — the tiers
--   are there. What was missing is this one authorization path using them.)
--
-- DEFAULT-DENY IS PRESERVED, DELIBERATELY
--   The column is NULLABLE and NULL means OWNER ONLY — exactly today's
--   behaviour. Nothing becomes more visible by applying this migration.
--   A business opts in per module, and until it does, a congregation's
--   giving records stay where they are.
--
--   That matters more than the convenience: giving is the most confidential
--   data a church holds, and many churches deliberately keep it from their
--   own staff. Widening it by default would have been a silent policy change
--   made by a migration.
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE.

ALTER TABLE public.custom_modules
  ADD COLUMN IF NOT EXISTS restricted_min_role text;

-- Only the roles that actually exist, and NOT 'viewer': a viewer is the
-- read-only tier and restricted modules are the last thing that should
-- widen to it. Owner-only stays expressible as NULL.
ALTER TABLE public.custom_modules
  DROP CONSTRAINT IF EXISTS custom_modules_restricted_min_role_check;
ALTER TABLE public.custom_modules
  ADD CONSTRAINT custom_modules_restricted_min_role_check
  CHECK (restricted_min_role IS NULL
         OR restricted_min_role IN ('member', 'manager', 'admin'));

COMMENT ON COLUMN public.custom_modules.restricted_min_role IS
  'Minimum business_users.role that may access this restricted module''s entries. NULL = owner only (the default, and the pre-existing behaviour). Read by restricted_modules._authorize, which still audits every access including denials.';

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
-- Expect: column present, constraint present, and EVERY existing module
-- still owner-only (nothing was widened by applying this).
SELECT
  (SELECT count(*) FROM information_schema.columns
    WHERE table_schema='public' AND table_name='custom_modules'
      AND column_name='restricted_min_role')                    AS column_ok,
  (SELECT count(*) FROM pg_constraint
    WHERE conname='custom_modules_restricted_min_role_check')   AS constraint_ok,
  (SELECT count(*) FROM public.custom_modules
    WHERE restricted_min_role IS NOT NULL)                      AS widened_by_this_migration;
