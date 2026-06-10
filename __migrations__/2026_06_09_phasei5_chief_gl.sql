-- ═════════════════════════════════════════════════════════════════════
-- Phase I.5 — Chief GL integration
-- ═════════════════════════════════════════════════════════════════════
-- Adds 'propose_journal_entry' + 'propose_account_reconciliation' to the
-- Phase G proposal_type CHECKs. Same dedicated-proposals architecture; no
-- chief_actions change. Idempotent. Apply via Supabase Studio.
-- ═════════════════════════════════════════════════════════════════════

ALTER TABLE public.chief_bookkeeping_proposals
    DROP CONSTRAINT IF EXISTS chief_bookkeeping_proposals_proposal_type_check;
ALTER TABLE public.chief_bookkeeping_proposals
    ADD CONSTRAINT chief_bookkeeping_proposals_proposal_type_check
    CHECK (proposal_type IN ('propose_match', 'propose_categorize', 'propose_exclude',
                             'propose_period_close', 'propose_journal_entry',
                             'propose_account_reconciliation'));

ALTER TABLE public.chief_learning_signals
    DROP CONSTRAINT IF EXISTS chief_learning_signals_proposal_type_check;
ALTER TABLE public.chief_learning_signals
    ADD CONSTRAINT chief_learning_signals_proposal_type_check
    CHECK (proposal_type IN ('propose_match', 'propose_categorize', 'propose_exclude',
                             'propose_period_close', 'propose_journal_entry',
                             'propose_account_reconciliation'));

-- ─── Rollback ────────────────────────────────────────────────────────
--   (restore the 4-value CHECK on both tables)

SELECT 'phase I.5 proposal types extended' AS status;
