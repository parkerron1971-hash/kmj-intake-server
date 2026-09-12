-- Read-only rollback probe, run as postgres after PR3 migration.
BEGIN;
DO $$
DECLARE signature text; client_role text;
BEGIN
 FOREACH signature IN ARRAY ARRAY[
  'public.chief_errand_event(uuid,uuid,jsonb)',
  'public.chief_errand_transition(uuid,uuid,text[],jsonb,jsonb,text)',
  'public.chief_errand_approve(uuid,uuid,uuid,text)',
  'public.chief_errand_plan(jsonb)',
  'public.chief_computer_settings(uuid,jsonb)'
 ] LOOP
  IF to_regprocedure(signature) IS NULL THEN RAISE EXCEPTION 'Missing runtime function'; END IF;
  FOREACH client_role IN ARRAY ARRAY['anon','authenticated'] LOOP
   IF has_function_privilege(client_role,signature,'EXECUTE') THEN
    RAISE EXCEPTION 'Browser role can execute runtime function';
   END IF;
  END LOOP;
  IF NOT has_function_privilege('service_role',signature,'EXECUTE') THEN
   RAISE EXCEPTION 'Service runtime grant missing';
  END IF;
 END LOOP;
 IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='public'
  AND tablename='chief_jobs' AND indexname='chief_jobs_one_active_per_business_kind') THEN
  RAISE EXCEPTION 'Single active job index missing';
 END IF;
END $$;
SELECT 'PASS: errand runtime functions are service-only and job uniqueness is installed' AS result;
ROLLBACK;
