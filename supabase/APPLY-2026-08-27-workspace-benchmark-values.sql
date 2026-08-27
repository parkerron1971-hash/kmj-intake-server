-- APPLY-2026-08-27-workspace-benchmark-values.sql
--
-- The VALUE half of the benchmark panel. The band half — average,
-- target, floor, the plain-language reading and its citation — lives in
-- workspace_benchmarks.py on purpose: a band is an editorial claim this
-- product asserts to a practitioner who may act on it, so it belongs in
-- reviewed code rather than in rows anyone can edit into a false claim.
--
-- This view therefore returns only (business_id, key, value). Every
-- arm computes one key from tables that already exist.
--
-- A key with no arm here simply has no value yet: the panel renders the
-- band with an empty figure, which reads as "not measured" and is the
-- honest state. Adding a metric is adding a UNION arm — nothing else
-- changes, because the layout binds by key.
--
-- Supersedes the `business_benchmarks` relation named in the previous
-- migration's field catalog, which was never created. Idempotent.

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
                  AND n.contact_id = s.contact_id
                  AND n.scheduled_for > s.scheduled_for
            )
        ) / NULLIF(COUNT(*), 0), 1)::numeric AS value
    FROM public.sessions s
    WHERE s.contact_id IS NOT NULL
      AND s.scheduled_for >= now() - interval '90 days'
      AND s.scheduled_for < now()
    GROUP BY s.business_id

    UNION ALL

    -- New clients who come back: contacts first seen 30-365 days ago
    -- who have more than one session. The window excludes the very
    -- recent, who have not had a fair chance to return yet.
    SELECT
        c.business_id,
        'new_client_return'::text,
        ROUND(100.0 * COUNT(*) FILTER (WHERE c.sessions > 1)
              / NULLIF(COUNT(*), 0), 1)::numeric
    FROM (
        SELECT ct.business_id, ct.id,
               (SELECT COUNT(*) FROM public.sessions s
                 WHERE s.business_id = ct.business_id AND s.contact_id = ct.id) AS sessions
        FROM public.contacts ct
        WHERE ct.created_at BETWEEN now() - interval '365 days'
                               AND now() - interval '30 days'
    ) c
    GROUP BY c.business_id

    UNION ALL

    -- Retail attach: retail revenue as a share of service revenue.
    -- Both sides come off invoice line items, so a business that does
    -- not itemise simply gets no row.
    SELECT
        i.business_id,
        'retail_attach'::text,
        ROUND(100.0 * SUM(CASE WHEN li ->> 'kind' = 'retail'
                               THEN (li ->> 'unit_amount_cents')::numeric ELSE 0 END)
              / NULLIF(SUM(CASE WHEN COALESCE(li ->> 'kind', 'service') <> 'retail'
                                THEN (li ->> 'unit_amount_cents')::numeric ELSE 0 END), 0),
              1)::numeric
    FROM public.invoices i
    CROSS JOIN LATERAL jsonb_array_elements(i.line_items) AS li
    WHERE i.status = 'paid'
      AND i.created_at >= now() - interval '90 days'
      AND jsonb_typeof(i.line_items) = 'array'
    GROUP BY i.business_id

    UNION ALL

    -- ── therapist ────────────────────────────────────────────────────
    -- Lower is better. Cancelled and no-show against everything booked
    -- in the window.
    SELECT
        s.business_id,
        'no_show_rate'::text,
        ROUND(100.0 * COUNT(*) FILTER (WHERE s.status IN ('no_show', 'cancelled'))
              / NULLIF(COUNT(*), 0), 1)::numeric
    FROM public.sessions s
    WHERE s.scheduled_for BETWEEN now() - interval '90 days' AND now()
    GROUP BY s.business_id

    UNION ALL

    SELECT
        c.business_id,
        'client_retention'::text,
        ROUND(100.0 * COUNT(*) FILTER (WHERE c.sessions >= 8)
              / NULLIF(COUNT(*), 0), 1)::numeric
    FROM (
        SELECT ct.business_id, ct.id,
               (SELECT COUNT(*) FROM public.sessions s
                 WHERE s.business_id = ct.business_id AND s.contact_id = ct.id) AS sessions
        FROM public.contacts ct
        WHERE ct.status = 'active'
    ) c
    GROUP BY c.business_id

    UNION ALL

    -- ── ministry ─────────────────────────────────────────────────────
    -- Guests marked first_time who were seen again afterwards.
    SELECT
        ct.business_id,
        'first_time_return'::text,
        ROUND(100.0 * COUNT(*) FILTER (
            WHERE EXISTS (
                SELECT 1 FROM public.sessions s
                WHERE s.business_id = ct.business_id
                  AND s.contact_id = ct.id
                  AND s.scheduled_for > ct.created_at
            )
        ) / NULLIF(COUNT(*), 0), 1)::numeric
    FROM public.contacts ct
    WHERE ct.status = 'first_time'
      AND ct.created_at >= now() - interval '365 days'
    GROUP BY ct.business_id

    UNION ALL

    -- ── nonprofit ────────────────────────────────────────────────────
    -- Donors who gave last year and gave again this year.
    SELECT
        ct.business_id,
        'donor_retention'::text,
        ROUND(100.0 * COUNT(*) FILTER (
            WHERE ct.last_interaction >= now() - interval '365 days'
        ) / NULLIF(COUNT(*), 0), 1)::numeric
    FROM public.contacts ct
    WHERE ct.status = 'donor'
    GROUP BY ct.business_id

    UNION ALL

    -- ── law firm + consultant ────────────────────────────────────────
    -- Realisation: invoiced against recorded. Both halves are cents, so
    -- the ratio is unit-free.
    SELECT
        i.business_id,
        'realization'::text,
        ROUND(100.0 * SUM(i.total_cents)
              / NULLIF(SUM(i.subtotal_cents), 0), 1)::numeric
    FROM public.invoices i
    WHERE i.status IN ('open', 'paid')
      AND i.created_at >= now() - interval '180 days'
    GROUP BY i.business_id

    UNION ALL

    -- Collection: banked against billed.
    SELECT
        i.business_id,
        'collection'::text,
        ROUND(100.0 * SUM(i.amount_paid_cents)
              / NULLIF(SUM(i.total_cents), 0), 1)::numeric
    FROM public.invoices i
    WHERE i.created_at >= now() - interval '180 days'
    GROUP BY i.business_id

    UNION ALL

    -- Lockup, in days of annual revenue. Lower is better; the panel is
    -- told so by the band's `direction`, not by this view.
    SELECT
        i.business_id,
        'collection_lockup'::text,
        ROUND(365.0 * SUM(i.amount_due_cents) FILTER (WHERE i.status = 'open')
              / NULLIF(SUM(i.amount_paid_cents), 0), 0)::numeric
    FROM public.invoices i
    WHERE i.created_at >= now() - interval '365 days'
    GROUP BY i.business_id;


COMMENT ON VIEW public.business_benchmark_values IS
    'Per-tenant VALUES for the benchmark panel — one row per (business, '
    'key). The bands they are read against (average, target, floor, '
    'reading, source) live in workspace_benchmarks.py, because a band is '
    'an editorial claim with a citation and belongs in reviewed code. Add '
    'a metric by adding a UNION arm; the layout binds by key.';

-- Inherits RLS from its base tables, so a business only ever sees its
-- own rows. Server code reads it with the service-role key, and the
-- app-layer owner check in workspace_composer_router does the gating.
ALTER VIEW public.business_benchmark_values SET (security_invoker = true);

GRANT SELECT ON public.business_benchmark_values TO authenticated, service_role;

COMMIT;
