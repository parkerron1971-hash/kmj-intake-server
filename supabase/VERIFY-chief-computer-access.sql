-- Read-only, transactional post-migration probe. Run as postgres in SQL Editor.
-- No credential value or business row is selected, created, or returned.
BEGIN;
DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['chief_errands','chief_errand_events','business_secrets'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname='public' AND c.relname=table_name AND c.relrowsecurity) THEN
      RAISE EXCEPTION 'Missing table or row security: %', table_name;
    END IF;
    IF has_table_privilege('anon', 'public.' || table_name, 'SELECT,INSERT,UPDATE,DELETE') THEN
      RAISE EXCEPTION 'Unexpected anonymous table privilege: %', table_name;
    END IF;
    IF has_table_privilege('authenticated', 'public.' || table_name, 'INSERT,UPDATE,DELETE') THEN
      RAISE EXCEPTION 'Unexpected browser write privilege: %', table_name;
    END IF;
  END LOOP;
  IF EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename='business_secrets') THEN
    RAISE EXCEPTION 'Vault must have zero user policies';
  END IF;
END $$;
SET LOCAL ROLE authenticated;
DO $$
BEGIN
  BEGIN
    PERFORM fields_ciphertext FROM public.business_secrets LIMIT 0;
    RAISE EXCEPTION 'FAIL: authenticated can SELECT vault ciphertext';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END $$;
RESET ROLE;
SET LOCAL ROLE anon;
DO $$
BEGIN
  BEGIN
    PERFORM fields_ciphertext FROM public.business_secrets LIMIT 0;
    RAISE EXCEPTION 'FAIL: anon can SELECT vault ciphertext';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END $$;
RESET ROLE;
SELECT 'PASS: row security and vault access denial verified; no credential values read' AS result;
ROLLBACK;
