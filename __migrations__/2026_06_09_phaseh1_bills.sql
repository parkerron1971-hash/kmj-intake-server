-- ═════════════════════════════════════════════════════════════════════
-- Phase H.1 v1 — Accounts Payable (bills) + recurring bills
-- ═════════════════════════════════════════════════════════════════════
-- New `bills` table (Fnew-A ruling: NOT extending business_expenses). A bill
-- is a LIABILITY owed to a vendor — distinct from business_expenses (recorded
-- actuals). Vendor is a free-text string in v1 (fork F2 lean; promote to a
-- vendors entity in v1.5 when 1099 / per-vendor needs it). Recurrence mirrors
-- the invoices recurrence model. 1099 flag is prep for H.3b/F.1.
--
-- Additive + idempotent. Clean DROP-TABLE rollback. Apply via Supabase Studio.
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.bills (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id           uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    vendor_name           text NOT NULL,
    description           text,
    amount                numeric(12,2) NOT NULL CHECK (amount >= 0),
    -- Hybrid chart of accounts (F12): 5-bucket primary + subcategory line item.
    category              text NOT NULL DEFAULT 'operating'
                            CHECK (category IN ('tax','owner_pay','operating','savings','other')),
    subcategory           text,
    due_date              date,
    status                text NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('draft','pending','scheduled','paid','overdue','cancelled')),
    paid_at               timestamptz,
    paid_amount           numeric(12,2),
    paid_via              text,                     -- 'plaid' | 'manual' | free-text
    -- H.2 reconciliation will populate this (Plaid debit ↔ bill).
    reconciled_to_transaction_id text,
    -- Recurrence (mirrors invoices). Template has recurrence_index=0.
    is_recurring          boolean NOT NULL DEFAULT false,
    recurrence_frequency  text CHECK (recurrence_frequency IN
                            ('weekly','biweekly','monthly','quarterly','annually')),
    recurrence_start      date,
    recurrence_end_type   text DEFAULT 'never',     -- never | after_count | on_date
    recurrence_end_value  text,
    recurrence_index      integer NOT NULL DEFAULT 0,
    recurrence_parent_id  uuid,
    recurrence_paused     boolean NOT NULL DEFAULT false,
    -- 1099 prep (H.3b / F.1).
    is_1099_eligible      boolean NOT NULL DEFAULT false,
    notes                 text,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bills_business_status
    ON public.bills (business_id, status, due_date);
CREATE INDEX IF NOT EXISTS idx_bills_recurrence_parent
    ON public.bills (business_id, recurrence_parent_id);

-- ─── RLS: owner full CRUD (practitioner manages their own bills) ─────
ALTER TABLE public.bills ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS bills_owner_select ON public.bills;
CREATE POLICY bills_owner_select ON public.bills FOR SELECT
    USING (EXISTS (SELECT 1 FROM public.businesses b
                   WHERE b.id = bills.business_id AND b.owner_id = auth.uid()));

DROP POLICY IF EXISTS bills_owner_insert ON public.bills;
CREATE POLICY bills_owner_insert ON public.bills FOR INSERT
    WITH CHECK (EXISTS (SELECT 1 FROM public.businesses b
                        WHERE b.id = bills.business_id AND b.owner_id = auth.uid()));

DROP POLICY IF EXISTS bills_owner_update ON public.bills;
CREATE POLICY bills_owner_update ON public.bills FOR UPDATE
    USING (EXISTS (SELECT 1 FROM public.businesses b
                   WHERE b.id = bills.business_id AND b.owner_id = auth.uid()))
    WITH CHECK (EXISTS (SELECT 1 FROM public.businesses b
                        WHERE b.id = bills.business_id AND b.owner_id = auth.uid()));

DROP POLICY IF EXISTS bills_owner_delete ON public.bills;
CREATE POLICY bills_owner_delete ON public.bills FOR DELETE
    USING (EXISTS (SELECT 1 FROM public.businesses b
                   WHERE b.id = bills.business_id AND b.owner_id = auth.uid()));

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP TABLE IF EXISTS public.bills;

-- ─── Verify ──────────────────────────────────────────────────────────
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' AND table_name = 'bills';
