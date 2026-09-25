-- Customer-owned confidential Link OAuth. Separate encrypted storage from the private pilot.
CREATE TABLE IF NOT EXISTS public.link_wallet_sessions (
  business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  encrypted_state text,
  oauth_state_hash text,
  lease_id uuid,
  lease_until timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (business_id, user_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS link_wallet_oauth_state_idx ON public.link_wallet_sessions(oauth_state_hash) WHERE oauth_state_hash IS NOT NULL;
ALTER TABLE public.link_wallet_sessions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.link_wallet_sessions FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.link_wallet_sessions TO service_role;

CREATE OR REPLACE FUNCTION public.link_wallet_acquire(
  p_business_id uuid, p_user_id uuid, p_lease_id uuid
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE row_value public.link_wallet_sessions;
BEGIN
  IF p_lease_id IS NULL THEN RAISE EXCEPTION 'lease_required'; END IF;
  INSERT INTO public.link_wallet_sessions(business_id,user_id)
    VALUES(p_business_id,p_user_id) ON CONFLICT DO NOTHING;
  UPDATE public.link_wallet_sessions SET lease_id=p_lease_id,
    lease_until=clock_timestamp()+interval '120 seconds'
    WHERE business_id=p_business_id AND user_id=p_user_id
      AND (lease_id IS NULL OR lease_until < clock_timestamp()) RETURNING * INTO row_value;
  IF NOT FOUND THEN RETURN jsonb_build_object('acquired',false); END IF;
  RETURN jsonb_build_object('acquired',true,'encrypted_state',row_value.encrypted_state);
END $$;

CREATE OR REPLACE FUNCTION public.link_wallet_save(
  p_business_id uuid, p_user_id uuid, p_lease_id uuid, p_encrypted_state text, p_oauth_state_hash text DEFAULT NULL
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF p_encrypted_state IS NULL OR length(p_encrypted_state)>65536
    OR (p_oauth_state_hash IS NOT NULL AND p_oauth_state_hash !~ '^[a-f0-9]{64}$') THEN
    RAISE EXCEPTION 'invalid_state';
  END IF;
  UPDATE public.link_wallet_sessions SET encrypted_state=p_encrypted_state,oauth_state_hash=p_oauth_state_hash,
    updated_at=clock_timestamp(),lease_until=clock_timestamp()+interval '120 seconds'
    WHERE business_id=p_business_id AND user_id=p_user_id
      AND lease_id=p_lease_id AND lease_until>clock_timestamp();
  RETURN FOUND;
END $$;

CREATE OR REPLACE FUNCTION public.link_wallet_release(
  p_business_id uuid, p_user_id uuid, p_lease_id uuid
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  UPDATE public.link_wallet_sessions SET lease_id=NULL,lease_until=NULL
    WHERE business_id=p_business_id AND user_id=p_user_id AND lease_id=p_lease_id;
  RETURN FOUND;
END $$;

REVOKE ALL ON FUNCTION public.link_wallet_acquire(uuid,uuid,uuid) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.link_wallet_save(uuid,uuid,uuid,text,text) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.link_wallet_release(uuid,uuid,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.link_wallet_acquire(uuid,uuid,uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.link_wallet_save(uuid,uuid,uuid,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.link_wallet_release(uuid,uuid,uuid) TO service_role;
CREATE OR REPLACE FUNCTION public.link_wallet_find_oauth(p_state_hash text)
RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  SELECT jsonb_build_object('business_id',business_id,'user_id',user_id)
  FROM public.link_wallet_sessions WHERE oauth_state_hash=p_state_hash
    AND updated_at>clock_timestamp()-interval '10 minutes';
$$;
REVOKE ALL ON FUNCTION public.link_wallet_find_oauth(text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.link_wallet_find_oauth(text) TO service_role;
NOTIFY pgrst, 'reload schema';

