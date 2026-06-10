-- ═════════════════════════════════════════════════════════════════════
-- Phase I.10 — vertical compliance reports
-- ═════════════════════════════════════════════════════════════════════
-- One column: tag a trust-account transaction with the client whose money
-- it is (per-client trust sub-balances on the Trust Reconciliation report).
-- Donor/990 reports + restricted-gift routing (invoice category
-- "restricted" → 4200 for nonprofits) need no schema — the GL accounts
-- were provisioned in I.7.
--
-- Additive + idempotent. Clean rollback. Apply via Supabase Studio.
-- ═════════════════════════════════════════════════════════════════════

ALTER TABLE public.plaid_transactions
  ADD COLUMN IF NOT EXISTS trust_contact_id uuid REFERENCES public.contacts(id) ON DELETE SET NULL;

COMMENT ON COLUMN public.plaid_transactions.trust_contact_id IS
  'I.10 — lawyer IOLTA: which client''s funds this trust-account transaction moves (per-client sub-balances).';

CREATE INDEX IF NOT EXISTS idx_plaid_tx_trust_contact
  ON public.plaid_transactions (business_id, trust_contact_id)
  WHERE trust_contact_id IS NOT NULL;

-- ─── Rollback ────────────────────────────────────────────────────────
--   ALTER TABLE public.plaid_transactions DROP COLUMN IF EXISTS trust_contact_id;

SELECT 'phase I.10 vertical reports ready' AS status;
