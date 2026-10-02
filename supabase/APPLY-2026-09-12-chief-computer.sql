-- Chief's computer PR1. Apply after merge. Additive; repeatable.
-- Prerequisites: businesses, auth.uid(), is_business_owner(uuid),
-- is_business_member(uuid), and the anon/authenticated/service_role roles.
-- This does not enable errands, store a secret, or start a browser.
BEGIN;

CREATE TABLE IF NOT EXISTS public.chief_errands (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  user_id uuid NOT NULL,
  job_id uuid,
  kind text NOT NULL CHECK (kind IN ('reorder','portal','cancel_order','custom')),
  status text NOT NULL DEFAULT 'planned' CHECK (status IN
    ('planned','approved','running','needs_you','paused','done','failed','stopped','cancelled','interrupted')),
  title text NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
  plan jsonb NOT NULL CHECK (jsonb_typeof(plan) = 'object'),
  hosts text[] NOT NULL CHECK (cardinality(hosts) BETWEEN 1 AND 20),
  spend_limit_cents integer NOT NULL CHECK (spend_limit_cents >= 0),
  planned_total_cents integer CHECK (planned_total_cents >= 0),
  observed_total_cents integer CHECK (observed_total_cents >= 0),
  approved_at timestamptz,
  approved_by uuid,
  approval_scope text CHECK (approval_scope IN ('chat','button','stepup:danger')),
  hold jsonb CHECK (jsonb_typeof(hold) = 'object'),
  receipt jsonb CHECK (jsonb_typeof(receipt) = 'object'),
  idempotency_key text,
  cancel_until timestamptz,
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  finished_at timestamptz,
  UNIQUE (id, business_id)
);
CREATE INDEX IF NOT EXISTS chief_errands_biz_idx ON public.chief_errands(business_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS chief_errands_idem_idx ON public.chief_errands(business_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL AND status IN ('planned','approved','running','needs_you','paused','done');

CREATE TABLE IF NOT EXISTS public.chief_errand_events (
  id bigserial PRIMARY KEY,
  errand_id uuid NOT NULL,
  -- Internal tenant key for export/erasure; not a change to the section 7 Event.
  business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  n integer NOT NULL CHECK (n > 0),
  at timestamptz NOT NULL DEFAULT now(),
  kind text NOT NULL CHECK (kind IN ('step','frame','needs_secret','secret_filled','needs_approval',
    'approved','paused','resumed','stopped','done','failed','note')),
  note text,
  frame_path text,
  url_host text,
  meta jsonb CHECK (jsonb_typeof(meta) = 'object'),
  UNIQUE (errand_id, n),
  FOREIGN KEY (errand_id, business_id) REFERENCES public.chief_errands(id, business_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS chief_errand_events_biz_idx ON public.chief_errand_events(business_id, errand_id, n);

CREATE TABLE IF NOT EXISTS public.business_secrets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  -- PR1 deliberately permits login persistence only. Saving cards/sessions/custom
  -- material requires an explicitly reviewed follow-up migration and validator.
  kind text NOT NULL CHECK (kind = 'login'),
  host text NOT NULL CHECK (length(host) BETWEEN 3 AND 253 AND host = lower(host)
    AND host ~ '^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$'),
  label text NOT NULL CHECK (length(label) BETWEEN 1 AND 120),
  fields_ciphertext text NOT NULL,
  display jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(display) = 'object'),
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_used_at timestamptz,
  use_count integer NOT NULL DEFAULT 0 CHECK (use_count >= 0),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','revoked')),
  CHECK (status = 'revoked' OR length(fields_ciphertext) BETWEEN 1 AND 32768)
);
CREATE INDEX IF NOT EXISTS business_secrets_biz_host_idx ON public.business_secrets(business_id, host)
  WHERE status = 'active';

ALTER TABLE public.chief_errands ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chief_errand_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.business_secrets ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.chief_errands, public.chief_errand_events, public.business_secrets FROM PUBLIC, anon, authenticated;
REVOKE ALL ON SEQUENCE public.chief_errand_events_id_seq FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.chief_errands, public.chief_errand_events TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.chief_errands, public.chief_errand_events, public.business_secrets TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.chief_errand_events_id_seq TO service_role;

DROP POLICY IF EXISTS chief_errands_read_business ON public.chief_errands;
CREATE POLICY chief_errands_read_business ON public.chief_errands FOR SELECT TO authenticated
  USING (public.is_business_owner(business_id) OR public.is_business_member(business_id));
DROP POLICY IF EXISTS chief_errand_events_read_business ON public.chief_errand_events;
CREATE POLICY chief_errand_events_read_business ON public.chief_errand_events FOR SELECT TO authenticated
  USING (public.is_business_owner(business_id) OR public.is_business_member(business_id));
-- No vault policy, even for an owner. Values only leave storage through the
-- future controller's authenticated server-side fill path, never a user SELECT.
COMMENT ON TABLE public.business_secrets IS 'Service-only encrypted logins. No user policies. Named columns only; never export ciphertext. CVC/OTP/card persistence disabled in PR1.';
COMMIT;
