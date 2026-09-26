-- Campaign operations for the platform owner. No tenant/browser table access.
-- Apply after the 2026-09-15 platform-marketing migration.
BEGIN;
CREATE TABLE IF NOT EXISTS public.platform_marketing_campaigns (
  id uuid PRIMARY KEY,
  tracking_key text NOT NULL UNIQUE,
  name text NOT NULL CHECK(length(name) BETWEEN 1 AND 100),
  brief jsonb NOT NULL,
  brief_hash text NOT NULL,
  stage text NOT NULL DEFAULT 'planning' CHECK(stage IN ('planning','producing','measuring','completed','archived')),
  plan jsonb,
  plan_brief_hash text,
  learning text NOT NULL DEFAULT '',
  revision integer NOT NULL DEFAULT 1 CHECK(revision > 0),
  updated_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.platform_marketing_campaign_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  campaign_id uuid NOT NULL REFERENCES public.platform_marketing_campaigns(id),
  snapshot jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.platform_marketing_plan_runs (
  id uuid PRIMARY KEY,
  campaign_id uuid NOT NULL REFERENCES public.platform_marketing_campaigns(id),
  revision integer NOT NULL,
  status text NOT NULL DEFAULT 'running' CHECK(status IN ('running','succeeded','failed')),
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz
);
CREATE INDEX IF NOT EXISTS marketing_plan_runs_time ON public.platform_marketing_plan_runs(created_at);
ALTER TABLE public.platform_marketing_posts ADD COLUMN IF NOT EXISTS campaign_id uuid REFERENCES public.platform_marketing_campaigns(id);
CREATE INDEX IF NOT EXISTS marketing_posts_campaign ON public.platform_marketing_posts(campaign_id,run_at);

CREATE TABLE IF NOT EXISTS public.platform_marketing_metrics (
  post_id uuid PRIMARY KEY REFERENCES public.platform_marketing_posts(id),
  provider_id text NOT NULL,
  metrics jsonb NOT NULL DEFAULT '[]',
  source_updated_at timestamptz,
  checked_at timestamptz NOT NULL DEFAULT now(),
  error text
);
CREATE TABLE IF NOT EXISTS public.platform_marketing_metric_sync (
  id boolean PRIMARY KEY DEFAULT true CHECK(id),
  attempted_at timestamptz,
  finished_at timestamptz,
  error text
);
INSERT INTO public.platform_marketing_metric_sync(id) VALUES(true) ON CONFLICT DO NOTHING;

ALTER TABLE public.platform_marketing_campaigns ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.platform_marketing_campaign_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.platform_marketing_plan_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.platform_marketing_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.platform_marketing_metric_sync ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.platform_marketing_campaigns,public.platform_marketing_campaign_events,
 public.platform_marketing_plan_runs,public.platform_marketing_metrics,public.platform_marketing_metric_sync FROM PUBLIC,anon,authenticated;
GRANT ALL ON public.platform_marketing_campaigns,public.platform_marketing_campaign_events,
 public.platform_marketing_plan_runs,public.platform_marketing_metrics,public.platform_marketing_metric_sync TO service_role;
GRANT USAGE,SELECT ON SEQUENCE public.platform_marketing_campaign_events_id_seq TO service_role;

CREATE OR REPLACE FUNCTION public.platform_marketing_campaign_record() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
  INSERT INTO public.platform_marketing_campaign_events(campaign_id,snapshot) VALUES(NEW.id,to_jsonb(NEW));
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS campaign_touch ON public.platform_marketing_campaigns;
CREATE TRIGGER campaign_touch BEFORE UPDATE ON public.platform_marketing_campaigns
 FOR EACH ROW EXECUTE FUNCTION public.platform_marketing_audit();
DROP TRIGGER IF EXISTS campaign_audit ON public.platform_marketing_campaigns;
CREATE TRIGGER campaign_audit AFTER INSERT OR UPDATE ON public.platform_marketing_campaigns
 FOR EACH ROW EXECUTE FUNCTION public.platform_marketing_campaign_record();

-- Serialize paid plan requests, including requests on different API replicas.
-- An interrupted call is never silently reissued with the same request ID.
CREATE OR REPLACE FUNCTION public.platform_marketing_claim_plan(request_id uuid, campaign uuid, expected_revision integer)
RETURNS jsonb LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE old public.platform_marketing_plan_runs; current_campaign public.platform_marketing_campaigns;
BEGIN
  PERFORM pg_advisory_xact_lock(9262026,1);
  SELECT * INTO old FROM public.platform_marketing_plan_runs WHERE id=request_id;
  IF FOUND THEN
    IF old.campaign_id <> campaign OR old.revision <> expected_revision THEN
      RAISE EXCEPTION 'Request belongs to another campaign revision';
    END IF;
    RETURN jsonb_build_object('claimed',false,'status',old.status);
  END IF;
  SELECT * INTO current_campaign FROM public.platform_marketing_campaigns WHERE id=campaign FOR UPDATE;
  IF NOT FOUND OR current_campaign.revision <> expected_revision OR current_campaign.stage='archived' THEN
    RAISE EXCEPTION 'Campaign changed; refresh before planning';
  END IF;
  IF EXISTS(SELECT 1 FROM public.platform_marketing_plan_runs WHERE campaign_id=campaign AND status='running' AND created_at>now()-interval '10 minutes') THEN
    RAISE EXCEPTION 'A plan is already being prepared';
  END IF;
  IF (SELECT count(*) FROM public.platform_marketing_plan_runs WHERE created_at>now()-interval '1 hour') >= 6 THEN
    RAISE EXCEPTION 'Six plan requests per hour; try later';
  END IF;
  UPDATE public.platform_marketing_plan_runs SET status='failed',error='Planning was interrupted; explicitly request a new plan.',finished_at=now()
    WHERE status='running' AND created_at<=now()-interval '10 minutes';
  INSERT INTO public.platform_marketing_plan_runs(id,campaign_id,revision) VALUES(request_id,campaign,expected_revision);
  RETURN jsonb_build_object('claimed',true,'status','running');
END $$;

-- One bounded provider read batch per 15 minutes across all callers/workers.
CREATE OR REPLACE FUNCTION public.platform_marketing_claim_metrics()
RETURNS jsonb LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE last_attempt timestamptz; items jsonb;
BEGIN
  SELECT attempted_at INTO last_attempt FROM public.platform_marketing_metric_sync WHERE id=true FOR UPDATE;
  IF last_attempt>now()-interval '15 minutes' THEN
    RETURN jsonb_build_object('claimed',false,'posts','[]'::jsonb);
  END IF;
  SELECT coalesce(jsonb_agg(to_jsonb(q)),'[]'::jsonb) INTO items FROM (
    SELECT p.id,p.provider_id,p.payload FROM public.platform_marketing_posts p
    LEFT JOIN public.platform_marketing_metrics m ON m.post_id=p.id
    WHERE p.status='published' AND p.provider_id IS NOT NULL AND p.run_at>now()-interval '90 days'
      AND (m.checked_at IS NULL OR m.checked_at<now()-interval '24 hours')
    ORDER BY m.checked_at ASC NULLS FIRST,p.run_at DESC LIMIT 25
  ) q;
  UPDATE public.platform_marketing_metric_sync SET attempted_at=now(),error=NULL WHERE id=true;
  RETURN jsonb_build_object('claimed',true,'posts',items);
END $$;

CREATE OR REPLACE FUNCTION public.platform_marketing_store_metrics(items jsonb)
RETURNS integer LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE item jsonb; n integer:=0;
BEGIN
  IF jsonb_array_length(items)>25 THEN RAISE EXCEPTION 'Batch too large'; END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(items) LOOP
    IF NOT EXISTS(SELECT 1 FROM public.platform_marketing_posts WHERE id=(item->>'post_id')::uuid AND provider_id=item->>'provider_id') THEN
      RAISE EXCEPTION 'Provider identity changed';
    END IF;
    INSERT INTO public.platform_marketing_metrics(post_id,provider_id,metrics,source_updated_at,error)
    VALUES((item->>'post_id')::uuid,item->>'provider_id',coalesce(item->'metrics','[]'::jsonb),(item->>'source_updated_at')::timestamptz,item->>'error')
    ON CONFLICT(post_id) DO UPDATE SET
      metrics=CASE WHEN EXCLUDED.error IS NULL THEN EXCLUDED.metrics ELSE platform_marketing_metrics.metrics END,
      source_updated_at=CASE WHEN EXCLUDED.error IS NULL THEN EXCLUDED.source_updated_at ELSE platform_marketing_metrics.source_updated_at END,
      checked_at=now(),error=EXCLUDED.error;
    n:=n+1;
  END LOOP;
  RETURN n;
END $$;
REVOKE ALL ON FUNCTION public.platform_marketing_campaign_record(),public.platform_marketing_claim_plan(uuid,uuid,integer),
 public.platform_marketing_claim_metrics(),public.platform_marketing_store_metrics(jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.platform_marketing_claim_plan(uuid,uuid,integer),public.platform_marketing_claim_metrics(),
 public.platform_marketing_store_metrics(jsonb) TO service_role;
COMMIT;
