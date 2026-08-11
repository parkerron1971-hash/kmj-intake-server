-- APPLY-2026-08-11-matters-fixture-schema.sql
--
-- Fixes the ONE custom_modules row in the whole database that does not
-- render. Found by running module_inspect (BE #515) over all 19 live
-- modules: 18 clean, 1 red.
--
--   business : 756acac9-a225-4c18-87b1-710a948d1228  "Vertical Test Lawyer"
--   module   : 0d5e2a10-1111-4a00-9a01-de5c0de00001  "Matters" (work_pipeline)
--   schema   : []   ← an ARRAY, not an object
--
-- DynamicModule runs validateModuleSchema and replaces the ENTIRE module
-- with a red "This module's schema is invalid" panel on any error, so the
-- lawyer fixture has been showing an error where its pipeline should be.
-- It is a fixture, not a customer, and business_type_module_blueprint was
-- checked separately and is clean — no real signup inherits this.
--
-- WHY NOT THE BLUEPRINT SCHEMA. business_type_module_blueprint has a
-- canonical lawyer/matters schema (title, client, matter_type,
-- jurisdiction, opposing_party, status, opened_date, description).
-- Applying it would orphan every value the 4 seeded entries actually
-- hold: they carry title / stage / note. The fixture's job is to show a
-- populated lawyer pipeline, so the schema is derived from the data that
-- is there rather than from the shape we wish were there. Re-seeding the
-- fixture onto the blueprint shape is a separate decision about what the
-- fixture should contain, not a rendering fix.
--
-- The 4 entries hold exactly: title, stage, note, demo_seed.
-- demo_seed is a marker, deliberately not given a field — it is metadata,
-- not something a practitioner should see or edit.
--
-- NOT CHANGED: the note text. It looked mojibake'd in a console
-- ("Transactional â next") but the stored character is codepoint 8212,
-- a proper em dash. The terminal was lying, not the database. Verified
-- before touching it; "fixing" it would have corrupted correct data.
--
-- ROLLBACK:
--   UPDATE public.custom_modules SET schema = '[]'::jsonb
--    WHERE id = '0d5e2a10-1111-4a00-9a01-de5c0de00001';
--   UPDATE public.module_entries SET data = jsonb_set(data,'{stage}','"discovery"')
--    WHERE module_id = '0d5e2a10-1111-4a00-9a01-de5c0de00001'
--      AND data->>'stage' = 'Discovery';

BEGIN;

-- 1. One seeded row says "discovery" where the others are capitalised.
--    The board groups by exact value, so the odd one out would render as
--    its own extra column beside "Discovery".
UPDATE public.module_entries
   SET data = jsonb_set(data, '{stage}', '"Discovery"')
 WHERE module_id = '0d5e2a10-1111-4a00-9a01-de5c0de00001'
   AND data->>'stage' = 'discovery';

-- 2. A schema that renders, drawn from the keys the entries actually use.
--    stage is a select, so the board view is legal — and work_pipeline is
--    the archetype this fixture already declares, so the board is the
--    thing it exists to demonstrate.
UPDATE public.custom_modules
   SET schema = jsonb_build_object(
         'fields', jsonb_build_array(
           jsonb_build_object('name','title','type','text',
                              'label','Matter','required', true),
           jsonb_build_object('name','stage','type','select','label','Stage',
                              'options', jsonb_build_array(
                                'Intake','Drafting','Discovery',
                                'Pre-trial','Probate','Closed')),
           jsonb_build_object('name','note','type','textarea',
                              'label','Next step')
         ),
         'views', jsonb_build_array('list','board'),
         'default_view', 'board',
         'board_column', 'stage',
         'default_sort', 'created_at'
       )
 WHERE id = '0d5e2a10-1111-4a00-9a01-de5c0de00001';

COMMIT;

-- VERIFY (expect: schema_type=object, 3 fields, 0 stray stage values):
--   SELECT jsonb_typeof(schema) AS schema_type,
--          jsonb_array_length(schema->'fields') AS n_fields
--     FROM public.custom_modules
--    WHERE id = '0d5e2a10-1111-4a00-9a01-de5c0de00001';
--
--   SELECT count(*) AS stage_values_not_in_options
--     FROM public.module_entries e
--     JOIN public.custom_modules m ON m.id = e.module_id
--    WHERE m.id = '0d5e2a10-1111-4a00-9a01-de5c0de00001'
--      AND NOT (m.schema->'fields'->1->'options') ? (e.data->>'stage');
