-- salon benchmark values.
--
-- OWNED BY THE SALON AGENT. One view per vertical exists for exactly
-- one reason: eight people cannot append UNION arms to one view without
-- colliding, and a merge conflict inside a SQL view is resolved by
-- guessing. Your arms live here and nowhere else.
--
-- Contract this view MUST honour, because `business_benchmark_values`
-- unions all seven of these and Postgres checks nothing for you:
--
--     column 1  business_id  uuid
--     column 2  key          text     -- must match a band key in
--                                     -- workspace_benchmarks/bands/salon.py
--     column 3  value        numeric  -- NULL or absent = "not measured"
--
-- A key with no arm here is NOT a bug. The panel renders its band with
-- an empty figure reading "not measured", which is the honest state --
-- and it is always better than a number computed from a column that
-- does not mean what the band says it means.
--
-- Idempotent. Safe to re-run.

BEGIN;

CREATE OR REPLACE VIEW public.business_benchmark_values_salon AS
    -- ── salon ────────────────────────────────────────────────────────
    -- Rebooking: of sessions completed in the last 90 days, the share
    -- whose contact has a LATER session already on the book. That is
    -- exactly what "left with the next appointment booked" means.
    SELECT
        s.business_id,
        'rebooking_rate'::text AS key,
        ROUND(100.0 * COUNT(*) FILTER (
            WHERE EXISTS (
                SELECT 1 FROM public.sessions n
                WHERE n.business_id = s.business_id
                  AND n.contact_id  = s.contact_id
                  AND n.scheduled_for > s.scheduled_for
                  AND n.status IN ('scheduled', 'completed')
            )
        ) / NULLIF(COUNT(*), 0), 1)::numeric AS value
    FROM public.sessions s
    WHERE s.contact_id IS NOT NULL
      AND s.status = 'completed'
      AND s.scheduled_for >= now() - interval '90 days'
      AND s.scheduled_for <  now()
    GROUP BY s.business_id

    UNION ALL

    -- New clients who came back: contacts first seen 30-365 days ago
    -- with more than one session. The window excludes the very recent,
    -- who have not had a fair chance to return yet.
    SELECT
        c.business_id,
        'new_client_return'::text,
        ROUND(100.0 * COUNT(*) FILTER (WHERE c.sessions > 1)
              / NULLIF(COUNT(*), 0), 1)::numeric
    FROM (
        SELECT ct.business_id, ct.id,
               (SELECT COUNT(*) FROM public.sessions s
                 WHERE s.business_id = ct.business_id
                   AND s.contact_id  = ct.id
                   AND s.status IN ('scheduled', 'completed')) AS sessions
        FROM public.contacts ct
        WHERE ct.created_at BETWEEN now() - interval '365 days'
                               AND now() - interval '30 days'
    ) c
    GROUP BY c.business_id
;

ALTER VIEW public.business_benchmark_values_salon SET (security_invoker = true);
GRANT SELECT ON public.business_benchmark_values_salon TO authenticated, service_role;

COMMIT;
