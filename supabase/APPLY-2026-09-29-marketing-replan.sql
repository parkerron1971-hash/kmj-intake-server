-- "Start this week over" for the Monday plan.
--
-- The first live plan (2026-09-28) quoted the standard price as the founding
-- price. Its drafts were never approved, but a planned week could not be
-- planned again: a succeeded run is closed for good. The owner can now start a
-- week over — only while nothing from it has been approved, submitted or
-- published. The claim cancels the week's remaining drafts and reopens the run
-- in one transaction, so a failure can never leave the week half-cancelled.
--
-- Replaces the three-argument claim (same body plus the replan branch); the
-- old signature is dropped so PostgREST cannot pick between two overloads.
-- Apply after APPLY-2026-09-28-marketing-engine.sql.
BEGIN;
DROP FUNCTION IF EXISTS public.platform_marketing_claim_run(uuid, date, text);
CREATE OR REPLACE FUNCTION public.platform_marketing_claim_run(run_id uuid, week date, source text,
                                                               replan boolean DEFAULT false)
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
  IF replan AND source = 'manual' AND r.status = 'succeeded'
     AND NOT EXISTS (SELECT 1 FROM public.platform_marketing_posts p
                     WHERE p.run_id = r.id AND p.status NOT IN ('draft','cancelled')) THEN
    -- Only a deliberate start-over cancels drafts. A crashed run keeps the
    -- drafts it saved; the engine finds them and records them instead.
    UPDATE public.platform_marketing_posts SET status='cancelled', revision=revision + 1
      WHERE platform_marketing_posts.run_id = r.id AND status = 'draft';
  ELSIF NOT ((r.status IN ('failed','skipped') AND (source = 'manual' OR r.attempts < 3))
             OR (r.status = 'running' AND r.created_at < now() - interval '15 minutes')) THEN
    RETURN false;
  END IF;
  UPDATE public.platform_marketing_runs
    SET status='running', trigger=source, attempts=r.attempts + 1, error=NULL,
        created_at=now(), finished_at=NULL
    WHERE id = r.id;
  RETURN true;
END $$;
REVOKE ALL ON FUNCTION public.platform_marketing_claim_run(uuid, date, text, boolean) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.platform_marketing_claim_run(uuid, date, text, boolean) TO service_role;
COMMIT;
