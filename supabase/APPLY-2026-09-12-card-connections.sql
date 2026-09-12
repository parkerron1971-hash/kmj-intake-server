BEGIN;
CREATE TABLE public.business_card_connections (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
 mode text NOT NULL CHECK(mode IN ('test','live','sandbox')),
 provider text NOT NULL DEFAULT 'stripe' CHECK(provider='stripe'),
 account_id text CHECK(account_id ~ '^acct_[A-Za-z0-9]+$'),
 status text NOT NULL DEFAULT 'disconnected' CHECK(status IN ('disconnected','connected','refreshing','reconnect_required')),
 tokens_ciphertext text,
 expires_at timestamptz,
 selected_card jsonb,
 version bigint NOT NULL DEFAULT 0,
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(business_id,mode), UNIQUE(account_id,mode),
 CHECK(tokens_ciphertext IS NULL OR length(tokens_ciphertext) BETWEEN 1 AND 32768)
);
CREATE TABLE public.card_connection_oauth_states (
 state_hash text PRIMARY KEY CHECK(length(state_hash)=64),
 verifier_hash text NOT NULL CHECK(length(verifier_hash)=64),
 user_id uuid NOT NULL,
 connection_id uuid NOT NULL REFERENCES public.business_card_connections(id) ON DELETE CASCADE,
 version bigint NOT NULL,
 status text NOT NULL DEFAULT 'issued' CHECK(status IN ('issued','exchanging','authorized')),
 account_id text,
 tokens_ciphertext text,
 expires_at timestamptz NOT NULL DEFAULT now()+interval '10 minutes'
);
ALTER TABLE public.business_card_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.card_connection_oauth_states ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.business_card_connections,public.card_connection_oauth_states FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.business_card_connections,public.card_connection_oauth_states TO service_role;

-- Lock the connection so a disconnect cannot race a new pending authorization.
CREATE FUNCTION public.card_connection_begin(p_business uuid,p_mode text,p_user uuid,p_state text,p_verifier text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE c public.business_card_connections;
BEGIN
 INSERT INTO business_card_connections(business_id,mode) VALUES(p_business,p_mode) ON CONFLICT(business_id,mode) DO NOTHING;
 SELECT * INTO c FROM business_card_connections WHERE business_id=p_business AND mode=p_mode FOR UPDATE;
 DELETE FROM card_connection_oauth_states WHERE connection_id=c.id OR expires_at<now();
 INSERT INTO card_connection_oauth_states(state_hash,verifier_hash,user_id,connection_id,version)
 VALUES(p_state,p_verifier,p_user,c.id,c.version);
 RETURN jsonb_build_object('id',c.id);
END $$;

-- Claims, selection, refresh completion and callback completion all compare versions.
CREATE FUNCTION public.card_connection_update(p_id uuid,p_version bigint,p_status text,p_account text,p_tokens text,p_expires timestamptz,p_card jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE c public.business_card_connections;
BEGIN
 UPDATE business_card_connections SET status=p_status,account_id=p_account,tokens_ciphertext=p_tokens,
 expires_at=p_expires,selected_card=p_card,version=version+1,updated_at=now()
 WHERE id=p_id AND version=p_version RETURNING * INTO c;
 IF NOT FOUND THEN RETURN NULL; END IF;
 RETURN to_jsonb(c);
END $$;

CREATE FUNCTION public.card_connection_disconnect(p_business uuid,p_mode text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE cid uuid;
BEGIN
 UPDATE business_card_connections SET status='disconnected',tokens_ciphertext=NULL,
 expires_at=NULL,selected_card=NULL,version=version+1,updated_at=now()
 WHERE business_id=p_business AND mode=p_mode RETURNING id INTO cid;
 DELETE FROM card_connection_oauth_states WHERE connection_id=cid;
END $$;
REVOKE ALL ON FUNCTION public.card_connection_begin(uuid,text,uuid,text,text),
 public.card_connection_update(uuid,bigint,text,text,text,timestamptz,jsonb),
 public.card_connection_disconnect(uuid,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.card_connection_begin(uuid,text,uuid,text,text),
 public.card_connection_update(uuid,bigint,text,text,text,timestamptz,jsonb),
 public.card_connection_disconnect(uuid,text) TO service_role;
COMMENT ON TABLE public.business_card_connections IS 'Customer-owned purchasing account connection. Read-only Stripe App access; no PAN/CVC. No browser/model/direct user access to tokens.';
-- Uninstall function: signed provider account, never a caller's business id.
CREATE OR REPLACE FUNCTION public.card_connection_uninstall(p_account text,p_mode text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
BEGIN
 WITH revoked AS (
   UPDATE business_card_connections SET status='disconnected',tokens_ciphertext=NULL,
     expires_at=NULL,selected_card=NULL,version=version+1,updated_at=now()
   WHERE mode=p_mode AND (account_id=p_account OR id IN (
     SELECT connection_id FROM card_connection_oauth_states WHERE account_id=p_account AND status='authorized'
   )) RETURNING id
 ) DELETE FROM card_connection_oauth_states WHERE connection_id IN (SELECT id FROM revoked);
END $$;
REVOKE ALL ON FUNCTION public.card_connection_uninstall(text,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.card_connection_uninstall(text,text) TO service_role;
COMMIT;
