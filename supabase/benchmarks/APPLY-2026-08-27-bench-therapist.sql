-- therapist benchmark values.
--
-- OWNED BY THE THERAPIST AGENT. One view per vertical exists for exactly
-- one reason: eight people cannot append UNION arms to one view without
-- colliding, and a merge conflict inside a SQL view is resolved by
-- guessing. Your arms live here and nowhere else.
--
-- Contract this view MUST honour, because `business_benchmark_values`
-- unions all seven of these and Postgres checks nothing for you:
--
--     column 1  business_id  uuid
--     column 2  key          text     -- must match a band key in
--                                     -- workspace_benchmarks/bands/therapist.py
--     column 3  value        numeric  -- NULL or absent = "not measured"
--
-- A key with no arm here is NOT a bug. The panel renders its band with
-- an empty figure reading "not measured", which is the honest state --
-- and it is always better than a number computed from a column that
-- does not mean what the band says it means.
--
-- Idempotent. Safe to re-run.

BEGIN;

CREATE OR REPLACE VIEW public.business_benchmark_values_therapist AS
    -- ── therapist ────────────────────────────────────────────────────
    -- Lower is better. The band carries that flag; this view does not
    -- need to know.
    SELECT
        s.business_id,
        'no_show_rate'::text AS key,
        ROUND(100.0 * COUNT(*) FILTER (WHERE s.status IN ('no_show', 'cancelled'))
              / NULLIF(COUNT(*), 0), 1)::numeric AS value
    FROM public.sessions s
    WHERE s.scheduled_for BETWEEN now() - interval '90 days' AND now()
    GROUP BY s.business_id

    UNION ALL

    -- Clients who reached eight sessions or more. Counted over active
    -- contacts only, so a practice is not marked down for people who
    -- finished well and closed.
    SELECT
        c.business_id,
        'client_retention'::text,
        ROUND(100.0 * COUNT(*) FILTER (WHERE c.sessions >= 8)
              / NULLIF(COUNT(*), 0), 1)::numeric
    FROM (
        SELECT ct.business_id, ct.id,
               (SELECT COUNT(*) FROM public.sessions s
                 WHERE s.business_id = ct.business_id
                   AND s.contact_id  = ct.id
                   AND s.status = 'completed') AS sessions
        FROM public.contacts ct
        WHERE ct.status IN ('active', 'vip')
    ) c
    GROUP BY c.business_id
;

ALTER VIEW public.business_benchmark_values_therapist SET (security_invoker = true);
GRANT SELECT ON public.business_benchmark_values_therapist TO authenticated, service_role;

COMMIT;
