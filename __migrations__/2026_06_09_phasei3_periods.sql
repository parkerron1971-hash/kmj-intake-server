-- ═════════════════════════════════════════════════════════════════════
-- Phase I.3 (PR1) — Period closing
-- ═════════════════════════════════════════════════════════════════════
-- Reshapes the (empty, never-written) accounting_periods table from I.1a to
-- the I.3 spec: period_type, reopen audit, closing-journal-entry link, and a
-- 'reopened' status. Monthly/quarterly close = status flip + audit; annual
-- close also posts a closing journal entry (Revenue/Expense → Retained
-- Earnings). Soft-lock overrides (period_edit_overrides) + the accountant
-- collaborator role ship in the next I.3 PRs.
--
-- Additive/idempotent: DROP+CREATE is safe because accounting_periods has
-- never been written (I.1/I.2 don't create period rows). Apply via Supabase.
-- ═════════════════════════════════════════════════════════════════════

DROP TABLE IF EXISTS public.accounting_periods CASCADE;

CREATE TABLE public.accounting_periods (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id              uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    period_type              text NOT NULL CHECK (period_type IN ('month', 'quarter', 'year')),
    period_start             date NOT NULL,
    period_end               date NOT NULL,
    status                   text NOT NULL DEFAULT 'open'
                               CHECK (status IN ('open', 'closed', 'reopened')),
    closed_at                timestamptz,
    closed_by                uuid,
    closed_via               text CHECK (closed_via IN ('owner', 'accountant', 'chief_auto_close')),
    closing_journal_entry_id uuid,            -- year-end only
    reopened_at              timestamptz,
    reopened_by              uuid,
    reopened_reason          text,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    UNIQUE (business_id, period_type, period_start, period_end)
);

CREATE INDEX IF NOT EXISTS idx_acct_periods_business
    ON public.accounting_periods (business_id, period_type, period_start);

ALTER TABLE public.accounting_periods ENABLE ROW LEVEL SECURITY;

-- v1: owner read (writes flow through the backend service role). The
-- accountant-role read/write policy lands with the business_collaborators PR.
DROP POLICY IF EXISTS accounting_periods_owner_read ON public.accounting_periods;
CREATE POLICY accounting_periods_owner_read ON public.accounting_periods
    FOR SELECT USING (EXISTS (SELECT 1 FROM public.businesses b
                              WHERE b.id = accounting_periods.business_id
                                AND b.owner_id = auth.uid()));

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP TABLE IF EXISTS public.accounting_periods CASCADE;

SELECT 'phase I.3 PR1 accounting_periods ready' AS status;
