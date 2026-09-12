-- PR5: apply after merge, following the foundation and runtime migrations.
-- Confirmed purchases are reconciled without running the browser again.
BEGIN;
CREATE OR REPLACE FUNCTION public.chief_errand_complete(p_business_id uuid,p_id uuid)
RETURNS public.chief_errands LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE r chief_errands; line jsonb; supplier_id uuid; day date; cents integer;
        expense_id uuid; marker text; pending boolean:=false;
BEGIN
 SELECT * INTO r FROM chief_errands WHERE id=p_id AND business_id=p_business_id FOR UPDATE;
 IF NOT FOUND OR r.status<>'done' OR r.kind<>'reorder' OR r.receipt IS NULL
    OR r.plan->>'__submission_attempted_at' IS NULL THEN
  RAISE EXCEPTION 'confirmed_order_required';
 END IF;
 IF r.plan->>'__completion_done'='true' AND r.receipt->>'document_id' IS NOT NULL THEN
  UPDATE chief_errands SET error=NULL WHERE id=r.id RETURNING * INTO r;
  RETURN r;
 END IF;
 day:=r.finished_at::date;
 cents:=(r.receipt->>'charged_cents')::integer;
 IF day IS NULL OR cents IS NULL OR cents<0 OR cents<>r.observed_total_cents THEN
  RAISE EXCEPTION 'invalid_receipt';
 END IF;
 supplier_id:=(r.plan->'supplier'->>'id')::uuid;
 IF r.plan->>'__inventory_done' IS DISTINCT FROM 'true' THEN
  FOR line IN SELECT * FROM jsonb_array_elements(r.plan->'items') LOOP
   UPDATE offerings SET reorder_pending_at=r.finished_at
    WHERE id=(line->>'offering_id')::uuid AND business_id=p_business_id;
   IF NOT FOUND THEN RAISE EXCEPTION 'inventory_item_missing'; END IF;
  END LOOP;
  UPDATE suppliers SET last_ordered_at=r.finished_at,
   notes=concat_ws(E'\n',nullif(notes,''),'Chief order '||(r.receipt->>'order_number'))
   WHERE id=supplier_id AND business_id=p_business_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'supplier_missing'; END IF;
  r.plan:=r.plan||'{"__inventory_done":true}'::jsonb;
 END IF;
 -- Fixed ID makes the purchase's undo entry idempotent even during repair.
 INSERT INTO chief_undo_log(id,business_id,user_id,action_type,action_json,result_json,status,created_at)
 VALUES(r.id,p_business_id,r.approved_by,'approve_errand',jsonb_build_object('errand_id',r.id),
  jsonb_build_object('errand_id',r.id,'status','done'),'undoable',r.finished_at)
 ON CONFLICT(id) DO NOTHING;
 IF EXISTS(SELECT 1 FROM chief_undo_log WHERE id=r.id AND business_id<>p_business_id) THEN
  RAISE EXCEPTION 'undo_collision';
 END IF;
 marker:='Chief errand '||r.id::text;
 SELECT id INTO expense_id FROM business_expenses WHERE id=r.id AND business_id=p_business_id AND notes=marker;
 IF expense_id IS NULL THEN
  IF EXISTS(SELECT 1 FROM accounting_periods WHERE business_id=p_business_id AND status='closed'
            AND period_start<=day AND period_end>=day) THEN
   pending:=true;
  ELSE
   -- Existing GL triggers enqueue this ordinary expense. Never post a second GL entry.
   INSERT INTO business_expenses(id,business_id,amount,category,subcategory,description,date,vendor,receipt_path,notes)
   VALUES(r.id,p_business_id,cents/100.0,'operating','Supplies',
    'Supplier order '||(r.receipt->>'order_number'),day,r.plan->'supplier'->>'name',
    r.receipt->>'receipt_path',marker) RETURNING id INTO expense_id;
  END IF;
 END IF;
 IF expense_id IS NOT NULL THEN r.receipt:=r.receipt||jsonb_build_object('expense_id',expense_id); END IF;
 r.plan:=r.plan||jsonb_build_object('__completion_done',NOT pending);
 UPDATE chief_errands SET plan=r.plan,receipt=r.receipt,
  error=CASE WHEN pending THEN 'Order confirmed; closed books need review before recording its expense. Do not reorder.'
   WHEN r.receipt->>'document_id' IS NULL THEN 'Order confirmed; receipt filing needs repair. Do not reorder.' ELSE NULL END
 WHERE id=r.id RETURNING * INTO r;
 RETURN r;
END $$;

CREATE OR REPLACE FUNCTION public.chief_errand_shown(p_business_id uuid,p_id uuid)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
BEGIN
 UPDATE chief_errands SET plan=jsonb_set(plan,'{__shown}','true'::jsonb,true)
 WHERE id=p_id AND business_id=p_business_id AND status IN ('done','failed','stopped','interrupted')
 AND plan->>'__shown' IS DISTINCT FROM 'true';
 RETURN FOUND;
END $$;
REVOKE ALL ON FUNCTION public.chief_errand_complete(uuid,uuid) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.chief_errand_shown(uuid,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.chief_errand_complete(uuid,uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.chief_errand_shown(uuid,uuid) TO service_role;
COMMIT;
