-- Restricted readings must never enter the ordinary, browser-readable store.
BEGIN;
CREATE OR REPLACE FUNCTION public.is_standard_module_store(p_business_id uuid, p_module_id uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS (SELECT 1 FROM public.custom_modules m WHERE m.id = p_module_id
    AND m.business_id = p_business_id
    AND coalesce(m.agent_config->>'access_level', '') <> 'restricted');
$$;
REVOKE ALL ON FUNCTION public.is_standard_module_store(uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.is_standard_module_store(uuid, uuid) TO anon, authenticated, service_role;
DROP POLICY IF EXISTS standard_module_store_only ON public.module_entries;
CREATE POLICY standard_module_store_only ON public.module_entries AS RESTRICTIVE FOR ALL TO anon, authenticated
USING (public.is_standard_module_store(business_id, module_id))
WITH CHECK (public.is_standard_module_store(business_id, module_id));

CREATE OR REPLACE FUNCTION public.require_standard_module_store() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF NOT public.is_standard_module_store(NEW.business_id, NEW.module_id) THEN
    RAISE EXCEPTION 'Restricted readings require the authorized restricted-module endpoint';
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS require_standard_module_store ON public.module_entries;
CREATE TRIGGER require_standard_module_store BEFORE INSERT OR UPDATE ON public.module_entries
FOR EACH ROW EXECUTE FUNCTION public.require_standard_module_store();
COMMIT;
