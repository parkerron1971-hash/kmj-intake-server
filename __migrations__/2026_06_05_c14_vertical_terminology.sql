-- ─────────────────────────────────────────────────────────────────
-- Phase C.1.4 v1 — Vertical-Aware Terminology seed updates
-- ─────────────────────────────────────────────────────────────────
-- Run via:  Supabase Studio → SQL editor → paste + Run
-- Idempotent, forward-only, additive.
--
-- Changes:
--   1. Seed `lawyer` archetype row in business_type_archetypes
--      (F4 ruling — fills the seed gap; NT8f LLM continues handling
--      vertical-specific intelligence inside the closed-archetype
--      surface, this row just gives the terminology layer + brand
--      defaults a canonical home).
--   2. Reconcile `coaching` ↔ `coach` drift (F5 ruling — canonical
--      key is `coach`). UPDATE the 1 existing business whose
--      type='coaching' to 'coach' via idempotent WHERE.
--
-- Verify SELECTs at the bottom confirm both landed cleanly.
-- ─────────────────────────────────────────────────────────────────

-- ─── 1. Insert lawyer archetype row ──────────────────────────────

INSERT INTO public.business_type_archetypes (
    business_type, display_name, description,
    default_service_models, default_pricing_models,
    default_engagement_length, default_produces_deliverables,
    default_sensitive_areas, required_disclaimers,
    contract_template_key, notes
) VALUES (
    'lawyer',
    'Lawyer / Legal Services',
    'Attorneys, legal consultants, and law firms — practice areas like litigation, contract, family, IP, criminal defense, immigration, estate planning.',
    ARRAY['one_on_one', 'project'],
    ARRAY['retainer', 'hourly', 'flat_fee'],
    'package_3_12_months',
    true,
    '{"conflict_check_required": true, "confidentiality_privileged": true, "trust_account_handling": false}'::jsonb,
    ARRAY['not_legal_advice_without_engagement', 'jurisdiction_specific', 'attorney_client_privilege'],
    'engagement_letter',
    'Client/matter-centric vocabulary. Conflict checks before engagement are non-negotiable. Trust account funds (IOLTA) require segregation in many jurisdictions — flag in onboarding.'
)
ON CONFLICT (business_type) DO NOTHING;

-- ─── 2. Reconcile coaching → coach ──────────────────────────────

-- Update any business whose type was set to legacy 'coaching' so the
-- terminology lookup finds the canonical 'coach' entry. Idempotent —
-- WHERE clause means re-running is a no-op.
UPDATE public.businesses
SET type = 'coach'
WHERE type = 'coaching';

-- Optional companion: also normalize business_profiles.business_type
-- in case any 'coaching' value drifted there.
UPDATE public.business_profiles
SET business_type = 'coach'
WHERE business_type = 'coaching';

-- ─── Verify ─────────────────────────────────────────────────────

SELECT business_type, display_name, default_service_models, default_pricing_models
FROM public.business_type_archetypes
WHERE business_type IN ('lawyer', 'coach')
ORDER BY business_type;

SELECT COUNT(*) AS coaching_businesses_remaining
FROM public.businesses
WHERE type = 'coaching';

SELECT COUNT(*) AS coach_businesses_total
FROM public.businesses
WHERE type = 'coach';
