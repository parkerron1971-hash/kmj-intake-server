-- Owner-only Solutionist marketing. Apply before configuring Buffer.
-- No tenant-facing RLS policies; only authenticated owner API routes use it.
BEGIN;
CREATE TABLE IF NOT EXISTS public.platform_marketing_config (
  id boolean PRIMARY KEY DEFAULT true CHECK(id),
  organization_id text NOT NULL DEFAULT '',
  channels jsonb NOT NULL DEFAULT '[]',
  paused boolean NOT NULL DEFAULT true,
  updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO public.platform_marketing_config(id) VALUES(true) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS public.platform_marketing_assets (
  id uuid PRIMARY KEY,
  sha256 text NOT NULL,
  url text NOT NULL,
  kind text NOT NULL CHECK(kind IN ('image','video')),
  mime_type text NOT NULL,
  name text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.platform_marketing_posts (
  id uuid PRIMARY KEY,
  campaign text NOT NULL,
  payload jsonb NOT NULL,
  content_hash text NOT NULL,
  approved_hash text,
  approved_by uuid,
  approved_at timestamptz,
  revision integer NOT NULL DEFAULT 1,
  status text NOT NULL DEFAULT 'draft' CHECK(status IN
    ('draft','approved','dispatching','submitted','published','failed','uncertain','cancelled')),
  run_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  provider_id text UNIQUE,
  external_url text,
  error text,
  claimed_at timestamptz,
  checked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK(expires_at > run_at)
);
CREATE INDEX IF NOT EXISTS platform_marketing_due ON public.platform_marketing_posts(status,run_at);
CREATE TABLE IF NOT EXISTS public.platform_marketing_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  post_id uuid NOT NULL REFERENCES public.platform_marketing_posts(id),
  snapshot jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.platform_marketing_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.platform_marketing_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.platform_marketing_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.platform_marketing_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.platform_marketing_config, public.platform_marketing_assets,
 public.platform_marketing_posts, public.platform_marketing_events FROM anon, authenticated;
GRANT ALL ON public.platform_marketing_config, public.platform_marketing_assets,
 public.platform_marketing_posts, public.platform_marketing_events TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.platform_marketing_events_id_seq TO service_role;

CREATE OR REPLACE FUNCTION public.platform_marketing_audit() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
  NEW.updated_at=now();
  RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION public.platform_marketing_record() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
  INSERT INTO public.platform_marketing_events(post_id,snapshot) VALUES(NEW.id,to_jsonb(NEW));
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS marketing_touch ON public.platform_marketing_posts;
CREATE TRIGGER marketing_touch BEFORE UPDATE ON public.platform_marketing_posts
 FOR EACH ROW EXECUTE FUNCTION public.platform_marketing_audit();
DROP TRIGGER IF EXISTS marketing_audit ON public.platform_marketing_posts;
CREATE TRIGGER marketing_audit AFTER INSERT OR UPDATE ON public.platform_marketing_posts
 FOR EACH ROW EXECUTE FUNCTION public.platform_marketing_record();

-- An atomic batch: either every exact reviewed version is approved or none is.
CREATE OR REPLACE FUNCTION public.platform_marketing_approve(items jsonb, actor uuid)
RETURNS integer LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE item jsonb; n integer := 0; r public.platform_marketing_posts;
BEGIN
  IF jsonb_array_length(items) < 1 OR jsonb_array_length(items) > 50 THEN
    RAISE EXCEPTION 'Choose between 1 and 50 posts';
  END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(items) ORDER BY value->>'id' LOOP
    SELECT * INTO r FROM public.platform_marketing_posts WHERE id=(item->>'id')::uuid FOR UPDATE;
    IF NOT FOUND OR r.status <> 'draft' OR r.revision <> (item->>'revision')::integer
      OR r.content_hash <> item->>'content_hash' OR r.run_at <= now() THEN
      RAISE EXCEPTION 'Post changed or schedule passed; refresh and review';
    END IF;
    UPDATE public.platform_marketing_posts SET status='approved', approved_hash=content_hash,
      approved_by=actor, approved_at=now() WHERE id=r.id;
    n=n+1;
  END LOOP;
  RETURN n;
END $$;

-- Claim one at a time. Pause serializes with claims. Already claimed posts may
-- finish; no future schedules are handed to Buffer. No automatic resend.
CREATE OR REPLACE FUNCTION public.platform_marketing_claim()
RETURNS SETOF public.platform_marketing_posts LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE paused_now boolean; rid uuid;
BEGIN
  SELECT paused INTO paused_now FROM public.platform_marketing_config WHERE id=true FOR UPDATE;
  IF paused_now IS DISTINCT FROM false THEN RETURN; END IF;
  UPDATE public.platform_marketing_posts SET status='uncertain',error='Delivery interrupted. Reconcile with Buffer before retrying.'
    WHERE status='dispatching' AND claimed_at < now()-interval '5 minutes';
  UPDATE public.platform_marketing_posts SET status='failed',error='Offer or delivery window expired. Edit and review a new schedule.'
    WHERE status='approved' AND expires_at <= now();
  SELECT id INTO rid FROM public.platform_marketing_posts
    WHERE status='approved' AND run_at<=now() AND expires_at>now()
      AND approved_hash=content_hash AND approved_by IS NOT NULL
    ORDER BY run_at,id LIMIT 1 FOR UPDATE SKIP LOCKED;
  IF rid IS NULL THEN RETURN; END IF;
  RETURN QUERY UPDATE public.platform_marketing_posts SET status='dispatching',claimed_at=now()
    WHERE id=rid RETURNING *;
END $$;
REVOKE ALL ON FUNCTION public.platform_marketing_audit(), public.platform_marketing_record(),
 public.platform_marketing_approve(jsonb,uuid),public.platform_marketing_claim() FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.platform_marketing_approve(jsonb,uuid),public.platform_marketing_claim() TO service_role;

-- Only immutable, explicitly uploaded marketing exports are publicly readable.
INSERT INTO storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
VALUES('platform-marketing','platform-marketing',true,104857600,ARRAY['image/png','image/jpeg','video/mp4'])
ON CONFLICT(id) DO NOTHING;
COMMIT;
