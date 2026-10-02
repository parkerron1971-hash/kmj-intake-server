-- Service-only purchase metadata; request/provider details are application-encrypted.
CREATE TABLE IF NOT EXISTS public.lane_purchases (
  id uuid PRIMARY KEY,
  business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  request_hash text NOT NULL CHECK (request_hash ~ '^[a-f0-9]{64}$'),
  encrypted_state text NOT NULL,
  phase text NOT NULL DEFAULT 'new',
  intent_id text UNIQUE,
  revision integer NOT NULL DEFAULT 0,
  checkout_claimed boolean NOT NULL DEFAULT false,
  lease_id uuid,
  lease_until timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS lane_one_open_purchase
  ON public.lane_purchases(business_id,user_id)
  WHERE phase NOT IN ('placed','rejected','closed');
ALTER TABLE public.lane_purchases ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.lane_purchases FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.lane_purchases TO service_role;

CREATE OR REPLACE FUNCTION public.lane_purchase_create(
 p_business_id uuid,p_user_id uuid,p_id uuid,p_encrypted_state text,p_request_hash text
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE r public.lane_purchases;
BEGIN
 IF p_encrypted_state IS NULL OR length(p_encrypted_state)>131072 THEN RAISE EXCEPTION 'invalid_state'; END IF;
 INSERT INTO public.lane_purchases(id,business_id,user_id,encrypted_state,request_hash)
 VALUES(p_id,p_business_id,p_user_id,p_encrypted_state,p_request_hash) ON CONFLICT DO NOTHING;
 SELECT * INTO r FROM public.lane_purchases WHERE id=p_id AND business_id=p_business_id AND user_id=p_user_id;
 RETURN FOUND AND r.request_hash=p_request_hash;
END $$;

CREATE OR REPLACE FUNCTION public.lane_purchase_list(p_business_id uuid,p_user_id uuid)
RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=public AS $$
 SELECT coalesce(jsonb_agg(to_jsonb(r)), '[]'::jsonb) FROM (
 SELECT id,encrypted_state,revision,checkout_claimed FROM public.lane_purchases
 WHERE business_id=p_business_id AND user_id=p_user_id ORDER BY created_at DESC LIMIT 20
 ) r;
$$;

CREATE OR REPLACE FUNCTION public.lane_purchase_acquire(p_business_id uuid,p_user_id uuid,p_id uuid,p_lease uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE r public.lane_purchases;
BEGIN
 IF p_lease IS NULL THEN RAISE EXCEPTION 'lease_required'; END IF;
 UPDATE public.lane_purchases SET lease_id=p_lease,lease_until=clock_timestamp()+interval '120 seconds'
 WHERE id=p_id AND business_id=p_business_id AND user_id=p_user_id
 AND (lease_id IS NULL OR lease_until<clock_timestamp()) RETURNING * INTO r;
 IF NOT FOUND THEN RETURN NULL; END IF;
 RETURN to_jsonb(r);
END $$;

CREATE OR REPLACE FUNCTION public.lane_purchase_save(
 p_business_id uuid,p_user_id uuid,p_id uuid,p_lease uuid,p_revision integer,
 p_phase text,p_intent_id text,p_encrypted_state text,p_claim boolean DEFAULT false
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE r public.lane_purchases;
BEGIN
 IF p_encrypted_state IS NULL OR length(p_encrypted_state)>131072
 OR p_phase NOT IN ('new','submitting','needs_info','review','approved','resolving',
 'products_needed','checkout_unknown','running','needs_human','placed','rejected','closed','attention')
 THEN RAISE EXCEPTION 'invalid_state'; END IF;
 UPDATE public.lane_purchases SET encrypted_state=p_encrypted_state,phase=p_phase,
 intent_id=coalesce(intent_id,p_intent_id),revision=revision+1,
 checkout_claimed=checkout_claimed OR p_claim,updated_at=clock_timestamp(),
 lease_until=clock_timestamp()+interval '120 seconds'
 WHERE id=p_id AND business_id=p_business_id AND user_id=p_user_id
 AND lease_id=p_lease AND lease_until>clock_timestamp() AND revision=p_revision
 AND (intent_id IS NULL OR intent_id IS NOT DISTINCT FROM p_intent_id)
 AND (NOT p_claim OR (NOT checkout_claimed AND p_phase='checkout_unknown' AND p_intent_id IS NOT NULL))
 RETURNING * INTO r;
 IF NOT FOUND THEN RETURN NULL; END IF;
 RETURN jsonb_build_object('revision',r.revision,'checkout_claimed',r.checkout_claimed);
END $$;

CREATE OR REPLACE FUNCTION public.lane_purchase_release(p_business_id uuid,p_user_id uuid,p_id uuid,p_lease uuid)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
BEGIN
 UPDATE public.lane_purchases SET lease_id=NULL,lease_until=NULL
 WHERE id=p_id AND business_id=p_business_id AND user_id=p_user_id AND lease_id=p_lease;
 RETURN FOUND;
END $$;

REVOKE ALL ON FUNCTION public.lane_purchase_create(uuid,uuid,uuid,text,text) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.lane_purchase_list(uuid,uuid) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.lane_purchase_acquire(uuid,uuid,uuid,uuid) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.lane_purchase_save(uuid,uuid,uuid,uuid,integer,text,text,text,boolean) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.lane_purchase_release(uuid,uuid,uuid,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.lane_purchase_create(uuid,uuid,uuid,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.lane_purchase_list(uuid,uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.lane_purchase_acquire(uuid,uuid,uuid,uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.lane_purchase_save(uuid,uuid,uuid,uuid,integer,text,text,text,boolean) TO service_role;
GRANT EXECUTE ON FUNCTION public.lane_purchase_release(uuid,uuid,uuid,uuid) TO service_role;
NOTIFY pgrst,'reload schema';
