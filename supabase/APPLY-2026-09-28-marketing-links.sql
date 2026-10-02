-- Every Solutionist marketing post carries its own short link.
--
-- Public captions stay clean (https://mysolutionist.app/go/<code>) while the
-- redirect behind the code adds the campaign tags, so a visit, lead or signup
-- can be followed back to the exact post that brought it. Before this, the
-- clean caption link carried no tags at all and every social visit arrived
-- untracked.
--
-- Clicks are counted per post per day in their own table, NOT on the post row:
-- every UPDATE of platform_marketing_posts writes a full audit snapshot, and a
-- click is not an edit. Apply after APPLY-2026-09-26-marketing-campaigns.sql.
BEGIN;
ALTER TABLE public.platform_marketing_posts ADD COLUMN IF NOT EXISTS link_code text;
CREATE UNIQUE INDEX IF NOT EXISTS platform_marketing_posts_link_code
  ON public.platform_marketing_posts(link_code) WHERE link_code IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.platform_marketing_link_clicks (
  post_id uuid NOT NULL REFERENCES public.platform_marketing_posts(id),
  day date NOT NULL,
  clicks integer NOT NULL DEFAULT 0 CHECK(clicks >= 0),
  PRIMARY KEY(post_id, day)
);
ALTER TABLE public.platform_marketing_link_clicks ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.platform_marketing_link_clicks FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.platform_marketing_link_clicks TO service_role;

-- Resolve a code to its tagged destination. Counts a click only when asked
-- (the caller has already excluded bots and Do Not Track) and only for a post
-- that has actually gone out: previewing a draft's link is not a click.
CREATE OR REPLACE FUNCTION public.platform_marketing_follow(code text, count_click boolean)
RETURNS text LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE r public.platform_marketing_posts;
BEGIN
  SELECT * INTO r FROM public.platform_marketing_posts WHERE link_code = code;
  IF NOT FOUND THEN RETURN NULL; END IF;
  IF count_click AND r.status IN ('submitted','published') THEN
    INSERT INTO public.platform_marketing_link_clicks(post_id, day, clicks)
      VALUES (r.id, (now() AT TIME ZONE 'UTC')::date, 1)
      ON CONFLICT (post_id, day) DO UPDATE
      SET clicks = public.platform_marketing_link_clicks.clicks + 1;
  END IF;
  RETURN r.payload->>'tracked_url';
END $$;
REVOKE ALL ON FUNCTION public.platform_marketing_follow(text, boolean) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.platform_marketing_follow(text, boolean) TO service_role;
COMMIT;
