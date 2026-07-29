-- APPLY-2026-07-29-contractor-vertical.sql
-- RUN ONCE in the Supabase SQL Editor (whole file).
--
-- Adds the 'contractor' vertical — trades: plumbing, electrical, HVAC,
-- roofing, remodel, landscape, carpentry.
--
-- WHY THIS SQL IS REQUIRED, NOT OPTIONAL
--   Path C Phase 1 replaced the businesses.type CHECK constraint with a
--   FOREIGN KEY to business_type_archetypes.business_type. That made the
--   archetype table the single source of truth for which types exist — so
--   a vertical added in Python ALONE cannot be saved. Onboarding would
--   offer the card and the insert would fail on the FK.
--
--   The code half of this change ships in the same arc (vertical_registry,
--   vertical_intelligence, vertical_terminology, contract framing,
--   autopilot, frontend picker). This file is what makes it storable.
--
-- WHY NOT service_provider
--   service_provider is the deliberate GENERIC baseline — vertical_registry
--   marks its Chief intelligence as "intentionally GENERIC baseline voice".
--   The trades have a shape it does not model: a JOB at a site, quoted
--   before it starts, materials and labor billed separately, a deposit up
--   front, and change orders when the scope moves. A contractor picking
--   "Service Provider" got the generic voice and no job vocabulary at all.
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE.
--   ON CONFLICT DO NOTHING — re-running is a no-op and will never overwrite
--   a curated row. No existing data is read or modified.

INSERT INTO public.business_type_archetypes (
    business_type,
    display_name,
    description,
    default_service_models,
    default_pricing_models,
    default_engagement_length,
    default_produces_deliverables,
    default_sensitive_areas,
    required_disclaimers,
    contract_template_key,
    notes
) VALUES (
    'contractor',
    'Contractor / Trades',
    'Trades and contracting — plumbing, electrical, HVAC, roofing, remodel, landscape, carpentry. Work is a JOB at a customer site: quoted before it starts, materials and labor billed separately, deposit up front, change orders when scope moves.',
    ARRAY['project', 'one_on_one'],
    ARRAY['flat_bid', 'hourly', 'time_and_materials', 'cost_plus'],
    'per_job',
    true,
    -- Licensing and permits are the real sensitivity here. Not privileged
    -- like a lawyer's file or clinical like a therapist's, but a contractor
    -- speaking outside their licensed trades is a genuine liability, and
    -- Chief is told so in vertical_context._vertical_specific_reminders.
    '{"licensing": "Work requiring a licensed trade or a pulled permit must not be advised on or quoted without the license."}'::jsonb,
    ARRAY[]::text[],
    'work_agreement',
    'Added 2026-07-29 closing the vertical-readiness audit gap: contractors scored 1/12 and did not exist as a vertical. Paired with the Python half in the same arc. Money model (estimate -> deposit -> progress -> final, change orders) is NOT yet built — that lands with the money primitives arc; this row makes the vertical selectable and correctly voiced first.'
)
ON CONFLICT (business_type) DO NOTHING;

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
-- Expect exactly one row, and the FK now accepts 'contractor'.
SELECT business_type, display_name, contract_template_key
FROM public.business_type_archetypes
WHERE business_type = 'contractor';
