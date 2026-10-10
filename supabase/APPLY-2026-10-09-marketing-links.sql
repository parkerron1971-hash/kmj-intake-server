-- APPLY-2026-10-09-marketing-links.sql
-- ─────────────────────────────────────────────────────────────────────
-- Tracked links on what goes out besides posts (the Reach plan's step 1:
-- "links on texts, emails and offers too"). A campaign touch (an email or a
-- text) that says {{link}} sends its own short link, {origin}/go/{code},
-- the same kind a desk post carries, so a tap on it is counted, and the
-- visit, lead, booking and payment that follow are credited to that touch
-- (utm_content = the link's id), exactly as a post's are.
--
--   marketing_links       one row per link: whose (business_id), what it is
--                         for (kind + ref_id + part: a campaign and its touch
--                         index; offers later), its code and where it goes.
--   marketing_link_hits   person clicks per link per day (a post's are
--                         marketing_link_clicks; same counting rule).
--   marketing_follow      a code that names no post now looks here: same
--                         answer {business_id, tracked_url}, and the click is
--                         counted for a person. A post's code wins.
--
-- Reads and writes go through the service role (business_marketing_store);
-- an owner never reads these tables directly. Idempotent.
--
-- Rollback:
--   DROP TABLE IF EXISTS public.marketing_link_hits, public.marketing_links;
--   (and re-run marketing_follow from APPLY-2026-10-07-marketing-suite.sql)
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.marketing_links (
  id           uuid PRIMARY KEY,
  business_id  uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  code         text NOT NULL CONSTRAINT marketing_links_code CHECK (code ~ '^[a-z2-7]{8}$'),
  kind         text NOT NULL CONSTRAINT marketing_links_kind CHECK (kind IN ('campaign')),
  ref_id       uuid NOT NULL,
  part         integer NOT NULL DEFAULT 0 CONSTRAINT marketing_links_part CHECK (part >= 0),
  channel      text CONSTRAINT marketing_links_channel CHECK (channel IS NULL OR channel IN ('email', 'sms')),
  landing_url  text NOT NULL,
  tracked_url  text NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT marketing_links_code_unique UNIQUE (code),
  CONSTRAINT marketing_links_for UNIQUE (kind, ref_id, part),
  CONSTRAINT marketing_links_id_business UNIQUE (id, business_id)
);

CREATE TABLE IF NOT EXISTS public.marketing_link_hits (
  link_id      uuid NOT NULL,
  business_id  uuid NOT NULL,
  day          date NOT NULL,
  clicks       integer NOT NULL DEFAULT 0 CONSTRAINT marketing_link_hits_count CHECK (clicks >= 0),
  CONSTRAINT marketing_link_hits_pkey PRIMARY KEY (link_id, day),
  CONSTRAINT marketing_link_hits_link FOREIGN KEY (link_id, business_id)
    REFERENCES public.marketing_links(id, business_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS marketing_links_business ON public.marketing_links (business_id, kind, ref_id);
CREATE INDEX IF NOT EXISTS marketing_link_hits_business ON public.marketing_link_hits (business_id, day);

ALTER TABLE public.marketing_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.marketing_link_hits ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.marketing_links, public.marketing_link_hits FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.marketing_links, public.marketing_link_hits TO service_role;

-- ── marketing_follow: a post's code first, then a link's ─────────────
CREATE OR REPLACE FUNCTION public.marketing_follow(p_code text, p_count_click boolean)
RETURNS TABLE(business_id uuid, tracked_url text)
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
#variable_conflict use_column
DECLARE r public.marketing_posts; l public.marketing_links;
BEGIN
  SELECT * INTO r FROM public.marketing_posts p WHERE p.link_code = p_code;
  IF FOUND THEN
    IF p_count_click AND r.status IN ('submitted','published','partly_published') THEN
      INSERT INTO public.marketing_link_clicks AS c (post_id, business_id, day, clicks)
        VALUES (r.id, r.business_id, (now() AT TIME ZONE 'UTC')::date, 1)
        ON CONFLICT ON CONSTRAINT marketing_link_clicks_pkey
        DO UPDATE SET clicks = c.clicks + 1;
    END IF;
    RETURN QUERY SELECT r.business_id, r.tracked_url;
    RETURN;
  END IF;
  -- A link is made only when its text or email is sent, so every link out
  -- there went out: a person's click on it counts.
  SELECT * INTO l FROM public.marketing_links k WHERE k.code = p_code;
  IF NOT FOUND THEN RETURN; END IF;
  IF p_count_click THEN
    INSERT INTO public.marketing_link_hits AS h (link_id, business_id, day, clicks)
      VALUES (l.id, l.business_id, (now() AT TIME ZONE 'UTC')::date, 1)
      ON CONFLICT ON CONSTRAINT marketing_link_hits_pkey
      DO UPDATE SET clicks = h.clicks + 1;
  END IF;
  RETURN QUERY SELECT l.business_id, l.tracked_url;
END $$;

REVOKE ALL ON FUNCTION public.marketing_follow(text, boolean) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.marketing_follow(text, boolean) TO service_role;
