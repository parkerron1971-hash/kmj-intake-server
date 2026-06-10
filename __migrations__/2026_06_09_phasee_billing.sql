-- ═════════════════════════════════════════════════════════════════════
-- Phase E — platform subscription billing (gate-ready, UNENFORCED)
-- ═════════════════════════════════════════════════════════════════════
-- Subscription bookkeeping columns on businesses (the Phase 5 draft's
-- columns, now actually applied) + business_id on the PRODUCTION
-- stripe_webhook_events shape (PR3) for billing-event triage.
-- NOTE: the old drafted supabase/billing-migration.sql is superseded by
-- this file — do NOT run that one (its stripe_webhook_events shape
-- conflicts with the deployed PR3 table).
--
-- Additive + idempotent. Clean rollback. Apply via Supabase Studio.
-- ═════════════════════════════════════════════════════════════════════

ALTER TABLE public.businesses
  ADD COLUMN IF NOT EXISTS stripe_customer_id        text,
  ADD COLUMN IF NOT EXISTS stripe_subscription_id    text,
  ADD COLUMN IF NOT EXISTS subscription_status       text
    CHECK (subscription_status IS NULL OR subscription_status IN (
      'trialing', 'active', 'past_due', 'canceled', 'incomplete', 'unpaid', 'paused'
    )),
  ADD COLUMN IF NOT EXISTS subscription_plan         text,   -- Stripe price id
  ADD COLUMN IF NOT EXISTS trial_ends_at             timestamptz,
  ADD COLUMN IF NOT EXISTS current_period_end        timestamptz,
  ADD COLUMN IF NOT EXISTS cancel_at_period_end      boolean DEFAULT false;

-- Billing-event triage column on the PRODUCTION webhook log (PR3 shape).
ALTER TABLE public.stripe_webhook_events
  ADD COLUMN IF NOT EXISTS business_id uuid;

-- The billing_status view the Settings BillingPanel reads (from the Phase 5
-- draft; included here so ONLY this file needs to run). security_invoker so
-- businesses RLS applies to the reader.
CREATE OR REPLACE VIEW public.billing_status
WITH (security_invoker = true) AS
SELECT
  b.id                               AS business_id,
  b.name                             AS business_name,
  b.owner_id,
  b.stripe_customer_id,
  b.stripe_subscription_id,
  b.subscription_status,
  b.subscription_plan,
  b.trial_ends_at,
  b.current_period_end,
  b.cancel_at_period_end,
  CASE WHEN b.subscription_status IN ('active', 'trialing') THEN true
       ELSE false END                AS has_access,
  CASE WHEN b.trial_ends_at IS NOT NULL AND b.trial_ends_at > now() THEN
         EXTRACT(EPOCH FROM (b.trial_ends_at - now())) / 86400
       ELSE NULL END                 AS trial_days_left
FROM public.businesses b;

GRANT SELECT ON public.billing_status TO authenticated;

-- ─── Rollback ────────────────────────────────────────────────────────
--   ALTER TABLE public.businesses DROP COLUMN IF EXISTS stripe_customer_id,
--     DROP COLUMN IF EXISTS stripe_subscription_id, DROP COLUMN IF EXISTS subscription_status,
--     DROP COLUMN IF EXISTS subscription_plan, DROP COLUMN IF EXISTS trial_ends_at,
--     DROP COLUMN IF EXISTS current_period_end, DROP COLUMN IF EXISTS cancel_at_period_end;
--   ALTER TABLE public.stripe_webhook_events DROP COLUMN IF EXISTS business_id;

SELECT 'phase E billing columns ready' AS status;
