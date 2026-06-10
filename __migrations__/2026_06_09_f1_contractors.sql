-- ═════════════════════════════════════════════════════════════════════
-- Phase F.1 v1 — Stripe outbound contractor payments
-- ═════════════════════════════════════════════════════════════════════
-- contractors: standalone table (ruled — NOT an extension of contacts).
--   Stripe Express accounts (Stripe owns identity + W-9 + 1099 delivery).
-- outbound_transfers: one row per Stripe Transfer to a contractor; each
--   paid transfer auto-creates a PAID AP bill (is_1099_eligible=true,
--   contractor_id linked) so the GL books Dr Expense/Cr AP + Dr AP/Cr Cash
--   through the existing bills pipeline (F15/F5 ruling).
--
-- Additive + idempotent. Clean DROP rollback. Apply via Supabase Studio.
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.contractors (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id         uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    name                text NOT NULL,
    email               text,
    stripe_account_id   text,             -- acct_… (Express; null until onboarding starts)
    onboarding_status   text NOT NULL DEFAULT 'invited'
                          CHECK (onboarding_status IN ('invited', 'pending', 'active', 'restricted')),
    is_1099_eligible    boolean NOT NULL DEFAULT true,
    default_category    text NOT NULL DEFAULT 'operating'
                          CHECK (default_category IN ('tax','owner_pay','operating','savings','other')),
    notes               text,
    invited_at          timestamptz NOT NULL DEFAULT now(),
    onboarded_at        timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_contractors_business
    ON public.contractors (business_id, onboarding_status);

CREATE TABLE IF NOT EXISTS public.outbound_transfers (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id         uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    contractor_id       uuid REFERENCES public.contractors(id) ON DELETE SET NULL,
    stripe_transfer_id  text,
    amount              numeric(12,2) NOT NULL CHECK (amount > 0),
    currency            text NOT NULL DEFAULT 'USD',
    status              text NOT NULL DEFAULT 'created'
                          CHECK (status IN ('created', 'paid', 'failed', 'reversed')),
    description         text,
    bill_id             uuid,             -- the auto-created AP bill
    created_at          timestamptz NOT NULL DEFAULT now(),
    paid_at             timestamptz,
    failed_at           timestamptz,
    failure_message     text
);
CREATE INDEX IF NOT EXISTS idx_outbound_transfers_business
    ON public.outbound_transfers (business_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_outbound_transfers_stripe
    ON public.outbound_transfers (stripe_transfer_id)
    WHERE stripe_transfer_id IS NOT NULL;

-- bills: link to the paying contractor (1099 aggregation joins through this).
ALTER TABLE public.bills
    ADD COLUMN IF NOT EXISTS contractor_id uuid REFERENCES public.contractors(id) ON DELETE SET NULL;

-- ─── RLS: owner read (writes via backend service role) + owner CRUD on contractors ─
ALTER TABLE public.contractors ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.outbound_transfers ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS contractors_owner_all ON public.contractors;
CREATE POLICY contractors_owner_all ON public.contractors
    FOR ALL
    USING (EXISTS (SELECT 1 FROM public.businesses b
                   WHERE b.id = contractors.business_id AND b.owner_id = auth.uid()))
    WITH CHECK (EXISTS (SELECT 1 FROM public.businesses b
                        WHERE b.id = contractors.business_id AND b.owner_id = auth.uid()));

DROP POLICY IF EXISTS outbound_transfers_owner_read ON public.outbound_transfers;
CREATE POLICY outbound_transfers_owner_read ON public.outbound_transfers
    FOR SELECT
    USING (EXISTS (SELECT 1 FROM public.businesses b
                   WHERE b.id = outbound_transfers.business_id AND b.owner_id = auth.uid()));

-- ─── Rollback ────────────────────────────────────────────────────────
--   ALTER TABLE public.bills DROP COLUMN IF EXISTS contractor_id;
--   DROP TABLE IF EXISTS public.outbound_transfers;
--   DROP TABLE IF EXISTS public.contractors;

SELECT 'phase F.1 contractors + outbound_transfers ready' AS status;
