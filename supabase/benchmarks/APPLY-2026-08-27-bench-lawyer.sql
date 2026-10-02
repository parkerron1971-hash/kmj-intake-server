-- lawyer benchmark values.
--
-- OWNED BY THE LAWYER AGENT. One view per vertical exists for exactly
-- one reason: eight people cannot append UNION arms to one view without
-- colliding, and a merge conflict inside a SQL view is resolved by
-- guessing. Your arms live here and nowhere else.
--
-- Contract this view MUST honour, because `business_benchmark_values`
-- unions all seven of these and Postgres checks nothing for you:
--
--     column 1  business_id  uuid
--     column 2  key          text     -- must match a band key in
--                                     -- workspace_benchmarks/bands/lawyer.py
--     column 3  value        numeric  -- NULL or absent = "not measured"
--
-- A key with no arm here is NOT a bug. The panel renders its band with
-- an empty figure reading "not measured", which is the honest state --
-- and it is always better than a number computed from a column that
-- does not mean what the band says it means.
--
-- Idempotent. Safe to re-run.

BEGIN;

CREATE OR REPLACE VIEW public.business_benchmark_values_lawyer AS
    -- ── law firm ─────────────────────────────────────────────────────
    -- Utilisation: the share of recorded time that is billable. Both
    -- halves come off time_entries, so the ratio is unit-free and does
    -- not care whether a rate was ever set.
    SELECT
        te.business_id,
        'utilization'::text AS key,
        ROUND(100.0 * SUM(te.minutes) FILTER (WHERE te.billable IS TRUE)
              / NULLIF(SUM(te.minutes), 0), 1)::numeric AS value
    FROM public.time_entries te
    WHERE te.occurred_on >= (now() - interval '180 days')::date
    GROUP BY te.business_id

    UNION ALL

    -- Realisation: of the billable value recorded, the share NOT written
    -- off. Nothing stores an invoiced amount per time entry, so a
    -- billed-vs-recorded ratio is not available -- but write-offs are
    -- exactly the leak realisation is meant to expose, and they are
    -- recorded, so this measures the real thing rather than a proxy.
    SELECT
        te.business_id,
        'realization'::text,
        ROUND(100.0 * SUM((te.minutes / 60.0) * te.rate)
                      FILTER (WHERE te.status <> 'written_off')
              / NULLIF(SUM((te.minutes / 60.0) * te.rate), 0), 1)::numeric
    FROM public.time_entries te
    WHERE te.billable IS TRUE
      AND te.rate IS NOT NULL
      AND te.occurred_on >= (now() - interval '180 days')::date
    GROUP BY te.business_id

    UNION ALL

    -- Collection: banked against billed. An invoice counts as billed
    -- once it has left the building, so drafts and cancellations are out
    -- of both halves.
    SELECT
        i.business_id,
        'collection'::text,
        ROUND(100.0 * SUM(i.total) FILTER (WHERE i.status = 'paid')
              / NULLIF(SUM(i.total), 0), 1)::numeric
    FROM public.invoices i
    WHERE i.status IN ('sent', 'viewed', 'paid', 'overdue')
      AND i.created_at >= now() - interval '180 days'
    GROUP BY i.business_id

    UNION ALL

    -- Lockup, in days of collected revenue: how long the firm's own
    -- money sits with clients. Lower is better; the band says so, not
    -- this view.
    --
    -- GUARDED. The ratio explodes when almost nothing has been
    -- collected: one real business here bills steadily, has collected
    -- 1.9% of it, and the raw figure came out at 19,345 days -- fifty-
    -- three years of lockup. That is arithmetically true and useless on
    -- a screen; it reads as a broken number, and the practitioner stops
    -- trusting the whole strip.
    --
    -- Past a year the quantity has stopped being a lockup measurement
    -- and become a statement that the business is not collecting, which
    -- the `collection` band already says, in plain language, with a
    -- citation. So beyond that this reports NOTHING and the panel says
    -- "not measured" -- one honest silence instead of two numbers where
    -- the louder one is noise.
    SELECT
        i.business_id,
        'collection_lockup'::text,
        ROUND(365.0 * SUM(i.total) FILTER (WHERE i.status IN ('sent', 'viewed', 'overdue'))
              / NULLIF(SUM(i.total) FILTER (WHERE i.status = 'paid'), 0), 0)::numeric
    FROM public.invoices i
    WHERE i.created_at >= now() - interval '365 days'
    GROUP BY i.business_id
    HAVING ROUND(365.0 * SUM(i.total) FILTER (WHERE i.status IN ('sent', 'viewed', 'overdue'))
                 / NULLIF(SUM(i.total) FILTER (WHERE i.status = 'paid'), 0), 0) <= 365
;

ALTER VIEW public.business_benchmark_values_lawyer SET (security_invoker = true);
GRANT SELECT ON public.business_benchmark_values_lawyer TO authenticated, service_role;

COMMIT;
