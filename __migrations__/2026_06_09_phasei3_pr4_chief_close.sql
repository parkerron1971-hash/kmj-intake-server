-- ═════════════════════════════════════════════════════════════════════
-- Phase I.3 PR4 — Chief proposes period close
-- ═════════════════════════════════════════════════════════════════════
-- Adds 'propose_period_close' to the Phase G proposal_type CHECKs (extends
-- the existing dedicated proposals architecture — no chief_actions change).
-- Idempotent. Apply via Supabase Studio.
-- ═════════════════════════════════════════════════════════════════════

ALTER TABLE public.chief_bookkeeping_proposals
    DROP CONSTRAINT IF EXISTS chief_bookkeeping_proposals_proposal_type_check;
ALTER TABLE public.chief_bookkeeping_proposals
    ADD CONSTRAINT chief_bookkeeping_proposals_proposal_type_check
    CHECK (proposal_type IN ('propose_match', 'propose_categorize',
                             'propose_exclude', 'propose_period_close'));

ALTER TABLE public.chief_learning_signals
    DROP CONSTRAINT IF EXISTS chief_learning_signals_proposal_type_check;
ALTER TABLE public.chief_learning_signals
    ADD CONSTRAINT chief_learning_signals_proposal_type_check
    CHECK (proposal_type IN ('propose_match', 'propose_categorize',
                             'propose_exclude', 'propose_period_close'));

-- ─── Rollback ────────────────────────────────────────────────────────
--   (restore the 3-value CHECK on both tables)

SELECT 'phase I.3 PR4 proposal_type extended' AS status;
