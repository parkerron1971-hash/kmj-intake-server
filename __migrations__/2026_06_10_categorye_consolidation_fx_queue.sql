-- ═════════════════════════════════════════════════════════════════════
-- Category E — entity groups + FX scaffold + queue claim columns
-- ═════════════════════════════════════════════════════════════════════
-- 1. entity_groups + businesses.entity_group_id — multi-entity roll-up
--    (consolidated P&L / Balance Sheet; NO eliminations v1 — surfaced).
-- 2. fx_rates — manual-entry FX scaffold (ledger is USD-only today).
-- 3. gl_sync_queue.claimed_by/claimed_at — multi-replica row claims
--    (atomic conditional PATCH; stale claims >5min reclaimable).
--
-- Additive + idempotent. Clean rollback. Apply via Supabase Studio.
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.entity_groups (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id    uuid NOT NULL,
  name        text NOT NULL,
  created_at  timestamptz DEFAULT now()
);

ALTER TABLE public.entity_groups ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS entity_groups_owner_all ON public.entity_groups;
CREATE POLICY entity_groups_owner_all ON public.entity_groups
  FOR ALL USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());

ALTER TABLE public.businesses
  ADD COLUMN IF NOT EXISTS entity_group_id uuid REFERENCES public.entity_groups(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS public.fx_rates (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id       uuid NOT NULL,
  base_currency  text NOT NULL,
  quote_currency text NOT NULL DEFAULT 'USD',
  rate           numeric(18,8) NOT NULL,
  as_of_date     date NOT NULL,
  source         text NOT NULL DEFAULT 'manual',
  created_at     timestamptz DEFAULT now(),
  UNIQUE (owner_id, base_currency, quote_currency, as_of_date)
);

ALTER TABLE public.fx_rates ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS fx_rates_owner_all ON public.fx_rates;
CREATE POLICY fx_rates_owner_all ON public.fx_rates
  FOR ALL USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());

ALTER TABLE public.gl_sync_queue
  ADD COLUMN IF NOT EXISTS claimed_by text,
  ADD COLUMN IF NOT EXISTS claimed_at timestamptz;

CREATE INDEX IF NOT EXISTS idx_gl_sync_queue_claim
  ON public.gl_sync_queue (claimed_at) WHERE processed_at IS NULL;

-- ─── Rollback ────────────────────────────────────────────────────────
--   ALTER TABLE public.gl_sync_queue DROP COLUMN IF EXISTS claimed_by,
--     DROP COLUMN IF EXISTS claimed_at;
--   ALTER TABLE public.businesses DROP COLUMN IF EXISTS entity_group_id;
--   DROP TABLE IF EXISTS public.fx_rates;
--   DROP TABLE IF EXISTS public.entity_groups;

SELECT 'category E consolidation + fx + queue claims ready' AS status;
