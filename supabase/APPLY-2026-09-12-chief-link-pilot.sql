-- Private single-owner Link rehearsal. No tokens or card data in readable columns.
CREATE TABLE IF NOT EXISTS public.chief_link_pilot_sessions (
  business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  encrypted_state text,
  lease_id uuid,
  lease_until timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (business_id, user_id)
);
ALTER TABLE public.chief_link_pilot_sessions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.chief_link_pilot_sessions FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.chief_link_pilot_sessions TO service_role;

CREATE OR REPLACE FUNCTION public.chief_link_pilot_acquire(
  p_business_id uuid, p_user_id uuid, p_lease_id uuid
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE row_value public.chief_link_pilot_sessions;
BEGIN
  IF p_lease_id IS NULL THEN RAISE EXCEPTION 'lease_required'; END IF;
  INSERT INTO public.chief_link_pilot_sessions(business_id,user_id)
    VALUES(p_business_id,p_user_id) ON CONFLICT DO NOTHING;
  UPDATE public.chief_link_pilot_sessions SET lease_id=p_lease_id,
    lease_until=clock_timestamp()+interval '120 seconds'
    WHERE business_id=p_business_id AND user_id=p_user_id
      AND (lease_id IS NULL OR lease_until < clock_timestamp()) RETURNING * INTO row_value;
  IF NOT FOUND THEN RETURN jsonb_build_object('acquired',false); END IF;
  RETURN jsonb_build_object('acquired',true,'encrypted_state',row_value.encrypted_state);
END $$;

CREATE OR REPLACE FUNCTION public.chief_link_pilot_save(
  p_business_id uuid, p_user_id uuid, p_lease_id uuid, p_encrypted_state text
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF p_encrypted_state IS NULL OR length(p_encrypted_state)>65536 THEN
    RAISE EXCEPTION 'invalid_state';
  END IF;
  UPDATE public.chief_link_pilot_sessions SET encrypted_state=p_encrypted_state,
    updated_at=clock_timestamp(),lease_until=clock_timestamp()+interval '120 seconds'
    WHERE business_id=p_business_id AND user_id=p_user_id
      AND lease_id=p_lease_id AND lease_until>clock_timestamp();
  RETURN FOUND;
END $$;

CREATE OR REPLACE FUNCTION public.chief_link_pilot_release(
  p_business_id uuid, p_user_id uuid, p_lease_id uuid
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  UPDATE public.chief_link_pilot_sessions SET lease_id=NULL,lease_until=NULL
    WHERE business_id=p_business_id AND user_id=p_user_id AND lease_id=p_lease_id;
  RETURN FOUND;
END $$;

REVOKE ALL ON FUNCTION public.chief_link_pilot_acquire(uuid,uuid,uuid) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.chief_link_pilot_save(uuid,uuid,uuid,text) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.chief_link_pilot_release(uuid,uuid,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.chief_link_pilot_acquire(uuid,uuid,uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.chief_link_pilot_save(uuid,uuid,uuid,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.chief_link_pilot_release(uuid,uuid,uuid) TO service_role;
NOTIFY pgrst, 'reload schema';
