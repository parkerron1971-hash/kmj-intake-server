-- ═════════════════════════════════════════════════════════════════════
-- Phase I.9 — business_budgets (Budget vs Actual)
-- ═════════════════════════════════════════════════════════════════════
-- One row per (business, year, month, category). Categories mirror the
-- Profit-First buckets + revenue: revenue / operating / owner_pay / tax /
-- savings / other. Backend writes via service role; owners read+write
-- their own via RLS (mirrors the contractors policy pattern).
--
-- Additive + idempotent. Clean rollback. Apply via Supabase Studio.
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.business_budgets (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  year        int  NOT NULL,
  month       int  NOT NULL CHECK (month BETWEEN 1 AND 12),
  category    text NOT NULL CHECK (category IN
                ('revenue', 'operating', 'owner_pay', 'tax', 'savings', 'other')),
  amount      numeric(14,2) NOT NULL DEFAULT 0,
  created_at  timestamptz DEFAULT now(),
  updated_at  timestamptz DEFAULT now(),
  UNIQUE (business_id, year, month, category)
);

CREATE INDEX IF NOT EXISTS idx_business_budgets_biz_ym
  ON public.business_budgets (business_id, year, month);

ALTER TABLE public.business_budgets ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS business_budgets_owner_all ON public.business_budgets;
CREATE POLICY business_budgets_owner_all ON public.business_budgets
    FOR ALL
    USING (EXISTS (SELECT 1 FROM public.businesses b
                   WHERE b.id = business_budgets.business_id AND b.owner_id = auth.uid()))
    WITH CHECK (EXISTS (SELECT 1 FROM public.businesses b
                        WHERE b.id = business_budgets.business_id AND b.owner_id = auth.uid()));

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP TABLE IF EXISTS public.business_budgets;

SELECT 'phase I.9 budgets ready' AS status;
