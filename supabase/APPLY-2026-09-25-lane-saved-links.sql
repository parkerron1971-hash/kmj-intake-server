-- Owner-saved merchant links for the Lane pilot: the page, the merchant's name and the
-- intended account, application-encrypted (lane_links.py). A starting point, never trust:
-- every purchase re-reads the page and still needs Wallet review and Lane approval.
-- Service-role only. Safe to re-run.
CREATE TABLE IF NOT EXISTS public.lane_saved_links (
  id uuid PRIMARY KEY,
  business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  link_hash text NOT NULL CHECK (link_hash ~ '^[a-f0-9]{64}$'),
  encrypted_state text NOT NULL CHECK (length(encrypted_state) <= 16384),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (business_id, user_id, link_hash)
);
ALTER TABLE public.lane_saved_links ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.lane_saved_links FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.lane_saved_links TO service_role;

-- Save or refresh one link. NULL when the owner already has 20 (lane_links.LIMIT).
CREATE OR REPLACE FUNCTION public.lane_link_save(
 p_business_id uuid,p_user_id uuid,p_id uuid,p_link_hash text,p_encrypted_state text
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE r_id uuid;
BEGIN
 IF p_encrypted_state IS NULL OR length(p_encrypted_state)>16384
 OR p_link_hash IS NULL OR p_link_hash !~ '^[a-f0-9]{64}$' THEN RAISE EXCEPTION 'invalid_state'; END IF;
 -- One owner's saves run one at a time, so two cannot race past the cap.
 PERFORM pg_advisory_xact_lock(hashtext('lane_saved_links:'||p_business_id::text||':'||p_user_id::text));
 UPDATE public.lane_saved_links SET encrypted_state=p_encrypted_state,updated_at=clock_timestamp()
  WHERE business_id=p_business_id AND user_id=p_user_id AND link_hash=p_link_hash RETURNING id INTO r_id;
 IF FOUND THEN RETURN r_id; END IF;
 IF (SELECT count(*) FROM public.lane_saved_links
     WHERE business_id=p_business_id AND user_id=p_user_id)>=20 THEN RETURN NULL; END IF;
 INSERT INTO public.lane_saved_links(id,business_id,user_id,link_hash,encrypted_state)
  VALUES(p_id,p_business_id,p_user_id,p_link_hash,p_encrypted_state) RETURNING id INTO r_id;
 RETURN r_id;
END $$;

CREATE OR REPLACE FUNCTION public.lane_link_list(p_business_id uuid,p_user_id uuid)
RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=public AS $$
 SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY r.updated_at DESC), '[]'::jsonb) FROM (
 SELECT id,link_hash,encrypted_state,updated_at FROM public.lane_saved_links
 WHERE business_id=p_business_id AND user_id=p_user_id ORDER BY updated_at DESC LIMIT 20
 ) r;
$$;

CREATE OR REPLACE FUNCTION public.lane_link_delete(p_business_id uuid,p_user_id uuid,p_id uuid)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
BEGIN
 DELETE FROM public.lane_saved_links WHERE id=p_id AND business_id=p_business_id AND user_id=p_user_id;
 RETURN FOUND;
END $$;

REVOKE ALL ON FUNCTION public.lane_link_save(uuid,uuid,uuid,text,text) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.lane_link_list(uuid,uuid) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.lane_link_delete(uuid,uuid,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.lane_link_save(uuid,uuid,uuid,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.lane_link_list(uuid,uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.lane_link_delete(uuid,uuid,uuid) TO service_role;
NOTIFY pgrst,'reload schema';
