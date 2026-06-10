-- ═════════════════════════════════════════════════════════════════════
-- Phase I.7 — vertical ledger separation (lawyer IOLTA trust accounts)
-- ═════════════════════════════════════════════════════════════════════
-- One flag: mark a linked bank account as a TRUST account. The GL engine
-- then books its activity Trust Account (1200) ↔ Client Trust Funds (2200)
-- — never income, expense, or operating cash — and the H.3a operating
-- reports exclude it. New COA accounts (2200 lawyer; 3300/4200 nonprofit)
-- provision lazily via ensure_chart_of_accounts on the next backfill or
-- queue drain — no COA SQL needed here.
--
-- Additive + idempotent. Clean rollback. Apply via Supabase Studio.
-- ═════════════════════════════════════════════════════════════════════

ALTER TABLE public.plaid_accounts
  ADD COLUMN IF NOT EXISTS is_trust_account boolean DEFAULT false;

COMMENT ON COLUMN public.plaid_accounts.is_trust_account IS
  'I.7 — lawyer IOLTA: account holds client funds; GL books its activity 1200<->2200, operating reports exclude it.';

-- ─── Rollback ────────────────────────────────────────────────────────
--   ALTER TABLE public.plaid_accounts DROP COLUMN IF EXISTS is_trust_account;

SELECT 'phase I.7 vertical ledgers ready' AS status;
