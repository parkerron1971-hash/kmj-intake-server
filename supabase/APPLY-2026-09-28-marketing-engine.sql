-- The Monday plan for Solutionist's own marketing (marketing_engine.py).
--
-- One run per planned week. The run id is derived from the week in code, so a
-- week is planned once: a scheduled retry, a restart or a second click all land
-- on the same row. A failed or skipped week can be claimed again, the scheduler
-- at most three times so a week that keeps failing stops spending; the owner's
-- own "plan this week" always may. A run that died mid-way (running for more
-- than 15 minutes) can be reclaimed; its drafts, if any were saved, are found by
-- run_id and kept rather than written twice.
--
-- Posts gain play_id and run_id: which play a post served and which week made
-- it. Both sit outside the approval fingerprint, like campaign_id. Apply after
-- APPLY-2026-09-28-marketing-links.sql.
BEGIN;
CREATE TABLE IF NOT EXISTS public.platform_marketing_runs (
  id uuid PRIMARY KEY,
  week_of date NOT NULL UNIQUE,
  trigger text NOT NULL CHECK(trigger IN ('scheduled','manual')),
  status text NOT NULL DEFAULT 'running' CHECK(status IN ('running','succeeded','failed','skipped')),
  attempts integer NOT NULL DEFAULT 1 CHECK(attempts > 0),
  signals jsonb,
  diagnosis jsonb,
  plays jsonb,
  slots jsonb,
  dropped jsonb,
  post_ids uuid[] NOT NULL DEFAULT '{}',
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz
);
ALTER TABLE public.platform_marketing_posts ADD COLUMN IF NOT EXISTS play_id text;
ALTER TABLE public.platform_marketing_posts ADD COLUMN IF NOT EXISTS run_id uuid
  REFERENCES public.platform_marketing_runs(id);
CREATE INDEX IF NOT EXISTS platform_marketing_posts_run ON public.platform_marketing_posts(run_id);

ALTER TABLE public.platform_marketing_runs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.platform_marketing_runs FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.platform_marketing_runs TO service_role;

CREATE OR REPLACE FUNCTION public.platform_marketing_claim_run(run_id uuid, week date, source text)
RETURNS boolean LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE r public.platform_marketing_runs;
BEGIN
  IF source NOT IN ('scheduled','manual') THEN
    RAISE EXCEPTION 'Unknown run source';
  END IF;
  INSERT INTO public.platform_marketing_runs(id, week_of, trigger)
    VALUES (run_id, week, source)
    ON CONFLICT (week_of) DO NOTHING;
  IF FOUND THEN RETURN true; END IF;
  SELECT * INTO r FROM public.platform_marketing_runs WHERE week_of = week FOR UPDATE;
  IF r.id <> run_id THEN RETURN false; END IF;
  IF (r.status IN ('failed','skipped') AND (source = 'manual' OR r.attempts < 3))
     OR (r.status = 'running' AND r.created_at < now() - interval '15 minutes') THEN
    UPDATE public.platform_marketing_runs
      SET status='running', trigger=source, attempts=r.attempts + 1, error=NULL,
          created_at=now(), finished_at=NULL
      WHERE id = r.id;
    RETURN true;
  END IF;
  RETURN false;
END $$;
REVOKE ALL ON FUNCTION public.platform_marketing_claim_run(uuid, date, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.platform_marketing_claim_run(uuid, date, text) TO service_role;
COMMIT;
