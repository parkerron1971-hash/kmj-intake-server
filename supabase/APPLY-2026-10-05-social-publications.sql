-- social_publications — every post a business sent (or scheduled) to its
-- connected social accounts through Post for Me (social_publish_router).
--
-- targets: which connections it went to ({connection_id, platform,
--          username, provider_account_id}); results: how it went on each
--          ({platform, username, success, url, error}).
-- approved_by + approved_hash: who pressed Post / Schedule, and a
--          fingerprint of exactly the words, photos, accounts and time they
--          approved.
-- Writes come from the backend (service role) only; owner + members read.
-- Additive + idempotent. Safe to apply before the backend deploy.

CREATE TABLE IF NOT EXISTS public.social_publications (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id      uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    caption          text NOT NULL DEFAULT '',
    media            jsonb NOT NULL DEFAULT '[]'::jsonb,
    targets          jsonb NOT NULL DEFAULT '[]'::jsonb,
    status           text NOT NULL DEFAULT 'posting'
                     CHECK (status IN ('scheduled', 'posting', 'posted', 'partly_posted',
                                       'failed', 'cancelled')),
    scheduled_at     timestamptz,
    provider_post_id text UNIQUE,
    results          jsonb NOT NULL DEFAULT '[]'::jsonb,
    approved_by      uuid,
    approved_hash    text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS social_publications_business_idx
    ON public.social_publications (business_id, created_at DESC);

ALTER TABLE public.social_publications ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS social_publications_owner_read ON public.social_publications;
CREATE POLICY social_publications_owner_read ON public.social_publications
    FOR SELECT USING (
        business_id IN (SELECT id FROM public.businesses WHERE owner_id = auth.uid())
    );

DROP POLICY IF EXISTS social_publications_member_read ON public.social_publications;
CREATE POLICY social_publications_member_read ON public.social_publications
    FOR SELECT USING (public.is_business_member(business_id));

GRANT SELECT ON public.social_publications TO authenticated;
GRANT ALL ON public.social_publications TO service_role;

-- Verify:
--   select count(*) from information_schema.columns
--   where table_schema = 'public' and table_name = 'social_publications';   -- 13
--
-- Rollback:
--   DROP TABLE IF EXISTS public.social_publications;
