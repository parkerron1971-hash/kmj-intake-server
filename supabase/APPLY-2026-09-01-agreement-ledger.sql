-- APPLY-2026-09-01-agreement-ledger.sql
-- RUN ONCE (whole file).
--
-- Switches five blueprint modules onto the new `agreement_ledger`
-- archetype and gives each its field mapping.
--
-- WHY THESE FIVE
--   The blueprint audit found modules tracking a signature by hand in a
--   generic table. Five are the same shape — a document attached to a
--   person that is either signed or is not, and that sometimes stops
--   being valid:
--
--     creative           agreements          project + signed_date
--     service_provider   agreements          client, scope + signed_date
--     lawyer             engagement-letters  matter, fee + signed_date
--     fitness_wellness   waivers             waiver_type, signed_date, EXPIRES
--     financial_educator disclosures         client, ack + signed_date
--
-- WHY NOT course_creator.terms, WHICH LOOKS LIKE A SIXTH
--   It has no signed date. Its fields are refund_window_days,
--   access_duration, redistribution_terms, refund_policy — that is a
--   POLICY DEFINITION, not a record of who signed what. Under this
--   archetype every row would read "not signed" forever, which is the
--   archetype lying rather than helping. It stays on fallback_generic,
--   the same call test_other_shapes_were_left_alone already pins for a
--   lawyer's intake form and a therapist's superbills. A closed enum
--   only means something if things are allowed not to fit.
--
-- STATE IS DERIVED — no status column is added and none is needed. The
--   UI computes not-signed / expired / expiring / signed from the two
--   date fields these modules already carry, which is why this migration
--   touches no row DATA at all: it is archetype + params only, and every
--   existing entry keeps working.
--
-- IDEMPOTENT AND REVERSIBLE.
--   Each UPDATE is guarded on business_type + module_slug and sets the
--   same values every run. To revert: set archetype = NULL and
--   archetype_params = NULL for these five rows; the modules fall back to
--   the generic table they render as today, with no data change.

-- creative — an Agreement is about a project; no expiry.
UPDATE public.business_type_module_blueprint SET
    archetype = 'agreement_ledger',
    archetype_params = '{"title_field": "project",
                         "signed_field": "signed_date",
                         "item_noun": "Agreement"}'::jsonb
WHERE business_type = 'creative' AND module_slug = 'agreements';

-- service_provider — the client is held as TEXT here, not a contact_link;
-- the ledger renders a plain name as written.
UPDATE public.business_type_module_blueprint SET
    archetype = 'agreement_ledger',
    archetype_params = '{"title_field": "scope",
                         "party_field": "client",
                         "signed_field": "signed_date",
                         "item_noun": "Agreement"}'::jsonb
WHERE business_type = 'service_provider' AND module_slug = 'agreements';

-- lawyer — the matter is what the letter is ABOUT; the client is the party.
-- An unsigned engagement letter is work being done for free, which is the
-- single clearest case for this archetype existing.
UPDATE public.business_type_module_blueprint SET
    archetype = 'agreement_ledger',
    archetype_params = '{"title_field": "matter",
                         "party_field": "client",
                         "signed_field": "signed_date",
                         "item_noun": "Engagement Letter"}'::jsonb
WHERE business_type = 'lawyer' AND module_slug = 'engagement-letters';

-- fitness_wellness — the only one with a real EXPIRY, and the reason the
-- expiring/expired states exist at all. An expired liability waiver is a
-- live risk that a signed_date column cannot show.
UPDATE public.business_type_module_blueprint SET
    archetype = 'agreement_ledger',
    archetype_params = '{"title_field": "waiver_type",
                         "party_field": "client",
                         "signed_field": "signed_date",
                         "expires_field": "expires",
                         "expiring_soon_days": 30,
                         "item_noun": "Waiver"}'::jsonb
WHERE business_type = 'fitness_wellness' AND module_slug = 'waivers';

-- financial_educator — the education-only acknowledgement. The vertical's
-- whole regulatory posture is that it teaches rather than advises, and
-- this is the document that records the client was told so.
UPDATE public.business_type_module_blueprint SET
    archetype = 'agreement_ledger',
    archetype_params = '{"title_field": "education_only_ack",
                         "party_field": "client",
                         "signed_field": "signed_date",
                         "item_noun": "Disclosure"}'::jsonb
WHERE business_type = 'financial_educator' AND module_slug = 'disclosures';

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
-- Expect exactly five rows, each with a signed_field that NAMES A FIELD
-- THAT EXISTS in its own schema. That second check is the one worth
-- running: a signed_field pointing at a missing key does not render an
-- empty column, it reads as "nobody has signed anything" and turns the
-- module into one long unsigned list.
SELECT business_type,
       module_slug,
       archetype_params ->> 'item_noun'      AS noun,
       archetype_params ->> 'signed_field'   AS signed_field,
       archetype_params ->> 'expires_field'  AS expires_field,
       (archetype_params ->> 'signed_field') IN (
           SELECT f ->> 'name' FROM jsonb_array_elements(schema -> 'fields') f
       ) AS signed_field_exists
FROM public.business_type_module_blueprint
WHERE archetype = 'agreement_ledger'
ORDER BY business_type;

-- And the one that must NOT have moved.
SELECT business_type, module_slug, coalesce(archetype, '(generic)') AS archetype
FROM public.business_type_module_blueprint
WHERE business_type = 'course_creator' AND module_slug = 'terms';
