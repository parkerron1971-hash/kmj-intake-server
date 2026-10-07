-- Marketing suite storage: one marketing desk per business (B3 of the
-- 2026-10-07 marketing-suite plan, decision D1).
--
-- The Mission Control desk (platform_marketing_*) is single-tenant: one config
-- row, one row per Buffer channel, week_of UNIQUE. These tables are the same
-- desk for every business, one row per post idea with its accounts in
-- `targets` (the shape social_publications uses). platform_marketing_* is not
-- touched here.
--
--   marketing_desks        one per business: settings (paused, accounts, hour)
--   marketing_runs         one per business per week: what was planned and why
--   marketing_posts        one per post idea; the approval is bound to
--                          content_hash (business_marketing_store.digest)
--   marketing_link_clicks  person clicks per post per day (a click is not an
--                          edit, so it stays off the post's audit trail)
--   marketing_post_events  a snapshot of every insert/update of a post
--
-- WHO CAN DO WHAT. Every write is the backend's, as the service role, after
-- its own owner check. The owner and the business's active members may READ
-- desks, runs and posts (owner policy + member policy, as social_* do; no
-- write policies). Clicks and events are service-role only. No USING (true)
-- anywhere. The owner check reads public.businesses under the caller's own
-- RLS and the member check goes through the SECURITY DEFINER helper
-- public.is_business_member, so no policy here can join the 42P17 cycle
-- (docs/RLS_MODEL.md, rules 2 and 3): nothing references these tables back.
--
-- THE FOUR RPCs (service_role only; nothing else may execute them):
--   marketing_claim_run   first claim of a business's week wins; a failed or
--                         skipped week is reclaimed by the scheduler at most 3
--                         attempts and by the owner always; a run stuck
--                         running 15+ minutes is reclaimable; a succeeded week
--                         only by a deliberate manual replan while none of its
--                         posts has been approved or sent.
--   marketing_approve     all-or-nothing for 1-50 posts of ONE business: each
--                         a draft at the reviewed revision and content_hash,
--                         still in the future, its flyer not mid-design.
--   marketing_claim_due   stale dispatching -> uncertain, expired approvals ->
--                         failed, then claims due posts whose approval still
--                         matches their content, on desks that are not paused.
--                         SKIP LOCKED on the posts; the desk row is share-locked
--                         so a pause (an UPDATE of that row) and a claim
--                         serialize: a claim either finishes first or skips
--                         the desk being paused.
--   marketing_follow      a short link's (business_id, tracked_url); counts a
--                         click only for a post that went out.
--
-- Requires public.businesses, public.is_business_member(uuid) and auth.uid()
-- (all live). Does not require the social_* tables. Idempotent: safe to apply
-- twice. Apply by hand after merge; nothing reads these tables yet.
--
-- Verify after applying:
--   SELECT t, to_regclass('public.' || t) IS NOT NULL AS present
--     FROM unnest(ARRAY['marketing_desks','marketing_runs','marketing_posts',
--                       'marketing_link_clicks','marketing_post_events']) AS t;
--   SELECT tablename, policyname, cmd, roles, qual FROM pg_policies
--    WHERE tablename LIKE 'marketing\_%' AND tablename NOT LIKE 'platform\_%'
--    ORDER BY 1, 2;            -- expect 6 SELECT policies, none with qual = true
--
-- Rollback (nothing else references these tables):
--   DROP FUNCTION IF EXISTS public.marketing_follow(text, boolean),
--     public.marketing_claim_due(integer),
--     public.marketing_approve(uuid, jsonb, uuid, text),
--     public.marketing_claim_run(uuid, uuid, date, text, text, boolean);
--   DROP TABLE IF EXISTS public.marketing_post_events, public.marketing_link_clicks,
--     public.marketing_posts, public.marketing_runs, public.marketing_desks;
--   DROP FUNCTION IF EXISTS public.marketing_post_record(), public.marketing_touch();

BEGIN;

-- ── tables ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.marketing_desks (
  business_id     uuid PRIMARY KEY REFERENCES public.businesses(id) ON DELETE CASCADE,
  plan_enabled    boolean NOT NULL DEFAULT false,
  paused          boolean NOT NULL DEFAULT false,
  connection_ids  uuid[] NOT NULL DEFAULT '{}',
  post_hour       smallint NOT NULL DEFAULT 11
                  CONSTRAINT marketing_desks_post_hour CHECK (post_hour BETWEEN 6 AND 21),
  audience        text,
  landing_url     text,
  work_photo_ids  uuid[] NOT NULL DEFAULT '{}',
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.marketing_runs (
  id           uuid PRIMARY KEY,
  business_id  uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  week_of      date NOT NULL,
  kind         text NOT NULL
               CONSTRAINT marketing_runs_kind CHECK (kind IN ('suggestion','week','openings')),
  trigger      text NOT NULL
               CONSTRAINT marketing_runs_trigger CHECK (trigger IN ('scheduled','manual')),
  status       text NOT NULL DEFAULT 'running'
               CONSTRAINT marketing_runs_status CHECK (status IN ('running','succeeded','failed','skipped')),
  attempts     integer NOT NULL DEFAULT 1 CONSTRAINT marketing_runs_attempts CHECK (attempts > 0),
  signals      jsonb,
  diagnosis    jsonb,
  plays        jsonb,
  slots        jsonb,
  dropped      jsonb,
  design       jsonb,
  post_ids     uuid[] NOT NULL DEFAULT '{}',
  error        text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  finished_at  timestamptz,
  CONSTRAINT marketing_runs_one_per_week UNIQUE (business_id, week_of),
  -- Lets a post name its run AND its business, so a post can never sit
  -- under another business's run.
  CONSTRAINT marketing_runs_id_business UNIQUE (id, business_id)
);

CREATE TABLE IF NOT EXISTS public.marketing_posts (
  id              uuid PRIMARY KEY,
  business_id     uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  run_id          uuid,
  play_id         text,
  source          text NOT NULL
                  CONSTRAINT marketing_posts_source CHECK (source IN
                    ('suggestion','plan','owner','chief','clip','opening')),
  caption         text NOT NULL DEFAULT '',
  publish_text    text NOT NULL DEFAULT '',
  landing_url     text,
  tracked_url     text,
  link_code       text,
  media           jsonb NOT NULL DEFAULT '{}'::jsonb
                  CONSTRAINT marketing_posts_media_object CHECK (jsonb_typeof(media) = 'object'),
  targets         jsonb NOT NULL DEFAULT '[]'::jsonb
                  CONSTRAINT marketing_posts_targets_array CHECK (jsonb_typeof(targets) = 'array'),
  opening         jsonb,
  design_status   text NOT NULL DEFAULT 'none'
                  CONSTRAINT marketing_posts_design_status CHECK (design_status IN
                    ('none','designing','ready','failed')),
  content_hash    text NOT NULL
                  CONSTRAINT marketing_posts_content_hash CHECK (content_hash ~ '^[a-f0-9]{64}$'),
  approved_hash   text,
  approved_by     uuid,
  approved_at     timestamptz,
  approved_via    text
                  CONSTRAINT marketing_posts_approved_via CHECK (approved_via IN ('owner','standing')),
  revision        integer NOT NULL DEFAULT 1 CONSTRAINT marketing_posts_revision CHECK (revision > 0),
  status          text NOT NULL DEFAULT 'draft'
                  CONSTRAINT marketing_posts_status CHECK (status IN
                    ('draft','approved','dispatching','submitted','published','partly_published',
                     'failed','uncertain','cancelled','pulled')),
  run_at          timestamptz NOT NULL,
  expires_at      timestamptz NOT NULL,
  publication_id  uuid,
  external_urls   jsonb NOT NULL DEFAULT '[]'::jsonb,
  error           text,
  claimed_at      timestamptz,
  checked_at      timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT marketing_posts_window CHECK (expires_at > run_at),
  CONSTRAINT marketing_posts_id_business UNIQUE (id, business_id),
  CONSTRAINT marketing_posts_run FOREIGN KEY (run_id, business_id)
    REFERENCES public.marketing_runs(id, business_id)
);

CREATE TABLE IF NOT EXISTS public.marketing_link_clicks (
  post_id      uuid NOT NULL,
  business_id  uuid NOT NULL,
  day          date NOT NULL,
  clicks       integer NOT NULL DEFAULT 0 CONSTRAINT marketing_link_clicks_count CHECK (clicks >= 0),
  CONSTRAINT marketing_link_clicks_pkey PRIMARY KEY (post_id, day),
  CONSTRAINT marketing_link_clicks_post FOREIGN KEY (post_id, business_id)
    REFERENCES public.marketing_posts(id, business_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS public.marketing_post_events (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  post_id      uuid NOT NULL,
  business_id  uuid NOT NULL,
  snapshot     jsonb NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT marketing_post_events_post FOREIGN KEY (post_id, business_id)
    REFERENCES public.marketing_posts(id, business_id) ON DELETE CASCADE
);

-- ── indexes ──────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS marketing_posts_due ON public.marketing_posts (status, run_at);
CREATE INDEX IF NOT EXISTS marketing_posts_business ON public.marketing_posts (business_id, run_at DESC);
CREATE INDEX IF NOT EXISTS marketing_posts_run_idx ON public.marketing_posts (run_id);
CREATE UNIQUE INDEX IF NOT EXISTS marketing_posts_link_code
  ON public.marketing_posts (link_code) WHERE link_code IS NOT NULL;
CREATE INDEX IF NOT EXISTS marketing_link_clicks_business ON public.marketing_link_clicks (business_id, day);
CREATE INDEX IF NOT EXISTS marketing_post_events_post ON public.marketing_post_events (post_id, id);
CREATE INDEX IF NOT EXISTS marketing_post_events_business ON public.marketing_post_events (business_id, id);

-- ── row level security: owner + member read, service-role writes ─────

ALTER TABLE public.marketing_desks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.marketing_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.marketing_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.marketing_link_clicks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.marketing_post_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS marketing_desks_owner_read ON public.marketing_desks;
CREATE POLICY marketing_desks_owner_read ON public.marketing_desks
  FOR SELECT TO authenticated
  USING (business_id IN (SELECT id FROM public.businesses WHERE owner_id = auth.uid()));
DROP POLICY IF EXISTS marketing_desks_member_read ON public.marketing_desks;
CREATE POLICY marketing_desks_member_read ON public.marketing_desks
  FOR SELECT TO authenticated
  USING (public.is_business_member(business_id));

DROP POLICY IF EXISTS marketing_runs_owner_read ON public.marketing_runs;
CREATE POLICY marketing_runs_owner_read ON public.marketing_runs
  FOR SELECT TO authenticated
  USING (business_id IN (SELECT id FROM public.businesses WHERE owner_id = auth.uid()));
DROP POLICY IF EXISTS marketing_runs_member_read ON public.marketing_runs;
CREATE POLICY marketing_runs_member_read ON public.marketing_runs
  FOR SELECT TO authenticated
  USING (public.is_business_member(business_id));

DROP POLICY IF EXISTS marketing_posts_owner_read ON public.marketing_posts;
CREATE POLICY marketing_posts_owner_read ON public.marketing_posts
  FOR SELECT TO authenticated
  USING (business_id IN (SELECT id FROM public.businesses WHERE owner_id = auth.uid()));
DROP POLICY IF EXISTS marketing_posts_member_read ON public.marketing_posts;
CREATE POLICY marketing_posts_member_read ON public.marketing_posts
  FOR SELECT TO authenticated
  USING (public.is_business_member(business_id));

-- Supabase's default privileges hand anon and authenticated everything on a
-- new public table; take it all back, then give the readers SELECT only.
REVOKE ALL ON public.marketing_desks, public.marketing_runs, public.marketing_posts,
  public.marketing_link_clicks, public.marketing_post_events FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.marketing_desks, public.marketing_runs, public.marketing_posts TO authenticated;
GRANT ALL ON public.marketing_desks, public.marketing_runs, public.marketing_posts,
  public.marketing_link_clicks, public.marketing_post_events TO service_role;
REVOKE ALL ON SEQUENCE public.marketing_post_events_id_seq FROM PUBLIC, anon, authenticated;
GRANT USAGE, SELECT ON SEQUENCE public.marketing_post_events_id_seq TO service_role;

-- ── the audit trail (same touch/record pattern as the platform desk) ─

CREATE OR REPLACE FUNCTION public.marketing_touch() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION public.marketing_post_record() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
  INSERT INTO public.marketing_post_events(post_id, business_id, snapshot)
    VALUES (NEW.id, NEW.business_id, to_jsonb(NEW));
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS marketing_desks_touch ON public.marketing_desks;
CREATE TRIGGER marketing_desks_touch BEFORE UPDATE ON public.marketing_desks
  FOR EACH ROW EXECUTE FUNCTION public.marketing_touch();
DROP TRIGGER IF EXISTS marketing_posts_touch ON public.marketing_posts;
CREATE TRIGGER marketing_posts_touch BEFORE UPDATE ON public.marketing_posts
  FOR EACH ROW EXECUTE FUNCTION public.marketing_touch();
DROP TRIGGER IF EXISTS marketing_posts_audit ON public.marketing_posts;
CREATE TRIGGER marketing_posts_audit AFTER INSERT OR UPDATE ON public.marketing_posts
  FOR EACH ROW EXECUTE FUNCTION public.marketing_post_record();

-- ── marketing_claim_run: one plan per business per week ──────────────
-- The run id is derived in code from (business, week), so a retry, a restart
-- or a second click lands on the same row. Same rules as
-- platform_marketing_claim_run, keyed by business.
CREATE OR REPLACE FUNCTION public.marketing_claim_run(p_run_id uuid, p_business_id uuid, p_week date,
                                                      p_kind text, p_source text,
                                                      p_replan boolean DEFAULT false)
RETURNS boolean LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE r public.marketing_runs;
BEGIN
  IF p_source IS NULL OR p_source NOT IN ('scheduled','manual') THEN
    RAISE EXCEPTION 'Unknown run source';
  END IF;
  IF p_kind IS NULL OR p_kind NOT IN ('suggestion','week','openings') THEN
    RAISE EXCEPTION 'Unknown run kind';
  END IF;
  INSERT INTO public.marketing_runs(id, business_id, week_of, kind, trigger)
    VALUES (p_run_id, p_business_id, p_week, p_kind, p_source)
    ON CONFLICT (business_id, week_of) DO NOTHING;
  IF FOUND THEN RETURN true; END IF;
  SELECT * INTO r FROM public.marketing_runs
    WHERE business_id = p_business_id AND week_of = p_week FOR UPDATE;
  IF r.id IS DISTINCT FROM p_run_id THEN RETURN false; END IF;
  IF p_replan AND p_source = 'manual' AND r.status = 'succeeded'
     AND NOT EXISTS (SELECT 1 FROM public.marketing_posts p
                     WHERE p.run_id = r.id AND p.status NOT IN ('draft','cancelled')) THEN
    -- Only a deliberate start-over cancels drafts. A crashed run keeps the
    -- drafts it saved; the planner finds them by run_id and keeps them.
    UPDATE public.marketing_posts p SET status = 'cancelled', revision = p.revision + 1
      WHERE p.run_id = r.id AND p.status = 'draft';
  ELSIF NOT ((r.status IN ('failed','skipped') AND (p_source = 'manual' OR r.attempts < 3))
             OR (r.status = 'running' AND r.created_at < now() - interval '15 minutes')) THEN
    RETURN false;
  END IF;
  UPDATE public.marketing_runs
    SET status = 'running', trigger = p_source, kind = p_kind, attempts = r.attempts + 1,
        error = NULL, created_at = now(), finished_at = NULL
    WHERE id = r.id;
  RETURN true;
END $$;

-- ── marketing_approve: every exact reviewed version, or none ─────────
-- p_items: [{"id": uuid, "revision": int, "content_hash": hex}, ...]
-- Locks in id order, so two approvals of overlapping batches cannot deadlock.
-- A post of another business reads exactly like a changed one.
CREATE OR REPLACE FUNCTION public.marketing_approve(p_business_id uuid, p_items jsonb, p_actor uuid,
                                                    p_via text DEFAULT 'owner')
RETURNS integer LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE item jsonb; n integer := 0; r public.marketing_posts;
BEGIN
  IF p_business_id IS NULL OR p_actor IS NULL THEN
    RAISE EXCEPTION 'Say which business and who approved';
  END IF;
  IF p_via IS NULL OR p_via NOT IN ('owner','standing') THEN
    RAISE EXCEPTION 'Unknown kind of approval';
  END IF;
  IF p_items IS NULL OR jsonb_typeof(p_items) <> 'array'
     OR jsonb_array_length(p_items) < 1 OR jsonb_array_length(p_items) > 50 THEN
    RAISE EXCEPTION 'Choose between 1 and 50 posts';
  END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(p_items) ORDER BY value->>'id' LOOP
    SELECT * INTO r FROM public.marketing_posts WHERE id = (item->>'id')::uuid FOR UPDATE;
    IF NOT FOUND OR r.business_id IS DISTINCT FROM p_business_id THEN
      RAISE EXCEPTION 'A post changed or its time passed; refresh and review again';
    END IF;
    IF r.design_status = 'designing' THEN
      RAISE EXCEPTION 'A flyer is still being made; approve that post when it is ready';
    END IF;
    IF r.status <> 'draft'
       OR r.revision IS DISTINCT FROM (item->>'revision')::integer
       OR r.content_hash IS DISTINCT FROM item->>'content_hash'
       OR r.run_at <= now() THEN
      RAISE EXCEPTION 'A post changed or its time passed; refresh and review again';
    END IF;
    UPDATE public.marketing_posts
      SET status = 'approved', approved_hash = content_hash, approved_by = p_actor,
          approved_at = now(), approved_via = p_via
      WHERE id = r.id;
    n := n + 1;
  END LOOP;
  RETURN n;
END $$;

-- ── marketing_claim_due: hand the sender what is due, once ───────────
-- A claim is never resent automatically: a send that stopped part-way is
-- 'uncertain' until a person checks the accounts. Already-claimed posts may
-- finish after a pause; nothing new is claimed from a paused desk, and a post
-- without a desk row is never claimed.
CREATE OR REPLACE FUNCTION public.marketing_claim_due(p_limit integer DEFAULT 10)
RETURNS SETOF public.marketing_posts LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
  IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100 THEN
    RAISE EXCEPTION 'Claim between 1 and 100 posts';
  END IF;
  UPDATE public.marketing_posts
    SET status = 'uncertain',
        error = 'Sending was interrupted. Check the accounts before sending it again.'
    WHERE status = 'dispatching' AND claimed_at < now() - interval '10 minutes';
  UPDATE public.marketing_posts
    SET status = 'failed',
        error = 'Its time to post passed before it went out. Edit it and approve a new time.'
    WHERE status = 'approved' AND expires_at <= now();
  RETURN QUERY
    WITH due AS (
      SELECT p.id
        FROM public.marketing_posts p
        JOIN public.marketing_desks d ON d.business_id = p.business_id
       WHERE p.status = 'approved' AND p.run_at <= now() AND p.expires_at > now()
         AND p.approved_hash = p.content_hash
         AND p.approved_by IS NOT NULL AND p.approved_via IS NOT NULL
         AND NOT d.paused
       ORDER BY p.run_at, p.id
       LIMIT p_limit
       FOR UPDATE OF p SKIP LOCKED
       FOR SHARE OF d SKIP LOCKED
    )
    UPDATE public.marketing_posts p
       SET status = 'dispatching', claimed_at = now()
      FROM due
     WHERE p.id = due.id
    RETURNING p.*;
END $$;

-- ── marketing_follow: a short link's destination ─────────────────────
-- Counts a click only when asked (the caller has excluded bots and Do Not
-- Track) and only for a post that went out; previewing a draft's link is not
-- a click. Unknown code: no row.
CREATE OR REPLACE FUNCTION public.marketing_follow(p_code text, p_count_click boolean)
RETURNS TABLE(business_id uuid, tracked_url text)
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
#variable_conflict use_column
DECLARE r public.marketing_posts;
BEGIN
  SELECT * INTO r FROM public.marketing_posts p WHERE p.link_code = p_code;
  IF NOT FOUND THEN RETURN; END IF;
  IF p_count_click AND r.status IN ('submitted','published','partly_published') THEN
    INSERT INTO public.marketing_link_clicks AS c (post_id, business_id, day, clicks)
      VALUES (r.id, r.business_id, (now() AT TIME ZONE 'UTC')::date, 1)
      ON CONFLICT ON CONSTRAINT marketing_link_clicks_pkey
      DO UPDATE SET clicks = c.clicks + 1;
  END IF;
  RETURN QUERY SELECT r.business_id, r.tracked_url;
END $$;

REVOKE ALL ON FUNCTION public.marketing_touch(), public.marketing_post_record(),
  public.marketing_claim_run(uuid, uuid, date, text, text, boolean),
  public.marketing_approve(uuid, jsonb, uuid, text),
  public.marketing_claim_due(integer),
  public.marketing_follow(text, boolean)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
  public.marketing_claim_run(uuid, uuid, date, text, text, boolean),
  public.marketing_approve(uuid, jsonb, uuid, text),
  public.marketing_claim_due(integer),
  public.marketing_follow(text, boolean)
  TO service_role;

COMMIT;

NOTIFY pgrst, 'reload schema';
