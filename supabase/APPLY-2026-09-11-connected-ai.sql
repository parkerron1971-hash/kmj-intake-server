-- Connected AI pilot. Apply manually after the chief_jobs and agent_queue schemas.
-- No provider credential enters these tables. Device and one-use pairing secrets
-- are SHA-256 hashes. Only the backend service role may invoke transitions.
BEGIN;

CREATE TABLE IF NOT EXISTS public.connected_ai_pairings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  owner_id uuid NOT NULL,
  provider text NOT NULL CHECK (provider IN ('chatgpt','claude')),
  secret_hash text NOT NULL UNIQUE,
  expires_at timestamptz NOT NULL DEFAULT now() + interval '10 minutes',
  consumed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.connected_ai_devices (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id),
  owner_id uuid NOT NULL,
  provider text NOT NULL CHECK (provider IN ('chatgpt','claude')),
  label text NOT NULL CHECK (length(label) BETWEEN 1 AND 80),
  token_hash text NOT NULL UNIQUE,
  state text NOT NULL DEFAULT 'login_required'
    CHECK (state IN ('signed_in','login_required','usage_limits','provider_not_installed','provider_unavailable')),
  last_seen_at timestamptz,
  expires_at timestamptz NOT NULL DEFAULT now() + interval '90 days',
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.connected_ai_pairings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.connected_ai_devices ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.connected_ai_pairings, public.connected_ai_devices FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.connected_ai_pairings, public.connected_ai_devices TO service_role;
CREATE INDEX IF NOT EXISTS connected_ai_devices_business ON public.connected_ai_devices(business_id);
CREATE INDEX IF NOT EXISTS connected_ai_pairings_business ON public.connected_ai_pairings(business_id);
ALTER TABLE public.agent_queue ADD COLUMN IF NOT EXISTS connected_ai_job_id uuid REFERENCES public.chief_jobs(id);
CREATE UNIQUE INDEX IF NOT EXISTS connected_ai_queue_job ON public.agent_queue(connected_ai_job_id)
  WHERE connected_ai_job_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS connected_ai_job_request ON public.chief_jobs(business_id, (params->>'request_id'))
  WHERE kind = 'connected_ai_follow_up';

-- Snapshot only the facts this pilot needs. Resolve an existing contact, never
-- accept a model-supplied recipient. Compare this again at completion AND send.
CREATE OR REPLACE FUNCTION public.connected_ai_invoice_snapshot(p_business uuid, p_invoice uuid)
RETURNS jsonb LANGUAGE plpgsql SET search_path = public AS $$
DECLARE i jsonb; c jsonb; matches integer; bname text;
BEGIN
  SELECT to_jsonb(v) INTO i FROM public.invoices v WHERE id=p_invoice AND business_id=p_business;
  IF i IS NULL OR i->>'status' NOT IN ('open','sent','overdue') OR i->>'archived_at' IS NOT NULL
    OR i->>'paid_at' IS NOT NULL OR coalesce((i->>'amount_due_cents')::bigint,0)<=0
    OR i->>'due_date' IS NULL OR (i->>'due_date')::date >= current_date THEN
    RAISE EXCEPTION 'invoice_not_overdue';
  END IF;
  IF nullif(i->>'contact_id','') IS NOT NULL THEN
    SELECT to_jsonb(v) INTO c FROM public.contacts v
      WHERE id=(i->>'contact_id')::uuid AND business_id=p_business;
  ELSE
    SELECT count(*) INTO matches FROM public.contacts v WHERE business_id=p_business
      AND lower(trim(v.email))=lower(trim(i->>'customer_email'));
    IF matches <> 1 THEN RAISE EXCEPTION 'invoice_contact_required'; END IF;
    SELECT to_jsonb(v) INTO c FROM public.contacts v WHERE business_id=p_business
      AND lower(trim(v.email))=lower(trim(i->>'customer_email'));
  END IF;
  IF c IS NULL OR coalesce(c->>'email','') NOT LIKE '%@%' THEN RAISE EXCEPTION 'invoice_contact_required'; END IF;
  SELECT name INTO bname FROM public.businesses WHERE id=p_business;
  RETURN jsonb_build_object('invoice_id',p_invoice,'contact_id',c->>'id',
    'contact_name',left(coalesce(c->>'name','Client'),160),
    'recipient_email',lower(trim(c->>'email')),
    'invoice_number',left(coalesce(nullif(i->>'invoice_number',''),i->>'id'),100),
    'amount_due_cents',(i->>'amount_due_cents')::bigint,'currency',upper(coalesce(i->>'currency','USD')),
    'due_date',i->>'due_date','business_name',left(coalesce(bname,'Your business'),160),
    'updated_at',i->>'updated_at');
END $$;
REVOKE ALL ON FUNCTION public.connected_ai_invoice_snapshot(uuid,uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.connected_ai_invoice_snapshot(uuid,uuid) TO service_role;

-- All transitions for a business share one transaction lock. This closes the
-- read/insert and revoke/complete races across Railway processes. The API also
-- authenticates and owner-checks every browser call; we recheck ownership here.
CREATE OR REPLACE FUNCTION public.connected_ai_transition(
  p_op text, p_business uuid, p_actor uuid, p_data jsonb DEFAULT '{}'::jsonb
) RETURNS jsonb LANGUAGE plpgsql SET search_path = public AS $$
DECLARE d public.connected_ai_devices; pair public.connected_ai_pairings;
  j public.chief_jobs; q public.agent_queue; snap jsonb; current_snap jsonb;
  qid uuid; jid uuid; out_value jsonb; owner uuid;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended(p_business::text, 411));
  SELECT owner_id INTO owner FROM public.businesses WHERE id=p_business;
  IF owner IS NULL OR owner <> p_actor THEN RAISE EXCEPTION 'owner_required'; END IF;

  IF p_op='pair' THEN
    IF (SELECT count(*) FROM public.connected_ai_pairings WHERE business_id=p_business
        AND consumed_at IS NULL AND expires_at>now())>=5 THEN RAISE EXCEPTION 'pairing_limit'; END IF;
    INSERT INTO public.connected_ai_pairings(business_id,owner_id,provider,secret_hash)
      VALUES(p_business,p_actor,p_data->>'provider',p_data->>'secret_hash') RETURNING * INTO pair;
    RETURN jsonb_build_object('id',pair.id,'expires_at',pair.expires_at);
  ELSIF p_op='claim' THEN
    SELECT * INTO pair FROM public.connected_ai_pairings WHERE business_id=p_business
      AND owner_id=p_actor AND secret_hash=p_data->>'secret_hash'
      AND consumed_at IS NULL AND expires_at>now() FOR UPDATE;
    IF pair.id IS NULL THEN RAISE EXCEPTION 'pairing_expired'; END IF;
    IF (SELECT count(*) FROM public.connected_ai_devices WHERE business_id=p_business
        AND revoked_at IS NULL AND expires_at>now())>=5 THEN RAISE EXCEPTION 'device_limit'; END IF;
    INSERT INTO public.connected_ai_devices(business_id,owner_id,provider,label,token_hash)
      VALUES(p_business,p_actor,pair.provider,p_data->>'label',p_data->>'token_hash') RETURNING * INTO d;
    UPDATE public.connected_ai_pairings SET consumed_at=now() WHERE id=pair.id;
    RETURN to_jsonb(d)-'token_hash';
  END IF;

  -- Browser status refresh also reconciles expired leases. Never silently run
  -- an interrupted task twice; retry is a new, explicit request.
  UPDATE public.chief_jobs SET status='interrupted',error='device_interrupted',finished_at=now()
    WHERE business_id=p_business AND kind='connected_ai_follow_up' AND status='running'
      AND (params->>'lease_until')::timestamptz <= now();
  UPDATE public.chief_jobs SET status='interrupted',error='queue_expired',finished_at=now()
    WHERE business_id=p_business AND kind='connected_ai_follow_up' AND status='queued'
      AND created_at<now()-interval '1 day';
  UPDATE public.chief_jobs SET status='failed',error='delivery_needs_check',
      params=params||jsonb_build_object('delivery_state','unknown'),finished_at=now()
    WHERE business_id=p_business AND kind='connected_ai_follow_up'
      AND params->>'delivery_state'='sending'
      AND (params->>'send_started_at')::timestamptz<now()-interval '5 minutes';
  IF p_op='status' THEN
    UPDATE public.chief_jobs jobs SET status='cancelled',finished_at=now()
      FROM public.agent_queue queue WHERE queue.connected_ai_job_id=jobs.id AND queue.business_id=p_business
        AND jobs.business_id=p_business AND jobs.kind='connected_ai_follow_up'
        AND jobs.status='awaiting_approval' AND queue.status='dismissed'
        AND jobs.params->>'delivery_state' IS NULL;
    RETURN jsonb_build_object(
      'devices',coalesce((SELECT jsonb_agg(to_jsonb(v)-'token_hash') FROM public.connected_ai_devices v
        WHERE business_id=p_business AND owner_id=p_actor AND revoked_at IS NULL),'[]'::jsonb),
      'jobs',coalesce((SELECT jsonb_agg(to_jsonb(v)) FROM (
        SELECT id,status,error,created_at,finished_at,result,
          params->>'provider' AS provider,params->>'device_id' AS device_id,
          params->'snapshot'->>'invoice_number' AS invoice_number,
          params->>'delivery_state' AS delivery_state
        FROM public.chief_jobs WHERE business_id=p_business AND user_id=p_actor
          AND kind='connected_ai_follow_up' ORDER BY created_at DESC LIMIT 30
      )v),'[]'::jsonb));
  END IF;

  IF p_op IN ('heartbeat','lease','complete','fail') THEN
    SELECT * INTO d FROM public.connected_ai_devices WHERE id=(p_data->>'device_id')::uuid
      AND business_id=p_business AND owner_id=p_actor AND token_hash=p_data->>'token_hash'
      AND revoked_at IS NULL AND expires_at>now() FOR UPDATE;
    IF d.id IS NULL THEN RAISE EXCEPTION 'device_revoked'; END IF;
  END IF;
  IF p_op='heartbeat' THEN
    UPDATE public.connected_ai_devices SET last_seen_at=now(),state=p_data->>'state' WHERE id=d.id;
    RETURN jsonb_build_object('ok',true,'active',CASE WHEN p_data->>'job_id' IS NULL THEN true ELSE EXISTS(
      SELECT 1 FROM public.chief_jobs WHERE id=(p_data->>'job_id')::uuid AND business_id=p_business
        AND status='running' AND params->>'device_id'=d.id::text
        AND params->>'lease_hash'=p_data->>'lease_hash'
        AND (params->>'lease_until')::timestamptz>now()) END);
  ELSIF p_op='enqueue' THEN
    SELECT * INTO j FROM public.chief_jobs WHERE business_id=p_business AND kind='connected_ai_follow_up'
      AND params->>'request_id'=p_data->>'request_id';
    IF j.id IS NOT NULL THEN
      IF j.params->>'invoice_id'<>p_data->>'invoice_id' OR j.params->>'device_id'<>p_data->>'device_id'
        THEN RAISE EXCEPTION 'request_conflict'; END IF;
      RETURN jsonb_build_object('id',j.id,'status',j.status,'deduplicated',true);
    END IF;
    SELECT * INTO d FROM public.connected_ai_devices WHERE id=(p_data->>'device_id')::uuid
      AND business_id=p_business AND owner_id=p_actor AND revoked_at IS NULL AND expires_at>now();
    IF d.id IS NULL OR d.state<>'signed_in' OR d.last_seen_at IS NULL OR d.last_seen_at<now()-interval '90 seconds'
      THEN RAISE EXCEPTION 'device_unavailable'; END IF;
    IF EXISTS(SELECT 1 FROM public.chief_jobs WHERE business_id=p_business AND kind='connected_ai_follow_up'
      AND (status IN ('queued','running') OR (params->>'invoice_id'=p_data->>'invoice_id'
        AND (status='awaiting_approval' OR params->>'delivery_state' IN ('sending','unknown','sent')))))
      THEN RAISE EXCEPTION 'job_already_active'; END IF;
    snap=public.connected_ai_invoice_snapshot(p_business,(p_data->>'invoice_id')::uuid);
    INSERT INTO public.chief_jobs(user_id,business_id,kind,status,source,params)
      VALUES(p_actor,p_business,'connected_ai_follow_up','queued','connected_ai',
        jsonb_build_object('request_id',p_data->>'request_id','device_id',d.id,'provider',d.provider,
          'invoice_id',p_data->>'invoice_id','snapshot',snap,
          'execution_source','customer_device','funding_source','provider_native_account')) RETURNING * INTO j;
    RETURN jsonb_build_object('id',j.id,'status',j.status,'deduplicated',false);
  ELSIF p_op='lease' THEN
    IF d.state<>'signed_in' OR d.last_seen_at IS NULL OR d.last_seen_at<now()-interval '90 seconds' THEN RAISE EXCEPTION 'device_unavailable'; END IF;
    SELECT * INTO j FROM public.chief_jobs WHERE business_id=p_business AND user_id=p_actor
      AND kind='connected_ai_follow_up' AND status='queued' AND params->>'device_id'=d.id::text
      ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1;
    IF j.id IS NULL THEN RETURN jsonb_build_object('job',NULL); END IF;
    BEGIN current_snap=public.connected_ai_invoice_snapshot(p_business,(j.params->>'invoice_id')::uuid);
    EXCEPTION WHEN OTHERS THEN current_snap=NULL; END;
    IF current_snap IS DISTINCT FROM j.params->'snapshot' THEN
      UPDATE public.chief_jobs SET status='interrupted',error='invoice_changed',finished_at=now() WHERE id=j.id;
      RETURN jsonb_build_object('job',NULL);
    END IF;
    UPDATE public.chief_jobs SET status='running',started_at=now(),params=params||jsonb_build_object(
      'lease_hash',p_data->>'lease_hash','lease_until',now()+interval '5 minutes') WHERE id=j.id;
    RETURN jsonb_build_object('job',jsonb_build_object('id',j.id,'provider',d.provider,
      'facts',(j.params->'snapshot')-'recipient_email'-'contact_id'-'invoice_id'-'updated_at'));
  ELSIF p_op IN ('complete','fail') THEN
    SELECT * INTO j FROM public.chief_jobs WHERE id=(p_data->>'job_id')::uuid AND business_id=p_business
      AND kind='connected_ai_follow_up' AND params->>'device_id'=d.id::text
      AND params->>'lease_hash'=p_data->>'lease_hash' FOR UPDATE;
    IF j.id IS NULL THEN RAISE EXCEPTION 'lease_invalid'; END IF;
    IF j.status='awaiting_approval' AND p_op='complete' THEN RETURN j.result; END IF;
    IF j.status<>'running' OR (j.params->>'lease_until')::timestamptz<=now() THEN RAISE EXCEPTION 'lease_expired'; END IF;
    IF p_op='fail' THEN
      UPDATE public.chief_jobs SET status='failed',error=p_data->>'error',finished_at=now() WHERE id=j.id;
      IF p_data->>'error' IN ('usage_limits','login_required') THEN
        UPDATE public.connected_ai_devices SET state=p_data->>'error' WHERE id=d.id;
      END IF;
      RETURN jsonb_build_object('ok',true);
    END IF;
    BEGIN current_snap=public.connected_ai_invoice_snapshot(p_business,(j.params->>'invoice_id')::uuid);
    EXCEPTION WHEN OTHERS THEN current_snap=NULL; END;
    IF current_snap IS DISTINCT FROM j.params->'snapshot' THEN
      UPDATE public.chief_jobs SET status='interrupted',error='invoice_changed',finished_at=now() WHERE id=j.id;
      RETURN jsonb_build_object('ok',false,'error','invoice_changed');
    END IF;
    INSERT INTO public.agent_queue(business_id,contact_id,agent,action_type,channel,subject,body,status,priority,ai_reasoning,connected_ai_job_id)
      VALUES(p_business,(current_snap->>'contact_id')::uuid,'chief','follow_up','email',
        p_data->>'subject',p_data->>'body','draft','medium',
        'Prepared through a connected '||d.provider||' account. A person must review before sending.',j.id) RETURNING id INTO qid;
    out_value=jsonb_build_object('ok',true,'queue_id',qid,'sent',false,'requires_human_review',true);
    UPDATE public.chief_jobs SET status='awaiting_approval',result=out_value,finished_at=now() WHERE id=j.id;
    RETURN out_value;
  ELSIF p_op IN ('revoke','cancel') THEN
    IF p_op='cancel' THEN
      SELECT * INTO j FROM public.chief_jobs WHERE id=(p_data->>'job_id')::uuid
        AND business_id=p_business AND user_id=p_actor AND kind='connected_ai_follow_up' FOR UPDATE;
      IF j.id IS NULL OR j.params->>'delivery_state' IS NOT NULL
        OR j.status NOT IN ('queued','running','awaiting_approval','cancelled')
        THEN RAISE EXCEPTION 'already_reviewed'; END IF;
    END IF;
    IF p_op='revoke' THEN
      UPDATE public.connected_ai_devices SET revoked_at=now() WHERE id=(p_data->>'device_id')::uuid
        AND business_id=p_business AND owner_id=p_actor;
    END IF;
    FOR j IN SELECT * FROM public.chief_jobs WHERE business_id=p_business AND user_id=p_actor
      AND kind='connected_ai_follow_up' AND status IN ('queued','running','awaiting_approval')
      AND coalesce(params->>'delivery_state','') NOT IN ('sending','unknown','sent')
      AND ((p_op='cancel' AND id=(p_data->>'job_id')::uuid)
        OR (p_op='revoke' AND params->>'device_id'=p_data->>'device_id')) FOR UPDATE LOOP
      UPDATE public.chief_jobs SET status='cancelled',finished_at=now() WHERE id=j.id;
      UPDATE public.agent_queue SET status='dismissed' WHERE connected_ai_job_id=j.id AND status='draft';
    END LOOP;
    RETURN jsonb_build_object('ok',true);
  ELSIF p_op='claim_send' THEN
    SELECT * INTO j FROM public.chief_jobs WHERE id=(p_data->>'job_id')::uuid AND business_id=p_business
      AND user_id=p_actor AND kind='connected_ai_follow_up' FOR UPDATE;
    IF j.id IS NULL OR j.status<>'awaiting_approval' OR j.params->>'delivery_state' IS NOT NULL
      THEN RAISE EXCEPTION 'already_reviewed'; END IF;
    IF NOT EXISTS(SELECT 1 FROM public.connected_ai_devices WHERE id=(j.params->>'device_id')::uuid
      AND business_id=p_business AND owner_id=p_actor AND revoked_at IS NULL AND expires_at>now())
      THEN RAISE EXCEPTION 'device_revoked'; END IF;
    current_snap=public.connected_ai_invoice_snapshot(p_business,(j.params->>'invoice_id')::uuid);
    IF current_snap IS DISTINCT FROM j.params->'snapshot' THEN RAISE EXCEPTION 'invoice_changed'; END IF;
    SELECT * INTO q FROM public.agent_queue WHERE connected_ai_job_id=j.id AND business_id=p_business FOR UPDATE;
    IF q.id IS NULL OR q.status<>'draft' THEN RAISE EXCEPTION 'already_reviewed'; END IF;
    UPDATE public.agent_queue SET subject=coalesce(p_data->>'subject',subject),body=coalesce(p_data->>'body',body),
      status='approved',reviewed_at=now() WHERE id=q.id RETURNING * INTO q;
    UPDATE public.chief_jobs SET params=params||jsonb_build_object('delivery_state','sending','send_started_at',now()) WHERE id=j.id;
    RETURN jsonb_build_object('item',to_jsonb(q),'expected_email',current_snap->>'recipient_email');
  ELSIF p_op='settle_send' THEN
    SELECT * INTO j FROM public.chief_jobs WHERE id=(p_data->>'job_id')::uuid AND business_id=p_business
      AND user_id=p_actor AND kind='connected_ai_follow_up' FOR UPDATE;
    IF j.id IS NULL OR j.params->>'delivery_state' IS DISTINCT FROM 'sending' THEN RAISE EXCEPTION 'already_reviewed'; END IF;
    UPDATE public.chief_jobs SET status=CASE WHEN (p_data->>'sent')::boolean THEN 'done' ELSE 'failed' END,
      params=params||jsonb_build_object('delivery_state',CASE WHEN (p_data->>'sent')::boolean THEN 'sent' ELSE 'unknown' END),
      result=result||jsonb_build_object('sent',(p_data->>'sent')::boolean,'provider_id',p_data->>'provider_id'),
      error=CASE WHEN (p_data->>'sent')::boolean THEN NULL ELSE 'delivery_needs_check' END,finished_at=now() WHERE id=j.id;
    UPDATE public.agent_queue SET status=CASE WHEN (p_data->>'sent')::boolean THEN 'sent' ELSE 'approved' END,
      sent_at=CASE WHEN (p_data->>'sent')::boolean THEN now() ELSE NULL END WHERE connected_ai_job_id=j.id;
    RETURN jsonb_build_object('ok',true);
  END IF;
  RAISE EXCEPTION 'unknown_operation';
END $$;
REVOKE ALL ON FUNCTION public.connected_ai_transition(text,uuid,uuid,jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.connected_ai_transition(text,uuid,uuid,jsonb) TO service_role;
COMMIT;
