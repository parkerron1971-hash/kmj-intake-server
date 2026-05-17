-- Pass 4.0h migration: production wiring for multi-module pipeline
-- =================================================================
--
-- Adds the two columns needed to opt practitioners into the
-- multi-module Composer pipeline on a per-business basis, and to
-- record which design module produced their Hero when they did.
--
-- Applied directly to production Supabase. No dev environment
-- exists; both statements are append-only with safe defaults so
-- existing reads/writes against either table continue to work
-- without modification:
--
--   * use_composer            NOT NULL DEFAULT FALSE
--     — existing businesses backfill to FALSE on add. Builder-only
--       flow remains the default; opt-in is explicit per row.
--
--   * hero_composer_module    NULL (no constraint)
--     — existing business_sites rows backfill to NULL on add.
--       Builder-generated Heros leave this NULL; Composer-generated
--       Heros write 'cathedral' or 'studio_brut'. Future modules
--       (Atelier, Pulpit, Field Manual, Floor) extend the string
--       set without further schema changes.
--
-- Apply via the Supabase SQL editor (or any Postgres client with
-- DDL privileges on the project). Then run the verification block
-- at the bottom of this file to confirm the columns landed with
-- the right types and defaults.

BEGIN;

ALTER TABLE businesses
  ADD COLUMN IF NOT EXISTS use_composer BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE business_sites
  ADD COLUMN IF NOT EXISTS hero_composer_module TEXT NULL;

COMMIT;

-- ─── Verification — run after the COMMIT above ─────────────────────
--
-- Expected result: two rows
--
--   table_name       | column_name           | data_type | is_nullable | column_default
--   ---------------- | --------------------- | --------- | ----------- | --------------
--   businesses       | use_composer          | boolean   | NO          | false
--   business_sites   | hero_composer_module  | text      | YES         | NULL

SELECT table_name, column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND ((table_name = 'businesses'      AND column_name = 'use_composer')
    OR (table_name = 'business_sites'  AND column_name = 'hero_composer_module'))
ORDER BY table_name, column_name;
