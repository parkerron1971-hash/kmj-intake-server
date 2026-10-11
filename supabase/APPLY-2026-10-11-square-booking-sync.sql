-- Apply after Square connections and locations. Service-only trial calendar mirror.
BEGIN;
SET LOCAL lock_timeout='5s';
CREATE TABLE IF NOT EXISTS public.square_booking_sync (
 business_id uuid NOT NULL,
 environment text NOT NULL,
 owner_id uuid NOT NULL,
 connection_id uuid NOT NULL,
 selection_revision uuid NOT NULL,
 enabled boolean NOT NULL DEFAULT false,
 lease uuid,
 lease_until timestamptz,
 due_at timestamptz NOT NULL DEFAULT now(),
 last_synced_at timestamptz,
 last_error text CHECK(last_error IN ('authorization','setup','unavailable','capacity','changed')),
 window_start timestamptz,
 window_end timestamptz,
 appointments jsonb NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(appointments)='array' AND jsonb_array_length(appointments)<=5000),
 PRIMARY KEY(business_id,environment),
 FOREIGN KEY(business_id,environment) REFERENCES public.square_connections ON DELETE CASCADE
);
ALTER TABLE public.square_booking_sync ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.square_booking_sync FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.square_booking_sync TO service_role;
CREATE INDEX IF NOT EXISTS square_booking_sync_due ON public.square_booking_sync(due_at) WHERE enabled;

-- Changing locations or disconnecting invalidates consent, the worker lease and all copies atomically.
CREATE OR REPLACE FUNCTION public.square_reset_sync() RETURNS trigger
LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
BEGIN
 IF NEW.connection_id IS DISTINCT FROM OLD.connection_id OR NEW.selection_revision IS DISTINCT FROM OLD.selection_revision
    OR NEW.status IS DISTINCT FROM OLD.status THEN
   DELETE FROM square_booking_sync WHERE business_id=NEW.business_id AND environment=NEW.environment;
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS square_reset_sync ON public.square_connections;
CREATE TRIGGER square_reset_sync AFTER UPDATE ON public.square_connections FOR EACH ROW EXECUTE FUNCTION public.square_reset_sync();

CREATE OR REPLACE FUNCTION public.square_sync_set(p_business uuid,p_environment text,p_user uuid,p_connection uuid,p_selection uuid,p_enabled boolean)
RETURNS boolean LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE c square_connections;
BEGIN
 PERFORM 1 FROM businesses WHERE id=p_business AND owner_id=p_user FOR UPDATE;
 IF NOT FOUND THEN RETURN false; END IF;
 SELECT * INTO c FROM square_connections WHERE business_id=p_business AND environment=p_environment FOR UPDATE;
 IF NOT FOUND OR c.status<>'connected' OR c.connection_id<>p_connection OR c.selection_revision<>p_selection THEN RETURN false; END IF;
 IF NOT p_enabled THEN DELETE FROM square_booking_sync WHERE business_id=p_business AND environment=p_environment; RETURN true; END IF;
 IF cardinality(c.selected_location_ids)=0 THEN RETURN false; END IF;
 INSERT INTO square_booking_sync(business_id,environment,owner_id,connection_id,selection_revision,enabled)
 VALUES(p_business,p_environment,p_user,p_connection,p_selection,true)
 ON CONFLICT(business_id,environment) DO NOTHING;
 RETURN true;
END $$;

CREATE OR REPLACE FUNCTION public.square_sync_claim(p_business uuid,p_environment text,p_user uuid)
RETURNS SETOF square_booking_sync LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE c square_connections;
BEGIN
 PERFORM 1 FROM businesses WHERE id=p_business AND owner_id=p_user FOR UPDATE;
 IF NOT FOUND THEN RETURN; END IF;
 SELECT * INTO c FROM square_connections WHERE business_id=p_business AND environment=p_environment FOR UPDATE;
 IF NOT FOUND OR c.status<>'connected' THEN RETURN; END IF;
 RETURN QUERY UPDATE square_booking_sync s SET lease=gen_random_uuid(),lease_until=now()+interval '3 minutes'
 WHERE s.business_id=p_business AND s.environment=p_environment AND s.owner_id=p_user AND s.enabled
 AND s.connection_id=c.connection_id AND s.selection_revision=c.selection_revision
 AND s.due_at<=now() AND (s.lease_until IS NULL OR s.lease_until<now()) RETURNING s.*;
END $$;

CREATE OR REPLACE FUNCTION public.square_sync_finish(p_business uuid,p_environment text,p_user uuid,p_lease uuid,p_appointments jsonb,p_start timestamptz,p_end timestamptz,p_error text)
RETURNS boolean LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
DECLARE c square_connections; s square_booking_sync;
BEGIN
 PERFORM 1 FROM businesses WHERE id=p_business AND owner_id=p_user FOR UPDATE;
 IF NOT FOUND THEN RETURN false; END IF;
 SELECT * INTO c FROM square_connections WHERE business_id=p_business AND environment=p_environment FOR UPDATE;
 IF NOT FOUND OR c.status<>'connected' THEN RETURN false; END IF;
 SELECT * INTO s FROM square_booking_sync WHERE business_id=p_business AND environment=p_environment FOR UPDATE;
 IF NOT FOUND OR NOT s.enabled OR s.owner_id<>p_user OR s.connection_id<>c.connection_id OR s.selection_revision<>c.selection_revision
 OR p_lease IS NULL OR s.lease IS NULL OR s.lease_until IS NULL OR s.lease IS DISTINCT FROM p_lease OR s.lease_until<=now() THEN RETURN false; END IF;
 IF p_error IS NULL THEN
   IF p_start IS NULL OR p_end IS NULL OR p_end<=p_start OR p_end-p_start>interval '93 days'
      OR p_appointments IS NULL OR jsonb_typeof(p_appointments)<>'array' OR jsonb_array_length(p_appointments)>5000 THEN RETURN false; END IF;
   -- Even a stale upstream page may never overwrite a newer booking version.
   IF EXISTS(SELECT 1 FROM jsonb_array_elements(s.appointments) old JOIN jsonb_array_elements(p_appointments) fresh
     ON old->>'id'=fresh->>'id' WHERE (old->>'version')::bigint>(fresh->>'version')::bigint) THEN
     p_error:='changed';
   END IF;
 END IF;
 UPDATE square_booking_sync SET lease=NULL,lease_until=NULL,due_at=now()+interval '15 minutes',last_error=p_error,
 appointments=CASE WHEN p_error IS NULL THEN p_appointments ELSE appointments END,
 window_start=CASE WHEN p_error IS NULL THEN p_start ELSE window_start END,
 window_end=CASE WHEN p_error IS NULL THEN p_end ELSE window_end END,
 last_synced_at=CASE WHEN p_error IS NULL THEN now() ELSE last_synced_at END
 WHERE business_id=p_business AND environment=p_environment;
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION public.square_reset_sync(),public.square_sync_set(uuid,text,uuid,uuid,uuid,boolean),
 public.square_sync_claim(uuid,text,uuid),public.square_sync_finish(uuid,text,uuid,uuid,jsonb,timestamptz,timestamptz,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.square_reset_sync(),public.square_sync_set(uuid,text,uuid,uuid,uuid,boolean),
 public.square_sync_claim(uuid,text,uuid),public.square_sync_finish(uuid,text,uuid,uuid,jsonb,timestamptz,timestamptz,text) TO service_role;
-- A new owner must give fresh consent, even if the account later changes back.
CREATE OR REPLACE FUNCTION public.square_owner_reset_sync() RETURNS trigger
LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
BEGIN
 IF NEW.owner_id IS DISTINCT FROM OLD.owner_id THEN DELETE FROM square_booking_sync WHERE business_id=NEW.id; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS square_owner_reset_sync ON public.businesses;
CREATE TRIGGER square_owner_reset_sync AFTER UPDATE OF owner_id ON public.businesses FOR EACH ROW EXECUTE FUNCTION public.square_owner_reset_sync();
REVOKE ALL ON FUNCTION public.square_owner_reset_sync() FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.square_owner_reset_sync() TO service_role;
NOTIFY pgrst,'reload schema';
COMMIT;
