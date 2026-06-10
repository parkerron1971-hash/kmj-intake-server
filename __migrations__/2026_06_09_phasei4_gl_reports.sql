-- ═════════════════════════════════════════════════════════════════════
-- Phase I.4 — Reports rebuilt on the GL as authoritative
-- ═════════════════════════════════════════════════════════════════════
-- Ledger lines gain subcategory + vendor so P&L line items (and the I.8
-- Expense/Revenue drill-downs) come straight from the GL with no source-
-- table joins. The plaid UPDATE enqueue-trigger also fires on
-- business_subcategory so a subcategory edit re-posts the GL line.
--
-- Additive + idempotent. Existing KMJ ledger rows will have NULL
-- subcategory/vendor — one Reverse Backfill + Run Backfill from the Admin
-- tab repopulates them (both are one-click, idempotent, and reversible).
-- ═════════════════════════════════════════════════════════════════════

ALTER TABLE public.ledger_entries
    ADD COLUMN IF NOT EXISTS subcategory text,
    ADD COLUMN IF NOT EXISTS vendor text;

-- Re-create the plaid UPDATE trigger with business_subcategory included.
DROP TRIGGER IF EXISTS gl_enq_plaid_upd ON public.plaid_transactions;
CREATE TRIGGER gl_enq_plaid_upd AFTER UPDATE ON public.plaid_transactions
    FOR EACH ROW WHEN (
        OLD.reconciliation_status IS DISTINCT FROM NEW.reconciliation_status
        OR OLD.business_category IS DISTINCT FROM NEW.business_category
        OR OLD.business_subcategory IS DISTINCT FROM NEW.business_subcategory
        OR OLD.excluded_from_books IS DISTINCT FROM NEW.excluded_from_books
        OR OLD.amount IS DISTINCT FROM NEW.amount
    ) EXECUTE FUNCTION public.gl_enqueue();

-- ─── Rollback ────────────────────────────────────────────────────────
--   ALTER TABLE public.ledger_entries
--     DROP COLUMN IF EXISTS subcategory, DROP COLUMN IF EXISTS vendor;
--   (re-create gl_enq_plaid_upd without the business_subcategory clause)

SELECT 'phase I.4 ledger line dimensions ready' AS status;
