-- APPLY-2026-11-16-tier-all-plans.sql
--
-- The plan columns accept every plan the server sells (feature_gates.ALL_PLANS).
--
-- Found 2026-11-16, the day the first real church paid: its subscription is
-- church_growing, but businesses.tier still says 'professional' (the no-card
-- trial's plan, written at signup). businesses_tier_check was last widened on
-- 2026-10-24 (ChurchSavvy) and never learned the four church plans
-- (2026-11-03), so the Stripe webhook's patch with tier = 'church_growing'
-- was refused, retried without `tier` (stripe_billing._apply_subscription_
-- state), and the old mirror stayed. businesses_comp_tier_check has the same
-- gap: POST /access/business/{id}/tier accepts every ALL_PLANS key, but a
-- church plan comp was refused by the database (and, until this PR, the
-- endpoint still answered ok).
--
--   businesses_tier_check       every ALL_PLANS key, plus the retired words
--                               rows may still hold (pro, enterprise, founder,
--                               free), as before
--   businesses_comp_tier_check  null or every ALL_PLANS key
--
-- Widening only: every row that satisfies today's lists satisfies these, so
-- the ADDs cannot fail on existing data (if one does, the transaction rolls
-- back and nothing changes). Safe before or after the backend deploy.
--
-- Then, in its OWN transaction, the stale mirror is put right for the rows the
-- database alone can prove: a church holding a founding place records the plan
-- key and the Stripe price it was claimed on (settings.founding_church = {n, at,
-- plan, price_id}, church_founding.claim). Where the live subscription is still
-- on that same price, the plan is known without the server's price table, and
-- tier is set to it. At most ten rows can qualify (the founding places); more
-- than that and it stops with nothing changed. Every other row whose mirror is
-- stale (a plan change after the founding place, or a church plan bought with
-- no founding place) is re-mirrored by its next Stripe event (each renewal
-- re-applies the subscription), now that the CHECK lets the write through.
--
-- Before (optional, read-only):
--   select tier, count(*) from public.businesses group by 1 order by 1;
--   select comp_tier, count(*) from public.businesses group by 1 order by 1;
--   -- what step 2 will change (expect 1 row today, the first church):
--   select id, tier, settings->'founding_church'->>'plan' as plan
--     from public.businesses
--    where subscription_status in ('active', 'trialing')
--      and jsonb_typeof(settings->'founding_church') = 'object'
--      and settings->'founding_church'->>'plan' in
--          ('church_small', 'church_growing', 'church_established', 'church_large')
--      and subscription_plan is not null
--      and subscription_plan = settings->'founding_church'->>'price_id'
--      and tier is distinct from settings->'founding_church'->>'plan';

-- ── 1. The two CHECKs ───────────────────────────────────────────────────────

BEGIN;
SET LOCAL lock_timeout = '5s';

ALTER TABLE public.businesses DROP CONSTRAINT IF EXISTS businesses_tier_check;
ALTER TABLE public.businesses ADD CONSTRAINT businesses_tier_check CHECK (
    tier = ANY (ARRAY[
        'starter', 'professional', 'practice',
        'solo', 'booked', 'boss',
        'church_small', 'church_growing', 'church_established', 'church_large',
        'cs_screens', 'cs_planning', 'cs_both',
        'pro', 'enterprise', 'founder', 'free'
    ]::text[])
);

ALTER TABLE public.businesses DROP CONSTRAINT IF EXISTS businesses_comp_tier_check;
ALTER TABLE public.businesses ADD CONSTRAINT businesses_comp_tier_check CHECK (
    comp_tier IS NULL OR comp_tier = ANY (ARRAY[
        'starter', 'professional', 'practice',
        'solo', 'booked', 'boss',
        'church_small', 'church_growing', 'church_established', 'church_large',
        'cs_screens', 'cs_planning', 'cs_both'
    ]::text[])
);

COMMIT;

-- ── 2. The founding churches' stale mirror ─────────────────────────────────

BEGIN;
SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
    n integer;
BEGIN
    SELECT count(*) INTO n
      FROM public.businesses b
     WHERE b.subscription_status IN ('active', 'trialing')
       AND jsonb_typeof(b.settings->'founding_church') = 'object'
       AND b.settings->'founding_church'->>'plan' IN
           ('church_small', 'church_growing', 'church_established', 'church_large')
       AND b.subscription_plan IS NOT NULL
       AND b.subscription_plan = b.settings->'founding_church'->>'price_id'
       AND b.tier IS DISTINCT FROM b.settings->'founding_church'->>'plan';
    IF n > 10 THEN
        RAISE EXCEPTION 'tier re-mirror would change % rows; at most 10 founding churches exist. Nothing changed.', n;
    END IF;

    UPDATE public.businesses b
       SET tier = b.settings->'founding_church'->>'plan'
     WHERE b.subscription_status IN ('active', 'trialing')
       AND jsonb_typeof(b.settings->'founding_church') = 'object'
       AND b.settings->'founding_church'->>'plan' IN
           ('church_small', 'church_growing', 'church_established', 'church_large')
       AND b.subscription_plan IS NOT NULL
       AND b.subscription_plan = b.settings->'founding_church'->>'price_id'
       AND b.tier IS DISTINCT FROM b.settings->'founding_church'->>'plan';
    GET DIAGNOSTICS n = ROW_COUNT;
    RAISE NOTICE 'tier re-mirrored on % founding church row(s)', n;
END $$;

COMMIT;

-- Check:
--   select conname, pg_get_constraintdef(oid) from pg_constraint
--    where conrelid = 'public.businesses'::regclass
--      and conname in ('businesses_comp_tier_check', 'businesses_tier_check');
--   -- 2 rows, each listing church_small, church_growing, church_established, church_large
--   select count(*) from public.businesses
--    where jsonb_typeof(settings->'founding_church') = 'object'
--      and subscription_status in ('active', 'trialing')
--      and subscription_plan = settings->'founding_church'->>'price_id'
--      and tier is distinct from settings->'founding_church'->>'plan';   -- 0
--
-- Rollback (restores the 2026-10-24 lists; first set any church_* tier back to
-- 'starter' and clear any church_* comp_tier, or the ADDs fail):
--   BEGIN;
--   UPDATE public.businesses SET tier = 'starter' WHERE tier LIKE 'church\_%';
--   UPDATE public.businesses SET comp_tier = NULL WHERE comp_tier LIKE 'church\_%';
--   ALTER TABLE public.businesses DROP CONSTRAINT businesses_tier_check;
--   ALTER TABLE public.businesses ADD CONSTRAINT businesses_tier_check CHECK (
--     tier = ANY (ARRAY['starter','pro','enterprise','professional','practice','founder','free',
--                       'solo','booked','boss','cs_screens','cs_planning','cs_both']::text[]));
--   ALTER TABLE public.businesses DROP CONSTRAINT businesses_comp_tier_check;
--   ALTER TABLE public.businesses ADD CONSTRAINT businesses_comp_tier_check CHECK (
--     comp_tier IS NULL OR comp_tier = ANY (ARRAY['starter','professional','practice',
--                       'solo','booked','boss','cs_screens','cs_planning','cs_both']::text[]));
--   COMMIT;
