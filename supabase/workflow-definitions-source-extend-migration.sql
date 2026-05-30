-- ═══════════════════════════════════════════════════════════════════════
-- workflow_definitions.source CHECK extend — admit 'module_spec'
-- ═══════════════════════════════════════════════════════════════════════
-- Phase B materializes a workflow from a ModuleSpec on accept. Until now
-- those rows wrote source='manual' as a workaround because the CHECK only
-- admitted ('blueprint','growth_objective','manual'). This widens it so
-- the provenance is honest.
--
-- NON-DESTRUCTIVE: strict superset (3 existing values preserved + 1 added).
-- All existing rows still satisfy the constraint. No data touched.
-- IDEMPOTENT: DROP IF EXISTS + re-ADD.
-- ═══════════════════════════════════════════════════════════════════════

BEGIN;

ALTER TABLE public.workflow_definitions DROP CONSTRAINT IF EXISTS workflow_definitions_source_check;

ALTER TABLE public.workflow_definitions ADD CONSTRAINT workflow_definitions_source_check
  CHECK (source = ANY (ARRAY[
    'blueprint',        -- LGS Phase 1 blueprint-spawned
    'growth_objective', -- LGS Phase 4 growth-objective-spawned
    'manual',           -- practitioner-created via UI / Chief
    'module_spec'       -- Phase B materialized from ModuleSpec.workflows[]
  ]::text[]));

COMMIT;
