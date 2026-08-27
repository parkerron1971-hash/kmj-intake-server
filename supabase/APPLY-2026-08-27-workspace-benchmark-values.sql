-- APPLY-2026-08-27-workspace-benchmark-values.sql
--
-- The VALUE half of the benchmark panel. The band half — average,
-- target, floor, the plain-language reading and its citation — lives in
-- workspace_benchmarks.py on purpose: a band is an editorial claim this
-- product asserts to a practitioner who may act on it, so it belongs in
-- reviewed code rather than in rows anyone can edit into a false claim.
--
-- This view therefore returns only (business_id, key, value).
--
-- ── WHY THIS FILE WAS REWRITTEN ─────────────────────────────────────
--
-- The first cut was written against columns that do not exist. It read
-- `invoices.line_items`, `subtotal_cents`, `total_cents`,
-- `amount_paid_cents` and `amount_due_cents`; the live table has
-- `items`, `subtotal`, `tax_amount` and `total` — numeric, in DOLLARS —
-- and NO paid-amount column at all. `status = 'paid'` plus `paid_at` is
-- the entire record of payment. CREATE VIEW would have failed outright.
--
-- Two arms were worse than broken, because they would have SUCCEEDED
-- and always returned nothing: they filtered `contacts.status` on
-- 'first_time' and 'donor', and the check constraint on that column
-- allows only lead|active|inactive|churned|vip. A ministry would have
-- been shown a guest-return rate of zero forever.
--
-- The lesson, which docs/MIGRATIONS.md already states: the file set is
-- not a faithful record of prod. These columns were verified against
-- information_schema on 2026-08-26 before this file was written.
--
-- ── WHAT IS DELIBERATELY ABSENT ─────────────────────────────────────
--
-- A key with no arm has no value, and the panel renders its band with an
-- empty figure reading "not measured". That is the honest state and it
-- is why these are left out rather than approximated:
--
--   retail_attach          needs the shape of `invoices.items`, which is
--                          practitioner-defined and not guaranteed to
--                          carry a retail/service distinction
--   chair_utilization      needs bookable floor hours; `availability`
--                          stores a chair COUNT, not a staffed roster
--   first_time_return      needs a first-visit marker on contacts;
--   second_time_return     `status` has no such value and nothing else
--   third_time_stay        records a visit ordinal
--   donor_retention        needs donors distinguishable from contacts
--   giving_participation   needs a household denominator
--   trades                 no source models jobs, estimates or
--                          memberships as rows yet
--   proposal_win_rate      consultant/coach only; nothing models a
--   retainer_renewal       proposal or a retainer term as a row
--   utilization_projected  needs booked-forward commitments, which
--                          sessions does not distinguish from history
--
-- Adding any of them is adding a UNION arm; nothing else changes,
-- because the layout binds by key.
--
-- Idempotent. Safe to re-run.

BEGIN;

DROP VIEW IF EXISTS public.business_benchmark_values;

CREATE VIEW public.business_benchmark_values AS

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

    UNION ALL

    -- ── therapist ────────────────────────────────────────────────────
    -- Lower is better. The band carries that flag; this view does not
    -- need to know.
    SELECT
        s.business_id,
        'no_show_rate'::text,
        ROUND(100.0 * COUNT(*) FILTER (WHERE s.status IN ('no_show', 'cancelled'))
              / NULLIF(COUNT(*), 0), 1)::numeric
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

    UNION ALL

    -- ── law firm ─────────────────────────────────────────────────────
    -- Utilisation: the share of recorded time that is billable. Both
    -- halves come off time_entries, so the ratio is unit-free and does
    -- not care whether a rate was ever set.
    SELECT
        te.business_id,
        'utilization'::text,
        ROUND(100.0 * SUM(te.minutes) FILTER (WHERE te.billable IS TRUE)
              / NULLIF(SUM(te.minutes), 0), 1)::numeric
    FROM public.time_entries te
    WHERE te.occurred_on >= (now() - interval '180 days')::date
    GROUP BY te.business_id

    UNION ALL

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
        'utilization_now'::text,
        ROUND(100.0 * SUM(te.minutes) FILTER (WHERE te.billable IS TRUE)
              / NULLIF(SUM(te.minutes), 0), 1)::numeric
    FROM public.time_entries te
    WHERE te.occurred_on >= (now() - interval '90 days')::date
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
                 / NULLIF(SUM(i.total) FILTER (WHERE i.status = 'paid'), 0), 0) <= 365;


COMMENT ON VIEW public.business_benchmark_values IS
    'Per-tenant VALUES for the benchmark panel - one row per (business, '
    'key). The bands they are read against (average, target, floor, '
    'reading, source) live in workspace_benchmarks.py, because a band is '
    'an editorial claim with a citation and belongs in reviewed code. A '
    'key with no arm here has no value, and the panel renders it as "not '
    'measured" rather than guessing. Add a metric by adding a UNION arm; '
    'the layout binds by key.';

-- Inherits RLS from its base tables, so a business only ever sees its
-- own rows. Server code reads it with the service-role key, and the
-- app-layer owner check in workspace_composer_router does the gating.
ALTER VIEW public.business_benchmark_values SET (security_invoker = true);

GRANT SELECT ON public.business_benchmark_values TO authenticated, service_role;

COMMIT;
