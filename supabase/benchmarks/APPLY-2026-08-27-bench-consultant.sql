-- consultant benchmark values.
--
-- OWNED BY THE CONSULTANT AGENT. One view per vertical exists for exactly
-- one reason: eight people cannot append UNION arms to one view without
-- colliding, and a merge conflict inside a SQL view is resolved by
-- guessing. Your arms live here and nowhere else.
--
-- Contract this view MUST honour, because `business_benchmark_values`
-- unions all seven of these and Postgres checks nothing for you:
--
--     column 1  business_id  uuid
--     column 2  key          text     -- must match a band key in
--                                     -- workspace_benchmarks/bands/consultant.py
--     column 3  value        numeric  -- NULL or absent = "not measured"
--
-- A key with no arm here is NOT a bug. The panel renders its band with
-- an empty figure reading "not measured", which is the honest state --
-- and it is always better than a number computed from a column that
-- does not mean what the band says it means.
--
-- Idempotent. Safe to re-run.

BEGIN;

CREATE OR REPLACE VIEW public.business_benchmark_values_consultant AS
    -- ── consultant + coach ───────────────────────────────────────────
    -- The SAME RATIO as `utilization` above, emitted under a second key
    -- on purpose. Billable-over-recorded is one measurement, but the
    -- industry norm for it is not one number: a lawyer's benchmark is
    -- 38% average / 50% target, a consultant's is 70% / 78%. Feeding
    -- both keys from one arm is what lets the band -- the editorial
    -- half, in workspace_benchmarks.py -- decide which profession's
    -- expectations this business is held to.
    --
    -- That split IS the design. One number, two honest readings.
    SELECT
        te.business_id,
        'utilization_now'::text AS key,
        ROUND(100.0 * SUM(te.minutes) FILTER (WHERE te.billable IS TRUE)
              / NULLIF(SUM(te.minutes), 0), 1)::numeric AS value
    FROM public.time_entries te
    WHERE te.occurred_on >= (now() - interval '90 days')::date
    GROUP BY te.business_id
;

ALTER VIEW public.business_benchmark_values_consultant SET (security_invoker = true);
GRANT SELECT ON public.business_benchmark_values_consultant TO authenticated, service_role;

COMMIT;
