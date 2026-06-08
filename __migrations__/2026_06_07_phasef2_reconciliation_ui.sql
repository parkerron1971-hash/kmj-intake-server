-- ═════════════════════════════════════════════════════════════════════
-- Phase F.2 v1.6 — Reconciliation UI
-- ═════════════════════════════════════════════════════════════════════
-- Audit-trail + payout-snapshot columns for the manual-match / ignore
-- flows and the matched table. reconciliation_status already allows
-- 'manual_matched' and 'ignored' (F.2 v1 CHECK), so no enum change.
--
-- Additive + idempotent. Rollback path is clean: DROP COLUMN on the four
-- new columns loses only the new audit/snapshot data — no existing F.2
-- v1/v1.5 column or row is touched.
-- ═════════════════════════════════════════════════════════════════════

ALTER TABLE public.plaid_transactions
    -- Why a manual match / ignore was made (practitioner-entered or
    -- Chief-proposed reasoning, later).
    ADD COLUMN IF NOT EXISTS manual_match_reason text,
    -- When the row was marked ignored (distinct from updated_at).
    ADD COLUMN IF NOT EXISTS ignored_at timestamptz,
    -- Snapshot of the matched Stripe payout so the matched table + match
    -- detail drawer render deltas without a live Stripe fetch per row.
    -- Written by the auto-match worker and the manual-match endpoint.
    ADD COLUMN IF NOT EXISTS reconciled_payout_amount numeric(14,2),
    ADD COLUMN IF NOT EXISTS reconciled_payout_date date;

-- Matched / unmatched lookups for the reconciliation tables.
CREATE INDEX IF NOT EXISTS idx_plaid_tx_recon_status
    ON public.plaid_transactions (business_id, reconciliation_status, date DESC);

-- ─── Rollback (if ever needed) ───────────────────────────────────────
--   ALTER TABLE public.plaid_transactions
--     DROP COLUMN IF EXISTS manual_match_reason,
--     DROP COLUMN IF EXISTS ignored_at,
--     DROP COLUMN IF EXISTS reconciled_payout_amount,
--     DROP COLUMN IF EXISTS reconciled_payout_date;
--   DROP INDEX IF EXISTS public.idx_plaid_tx_recon_status;

-- ─── Verify ──────────────────────────────────────────────────────────
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'plaid_transactions'
  AND column_name IN ('manual_match_reason', 'ignored_at',
                      'reconciled_payout_amount', 'reconciled_payout_date')
ORDER BY column_name;
