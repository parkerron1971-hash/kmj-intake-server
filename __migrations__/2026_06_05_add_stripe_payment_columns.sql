-- ─────────────────────────────────────────────────────────────────
-- Phase D.4 PR 1 — Stripe Connect + per-booking payment columns
-- ─────────────────────────────────────────────────────────────────
-- Run via:  Supabase Studio → SQL editor → paste + Run
-- Idempotent, forward-only, additive only (no data touched).
--
-- What this does:
--   1. businesses.stripe_account_id text NULL — the connected
--      Stripe Standard account id ("acct_...") the practitioner
--      onboarded under their own Stripe login. Storing the id is
--      enough — every Stripe API call passes Stripe-Account: <id>
--      and uses the platform key for auth.
--   2. module_entries.paid_at timestamptz NULL — when the booking
--      was paid (set by webhook on payment_intent.succeeded /
--      checkout.session.completed).
--   3. module_entries.stripe_charge_id text NULL — the underlying
--      charge id once captured (audit + refunds).
--   4. module_entries.stripe_payment_intent_id text NULL — the
--      PI id created when the customer kicked off the optional
--      "Pay now" flow (lets the success handler reconcile in
--      either direction without UUID collisions).
--
-- After this runs, Phase D.4 PR 1 backend can be deployed.
-- ─────────────────────────────────────────────────────────────────

ALTER TABLE public.businesses
    ADD COLUMN IF NOT EXISTS stripe_account_id text;

ALTER TABLE public.module_entries
    ADD COLUMN IF NOT EXISTS paid_at timestamptz;

ALTER TABLE public.module_entries
    ADD COLUMN IF NOT EXISTS stripe_charge_id text;

ALTER TABLE public.module_entries
    ADD COLUMN IF NOT EXISTS stripe_payment_intent_id text;

-- Verify the new columns landed:
SELECT
    table_name,
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE (table_name = 'businesses' AND column_name = 'stripe_account_id')
   OR (table_name = 'module_entries' AND column_name IN ('paid_at','stripe_charge_id','stripe_payment_intent_id'))
ORDER BY table_name, column_name;
