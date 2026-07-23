-- APPLY-2026-07-23-error-sweep.sql
-- Fixes the Mission Control server-error burst (26 entries / 12h).
-- Three schema-drift objects the code queries but the DB never got.
-- Safe to run repeatedly (IF NOT EXISTS everywhere).
--
-- ALSO RUN (if not already applied): APPLY-2026-07-10-chief-scheduled-actions.sql
--   → the scheduler sweep errors EVERY MINUTE until that table exists.

-- 1) api_usage.created_at — launch_access + spend_guard filter on it
--    ("column api_usage.created_at does not exist").
ALTER TABLE public.api_usage
  ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS api_usage_created_at_idx
  ON public.api_usage (created_at DESC);

-- 2) module_entries booking fields — availability_engine reads both
--    ("column module_entries.appointment_at does not exist").
ALTER TABLE public.module_entries
  ADD COLUMN IF NOT EXISTS appointment_at timestamptz;
ALTER TABLE public.module_entries
  ADD COLUMN IF NOT EXISTS duration_min_at_booking integer;
CREATE INDEX IF NOT EXISTS module_entries_appointment_at_idx
  ON public.module_entries (appointment_at)
  WHERE appointment_at IS NOT NULL;
