-- 2026-09-18 — intake_forms.form_type: the database and the code must agree.
--
-- The CHECK allowed six values (connect_card, discovery, consultation,
-- general, volunteer, event). chief_form_actions._FORM_TYPES and the Chief
-- prompt allowed ten (general, intake, discovery, consultation,
-- connect_card, volunteer, application, feedback, waitlist, quote) — and
-- the prompt's own example uses "intake". Every create_client_form with
-- intake / application / feedback / waitlist / quote was accepted by the
-- handler and rejected by Postgres: "I couldn't save that form just now".
--
-- Union of both lists. Additive: no existing row is affected.
-- Applied via the Management API on 2026-09-18 in the same PR as the code.

ALTER TABLE public.intake_forms
  DROP CONSTRAINT IF EXISTS intake_forms_form_type_check;

ALTER TABLE public.intake_forms
  ADD CONSTRAINT intake_forms_form_type_check
  CHECK (form_type = ANY (ARRAY[
    'general', 'intake', 'discovery', 'consultation', 'connect_card',
    'volunteer', 'application', 'feedback', 'waitlist', 'quote', 'event'
  ]::text[]));

-- verify:
-- select pg_get_constraintdef(oid) from pg_constraint
--  where conname = 'intake_forms_form_type_check';
