-- ═════════════════════════════════════════════════════════════════════
-- Phase I.3 PR2 — soft-lock audit trail
-- ═════════════════════════════════════════════════════════════════════
-- Records every edit made to a row dated in a CLOSED period (R3 soft-lock:
-- allowed with a reason, never silent). Client-edited surfaces (invoices,
-- business_expenses) check + write via the frontend; backend-mediated
-- surfaces (bills, plaid_transactions) gate + write server-side. Both land
-- the same audit row with pre/post snapshots.
--
-- Additive/idempotent. Clean DROP rollback. Apply via Supabase Studio.
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.period_edit_overrides (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id           uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    accounting_period_id  uuid REFERENCES public.accounting_periods(id) ON DELETE SET NULL,
    source_type           text NOT NULL,   -- invoice | business_expense | bill | plaid_transaction | journal_entry
    source_id             text NOT NULL,
    override_reason       text NOT NULL,
    override_by           uuid,
    override_by_role      text,            -- owner | accountant
    override_at           timestamptz NOT NULL DEFAULT now(),
    pre_change_snapshot   jsonb,
    post_change_snapshot  jsonb
);

CREATE INDEX IF NOT EXISTS idx_period_overrides_business
    ON public.period_edit_overrides (business_id, override_at DESC);
CREATE INDEX IF NOT EXISTS idx_period_overrides_period
    ON public.period_edit_overrides (accounting_period_id);

ALTER TABLE public.period_edit_overrides ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS period_overrides_owner_read ON public.period_edit_overrides;
CREATE POLICY period_overrides_owner_read ON public.period_edit_overrides
    FOR SELECT USING (EXISTS (SELECT 1 FROM public.businesses b
                              WHERE b.id = period_edit_overrides.business_id
                                AND b.owner_id = auth.uid()));

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP TABLE IF EXISTS public.period_edit_overrides;

SELECT 'phase I.3 PR2 period_edit_overrides ready' AS status;
