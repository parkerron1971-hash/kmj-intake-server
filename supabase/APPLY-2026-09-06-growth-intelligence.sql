-- Additive. Apply before enabling Growth Intelligence. Service-only tables:
-- the API checks verified owner/team role; Chief uses its authorized dispatcher.
BEGIN;
CREATE TABLE IF NOT EXISTS public.growth_records (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('preferences','actions','costs','attributions')),
  data jsonb NOT NULL DEFAULT '{}',
  revision integer NOT NULL DEFAULT 1,
  last_request_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS growth_records_business ON public.growth_records(business_id,kind);
CREATE UNIQUE INDEX IF NOT EXISTS growth_preferences_once ON public.growth_records(business_id) WHERE kind='preferences';
CREATE UNIQUE INDEX IF NOT EXISTS growth_invoice_credit_once ON public.growth_records(business_id,(data->>'invoice_id'))
  WHERE kind='attributions' AND coalesce((data->>'archived')::boolean,false)=false;
ALTER TABLE public.growth_records ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.growth_records FROM anon, authenticated;
GRANT ALL ON public.growth_records TO service_role;

CREATE TABLE IF NOT EXISTS public.growth_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  contact_id uuid REFERENCES public.contacts(id) ON DELETE SET NULL,
  kind text NOT NULL,
  occurred_at timestamptz NOT NULL,
  data jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS growth_events_business_time ON public.growth_events(business_id,occurred_at);
CREATE UNIQUE INDEX IF NOT EXISTS growth_interaction_once ON public.growth_events(business_id,contact_id,occurred_at) WHERE kind='interaction';
ALTER TABLE public.growth_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.growth_events FROM anon, authenticated;
GRANT ALL ON public.growth_events TO service_role;

-- Capture future history across every contact writer (UI, Chief, automations).
-- Deliberately do not fabricate historical touches from the latest-touch field.
CREATE OR REPLACE FUNCTION public.capture_growth_contact_event() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
  IF NEW.last_interaction IS NOT NULL AND (TG_OP='INSERT' OR NEW.last_interaction IS DISTINCT FROM OLD.last_interaction) THEN
    INSERT INTO public.growth_events(business_id,contact_id,kind,occurred_at)
      VALUES(NEW.business_id,NEW.id,'interaction',NEW.last_interaction) ON CONFLICT DO NOTHING;
  END IF;
  IF TG_OP='UPDATE' AND NEW.status IS DISTINCT FROM OLD.status THEN
    INSERT INTO public.growth_events(business_id,contact_id,kind,occurred_at,data)
      VALUES(NEW.business_id,NEW.id,'status',now(),jsonb_build_object('from',OLD.status,'to',NEW.status));
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.capture_growth_contact_event() FROM PUBLIC;
DROP TRIGGER IF EXISTS capture_growth_contact ON public.contacts;
CREATE TRIGGER capture_growth_contact AFTER INSERT OR UPDATE OF last_interaction,status ON public.contacts
FOR EACH ROW EXECUTE FUNCTION public.capture_growth_contact_event();

-- Accurate history coverage marker, stable on migration replay.
INSERT INTO public.growth_records(business_id,kind,data)
 SELECT id,'preferences',jsonb_build_object('timezone','UTC','currency','USD','weekly_hours',null,'history_since',now())
 FROM public.businesses ON CONFLICT DO NOTHING;

-- Businesses created after rollout need the same history coverage marker.
CREATE OR REPLACE FUNCTION public.initialize_growth_preferences() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
  INSERT INTO public.growth_records(business_id,kind,data)
    VALUES(NEW.id,'preferences',jsonb_build_object('timezone','UTC','currency','USD','weekly_hours',null,'history_since',now()))
    ON CONFLICT DO NOTHING;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.initialize_growth_preferences() FROM PUBLIC;
DROP TRIGGER IF EXISTS initialize_growth_preferences ON public.businesses;
CREATE TRIGGER initialize_growth_preferences AFTER INSERT ON public.businesses
FOR EACH ROW EXECUTE FUNCTION public.initialize_growth_preferences();
COMMIT;
