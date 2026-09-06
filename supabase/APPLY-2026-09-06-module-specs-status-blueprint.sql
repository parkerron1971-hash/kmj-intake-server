-- APPLY-2026-09-06-module-specs-status-blueprint.sql
-- The idea-to-business door (business_blueprint.py) keeps the MAP of a
-- business as a module_specs row with status='blueprint' — never a card,
-- never accepted — so the forms and site brief survive the turn and
-- replay() can hand the finished cards back. The status CHECK only knew
-- draft / accepted / rejected, so the map row was silently refused on
-- the first live run (KMJ, 2026-09-06). 'superseded' is for a map a
-- newer layout replaced.
--
-- APPLIED to production 2026-09-06 via the Management API.

ALTER TABLE public.module_specs
  DROP CONSTRAINT IF EXISTS module_specs_status_check;

ALTER TABLE public.module_specs
  ADD CONSTRAINT module_specs_status_check
  CHECK (status = ANY (ARRAY['draft'::text, 'accepted'::text, 'rejected'::text,
                             'blueprint'::text, 'superseded'::text]));
