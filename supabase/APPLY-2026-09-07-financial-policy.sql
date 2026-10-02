BEGIN;
CREATE TABLE IF NOT EXISTS public.business_financial_policies (
  business_id uuid PRIMARY KEY REFERENCES public.businesses(id) ON DELETE CASCADE,
  mode text NOT NULL CHECK (mode IN ('standard', 'view_only')),
  provider_review_required boolean NOT NULL DEFAULT true,
  updated_by uuid NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.business_financial_account_locks (
  business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  stripe_account_id text NOT NULL,
  PRIMARY KEY (business_id, stripe_account_id)
);
CREATE INDEX IF NOT EXISTS financial_account_locks_account_idx ON public.business_financial_account_locks(stripe_account_id);
CREATE TABLE IF NOT EXISTS public.business_financial_policy_history (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  previous_mode text NOT NULL,
  mode text NOT NULL,
  actor_id uuid NOT NULL,
  reason text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.business_financial_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.business_financial_account_locks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.business_financial_policy_history ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.business_financial_policies, public.business_financial_account_locks, public.business_financial_policy_history FROM anon, authenticated;
GRANT ALL ON public.business_financial_policies, public.business_financial_account_locks, public.business_financial_policy_history TO service_role;

CREATE OR REPLACE FUNCTION public.set_business_financial_policy(p_business_id uuid, p_actor_id uuid, p_mode text, p_reason text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE b public.businesses; previous text; result public.business_financial_policies;
BEGIN
  IF p_mode NOT IN ('standard', 'view_only') OR length(trim(p_reason)) < 10 THEN
    RAISE EXCEPTION 'Invalid policy change';
  END IF;
  SELECT * INTO b FROM public.businesses WHERE id = p_business_id FOR UPDATE;
  IF NOT FOUND OR b.owner_id IS DISTINCT FROM p_actor_id THEN RAISE EXCEPTION 'Owner access required'; END IF;
  SELECT mode INTO previous FROM public.business_financial_policies WHERE business_id = p_business_id FOR UPDATE;
  IF b.stripe_account_id IS NOT NULL THEN
    INSERT INTO public.business_financial_account_locks(business_id, stripe_account_id)
      VALUES (p_business_id, b.stripe_account_id) ON CONFLICT DO NOTHING;
  END IF;
  INSERT INTO public.business_financial_policies(business_id, mode, provider_review_required, updated_by)
    VALUES (p_business_id, p_mode, p_mode = 'view_only', p_actor_id)
    ON CONFLICT (business_id) DO UPDATE SET mode = EXCLUDED.mode,
      provider_review_required = EXCLUDED.provider_review_required,
      updated_by = EXCLUDED.updated_by, updated_at = now() RETURNING * INTO result;
  INSERT INTO public.business_financial_policy_history(business_id, previous_mode, mode, actor_id, reason)
    VALUES (p_business_id, coalesce(previous, 'standard'), p_mode, p_actor_id, p_reason);
  RETURN to_jsonb(result);
END;
$$;
REVOKE ALL ON FUNCTION public.set_business_financial_policy(uuid, uuid, text, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.set_business_financial_policy(uuid, uuid, text, text) TO service_role;

-- Preserve provider ownership across future disconnects and reject a connection
-- that races with a view-only policy change, including a direct browser write.
INSERT INTO public.business_financial_account_locks(business_id, stripe_account_id)
  SELECT id, stripe_account_id FROM public.businesses WHERE stripe_account_id IS NOT NULL
  ON CONFLICT DO NOTHING;
CREATE OR REPLACE FUNCTION public.guard_financial_account_connection() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF NEW.stripe_account_id IS NOT NULL AND (TG_OP = 'INSERT' OR NEW.stripe_account_id IS DISTINCT FROM OLD.stripe_account_id)
    AND EXISTS (SELECT 1 FROM public.business_financial_policies WHERE business_id = NEW.id AND mode = 'view_only') THEN
    RAISE EXCEPTION 'Payment connections are disabled by the financial policy';
  END IF;
  IF NEW.stripe_account_id IS NOT NULL THEN
    INSERT INTO public.business_financial_account_locks(business_id, stripe_account_id)
      VALUES (NEW.id, NEW.stripe_account_id) ON CONFLICT DO NOTHING;
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS guard_financial_account_connection ON public.businesses;
CREATE TRIGGER guard_financial_account_connection AFTER INSERT OR UPDATE OF stripe_account_id ON public.businesses
FOR EACH ROW EXECUTE FUNCTION public.guard_financial_account_connection();
COMMIT;
