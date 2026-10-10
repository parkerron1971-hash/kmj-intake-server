-- Square connection foundation. Apply manually before enabling SQUARE_ENABLED.
BEGIN;
SET LOCAL lock_timeout = '5s';
CREATE TABLE IF NOT EXISTS public.square_connections (
  business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  environment text NOT NULL CHECK (environment IN ('sandbox','production')),
  status text NOT NULL DEFAULT 'disconnected' CHECK (status IN ('disconnected','connected','revocation_pending')),
  merchant_id text,
  credentials text, -- Fernet ciphertext; access/refresh tokens never stored in plaintext
  expires_at timestamptz,
  connected_at timestamptz,
  revision uuid NOT NULL DEFAULT gen_random_uuid(),
  attempt_id uuid,
  user_id uuid,
  ticket_hash text,
  state_hash text,
  browser_hash text,
  attempt_expires_at timestamptz,
  callback_claimed boolean NOT NULL DEFAULT false,
  revoke_lease_until timestamptz,
  PRIMARY KEY (business_id, environment),
  UNIQUE (environment, merchant_id),
  UNIQUE (ticket_hash),
  UNIQUE (state_hash)
);
ALTER TABLE public.square_connections ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.square_connections FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.square_connections TO service_role;

-- All routines are service-only, SECURITY INVOKER, and use a fixed search path.
-- Owner checks are repeated inside write transactions to handle ownership changes.
CREATE OR REPLACE FUNCTION public.square_start(p_business uuid, p_environment text, p_user uuid, p_ticket text)
RETURNS boolean LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE c square_connections;
BEGIN
  PERFORM 1 FROM businesses WHERE id=p_business AND owner_id=p_user FOR UPDATE;
  IF NOT FOUND THEN RETURN false; END IF;
  INSERT INTO square_connections(business_id,environment) VALUES(p_business,p_environment) ON CONFLICT DO NOTHING;
  SELECT * INTO c FROM square_connections WHERE business_id=p_business AND environment=p_environment FOR UPDATE;
  IF c.status <> 'disconnected' THEN RETURN false; END IF;
  UPDATE square_connections SET attempt_id=gen_random_uuid(), user_id=p_user,
    ticket_hash=p_ticket, state_hash=NULL, browser_hash=NULL, callback_claimed=false,
    attempt_expires_at=now()+interval '10 minutes'
    WHERE business_id=p_business AND environment=p_environment;
  RETURN true;
END $$;

CREATE OR REPLACE FUNCTION public.square_begin(p_ticket text, p_state text, p_browser text, p_environment text)
RETURNS boolean LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
  UPDATE square_connections SET ticket_hash=NULL, state_hash=p_state, browser_hash=p_browser
    WHERE ticket_hash=p_ticket AND environment=p_environment AND status='disconnected' AND attempt_expires_at>now();
  RETURN FOUND;
END $$;

CREATE OR REPLACE FUNCTION public.square_claim(p_state text, p_browser text, p_environment text)
RETURNS TABLE(business_id uuid, user_id uuid, attempt_id uuid)
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
  RETURN QUERY UPDATE square_connections c SET callback_claimed=true
    WHERE c.state_hash=p_state AND c.browser_hash=p_browser AND c.environment=p_environment
      AND c.status='disconnected' AND NOT c.callback_claimed AND c.attempt_expires_at>now()
    RETURNING c.business_id,c.user_id,c.attempt_id;
END $$;

CREATE OR REPLACE FUNCTION public.square_finish(p_business uuid, p_environment text, p_user uuid,
  p_attempt uuid, p_merchant text, p_credentials text, p_expires timestamptz)
RETURNS boolean LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
  PERFORM 1 FROM businesses WHERE id=p_business AND owner_id=p_user FOR UPDATE;
  IF NOT FOUND THEN RETURN false; END IF;
  UPDATE square_connections SET status='connected', merchant_id=p_merchant, credentials=p_credentials,
    expires_at=p_expires, connected_at=now(), revision=gen_random_uuid(), attempt_id=NULL,
    user_id=NULL, ticket_hash=NULL, state_hash=NULL, browser_hash=NULL, attempt_expires_at=NULL, callback_claimed=false
    WHERE business_id=p_business AND environment=p_environment AND attempt_id=p_attempt
      AND user_id=p_user AND callback_claimed AND status='disconnected' AND attempt_expires_at>now();
  RETURN FOUND;
EXCEPTION WHEN unique_violation THEN RETURN false;
END $$;

CREATE OR REPLACE FUNCTION public.square_refresh(p_business uuid, p_environment text,
  p_revision uuid, p_credentials text, p_expires timestamptz)
RETURNS boolean LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
  UPDATE square_connections SET credentials=p_credentials, expires_at=p_expires, revision=gen_random_uuid()
    WHERE business_id=p_business AND environment=p_environment AND revision=p_revision AND status='connected';
  RETURN FOUND;
END $$;

-- Disable local access BEFORE contacting Square; keep the merchant reserved until
-- revocation succeeds. A timed lease prevents concurrent requests revoking a new grant.
CREATE OR REPLACE FUNCTION public.square_disconnect(p_business uuid, p_environment text, p_user uuid)
RETURNS TABLE(merchant_id text, revision uuid)
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
  PERFORM 1 FROM businesses WHERE id=p_business AND owner_id=p_user FOR UPDATE;
  IF NOT FOUND THEN RETURN; END IF;
  RETURN QUERY UPDATE square_connections c SET status=CASE WHEN c.merchant_id IS NULL THEN 'disconnected' ELSE 'revocation_pending' END,
    credentials=NULL, expires_at=NULL, attempt_id=NULL, user_id=NULL, ticket_hash=NULL, state_hash=NULL,
    browser_hash=NULL, attempt_expires_at=NULL, callback_claimed=false, revision=gen_random_uuid(),
    revoke_lease_until=now()+interval '2 minutes'
    WHERE c.business_id=p_business AND c.environment=p_environment
      AND (c.revoke_lease_until IS NULL OR c.revoke_lease_until<now())
    RETURNING c.merchant_id,c.revision;
END $$;

CREATE OR REPLACE FUNCTION public.square_finish_disconnect(p_business uuid, p_environment text, p_revision uuid)
RETURNS boolean LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
  UPDATE square_connections SET status='disconnected', merchant_id=NULL, connected_at=NULL, revoke_lease_until=NULL
    WHERE business_id=p_business AND environment=p_environment AND revision=p_revision;
  RETURN FOUND;
END $$;

REVOKE ALL ON FUNCTION public.square_start(uuid,text,uuid,text), public.square_begin(text,text,text,text),
  public.square_claim(text,text,text), public.square_finish(uuid,text,uuid,uuid,text,text,timestamptz),
  public.square_refresh(uuid,text,uuid,text,timestamptz), public.square_disconnect(uuid,text,uuid),
  public.square_finish_disconnect(uuid,text,uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.square_start(uuid,text,uuid,text), public.square_begin(text,text,text,text),
  public.square_claim(text,text,text), public.square_finish(uuid,text,uuid,uuid,text,text,timestamptz),
  public.square_refresh(uuid,text,uuid,text,timestamptz), public.square_disconnect(uuid,text,uuid),
  public.square_finish_disconnect(uuid,text,uuid) TO service_role;
NOTIFY pgrst, 'reload schema';
COMMIT;
