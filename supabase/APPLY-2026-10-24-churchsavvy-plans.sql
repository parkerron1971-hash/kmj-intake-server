-- ChurchSavvy's own plans: cs_screens / cs_planning / cs_both
-- (feature_gates.CHURCHSAVVY_PLANS, churchsavvy_billing.py).
--
-- The same two CHECKs as the barber and salon plans (2026-10-04):
--   comp_tier — the owner's comp (Mission Control), so a church that
--               started on ChurchSavvy before checkout existed can be kept
--               on its plan, and a test church can be put on one;
--   tier      — the webhook's mirror of the subscription's plan.
-- Widening only: every existing row already satisfies the new lists.
-- Safe to apply before or after the backend deploy.

BEGIN;

ALTER TABLE public.businesses DROP CONSTRAINT IF EXISTS businesses_comp_tier_check;
ALTER TABLE public.businesses ADD CONSTRAINT businesses_comp_tier_check CHECK (
    comp_tier IS NULL OR comp_tier = ANY (ARRAY[
        'starter', 'professional', 'practice',
        'solo', 'booked', 'boss',
        'cs_screens', 'cs_planning', 'cs_both'
    ]::text[])
);

ALTER TABLE public.businesses DROP CONSTRAINT IF EXISTS businesses_tier_check;
ALTER TABLE public.businesses ADD CONSTRAINT businesses_tier_check CHECK (
    tier = ANY (ARRAY[
        'starter', 'pro', 'enterprise', 'professional', 'practice', 'founder', 'free',
        'solo', 'booked', 'boss',
        'cs_screens', 'cs_planning', 'cs_both'
    ]::text[])
);

COMMIT;

-- Verify:
--   select conname, pg_get_constraintdef(oid) from pg_constraint
--   where conrelid = 'public.businesses'::regclass
--     and conname in ('businesses_comp_tier_check', 'businesses_tier_check');
--
-- Rollback (restores the 2026-10-04 lists; first clear any cs_* comp_tier
-- and set any cs_* tier back to 'starter'):
--   ALTER TABLE public.businesses DROP CONSTRAINT businesses_comp_tier_check;
--   ALTER TABLE public.businesses ADD CONSTRAINT businesses_comp_tier_check CHECK (
--     comp_tier IS NULL OR comp_tier = ANY (ARRAY['starter','professional','practice','solo','booked','boss']::text[]));
--   ALTER TABLE public.businesses DROP CONSTRAINT businesses_tier_check;
--   ALTER TABLE public.businesses ADD CONSTRAINT businesses_tier_check CHECK (
--     tier = ANY (ARRAY['starter','pro','enterprise','professional','practice','founder','free','solo','booked','boss']::text[]));
