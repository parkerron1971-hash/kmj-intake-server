-- APPLY-2026-07-29-therapist-vertical.sql
-- RUN ONCE in the Supabase SQL Editor (whole file).
--
-- Adds the 'therapist' vertical — private practice mental health.
--
-- LAUNCHED NARROW, ON PURPOSE
--   Clinical records are OUT OF SCOPE. Scheduling, billing and practice
--   admin only.
--
--   Storing session content or clinical detail would make the platform a
--   HIPAA business associate, which requires a signed BAA with EVERY
--   downstream processor that could touch the data — the model provider,
--   Supabase, Twilio, Stripe — plus a hard gate on what Chief may read.
--   None of that is in place. That is a legal posture, not a checklist row.
--
--   So the vertical ships useful and bounded. A private practice genuinely
--   needs scheduling, invoicing and a cancellation policy that holds, and
--   none of that carries PHI beyond the contact record any business keeps.
--
--   The boundary is ENFORCED, not documented: vertical_scope.py refuses
--   clinical modules at both custom-module create paths (ensure_module and
--   accept_module_spec), and the refusal names the reason.
--
--   This is a narrowed launch, NOT a permanent limitation. When a BAA
--   posture exists, the vertical_scope entry is deleted and the capability
--   lands deliberately rather than by accident.
--
-- WHY NOT fitness_wellness
--   That vertical exists and is the nearest neighbour, but it actively
--   forbids this register: its Chief profile taboos "clinical/medical
--   claims" and its reminder is "No clinical claims without licensure".
--   A licensed therapist stamped fitness_wellness would be told not to
--   sound like what they are.
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE.

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
    'therapist',
    'Therapist / Counselor',
    'Private practice mental health — LCSW, LMFT, LPC, psychologist. Recurring sessions, a cancellation policy that holds, private pay or superbills. Clinical records are out of scope on this platform.',
    ARRAY['one_on_one', 'group'],
    ARRAY['flat_fee', 'sliding_scale'],
    'ongoing',
    false,
    -- The sensitivity that defines this vertical. Read by the disclaimer
    -- surface and by Chief's own gating.
    '{"phi": "Protected Health Information. Clinical records, session content, diagnoses and treatment detail are OUT OF SCOPE — the platform holds no PHI and is not a HIPAA business associate. Scheduling, billing and admin only.", "confidentiality": "Appointment confirmations may be read by someone other than the client; they must never describe the purpose or content of a session."}'::jsonb,
    ARRAY[]::text[],
    'practice_agreement',
    'Added 2026-07-29 on Kevin''s ruling: launch therapists with clinical notes explicitly out of scope. Enforced by vertical_scope.py at both module-create paths, not merely documented. Revisit when a BAA posture exists.'
)
ON CONFLICT (business_type) DO NOTHING;

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
SELECT business_type, display_name, contract_template_key,
       default_sensitive_areas ? 'phi' AS phi_flagged
FROM public.business_type_archetypes
WHERE business_type = 'therapist';
