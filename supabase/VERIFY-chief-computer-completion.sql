BEGIN;
DO $$ BEGIN
 IF to_regprocedure('public.chief_errand_complete(uuid,uuid)') IS NULL THEN
  RAISE EXCEPTION 'completion function missing'; END IF;
 IF has_function_privilege('authenticated','public.chief_errand_complete(uuid,uuid)','EXECUTE')
 OR has_function_privilege('anon','public.chief_errand_complete(uuid,uuid)','EXECUTE')
 OR has_function_privilege('authenticated','public.chief_errand_shown(uuid,uuid)','EXECUTE') THEN
  RAISE EXCEPTION 'browser role can execute completion'; END IF;
 IF NOT has_function_privilege('service_role','public.chief_errand_complete(uuid,uuid)','EXECUTE') THEN
  RAISE EXCEPTION 'service role cannot complete'; END IF;
END $$;
SELECT 'PASS: completion functions exist and browser execution is denied' AS result;
ROLLBACK;
