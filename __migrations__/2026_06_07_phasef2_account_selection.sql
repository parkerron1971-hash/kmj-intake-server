-- ═════════════════════════════════════════════════════════════════════
-- Phase F.2 v1.1 — Per-account selection control
-- ═════════════════════════════════════════════════════════════════════
-- Production finding: Plaid Link linked ALL accounts at an institution
-- (multiple checking + savings + credit cards) when only one belongs to
-- the business. This migration adds the columns that let a practitioner
-- include/exclude individual accounts from bookkeeping and soft-remove the
-- ones that don't belong — without destroying transaction history.
--
-- Additive + idempotent. Safe to re-run. Apply via Supabase Studio → SQL.
-- ═════════════════════════════════════════════════════════════════════

ALTER TABLE public.plaid_accounts
    -- Excluded accounts stay synced but are omitted from the Cash Flow
    -- KPIs, bucket bars, Needs-Review list, and reconciliation matching.
    ADD COLUMN IF NOT EXISTS included_in_bookkeeping boolean NOT NULL DEFAULT true,
    -- Soft-delete marker. Removed accounts are hidden from the UI and
    -- treated as excluded everywhere; their historical transactions are
    -- retained for audit, but the sync skips inserting new ones for them.
    ADD COLUMN IF NOT EXISTS deleted_at timestamptz;

-- Performant "included, not removed" filtering for summary / transactions.
CREATE INDEX IF NOT EXISTS idx_plaid_accounts_included
    ON public.plaid_accounts (business_id, included_in_bookkeeping)
    WHERE deleted_at IS NULL;

-- ─── RLS parity ──────────────────────────────────────────────────────
-- Writes flow through the backend service role (PATCH/DELETE endpoints),
-- which bypasses RLS. This owner-UPDATE policy is defense-in-depth +
-- enables future direct client toggles, mirroring plaid_tx_owner_update.
DROP POLICY IF EXISTS plaid_accounts_owner_update ON public.plaid_accounts;
CREATE POLICY plaid_accounts_owner_update ON public.plaid_accounts
    FOR UPDATE
    USING (
        EXISTS (
            SELECT 1 FROM public.businesses b
            WHERE b.id = plaid_accounts.business_id
              AND b.owner_id = auth.uid()
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.businesses b
            WHERE b.id = plaid_accounts.business_id
              AND b.owner_id = auth.uid()
        )
    );

-- ═════════════════════════════════════════════════════════════════════
-- Kevin's current-state cleanup (KMJ Creative Solutions)
-- ═════════════════════════════════════════════════════════════════════
-- KMJ has accounts linked that shouldn't be. Review the list, then use the
-- new per-account control in BUILD → Integrations → Bank Connection to
-- exclude or remove the unwanted ones (no manual SQL write needed).
--
--   SELECT account_id, name, official_name, type, subtype, mask,
--          last_balance, included_in_bookkeeping, deleted_at
--   FROM public.plaid_accounts
--   WHERE business_id = '12773842-3cc6-41a7-9094-b8606e3f7549'
--   ORDER BY name;
--
-- (If you prefer SQL: set included_in_bookkeeping = false for the rows you
--  don't want, or set deleted_at = now() to remove them entirely.)

-- ─── Verify ──────────────────────────────────────────────────────────
SELECT column_name, data_type, column_default, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'plaid_accounts'
  AND column_name IN ('included_in_bookkeeping', 'deleted_at')
ORDER BY column_name;
