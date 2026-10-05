-- Barber and salon plans: Solo / Booked / Boss (feature_gates.AUDIENCE_PLANS).
--
-- Two CHECKs list the plan keys a business row may carry:
--   comp_tier — the owner's comp (Mission Control), so a test business
--               can be put on Solo / Booked / Boss before they are sold;
--   tier      — the webhook's mirror of the subscription's plan. When the
--               CHECK refused a key, stripe_billing dropped `tier` and
--               retried, so a new plan would have lost its mirror silently.
-- Widening only: every existing row already satisfies the new lists.
-- Safe to apply before or after the backend deploy.

BEGIN;

ALTER TABLE public.businesses DROP CONSTRAINT IF EXISTS businesses_comp_tier_check;
ALTER TABLE public.businesses ADD CONSTRAINT businesses_comp_tier_check CHECK (
    comp_tier IS NULL OR comp_tier = ANY (ARRAY[
        'starter', 'professional', 'practice',
        'solo', 'booked', 'boss'
    ]::text[])
);

ALTER TABLE public.businesses DROP CONSTRAINT IF EXISTS businesses_tier_check;
ALTER TABLE public.businesses ADD CONSTRAINT businesses_tier_check CHECK (
    tier = ANY (ARRAY[
        'starter', 'pro', 'enterprise', 'professional', 'practice', 'founder', 'free',
        'solo', 'booked', 'boss'
    ]::text[])
);

COMMIT;

-- Verify:
--   select conname, pg_get_constraintdef(oid) from pg_constraint
--   where conrelid = 'public.businesses'::regclass
--     and conname in ('businesses_comp_tier_check', 'businesses_tier_check');
--
-- Rollback (restores the 2026-07-30 lists):
--   ALTER TABLE public.businesses DROP CONSTRAINT businesses_comp_tier_check;
--   ALTER TABLE public.businesses ADD CONSTRAINT businesses_comp_tier_check CHECK (
--     comp_tier IS NULL OR comp_tier = ANY (ARRAY['starter','professional','practice']::text[]));
--   ALTER TABLE public.businesses DROP CONSTRAINT businesses_tier_check;
--   ALTER TABLE public.businesses ADD CONSTRAINT businesses_tier_check CHECK (
--     tier = ANY (ARRAY['starter','pro','enterprise','professional','practice','founder','free']::text[]));
