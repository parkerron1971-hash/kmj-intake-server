-- ═════════════════════════════════════════════════════════════════════
-- Phase G — Chief Bookkeeping Intelligence
-- ═════════════════════════════════════════════════════════════════════
-- IMPORTANT DEVIATION FROM RULING 1 (surfaced to Kevin):
-- Ruling 1 said "extend the existing chief_actions.action_type CHECK
-- constraint". That constraint does NOT exist — chief_actions is an
-- append-only audit log with no CHECK, and the only action_type list
-- (VALID_ACTION_TYPES in chief_of_staff.py) is a documentation-only Python
-- set that is never enforced. Adding a CHECK to chief_actions would risk
-- breaking the 80+ existing handlers' audit writes (a regression).
--
-- So proposals get a DEDICATED table with their own proposal_type CHECK +
-- a real status lifecycle (the prompt's inline-call note explicitly allowed
-- "a separate chief_bookkeeping_proposals table"). Inbox routing reuses the
-- existing agent_queue 'proposal' action_type — NO constraint surgery.
--
-- Additive + idempotent. Clean rollback (DROP TABLE; nothing existing is
-- touched). Apply via Supabase Studio → SQL editor → Run.
-- ═════════════════════════════════════════════════════════════════════

-- ─── Chief bookkeeping proposals (pending → approved/rejected/inbox) ──
CREATE TABLE IF NOT EXISTS public.chief_bookkeeping_proposals (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id          uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    proposal_type        text NOT NULL CHECK (proposal_type IN
                            ('propose_match', 'propose_categorize', 'propose_exclude')),
    status               text NOT NULL DEFAULT 'pending' CHECK (status IN
                            ('pending', 'approved', 'rejected', 'sent_to_inbox')),
    -- Subject references (nullable; depends on type).
    plaid_transaction_id text,
    stripe_payout_id     text,
    -- Full proposed action payload (what approve executes).
    proposed             jsonb NOT NULL,
    confidence           numeric,
    reasoning            text,
    resolved_at          timestamptz,
    created_at           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chief_bk_proposals_business
    ON public.chief_bookkeeping_proposals (business_id, status, created_at DESC);

ALTER TABLE public.chief_bookkeeping_proposals ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS chief_bk_proposals_owner_read ON public.chief_bookkeeping_proposals;
CREATE POLICY chief_bk_proposals_owner_read ON public.chief_bookkeeping_proposals
    FOR SELECT
    USING (EXISTS (SELECT 1 FROM public.businesses b
                   WHERE b.id = chief_bookkeeping_proposals.business_id
                     AND b.owner_id = auth.uid()));

-- ─── Chief learning signals (capture practitioner overrides) ─────────
-- Schema exactly as ruled (Ruling 3).
CREATE TABLE IF NOT EXISTS public.chief_learning_signals (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id           uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    proposal_type         text NOT NULL CHECK (proposal_type IN
                             ('propose_match', 'propose_categorize', 'propose_exclude')),
    original_proposal     jsonb NOT NULL,
    practitioner_override  jsonb,
    override_reason       text,
    created_at            timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chief_learning_signals_business
    ON public.chief_learning_signals (business_id, created_at DESC);

ALTER TABLE public.chief_learning_signals ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS chief_learning_signals_owner_read ON public.chief_learning_signals;
CREATE POLICY chief_learning_signals_owner_read ON public.chief_learning_signals
    FOR SELECT
    USING (EXISTS (SELECT 1 FROM public.businesses b
                   WHERE b.id = chief_learning_signals.business_id
                     AND b.owner_id = auth.uid()));

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP TABLE IF EXISTS public.chief_learning_signals;
--   DROP TABLE IF EXISTS public.chief_bookkeeping_proposals;

-- ─── Verify ──────────────────────────────────────────────────────────
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('chief_bookkeeping_proposals', 'chief_learning_signals')
ORDER BY table_name;
