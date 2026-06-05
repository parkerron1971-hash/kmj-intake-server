-- ─────────────────────────────────────────────────────────────────
-- Phase D.4 PR 3a — Invoicing unification (Philosophy A)
-- ─────────────────────────────────────────────────────────────────
-- Run via:  Supabase Studio → SQL editor → paste + Run
-- Idempotent, forward-only, additive only on the existing invoices
-- table. Drops PR 3's deferred stripe_disputes_cache (never written
-- to). stripe_webhook_events stays.
--
-- Ruling (Philosophy A): the pre-existing invoices table +
-- InvoicesPanel.tsx + stripe_proxy.py Payment Link flow IS the
-- canonical invoicing system. PR 3's Stripe-Invoice schema is cut.
--
-- What this does:
--   1. ADD refund_amount_cents int NULL on existing invoices.
--      Set by charge.refunded webhook handler when the refunded
--      charge's metadata.source_type='invoice'.
--   2. ADD refunded_at timestamptz NULL on existing invoices.
--      Same trigger. Status stays 'paid'; refund details land here.
--   3. DROP stripe_disputes_cache (PR 3a kill — disputes UI in PR 3b
--      may use a different shape; nothing has written here yet).
--
-- PR 3's __migrations__/2026_06_05_pr3_payments_tables.sql is now
-- superseded for the invoices + disputes parts; the
-- stripe_webhook_events table from that migration STAYS (idempotency
-- log is philosophy-agnostic).
-- ─────────────────────────────────────────────────────────────────

-- 1. Additive refund columns on existing invoices.
ALTER TABLE public.invoices
    ADD COLUMN IF NOT EXISTS refund_amount_cents integer;
ALTER TABLE public.invoices
    ADD COLUMN IF NOT EXISTS refunded_at timestamptz;

-- 2. Drop the PR 3 disputes cache (never written; deferred to PR 3b).
DROP TABLE IF EXISTS public.stripe_disputes_cache;

-- Verify:
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema='public'
  AND table_name='invoices'
  AND column_name IN ('refund_amount_cents','refunded_at')
ORDER BY column_name;

SELECT to_regclass('public.stripe_disputes_cache') AS disputes_cache_present;
SELECT to_regclass('public.stripe_webhook_events') AS webhook_events_present;
