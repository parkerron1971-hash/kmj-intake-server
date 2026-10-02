BEGIN;
CREATE TABLE IF NOT EXISTS public.media_assets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('source','clip')),
  source_id uuid REFERENCES public.media_assets(id) ON DELETE CASCADE,
  name text NOT NULL,
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','processing','ready','failed')),
  configuration jsonb NOT NULL,
  drive_file_id text,
  source_version text,
  encrypted_token text,
  byte_size bigint NOT NULL DEFAULT 0 CHECK (byte_size >= 0),
  duration_seconds double precision,
  sha256 text,
  error text,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  finished_at timestamptz,
  lease_id uuid,
  approval jsonb,
  CHECK ((kind='source' AND source_id IS NULL) OR (kind='clip' AND source_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS media_assets_business_idx ON public.media_assets(business_id,created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS media_one_active_per_business ON public.media_assets(business_id) WHERE status IN ('queued','processing');
CREATE UNIQUE INDEX IF NOT EXISTS media_one_processing_globally ON public.media_assets((true)) WHERE status='processing';
ALTER TABLE public.media_assets ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.media_assets FROM anon,authenticated;
GRANT ALL ON public.media_assets TO service_role;
INSERT INTO storage.buckets(id,name,public,file_size_limit) VALUES('program-media','program-media',false,1073741824)
  ON CONFLICT(id) DO UPDATE SET public=false,file_size_limit=1073741824;
DROP POLICY IF EXISTS private_media_bucket_boundary ON storage.objects;
CREATE POLICY private_media_bucket_boundary ON storage.objects AS RESTRICTIVE FOR ALL TO anon,authenticated
  USING(bucket_id <> 'program-media') WITH CHECK(bucket_id <> 'program-media');

CREATE OR REPLACE FUNCTION public.enqueue_media_asset(p_business_id uuid,p_actor_id uuid,p_asset jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path=public AS $$
DECLARE saved public.media_assets; used bigint;
BEGIN
  PERFORM id FROM public.businesses WHERE id=p_business_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Business unavailable'; END IF;
  IF EXISTS(SELECT 1 FROM public.media_assets WHERE business_id=p_business_id AND status IN ('queued','processing')) THEN
    RETURN jsonb_build_object('refused','A recording or clip is already processing. Wait for it to finish.');
  END IF;
  SELECT coalesce(sum(byte_size),0) INTO used FROM public.media_assets WHERE business_id=p_business_id AND status<>'failed';
  IF used+coalesce((p_asset->>'byte_size')::bigint,0)+104857600 > 21474836480 THEN
    RETURN jsonb_build_object('refused','This media library has reached its 20 GB allowance. Contact support before importing more.');
  END IF;
  IF p_asset->>'kind'='clip' AND NOT EXISTS(SELECT 1 FROM public.media_assets WHERE id=(p_asset->>'source_id')::uuid AND business_id=p_business_id AND kind='source' AND status='ready') THEN
    RAISE EXCEPTION 'Source is not ready in this business';
  END IF;
  INSERT INTO public.media_assets(business_id,kind,source_id,name,configuration,drive_file_id,source_version,encrypted_token,byte_size,created_by)
    VALUES(p_business_id,p_asset->>'kind',(p_asset->>'source_id')::uuid,p_asset->>'name',p_asset->'configuration',p_asset->>'drive_file_id',p_asset->>'source_version',p_asset->>'encrypted_token',coalesce((p_asset->>'byte_size')::bigint,0),p_actor_id)
    RETURNING * INTO saved;
  RETURN to_jsonb(saved);
END $$;

CREATE OR REPLACE FUNCTION public.claim_media_asset() RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path=public AS $$
DECLARE saved public.media_assets;
BEGIN
  IF NOT pg_try_advisory_xact_lock(20260907,71) THEN RETURN NULL; END IF;
  UPDATE public.media_assets SET status='failed',error='Processing was interrupted. Select the source or create the clip again.',encrypted_token=NULL,finished_at=now()
    WHERE (status='processing' AND started_at < now()-interval '35 minutes') OR (status='queued' AND created_at < now()-interval '55 minutes');
  IF EXISTS(SELECT 1 FROM public.media_assets WHERE status='processing') THEN RETURN NULL; END IF;
  SELECT * INTO saved FROM public.media_assets WHERE status='queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1;
  IF NOT FOUND THEN RETURN NULL; END IF;
  UPDATE public.media_assets SET status='processing',started_at=now(),lease_id=gen_random_uuid()
    WHERE id=saved.id RETURNING * INTO saved;
  RETURN to_jsonb(saved);
END $$;

CREATE OR REPLACE FUNCTION public.preserve_media_review() RETURNS trigger
LANGUAGE plpgsql SET search_path=public AS $$
BEGIN
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.business_id IS DISTINCT FROM OLD.business_id OR NEW.kind IS DISTINCT FROM OLD.kind
    OR NEW.source_id IS DISTINCT FROM OLD.source_id OR NEW.configuration IS DISTINCT FROM OLD.configuration
    OR NEW.created_by IS DISTINCT FROM OLD.created_by OR NEW.created_at IS DISTINCT FROM OLD.created_at
    OR NEW.drive_file_id IS DISTINCT FROM OLD.drive_file_id OR NEW.source_version IS DISTINCT FROM OLD.source_version THEN
    RAISE EXCEPTION 'Create a new media item for changed content';
  END IF;
  IF OLD.status='ready' AND (NEW.status IS DISTINCT FROM OLD.status OR NEW.sha256 IS DISTINCT FROM OLD.sha256 OR NEW.byte_size IS DISTINCT FROM OLD.byte_size) THEN
    RAISE EXCEPTION 'Finished media is immutable';
  END IF;
  IF OLD.approval IS NOT NULL AND NEW.approval IS DISTINCT FROM OLD.approval THEN
    RAISE EXCEPTION 'Create a new clip and review it again';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS preserve_media_review ON public.media_assets;
CREATE TRIGGER preserve_media_review BEFORE UPDATE ON public.media_assets FOR EACH ROW EXECUTE FUNCTION public.preserve_media_review();
REVOKE ALL ON FUNCTION public.enqueue_media_asset(uuid,uuid,jsonb),public.claim_media_asset() FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.enqueue_media_asset(uuid,uuid,jsonb),public.claim_media_asset() TO service_role;
COMMIT;
