-- PR3. Apply after the Chief computer foundation. Service-only transactions.
BEGIN;

CREATE OR REPLACE FUNCTION public.chief_errand_event(
 p_business_id uuid, p_id uuid, p_event jsonb
) RETURNS public.chief_errand_events LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE out_row chief_errand_events;
BEGIN
 PERFORM 1 FROM chief_errands WHERE id=p_id AND business_id=p_business_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'errand_not_found'; END IF;
 INSERT INTO chief_errand_events(errand_id,business_id,n,kind,note,frame_path,url_host,meta)
 SELECT p_id,p_business_id,coalesce(max(n),0)+1,p_event->>'kind',p_event->>'note',
  p_event->>'frame_path',p_event->>'url_host',coalesce(p_event->'meta','{}'::jsonb)
 FROM chief_errand_events WHERE errand_id=p_id RETURNING * INTO out_row;
 RETURN out_row;
END $$;

CREATE OR REPLACE FUNCTION public.chief_errand_transition(
 p_business_id uuid, p_id uuid, p_expected text[], p_patch jsonb,
 p_event jsonb DEFAULT NULL, p_hold_id text DEFAULT NULL
) RETURNS public.chief_errands LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE current_row chief_errands; next_row chief_errands; new_status text;
BEGIN
 SELECT * INTO current_row FROM chief_errands WHERE id=p_id AND business_id=p_business_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'errand_not_found'; END IF;
 IF p_expected IS NULL OR cardinality(p_expected)=0 OR NOT current_row.status=ANY(p_expected) OR
    (p_hold_id IS NOT NULL AND current_row.hold->>'id' IS DISTINCT FROM p_hold_id) THEN
  RAISE EXCEPTION 'errand_changed';
 END IF;
 IF EXISTS (SELECT 1 FROM jsonb_object_keys(p_patch) k WHERE k NOT IN
   ('status','hold','observed_total_cents','receipt','cancel_until','error','started_at','finished_at','plan')) THEN
  RAISE EXCEPTION 'errand_patch_not_allowed';
 END IF;
 new_status:=coalesce(p_patch->>'status',current_row.status);
 IF new_status<>current_row.status AND NOT (
   (current_row.status='planned' AND new_status IN ('cancelled','stopped')) OR
   (current_row.status='approved' AND new_status IN ('running','paused','stopped','interrupted','failed')) OR
   (current_row.status='running' AND new_status IN ('needs_you','paused','done','failed','stopped','interrupted')) OR
   (current_row.status='needs_you' AND new_status IN ('running','paused','stopped','failed','interrupted')) OR
   (current_row.status='paused' AND new_status IN ('running','needs_you','stopped','failed','interrupted'))
 ) THEN RAISE EXCEPTION 'errand_transition_not_allowed'; END IF;
 next_row:=jsonb_populate_record(current_row,p_patch);
 UPDATE chief_errands SET status=next_row.status,hold=next_row.hold,
  observed_total_cents=next_row.observed_total_cents,receipt=next_row.receipt,
  cancel_until=next_row.cancel_until,error=next_row.error,started_at=next_row.started_at,
  finished_at=next_row.finished_at,plan=next_row.plan WHERE id=p_id RETURNING * INTO next_row;
 IF p_event IS NOT NULL THEN PERFORM chief_errand_event(p_business_id,p_id,p_event); END IF;
 RETURN next_row;
END $$;

CREATE OR REPLACE FUNCTION public.chief_errand_approve(
 p_business_id uuid, p_id uuid, p_user_id uuid, p_scope text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE e chief_errands; j chief_jobs;
BEGIN
 -- Approval and the job insert commit together. The HTTP caller starts exactly
 -- this prepared job after commit; retries never enqueue another browser.
 SELECT * INTO e FROM chief_errands WHERE id=p_id AND business_id=p_business_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'errand_not_found'; END IF;
 IF e.status<>'planned' THEN RAISE EXCEPTION 'errand_changed'; END IF;
 IF p_scope IS NULL OR p_scope NOT IN ('chat','button','stepup:danger') THEN RAISE EXCEPTION 'invalid_scope'; END IF;
 INSERT INTO chief_jobs(user_id,business_id,kind,status,source,params)
 VALUES(p_user_id,p_business_id,'errand','queued','approval',jsonb_build_object('errand_id',p_id)) RETURNING * INTO j;
 UPDATE chief_errands SET status='approved',job_id=j.id,approved_at=now(),
  approved_by=p_user_id,approval_scope=p_scope WHERE id=p_id RETURNING * INTO e;
 PERFORM chief_errand_event(p_business_id,p_id,'{"kind":"approved","note":"The owner or manager approved this errand."}'::jsonb);
 RETURN jsonb_build_object('errand',to_jsonb(e),'job',to_jsonb(j));
END $$;

CREATE OR REPLACE FUNCTION public.chief_errand_plan(p_row jsonb)
RETURNS public.chief_errands LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE e chief_errands; bid uuid:=(p_row->>'business_id')::uuid;
BEGIN
 -- Serialize plans for this business so overlapping multi-item plans cannot
 -- order the same offering twice despite having different aggregate keys.
 PERFORM 1 FROM businesses WHERE id=bid FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'business_not_found'; END IF;
 SELECT * INTO e FROM chief_errands old WHERE business_id=bid
  AND status IN ('planned','approved','running','needs_you','paused','done')
  AND (idempotency_key=p_row->>'idempotency_key' OR
   (kind='reorder' AND p_row->>'kind'='reorder' AND created_at>=date_trunc('day',now()) AND EXISTS (
    SELECT 1 FROM jsonb_array_elements(old.plan->'items') a,
      jsonb_array_elements(p_row->'plan'->'items') b
    WHERE a->>'offering_id'=b->>'offering_id'
   ))) ORDER BY created_at DESC LIMIT 1;
 IF FOUND THEN RETURN e; END IF;
 INSERT INTO chief_errands(business_id,user_id,kind,title,plan,hosts,spend_limit_cents,
  planned_total_cents,idempotency_key)
 VALUES(bid,(p_row->>'user_id')::uuid,p_row->>'kind',p_row->>'title',p_row->'plan',
  ARRAY(SELECT jsonb_array_elements_text(p_row->'hosts')),
  (p_row->>'spend_limit_cents')::integer,(p_row->>'planned_total_cents')::integer,
  p_row->>'idempotency_key') RETURNING * INTO e;
 PERFORM chief_errand_event(bid,e.id,'{"kind":"note","note":"Errand planned; waiting for approval."}'::jsonb);
 RETURN e;
END $$;

CREATE OR REPLACE FUNCTION public.chief_computer_settings(p_business_id uuid,p_settings jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE result jsonb;
BEGIN
 UPDATE businesses SET settings=jsonb_set(coalesce(settings,'{}'::jsonb),'{computer}',p_settings,true)
 WHERE id=p_business_id RETURNING settings->'computer' INTO result;
 IF NOT FOUND THEN RAISE EXCEPTION 'business_not_found'; END IF;
 RETURN result;
END $$;

REVOKE ALL ON FUNCTION public.chief_errand_event(uuid,uuid,jsonb),
 public.chief_errand_transition(uuid,uuid,text[],jsonb,jsonb,text),
 public.chief_errand_approve(uuid,uuid,uuid,text), public.chief_errand_plan(jsonb),
 public.chief_computer_settings(uuid,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.chief_errand_event(uuid,uuid,jsonb),
 public.chief_errand_transition(uuid,uuid,text[],jsonb,jsonb,text),
 public.chief_errand_approve(uuid,uuid,uuid,text),public.chief_errand_plan(jsonb),
 public.chief_computer_settings(uuid,jsonb) TO service_role;
COMMIT;
