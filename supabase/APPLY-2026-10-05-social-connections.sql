-- social_connections — which social accounts a business connected through
-- Post for Me (social_connect_router). One row per account.
--
-- NO TOKENS: the network's access/refresh tokens live at Post for Me and
-- are stripped before anything reaches us (post_for_me.public_account).
-- This table holds only what the app shows.
--
-- One account belongs to one business: unique (provider, provider_account_id).
-- Writes come from the backend (service role) only. Members of the business
-- may read their own rows. The owner reads through an owner policy of its
-- own: business_users holds no rows for owners, so a seat-only policy would
-- hide a business's connections from the person who connected them.
-- Additive + idempotent. Safe to apply before the backend deploy.

CREATE TABLE IF NOT EXISTS public.social_connections (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id         uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    provider            text NOT NULL DEFAULT 'post_for_me',
    platform            text NOT NULL,
    provider_account_id text NOT NULL,
    username            text,
    profile_photo_url   text,
    status              text NOT NULL DEFAULT 'connected'
                        CHECK (status IN ('connected', 'disconnected')),
    connected_by        uuid,
    connected_at        timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT social_connections_one_business UNIQUE (provider, provider_account_id)
);

CREATE INDEX IF NOT EXISTS social_connections_business_idx
    ON public.social_connections (business_id, provider);

ALTER TABLE public.social_connections ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS social_connections_owner_read ON public.social_connections;
CREATE POLICY social_connections_owner_read ON public.social_connections
    FOR SELECT USING (
        business_id IN (SELECT id FROM public.businesses WHERE owner_id = auth.uid())
    );

DROP POLICY IF EXISTS social_connections_member_read ON public.social_connections;
CREATE POLICY social_connections_member_read ON public.social_connections
    FOR SELECT USING (public.is_business_member(business_id));

GRANT SELECT ON public.social_connections TO authenticated;
GRANT ALL ON public.social_connections TO service_role;

-- Verify:
--   select column_name from information_schema.columns
--   where table_schema = 'public' and table_name = 'social_connections';
--   select polname from pg_policy where polrelid = 'public.social_connections'::regclass;
--
-- Rollback:
--   DROP TABLE IF EXISTS public.social_connections;
