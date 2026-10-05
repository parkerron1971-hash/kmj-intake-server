-- Find my best clips (Grow → Video Clips). Apply BEFORE raising the
-- project-wide storage upload limit (Management API config/storage
-- fileSizeLimit, 100 MB → 5 GB): every bucket that relied on the 100 MB
-- project cap gets that cap as its own limit first, so the raise only
-- reaches program-media.
BEGIN;

UPDATE storage.buckets SET file_size_limit = 104857600 WHERE file_size_limit IS NULL;
UPDATE storage.buckets SET file_size_limit = 5368709120 WHERE id = 'program-media';

-- Recordings uploaded from a computer exist before their bytes arrive.
ALTER TABLE public.media_assets DROP CONSTRAINT IF EXISTS media_assets_status_check;
ALTER TABLE public.media_assets ADD CONSTRAINT media_assets_status_check
  CHECK (status IN ('uploading','queued','processing','ready','failed'));
-- Keep or skip on a finished clip, and when the original recording was
-- removed under the 7-day rule. Neither is part of the reviewed content,
-- so preserve_media_review leaves them editable.
ALTER TABLE public.media_assets ADD COLUMN IF NOT EXISTS decision text CHECK (decision IN ('kept','skipped'));
ALTER TABLE public.media_assets ADD COLUMN IF NOT EXISTS decided_at timestamptz;
ALTER TABLE public.media_assets ADD COLUMN IF NOT EXISTS source_removed_at timestamptz;

CREATE TABLE IF NOT EXISTS public.media_clip_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  source_id uuid NOT NULL REFERENCES public.media_assets(id) ON DELETE CASCADE,
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','working','completed','failed','cancelled')),
  stage text NOT NULL DEFAULT 'queued',
  percent double precision NOT NULL DEFAULT 0,
  clips_done integer NOT NULL DEFAULT 0,
  clips_total integer NOT NULL DEFAULT 0,
  options jsonb NOT NULL DEFAULT '{}'::jsonb,
  source_seconds double precision NOT NULL CHECK (source_seconds > 0),
  error text,
  counts jsonb,
  cost jsonb,
  timings jsonb,
  units integer NOT NULL DEFAULT 0,
  attempt integer NOT NULL DEFAULT 0,
  lease_id uuid,
  lease_until timestamptz,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  finished_at timestamptz
);
CREATE INDEX IF NOT EXISTS media_clip_runs_business_idx ON public.media_clip_runs(business_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS media_clip_runs_one_active_per_business ON public.media_clip_runs(business_id) WHERE status IN ('queued','working');
ALTER TABLE public.media_clip_runs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.media_clip_runs FROM anon, authenticated;
GRANT ALL ON public.media_clip_runs TO service_role;

-- One run at a time across the platform (the clip service runs one job).
-- A lease that lapsed means the API restarted mid-run: take it back and
-- resume, since the clip service keeps the job under the same id. Give up
-- after three claims or two hours.
CREATE OR REPLACE FUNCTION public.claim_clip_run() RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = public AS $$
DECLARE saved public.media_clip_runs;
BEGIN
  IF NOT pg_try_advisory_xact_lock(20261005, 1) THEN RETURN NULL; END IF;
  UPDATE public.media_clip_runs
     SET status = 'failed', stage = 'failed', finished_at = now(),
         error = 'Finding clips was interrupted. Try again.'
   WHERE status IN ('queued','working')
     AND (created_at < now() - interval '2 hours'
          OR (status = 'working' AND lease_until < now() AND attempt >= 3));
  IF EXISTS (SELECT 1 FROM public.media_clip_runs WHERE status = 'working' AND lease_until >= now()) THEN
    RETURN NULL;
  END IF;
  SELECT * INTO saved FROM public.media_clip_runs
   WHERE status = 'queued' OR (status = 'working' AND lease_until < now())
   ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1;
  IF NOT FOUND THEN RETURN NULL; END IF;
  UPDATE public.media_clip_runs
     SET status = 'working', lease_id = gen_random_uuid(), lease_until = now() + interval '2 minutes',
         attempt = attempt + 1, started_at = coalesce(started_at, now())
   WHERE id = saved.id RETURNING * INTO saved;
  RETURN to_jsonb(saved);
END $$;
REVOKE ALL ON FUNCTION public.claim_clip_run() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_clip_run() TO service_role;

COMMIT;
