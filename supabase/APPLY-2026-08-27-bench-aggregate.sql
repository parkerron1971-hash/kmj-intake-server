-- The benchmark values every vertical's panel reads.
--
-- SHARED. Do not edit this to add a metric -- add a UNION arm to your own
-- `supabase/benchmarks/APPLY-*-bench-<vertical>.sql` instead. This file
-- changes only when a whole VERTICAL is added or removed, which is a
-- product decision rather than a metric one.
--
-- The bands these values are read against live in
-- workspace_benchmarks/bands/<vertical>.py -- in reviewed code, because a
-- band is an editorial claim with a citation attached and rows can be
-- edited into a false claim with no trace.
--
-- Apply the seven per-vertical files FIRST; this depends on all of them.
-- Idempotent. Safe to re-run.

BEGIN;

DROP VIEW IF EXISTS public.business_benchmark_values;

CREATE VIEW public.business_benchmark_values AS
    SELECT business_id, key, value FROM public.business_benchmark_values_salon
    UNION ALL
    SELECT business_id, key, value FROM public.business_benchmark_values_trades
    UNION ALL
    SELECT business_id, key, value FROM public.business_benchmark_values_therapist
    UNION ALL
    SELECT business_id, key, value FROM public.business_benchmark_values_ministry
    UNION ALL
    SELECT business_id, key, value FROM public.business_benchmark_values_consultant
    UNION ALL
    SELECT business_id, key, value FROM public.business_benchmark_values_nonprofit
    UNION ALL
    SELECT business_id, key, value FROM public.business_benchmark_values_lawyer;

COMMENT ON VIEW public.business_benchmark_values IS
    'Per-tenant benchmark VALUES, unioned from one view per vertical so '
    'that adding a metric touches exactly one file. Bands live in '
    'workspace_benchmarks/bands/<vertical>.py. A key with no arm has no '
    'value and the panel renders it as "not measured".';

ALTER VIEW public.business_benchmark_values SET (security_invoker = true);
GRANT SELECT ON public.business_benchmark_values TO authenticated, service_role;

COMMIT;
