-- APPLY-2026-08-26-workspace-composer.sql
--
-- Chief workspace composer, phase one. See
-- docs/WORKSPACE_COMPOSER_SPEC.md.
--
-- Three things:
--   1. Where a business's chosen layout lives.
--   2. A lane column on sessions, so a chair/crew timeline has something
--      to group by.
--   3. `business_metrics` — named figures, one row per figure, so a
--      metric_row can bind three numbers through one descriptor.
--
-- Idempotent. Safe to re-run.

BEGIN;

-- ─── 1. layout state on the business profile ────────────────────────
-- Lives alongside terminology_overrides (VABI v1.5) rather than in a new
-- table: it is one row per business, always read with the profile, and a
-- join for it would be pure ceremony.

ALTER TABLE public.business_profiles
    ADD COLUMN IF NOT EXISTS workspace_archetype text,
    ADD COLUMN IF NOT EXISTS workspace_layout jsonb,
    ADD COLUMN IF NOT EXISTS workspace_terminology jsonb NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN public.business_profiles.workspace_archetype IS
    'One of salon | law_firm | ministry | consultant | trades. Chief picks '
    'at onboarding; the practitioner can override in one tap.';

COMMENT ON COLUMN public.business_profiles.workspace_layout IS
    'The validated layout schema this business renders. Written only by '
    'workspace_composer_router after workspace_layout_validator passes — '
    'nothing else should write this column.';

COMMENT ON COLUMN public.business_profiles.workspace_terminology IS
    'Resolved terminology map: { key: { value, origin } }. A row with '
    'origin = user_override is never overwritten by an automatic write.';

-- The enum is deliberately a CHECK and not a Postgres enum type: phase two
-- may add archetypes, and ALTER TYPE ... ADD VALUE cannot run inside a
-- transaction, which has bitten this schema before.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'business_profiles_workspace_archetype_check'
    ) THEN
        ALTER TABLE public.business_profiles
            ADD CONSTRAINT business_profiles_workspace_archetype_check
            CHECK (workspace_archetype IS NULL OR workspace_archetype IN
                   ('salon', 'law_firm', 'ministry', 'consultant', 'trades'));
    END IF;
END $$;


-- ─── 2. the lane column ─────────────────────────────────────────────
-- Who is doing the work. A salon floor binds this to business_users.id, a
-- crew board to contractors.id. Deliberately NOT a foreign key: the layout
-- declares which table supplies the lanes, and a FK to one of them would
-- pick a winner between two verticals that are equally right.

ALTER TABLE public.sessions
    ADD COLUMN IF NOT EXISTS assigned_to uuid;

COMMENT ON COLUMN public.sessions.assigned_to IS
    'Lane key for the timeline_day primitive: business_users.id on a '
    'staffed floor, contractors.id on a crew board. Unconstrained on '
    'purpose — the workspace layout names the lane source.';

CREATE INDEX IF NOT EXISTS idx_sessions_business_assigned
    ON public.sessions (business_id, assigned_to, scheduled_for);


-- ─── 3. named figures ───────────────────────────────────────────────
-- A metric_row binds a COLLECTION of figures through one source
-- descriptor. Without a source shaped like this it would need three
-- separate queries, which the layout schema has no way to express.
--
-- Keys shipped here are the ones the five presets bind. Each is computed
-- from tables that already exist; a key with no data for a business simply
-- does not appear, and the primitive renders what it gets.

CREATE OR REPLACE VIEW public.business_metrics AS

    -- Invoiced but not paid. The lawyer's and consultant's "unbilled".
    SELECT
        i.business_id,
        'unbilled_amount'::text                                 AS key,
        'Unbilled'::text                                        AS label,
        (COALESCE(SUM(i.amount_due_cents), 0) / 100.0)::numeric  AS value,
        MIN(i.currency)                                         AS unit,
        NULL::text                                              AS trend,
        now()                                                   AS computed_at
    FROM public.invoices i
    WHERE i.status IN ('draft', 'open')
    GROUP BY i.business_id

    UNION ALL

    -- Work in progress: scheduled time not yet on an invoice, valued at
    -- nothing here — this is an hours figure, not a money one.
    SELECT
        s.business_id,
        'wip_amount'::text,
        'Work in progress'::text,
        (COALESCE(SUM(s.duration_minutes), 0) / 60.0)::numeric,
        'hours'::text,
        NULL::text,
        now()
    FROM public.sessions s
    WHERE s.status = 'scheduled'
      AND s.scheduled_for < now()
    GROUP BY s.business_id

    UNION ALL

    -- Client funds held. Asset-side ledger lines on the trust accounts.
    SELECT
        le.business_id,
        'trust_balance'::text,
        'In trust'::text,
        (COALESCE(SUM(le.debit - le.credit), 0))::numeric,
        MIN(le.currency),
        NULL::text,
        now()
    FROM public.ledger_entries le
    WHERE le.account_type = 'asset'
      AND le.account_code LIKE '1%'
    GROUP BY le.business_id

    UNION ALL

    -- Retainer hours drawn this calendar month.
    SELECT
        s.business_id,
        'retainer_hours_drawn'::text,
        'Hours drawn'::text,
        (COALESCE(SUM(s.duration_minutes), 0) / 60.0)::numeric,
        'hours'::text,
        NULL::text,
        now()
    FROM public.sessions s
    WHERE s.status IN ('completed', 'scheduled')
      AND s.scheduled_for >= date_trunc('month', now())
    GROUP BY s.business_id

    UNION ALL

    -- Retainer hours still available. Nothing models a retainer ceiling
    -- yet, so this reports the drawn figure against a null remainder
    -- rather than inventing a denominator.
    SELECT
        s.business_id,
        'retainer_hours_remaining'::text,
        'Hours remaining'::text,
        NULL::numeric,
        'hours'::text,
        NULL::text,
        now()
    FROM public.sessions s
    GROUP BY s.business_id;

COMMENT ON VIEW public.business_metrics IS
    'Named figures for the metric_row primitive: one row per figure per '
    'business. Bound by workspace layouts via '
    'filter: { key: [...] }. Add a key by adding a UNION arm.';

-- The view inherits RLS from its base tables (security_invoker), so a
-- business only ever sees its own rows. Server code reads it with the
-- service-role key and the app-layer owner check in
-- workspace_composer_router does the gating.
ALTER VIEW public.business_metrics SET (security_invoker = true);

GRANT SELECT ON public.business_metrics TO authenticated, service_role;

COMMIT;
