-- Apply after APPLY-2026-10-08-square-connections.sql. No bookings are imported.
BEGIN;
SET LOCAL lock_timeout='5s';
ALTER TABLE public.square_connections
  ADD COLUMN IF NOT EXISTS connection_id uuid NOT NULL DEFAULT gen_random_uuid(),
  ADD COLUMN IF NOT EXISTS selected_location_ids text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS selection_revision uuid NOT NULL DEFAULT gen_random_uuid();

CREATE OR REPLACE FUNCTION public.square_finish(p_business uuid, p_environment text, p_user uuid,
  p_attempt uuid, p_merchant text, p_credentials text, p_expires timestamptz)
RETURNS boolean LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
  PERFORM 1 FROM businesses WHERE id=p_business AND owner_id=p_user FOR UPDATE;
  IF NOT FOUND THEN RETURN false; END IF;
  UPDATE square_connections SET connection_id=gen_random_uuid(), selected_location_ids='{}', selection_revision=gen_random_uuid(), status='connected', merchant_id=p_merchant, credentials=p_credentials,
    expires_at=p_expires, connected_at=now(), revision=gen_random_uuid(), attempt_id=NULL,
    user_id=NULL, ticket_hash=NULL, state_hash=NULL, browser_hash=NULL, attempt_expires_at=NULL, callback_claimed=false
    WHERE business_id=p_business AND environment=p_environment AND attempt_id=p_attempt
      AND user_id=p_user AND callback_claimed AND status='disconnected' AND attempt_expires_at>now();
  RETURN FOUND;
EXCEPTION WHEN unique_violation THEN RETURN false;
END $$;


CREATE OR REPLACE FUNCTION public.square_disconnect(p_business uuid, p_environment text, p_user uuid)
RETURNS TABLE(merchant_id text, revision uuid)
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
  PERFORM 1 FROM businesses WHERE id=p_business AND owner_id=p_user FOR UPDATE;
  IF NOT FOUND THEN RETURN; END IF;
  RETURN QUERY UPDATE square_connections c SET connection_id=gen_random_uuid(), selected_location_ids='{}', selection_revision=gen_random_uuid(), status=CASE WHEN c.merchant_id IS NULL THEN 'disconnected' ELSE 'revocation_pending' END,
    credentials=NULL, expires_at=NULL, attempt_id=NULL, user_id=NULL, ticket_hash=NULL, state_hash=NULL,
    browser_hash=NULL, attempt_expires_at=NULL, callback_claimed=false, revision=gen_random_uuid(),
    revoke_lease_until=now()+interval '2 minutes'
    WHERE c.business_id=p_business AND c.environment=p_environment
      AND (c.revoke_lease_until IS NULL OR c.revoke_lease_until<now())
    RETURNING c.merchant_id,c.revision;
END $$;


CREATE OR REPLACE FUNCTION public.square_save_locations(p_business uuid, p_environment text, p_user uuid,
  p_connection uuid, p_selection_revision uuid, p_locations text[])
RETURNS uuid LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE result uuid;
BEGIN
  PERFORM 1 FROM businesses WHERE id=p_business AND owner_id=p_user FOR UPDATE;
  IF NOT FOUND THEN RETURN NULL; END IF;
  IF p_locations IS NULL OR cardinality(p_locations)>20 OR array_position(p_locations,NULL) IS NOT NULL
    OR EXISTS(SELECT 1 FROM unnest(p_locations) AS x WHERE x !~ '^[A-Za-z0-9_-]{1,192}$')
    OR cardinality(p_locations)<>(SELECT count(DISTINCT x) FROM unnest(p_locations) AS x)
    THEN RETURN NULL; END IF;
  UPDATE square_connections SET selected_location_ids=p_locations, selection_revision=gen_random_uuid()
    WHERE business_id=p_business AND environment=p_environment AND status='connected'
      AND connection_id=p_connection AND selection_revision=p_selection_revision
    RETURNING selection_revision INTO result;
  RETURN result;
END $$;
REVOKE ALL ON FUNCTION public.square_save_locations(uuid,text,uuid,uuid,uuid,text[]) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.square_save_locations(uuid,text,uuid,uuid,uuid,text[]) TO service_role;
NOTIFY pgrst,'reload schema';
COMMIT;
