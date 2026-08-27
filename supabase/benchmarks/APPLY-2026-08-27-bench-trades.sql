-- trades benchmark values.
--
-- OWNED BY THE TRADES AGENT. One view per vertical exists for exactly
-- one reason: eight people cannot append UNION arms to one view without
-- colliding, and a merge conflict inside a SQL view is resolved by
-- guessing. Your arms live here and nowhere else.
--
-- Contract this view MUST honour, because `business_benchmark_values`
-- unions all seven of these and Postgres checks nothing for you:
--
--     column 1  business_id  uuid
--     column 2  key          text     -- must match a band key in
--                                     -- workspace_benchmarks/bands/trades.py
--     column 3  value        numeric  -- NULL or absent = "not measured"
--
-- A key with no arm here is NOT a bug. The panel renders its band with
-- an empty figure reading "not measured", which is the honest state --
-- and it is always better than a number computed from a column that
-- does not mean what the band says it means.
--
-- Idempotent. Safe to re-run.

BEGIN;

CREATE OR REPLACE VIEW public.business_benchmark_values_trades AS
    -- Nothing is computable for this vertical yet, and saying so in SQL
    -- is better than leaving the view out: the aggregate below unions a
    -- fixed list of seven, so this must exist and must have the right
    -- shape. It returns no rows.
    SELECT
        b.id          AS business_id,
        NULL::text    AS key,
        NULL::numeric AS value
    FROM public.businesses b
    WHERE false
;

ALTER VIEW public.business_benchmark_values_trades SET (security_invoker = true);
GRANT SELECT ON public.business_benchmark_values_trades TO authenticated, service_role;

COMMIT;
