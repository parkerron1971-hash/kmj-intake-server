-- ═════════════════════════════════════════════════════════════════════
-- Phase F.2 v1.5 — Dedicated Transactions panel
-- ═════════════════════════════════════════════════════════════════════
-- Adds the per-transaction "exclude from books" flag (for personal spend
-- that lands in a business account) + a free-text notes field for
-- practitioner annotations. Additive + idempotent. Apply via Supabase
-- Studio → SQL editor → Run.
-- ═════════════════════════════════════════════════════════════════════

ALTER TABLE public.plaid_transactions
    -- Excluded transactions stay visible in the Transactions panel (dimmed
    -- + "Excluded" pill) but drop out of Cash Flow KPIs/buckets, the Tax
    -- Set-Aside math, Needs-Review, and reconciliation. Reversible.
    ADD COLUMN IF NOT EXISTS excluded_from_books boolean NOT NULL DEFAULT false,
    -- Practitioner memo, distinct from practitioner_notes (which the
    -- categorize drawer already writes). notes is the panel's annotation
    -- field; practitioner_notes is retained for back-compat.
    ADD COLUMN IF NOT EXISTS notes text;

-- Index strategy (Claude Code's call): the dominant Transactions-panel
-- query is "this business, not-excluded, newest first", with optional
-- date-range / account / bucket refinements layered on. A composite on
-- (business_id, excluded_from_books, date DESC) serves both the default
-- (excluded_from_books = false) and the "show excluded" toggle without a
-- partial predicate, and supports the date-desc ordering directly. The
-- existing idx_plaid_tx_account covers single-account drilldowns.
CREATE INDEX IF NOT EXISTS idx_plaid_tx_books
    ON public.plaid_transactions (business_id, excluded_from_books, date DESC);

-- ─── Verify ──────────────────────────────────────────────────────────
SELECT column_name, data_type, column_default, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'plaid_transactions'
  AND column_name IN ('excluded_from_books', 'notes')
ORDER BY column_name;

-- Sample EXPLAIN to confirm the index is chosen for the default query
-- (run manually in Kevin's env — DB not reachable from the build host):
--   EXPLAIN ANALYZE
--   SELECT * FROM public.plaid_transactions
--   WHERE business_id = '12773842-3cc6-41a7-9094-b8606e3f7549'
--     AND excluded_from_books = false
--   ORDER BY date DESC
--   LIMIT 50;
