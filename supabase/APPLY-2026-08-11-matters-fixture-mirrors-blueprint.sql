-- APPLY-2026-08-11-matters-fixture-mirrors-blueprint.sql
--
-- Follow-up to APPLY-2026-08-11-matters-fixture-schema.sql.
--
-- That migration made the Vertical Test Lawyer's "Matters" module RENDER,
-- using a schema derived from the data its 4 entries actually held
-- (title / stage / note). That was the right scope for a rendering fix,
-- but it left the fixture showing a shape no real lawyer ever gets.
--
-- A vertical fixture exists to answer "what does a lawyer see when they
-- sign up". It can only answer that if it matches
-- business_type_module_blueprint, which is the row module_blueprint_agent
-- actually provisions. This migration makes the module and its entries
-- mirror that blueprint.
--
--   business : 756acac9-a225-4c18-87b1-710a948d1228  "Vertical Test Lawyer"
--   module   : 0d5e2a10-1111-4a00-9a01-de5c0de00001  "Matters"
--   mirrors  : business_type_module_blueprint WHERE business_type='lawyer'
--                AND module_slug='matters'
--
-- THE BLUEPRINT IS COPIED, NOT RETYPED. The schema and agent_config are
-- SELECTed from the blueprint row, so this cannot drift from it and does
-- not depend on my transcription. If the blueprint changes, re-running
-- this re-syncs the fixture.
--
-- ENTRY MIGRATION. The blueprint has no `stage` field, so the 4 entries
-- are remapped onto its fields. Every value is GROUNDED in what the row
-- already said — nothing is invented:
--   title          unchanged
--   matter_type    stated verbatim in each note ("Civil litigation",
--                  "Transactional", "Family"; "Estate of..." for probate)
--   opposing_party the defendant in the "X v. Y" titles; NULL for the two
--                  that are not adversarial
--   status         'active' — all four are live matters mid-process
--   opened_date    the entry's own created_at date
--   description    stage + the existing note, so no text is lost
--   jurisdiction   left NULL. It appears nowhere in the data and a
--                  plausible-looking court name is exactly the kind of
--                  invented detail a fixture should not teach.
--   client         left NULL. It is a contact_link and these demo rows
--                  have no contacts behind them; a dangling uuid would
--                  render as "(unknown contact)".
--
-- NOTE ON THE BOARD: the blueprint is views:['list'] even though the
-- archetype is work_pipeline and `status` is a select that could drive a
-- board. The previous migration gave this fixture a board; mirroring the
-- blueprint takes it away again, which is correct — the fixture should
-- show what ships, not what I would prefer ships. Whether the lawyer
-- BLUEPRINT should offer a board is a product decision affecting every
-- future lawyer signup, and is deliberately not made here.
--
-- ROLLBACK: see APPLY-2026-08-11-matters-fixture-schema.sql, which is the
-- state immediately before this one.

BEGIN;

-- 1. Module shape: copied straight from the blueprint row.
UPDATE public.custom_modules m
   SET schema       = b.schema,
       agent_config = b.agent_config,
       archetype    = b.archetype,
       icon         = b.icon,
       description  = b.description
  FROM public.business_type_module_blueprint b
 WHERE m.id = '0d5e2a10-1111-4a00-9a01-de5c0de00001'
   AND b.business_type = 'lawyer'
   AND b.module_slug   = 'matters';

-- 2. Entries remapped onto the blueprint's fields, one statement per row
--    so each mapping is readable and reviewable rather than clever.

UPDATE public.module_entries SET data = jsonb_build_object(
    'title',          'Estate of R. Nakamura',
    'matter_type',    'estate',
    'status',         'active',
    'opened_date',    to_char(created_at, 'YYYY-MM-DD'),
    'description',    'Probate stage. Next: inventory filing',
    'demo_seed',      true)
 WHERE module_id = '0d5e2a10-1111-4a00-9a01-de5c0de00001'
   AND data->>'title' = 'Estate of R. Nakamura';

UPDATE public.module_entries SET data = jsonb_build_object(
    'title',          data->>'title',          -- keeps the em dash exactly as stored
    'matter_type',    'transactional',
    'status',         'active',
    'opened_date',    to_char(created_at, 'YYYY-MM-DD'),
    'description',    'Drafting stage. Next: redline back',
    'demo_seed',      true)
 WHERE module_id = '0d5e2a10-1111-4a00-9a01-de5c0de00001'
   AND data->>'title' LIKE 'Vance LLC%';

UPDATE public.module_entries SET data = jsonb_build_object(
    'title',          'Ruiz v. Sandoval',
    'matter_type',    'family',
    'opposing_party', 'Sandoval',
    'status',         'active',
    'opened_date',    to_char(created_at, 'YYYY-MM-DD'),
    'description',    'Pre-trial stage. Next: mediation prep',
    'demo_seed',      true)
 WHERE module_id = '0d5e2a10-1111-4a00-9a01-de5c0de00001'
   AND data->>'title' = 'Ruiz v. Sandoval';

UPDATE public.module_entries SET data = jsonb_build_object(
    'title',          'Hollis v. Brightwater Development',
    'matter_type',    'litigation',
    'opposing_party', 'Brightwater Development',
    'status',         'active',
    'opened_date',    to_char(created_at, 'YYYY-MM-DD'),
    'description',    'Discovery stage. Next: expert disclosure',
    'demo_seed',      true)
 WHERE module_id = '0d5e2a10-1111-4a00-9a01-de5c0de00001'
   AND data->>'title' = 'Hollis v. Brightwater Development';

COMMIT;

-- VERIFY:
--   -- module matches the blueprint byte for byte
--   SELECT (m.schema = b.schema) AS schema_matches,
--          (m.agent_config = b.agent_config) AS config_matches
--     FROM public.custom_modules m, public.business_type_module_blueprint b
--    WHERE m.id = '0d5e2a10-1111-4a00-9a01-de5c0de00001'
--      AND b.business_type='lawyer' AND b.module_slug='matters';
--
--   -- every entry key is a field the blueprint declares (plus demo_seed)
--   SELECT count(*) AS keys_with_no_field
--     FROM public.module_entries e,
--          LATERAL jsonb_object_keys(e.data) k
--    WHERE e.module_id = '0d5e2a10-1111-4a00-9a01-de5c0de00001'
--      AND k <> 'demo_seed'
--      AND NOT EXISTS (
--          SELECT 1 FROM public.business_type_module_blueprint b,
--                        LATERAL jsonb_array_elements(b.schema->'fields') f
--           WHERE b.business_type='lawyer' AND b.module_slug='matters'
--             AND f->>'name' = k);
