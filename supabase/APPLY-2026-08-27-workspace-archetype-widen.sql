-- APPLY-2026-08-27-workspace-archetype-widen.sql
--
-- The archetype CHECK allowed five values. Seven presets ship.
--
-- `therapist` and `nonprofit` are real layouts, chosen by a real
-- classifier, that could not be SAVED: the app-layer validator accepted
-- them (it checks workspace_layouts.ARCHETYPES, which has seven), and
-- then the CHECK constraint rejected the write with 23514.
--
-- And the rejection was SILENT. sb_clients._sync_request logs a warning
-- and returns None on 4xx; _persist ignored the return value. So a
-- therapist choosing their workspace got a cheerful success, nothing was
-- written, and the next page load asked them to choose again. Forever.
-- No error reached the practitioner and none reached the app -- only a
-- line in the Railway log that nobody was watching.
--
-- That is the same failure class as the two benchmark arms that filtered
-- `contacts.status` on values the constraint does not allow: it succeeds
-- and does nothing, which is worse than a crash, because a crash gets
-- fixed on the first report.
--
-- Two things change here. This file widens the constraint to the seven
-- presets that actually exist. `__tests__/test_workspace_archetypes.py`
-- now PARSES this file and fails if the list disagrees with
-- workspace_layouts.ARCHETYPES, so the two cannot drift apart again --
-- which is the only durable fix, because widening it by hand is exactly
-- what was forgotten the first time.
--
-- Idempotent. Safe to re-run.

BEGIN;

ALTER TABLE public.business_profiles
    DROP CONSTRAINT IF EXISTS business_profiles_workspace_archetype_check;

-- Still a CHECK and deliberately not a Postgres enum: ALTER TYPE ... ADD
-- VALUE cannot run inside a transaction, and every migration here runs
-- in one. A CHECK can be widened transactionally, which is what this
-- file is doing.
ALTER TABLE public.business_profiles
    ADD CONSTRAINT business_profiles_workspace_archetype_check
    CHECK (workspace_archetype IS NULL OR workspace_archetype IN (
        'salon',
        'trades',
        'therapist',
        'ministry',
        'consultant',
        'nonprofit',
        'law_firm'
    ));

COMMENT ON COLUMN public.business_profiles.workspace_archetype IS
    'Which layout preset this business renders. One of the seven in '
    'workspace_layouts/ -- salon | trades | therapist | ministry | '
    'consultant | nonprofit | law_firm. Chief picks at onboarding and the '
    'practitioner can override in one tap. The CHECK above must list '
    'exactly the presets that exist; a test parses this file and fails '
    'the build if it does not.';

COMMIT;
