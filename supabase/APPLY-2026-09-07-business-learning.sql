-- Apply before deploying business learning. Private, service-only storage.
BEGIN;
CREATE TABLE IF NOT EXISTS public.business_operating_profiles (
  business_id uuid PRIMARY KEY REFERENCES public.businesses(id) ON DELETE CASCADE,
  revision integer NOT NULL CHECK (revision > 0),
  profile jsonb NOT NULL CHECK (jsonb_typeof(profile) = 'object'),
  status text NOT NULL CHECK (status IN ('discovering','needs_input','needs_research','ready_to_build')),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.business_operating_profile_history (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  revision integer NOT NULL,
  profile jsonb NOT NULL,
  reason text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (business_id, revision)
);
ALTER TABLE public.business_operating_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.business_operating_profile_history ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.business_operating_profiles, public.business_operating_profile_history FROM anon, authenticated;
GRANT ALL ON public.business_operating_profiles, public.business_operating_profile_history TO service_role;

CREATE OR REPLACE FUNCTION public.save_business_operating_profile(
  p_business_id uuid, p_expected_revision integer, p_profile jsonb, p_reason text, p_status text
) RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = public AS $$
DECLARE current_revision integer; saved public.business_operating_profiles;
BEGIN
  -- Locks a stable parent even for the first write. Concurrent first writes and
  -- corrections cannot both claim revision 1 or silently overwrite each other.
  PERFORM 1 FROM public.businesses WHERE id = p_business_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'business not found'; END IF;
  SELECT revision INTO current_revision FROM public.business_operating_profiles WHERE business_id = p_business_id;
  IF coalesce(current_revision, 0) <> p_expected_revision THEN
    RETURN jsonb_build_object('conflict', true);
  END IF;
  INSERT INTO public.business_operating_profiles (business_id, revision, profile, status)
    VALUES (p_business_id, p_expected_revision + 1, p_profile, p_status)
    ON CONFLICT (business_id) DO UPDATE SET revision = excluded.revision,
      profile = excluded.profile, status = excluded.status, updated_at = now()
    RETURNING * INTO saved;
  INSERT INTO public.business_operating_profile_history (business_id, revision, profile, reason)
    VALUES (p_business_id, saved.revision, p_profile, left(p_reason, 200));
  RETURN to_jsonb(saved);
END $$;
REVOKE ALL ON FUNCTION public.save_business_operating_profile(uuid,integer,jsonb,text,text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.save_business_operating_profile(uuid,integer,jsonb,text,text) TO service_role;
COMMIT;
