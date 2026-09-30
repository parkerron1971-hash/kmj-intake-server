-- Service-only, encrypted customer connections and purchase journal.
BEGIN;
CREATE TABLE IF NOT EXISTS public.agentcard_wallets (
 business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
 user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 wallet_binding text NOT NULL CHECK (length(wallet_binding)=64),
 encrypted_state text NOT NULL DEFAULT '',
 revision integer NOT NULL DEFAULT 0,
 lease uuid,
 lease_until timestamptz,
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(business_id,user_id,wallet_binding)
);
ALTER TABLE public.agentcard_wallets ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.agentcard_wallets FROM PUBLIC,anon,authenticated;
GRANT ALL ON public.agentcard_wallets TO service_role;

CREATE OR REPLACE FUNCTION public.agentcard_wallet_acquire(p_business_id uuid,p_user_id uuid,p_binding text,p_lease uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE r public.agentcard_wallets;
BEGIN
 INSERT INTO public.agentcard_wallets(business_id,user_id,wallet_binding)
 VALUES(p_business_id,p_user_id,p_binding) ON CONFLICT DO NOTHING;
 UPDATE public.agentcard_wallets SET lease=p_lease,lease_until=clock_timestamp()+interval '240 seconds'
 WHERE business_id=p_business_id AND user_id=p_user_id AND wallet_binding=p_binding
 AND (lease IS NULL OR lease_until<clock_timestamp()) RETURNING * INTO r;
 IF NOT FOUND THEN RETURN NULL; END IF;
 RETURN to_jsonb(r);
END $$;

CREATE OR REPLACE FUNCTION public.agentcard_wallet_save(p_business_id uuid,p_user_id uuid,p_binding text,p_lease uuid,p_revision integer,p_state text)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE v integer;
BEGIN
 UPDATE public.agentcard_wallets SET encrypted_state=p_state,revision=revision+1,updated_at=now()
 WHERE business_id=p_business_id AND user_id=p_user_id AND wallet_binding=p_binding
 AND lease=p_lease AND lease_until>clock_timestamp() AND revision=p_revision
 RETURNING revision INTO v;
 RETURN v;
END $$;

CREATE OR REPLACE FUNCTION public.agentcard_wallet_release(p_business_id uuid,p_user_id uuid,p_binding text,p_lease uuid)
RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path=public AS $$
 UPDATE public.agentcard_wallets SET lease=NULL,lease_until=NULL
 WHERE business_id=p_business_id AND user_id=p_user_id AND wallet_binding=p_binding AND lease=p_lease;
$$;

CREATE TABLE IF NOT EXISTS public.agentcard_events (
 id text PRIMARY KEY,
 event_type text NOT NULL,
 livemode boolean NOT NULL,
 encrypted_payload text NOT NULL,
 received_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.agentcard_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.agentcard_events FROM PUBLIC,anon,authenticated;
GRANT ALL ON public.agentcard_events TO service_role;
REVOKE ALL ON FUNCTION public.agentcard_wallet_acquire(uuid,uuid,text,uuid),public.agentcard_wallet_save(uuid,uuid,text,uuid,integer,text),public.agentcard_wallet_release(uuid,uuid,text,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.agentcard_wallet_acquire(uuid,uuid,text,uuid),public.agentcard_wallet_save(uuid,uuid,text,uuid,integer,text),public.agentcard_wallet_release(uuid,uuid,text,uuid) TO service_role;
COMMIT;
