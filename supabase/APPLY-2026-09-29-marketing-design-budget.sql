-- The Monday plan's pictures and the money they may spend (marketing_design.py).
--
-- design_budget_usd: the monthly amount the plan may spend on generated
-- pictures (the week's hero image). Flyers are built by code and cost
-- nothing, so they never draw on it. Owner-only through
-- PUT /platform/marketing/engine/budget; Chief has no action that changes it.
--
-- platform_marketing_runs.design: what a run made — flyer asset per slot,
-- the hero image's artwork id (whose recorded provider cost is the spend),
-- and a budget request when the month ran out.
-- Apply after APPLY-2026-09-28-marketing-engine.sql.
BEGIN;
ALTER TABLE public.platform_marketing_config
  ADD COLUMN IF NOT EXISTS design_budget_usd numeric(8,2) NOT NULL DEFAULT 10
  CHECK (design_budget_usd >= 0 AND design_budget_usd <= 500);
ALTER TABLE public.platform_marketing_runs ADD COLUMN IF NOT EXISTS design jsonb;
COMMIT;
