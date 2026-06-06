-- ─────────────────────────────────────────────────────────────────
-- Path C Phase 1 — 1b Additive archetype seed
-- ─────────────────────────────────────────────────────────────────
-- Adds business_type_archetypes rows for every value the current
-- businesses_type_check constraint allows but the archetype table
-- doesn't yet contain. STRICTLY ADDITIVE — every INSERT carries
-- ON CONFLICT (business_type) DO NOTHING so re-runs are no-ops and
-- existing curated archetype rows (lawyer, coach, ministry, etc.)
-- are NEVER overwritten.
--
-- This is the load-bearing precondition for 1f (FK migration). Every
-- prod businesses.type value must have a corresponding archetype row
-- before the CHECK constraint can be replaced with a FOREIGN KEY.
--
-- After this migration, the union of {archetype rows} ⊇ {constraint
-- values}, so the FK in 1f will not reject any existing row.
--
-- IDEMPOTENT, FORWARD-ONLY, NON-DESTRUCTIVE.
--
-- Apply via Supabase Studio → SQL editor → Run.
-- Run 2026_06_07_pathc_phase1_diagnostic.sql first to confirm scope.
-- ─────────────────────────────────────────────────────────────────

-- ─── Generic / utility verticals ────────────────────────────────

-- 'custom' — explicit catch-all for self-described businesses that
-- don't fit a built-in vertical. Generic dictionary applies.
INSERT INTO public.business_type_archetypes (
    business_type, display_name, description,
    default_service_models, default_pricing_models,
    default_engagement_length, default_produces_deliverables,
    default_sensitive_areas, required_disclaimers,
    contract_template_key, notes
) VALUES (
    'custom',
    'Custom / Other',
    'Self-described businesses that do not fit a built-in vertical. Generic terminology applies; practitioner can override via Settings → Terminology.',
    ARRAY['one_on_one', 'group', 'project'],
    ARRAY['flat_fee', 'hourly'],
    'flexible',
    true,
    '{}'::jsonb,
    ARRAY[]::text[],
    'general_services_agreement',
    'Generic baseline. No vertical-specific overrides by design — Chief proposes terminology via /terminology/overrides/generate when needed.'
)
ON CONFLICT (business_type) DO NOTHING;

-- 'general' — legacy generic value, predates 'custom'. Same shape.
INSERT INTO public.business_type_archetypes (
    business_type, display_name, description,
    default_service_models, default_pricing_models,
    default_engagement_length, default_produces_deliverables,
    default_sensitive_areas, required_disclaimers,
    contract_template_key, notes
) VALUES (
    'general',
    'General Business',
    'Generic small business with no specialized vertical semantics. Use ''custom'' for new businesses; this row exists for backward compatibility with legacy data.',
    ARRAY['one_on_one', 'group', 'project'],
    ARRAY['flat_fee', 'hourly'],
    'flexible',
    true,
    '{}'::jsonb,
    ARRAY[]::text[],
    'general_services_agreement',
    'Legacy generic. Prefer ''custom'' for new businesses.'
)
ON CONFLICT (business_type) DO NOTHING;

-- ─── Service / professional verticals ──────────────────────────

-- 'service_provider' — generic services umbrella. May already exist.
INSERT INTO public.business_type_archetypes (
    business_type, display_name, description,
    default_service_models, default_pricing_models,
    default_engagement_length, default_produces_deliverables,
    default_sensitive_areas, required_disclaimers,
    contract_template_key, notes
) VALUES (
    'service_provider',
    'Service Provider',
    'Generic service business — provides labor or expertise for hire. Use a more specific vertical (lawyer, coach, consultant, creative, fitness_wellness, etc.) when one fits.',
    ARRAY['one_on_one', 'project'],
    ARRAY['flat_fee', 'hourly'],
    'flexible',
    true,
    '{}'::jsonb,
    ARRAY[]::text[],
    'general_services_agreement',
    'Intentionally generic baseline.'
)
ON CONFLICT (business_type) DO NOTHING;

-- 'personal_services' — barbers, salons, spas, etc. May already exist.
INSERT INTO public.business_type_archetypes (
    business_type, display_name, description,
    default_service_models, default_pricing_models,
    default_engagement_length, default_produces_deliverables,
    default_sensitive_areas, required_disclaimers,
    contract_template_key, notes
) VALUES (
    'personal_services',
    'Personal Services',
    'Walk-in or appointment-based personal services — barbers, salons, spas, nail technicians, massage. Per-appointment billing; minimal documentation.',
    ARRAY['one_on_one'],
    ARRAY['per_appointment', 'flat_fee'],
    'single_session',
    false,
    '{}'::jsonb,
    ARRAY[]::text[],
    'service_agreement',
    'Walk-in friendly. Appointments often pre-paid or paid at end of visit.'
)
ON CONFLICT (business_type) DO NOTHING;

-- 'agency' — design / marketing / dev shops billing project or retainer.
INSERT INTO public.business_type_archetypes (
    business_type, display_name, description,
    default_service_models, default_pricing_models,
    default_engagement_length, default_produces_deliverables,
    default_sensitive_areas, required_disclaimers,
    contract_template_key, notes
) VALUES (
    'agency',
    'Agency / Studio',
    'Design, marketing, branding, or development agencies — usually project-based or retainer with multiple deliverables.',
    ARRAY['project', 'retainer'],
    ARRAY['flat_fee', 'retainer', 'hourly'],
    'package_1_3_months',
    true,
    '{"deliverable_handoff": true, "ip_assignment": true}'::jsonb,
    ARRAY['scope_change_clause_required'],
    'agency_master_services_agreement',
    'Project-shaped work with deliverables. SOWs frequent; scope creep is a recurring trust-layer concern.'
)
ON CONFLICT (business_type) DO NOTHING;

-- ─── Mission-driven / community ────────────────────────────────

-- 'church' — legacy value; many existing businesses use this rather
-- than the canonical 'ministry'. Phase 2 will rule on dedup.
INSERT INTO public.business_type_archetypes (
    business_type, display_name, description,
    default_service_models, default_pricing_models,
    default_engagement_length, default_produces_deliverables,
    default_sensitive_areas, required_disclaimers,
    contract_template_key, notes
) VALUES (
    'church',
    'Church',
    'Local congregations and church organizations. Member-centric. Often overlaps with the canonical ''ministry'' archetype — Phase 2 will rule on whether these merge.',
    ARRAY['group', 'community'],
    ARRAY['donation', 'tithe', 'free'],
    'ongoing',
    false,
    '{"pastoral_confidentiality": true, "giving_not_sales": true}'::jsonb,
    ARRAY['501c3_status_disclosure_recommended'],
    'membership_agreement',
    'Member language, not customer. Avoid framing giving as a sales transaction.'
)
ON CONFLICT (business_type) DO NOTHING;

-- 'nonprofit' — broader umbrella; 501(c)(3) orgs, foundations, etc.
INSERT INTO public.business_type_archetypes (
    business_type, display_name, description,
    default_service_models, default_pricing_models,
    default_engagement_length, default_produces_deliverables,
    default_sensitive_areas, required_disclaimers,
    contract_template_key, notes
) VALUES (
    'nonprofit',
    'Nonprofit / Foundation',
    'Mission-driven organizations including 501(c)(3)s, foundations, and community orgs. Donor-funded; program-centric rather than service-centric.',
    ARRAY['program', 'community', 'grant'],
    ARRAY['donation', 'grant', 'membership_dues'],
    'ongoing',
    false,
    '{"donor_anonymity_optional": true, "501c3_compliance": true}'::jsonb,
    ARRAY['501c3_status_disclosure_recommended'],
    'donor_acknowledgement_letter',
    'Donor / member / participant language. Programmatic outcomes over deliverables.'
)
ON CONFLICT (business_type) DO NOTHING;

-- ─── Digital / SaaS / commerce ─────────────────────────────────

-- 'ecommerce' — physical or digital product sales.
INSERT INTO public.business_type_archetypes (
    business_type, display_name, description,
    default_service_models, default_pricing_models,
    default_engagement_length, default_produces_deliverables,
    default_sensitive_areas, required_disclaimers,
    contract_template_key, notes
) VALUES (
    'ecommerce',
    'E-commerce',
    'Physical or digital product sales — direct-to-consumer or wholesale. Order / SKU / shipment centric; subscription overlay common.',
    ARRAY['product', 'subscription'],
    ARRAY['per_unit', 'subscription'],
    'per_order',
    true,
    '{"returns_policy_required": true, "shipping_addresses_pii": true}'::jsonb,
    ARRAY['returns_and_refunds_policy', 'shipping_disclosure'],
    'terms_of_sale',
    'Customer / order / shipment vocabulary. Subscription products bridge to ongoing engagement.'
)
ON CONFLICT (business_type) DO NOTHING;

-- 'saas' — SaaS / digital tools. Subscription-first, account-centric.
INSERT INTO public.business_type_archetypes (
    business_type, display_name, description,
    default_service_models, default_pricing_models,
    default_engagement_length, default_produces_deliverables,
    default_sensitive_areas, required_disclaimers,
    contract_template_key, notes
) VALUES (
    'saas',
    'SaaS / Software',
    'Software-as-a-service products — recurring subscription, seat-based or usage-based billing. Customer / account / seat vocabulary; uptime and data-handling commitments matter.',
    ARRAY['subscription', 'self_service'],
    ARRAY['subscription', 'usage_based'],
    'recurring_monthly',
    false,
    '{"data_processing_agreement_required": true, "gdpr_applicable_in_eu": true}'::jsonb,
    ARRAY['terms_of_service_required', 'privacy_policy_required', 'dpa_optional'],
    'subscription_agreement',
    'Customer / account / seat. SLA + uptime commitments may apply for higher tiers.'
)
ON CONFLICT (business_type) DO NOTHING;

-- ─── Coaching duplication (Phase 2 will rule on dedup) ──────────
-- 'coaching' is a legacy duplicate of 'coach'. Seed an archetype row
-- so the FK migration in 1f doesn't reject any (unlikely-but-possible)
-- business still stamped 'coaching' before 1d's app-level sync runs.
-- Phase 2 ruling on dedup options α/β/γ governs whether this row
-- stays, is removed, or becomes an explicit alias.

INSERT INTO public.business_type_archetypes (
    business_type, display_name, description,
    default_service_models, default_pricing_models,
    default_engagement_length, default_produces_deliverables,
    default_sensitive_areas, required_disclaimers,
    contract_template_key, notes
) VALUES (
    'coaching',
    'Coaching (legacy)',
    'Legacy duplicate of the canonical ''coach'' archetype. Kept to make the FK constraint applicable to any residual data; Phase 2 ruling will dedup.',
    ARRAY['one_on_one', 'group'],
    ARRAY['flat_fee', 'package', 'subscription'],
    'package_3_12_months',
    false,
    '{}'::jsonb,
    ARRAY[]::text[],
    'coaching_agreement',
    'PHASE 2 PENDING — dedup against ''coach''. Treat as alias until ruled.'
)
ON CONFLICT (business_type) DO NOTHING;

-- ─── Verify ─────────────────────────────────────────────────────
-- After running, expect 17 or 18 archetype rows total (depending
-- on which of the above existed already). Re-run the diagnostic
-- file to confirm Q5 returns zero rows (every businesses.type
-- value is now covered).

SELECT business_type, display_name
FROM public.business_type_archetypes
ORDER BY business_type;
