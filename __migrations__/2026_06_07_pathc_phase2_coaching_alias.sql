-- ─────────────────────────────────────────────────────────────────
-- Path C Phase 2 — 2a Coaching γ-mirror (alias to coach)
-- ─────────────────────────────────────────────────────────────────
-- Phase 1's seed_archetypes migration added a placeholder 'coaching'
-- row marked "PHASE 2 PENDING — dedup against 'coach'". This brings
-- the row into perfect alignment with the canonical 'coach' archetype
-- so a business stamped 'coaching' resolves to the same vocabulary +
-- defaults as one stamped 'coach'.
--
-- The frontend dictionary (dictionary.ts) and backend mirror
-- (vertical_terminology.py) currently route 'coaching' through the
-- generic baseline because they only define overrides keyed on
-- 'coach'. Phase 2 fixes that at the dictionary layer too — by adding
-- an explicit 'coaching' override that mirrors 'coach' field-for-
-- field. Both layers (DB row + dictionary mirror) ship in the same
-- coordinated arc so a 'coaching' business gets full parity end-to-end.
--
-- IDEMPOTENT, FORWARD-ONLY, NON-DESTRUCTIVE.
-- Apply via Supabase Studio → SQL editor → Run.
-- ─────────────────────────────────────────────────────────────────

UPDATE public.business_type_archetypes
SET
    display_name = 'Coaching',
    description  = 'Coaching practice — life, executive, business, or specialty. Client and session-centric. Engagement is multi-month with regular cadence. Alias to ''coach''.',
    default_service_models      = ARRAY['one_on_one', 'group'],
    default_pricing_models      = ARRAY['package', 'subscription'],
    default_engagement_length   = 'package_3_12_months',
    default_produces_deliverables = false,
    default_sensitive_areas     = '{}'::jsonb,
    required_disclaimers        = ARRAY['not_therapy_or_clinical_advice', 'results_vary_individually'],
    contract_template_key       = 'coaching_agreement',
    notes                       = 'Aliased to canonical ''coach'' archetype (Path C Phase 2). Both rows share dictionary entries + behavior. Treat ''coaching'' as a legacy synonym; new businesses get ''coach''.'
WHERE business_type = 'coaching';

-- ─── Verify ─────────────────────────────────────────────────────
SELECT business_type, display_name, default_service_models,
       default_pricing_models, contract_template_key
FROM public.business_type_archetypes
WHERE business_type IN ('coach', 'coaching')
ORDER BY business_type;
