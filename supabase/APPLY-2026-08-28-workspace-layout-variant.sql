-- APPLY-2026-08-28-workspace-layout-variant.sql
--
-- Which DESK a business opens on, within its archetype.
--
-- `workspace_archetype` says which room the business is in. It cannot
-- say what that room should lead with this fortnight, and those are
-- different questions: two law firms both resolve to `law_firm`, but one
-- is drowning in filings and the other has not been paid since June.
-- Until now both got the docket, because the archetype was the only dial
-- there was.
--
-- Chief picks the variant from the business's own benchmark values and
-- re-picks when they move. See workspace_layout_picker.py.
--
-- ── WHY THE ORIGIN COLUMN ───────────────────────────────────────────
--
-- Exactly the rule terminology already follows, for exactly the same
-- reason. A practitioner who has chosen a desk has told us something we
-- could not compute; re-deciding it for them next Tuesday is not
-- intelligence, it is forgetting. `user_override` is never overwritten
-- by an automatic write — the picker only ever reports what it WOULD
-- have chosen, and the surface offers the way back.
--
-- NULL variant is not a gap: it means "the default for this archetype",
-- which is what every existing row already means and why this migration
-- needs no backfill.
--
-- Idempotent. Safe to re-run.

BEGIN;

ALTER TABLE public.business_profiles
    ADD COLUMN IF NOT EXISTS workspace_layout_variant text,
    ADD COLUMN IF NOT EXISTS workspace_layout_variant_origin text;

COMMENT ON COLUMN public.business_profiles.workspace_layout_variant IS
    'Which layout of the chosen archetype this business opens on. NULL '
    'means the archetype default, which is what every row meant before '
    'this column existed. Validated in app code against '
    'workspace_layouts.VARIANTS rather than by a CHECK: variants are '
    'added far more often than archetypes, and a too-narrow CHECK on '
    'workspace_archetype already silently swallowed two presets once.';

COMMENT ON COLUMN public.business_profiles.workspace_layout_variant_origin IS
    'chief | user_override. A user_override is NEVER overwritten by an '
    'automatic write — same rule as workspace_terminology, same reason: '
    'a choice the practitioner made carries information we could not '
    'compute, and re-deciding it for them is forgetting, not '
    'intelligence.';

-- Deliberately NOT a CHECK constraint on the variant.
--
-- On 2026-08-27 the archetype CHECK allowed five values while seven
-- presets shipped, and because sb_clients returns None on any 4xx the
-- rejected writes were completely silent: a therapist chose a workspace,
-- was told it saved, and was asked again on the next load. Forever.
--
-- Variants will be added far more often than archetypes were, so the
-- same trap would be sprung far more often. The app validates against
-- workspace_layouts.VARIANTS and falls back to the default on anything
-- unknown, which means a stale value degrades to a working desk instead
-- of to a blank one. The origin column IS constrained, because it has
-- exactly two legal values and always will.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'business_profiles_layout_variant_origin_check'
    ) THEN
        ALTER TABLE public.business_profiles
            ADD CONSTRAINT business_profiles_layout_variant_origin_check
            CHECK (workspace_layout_variant_origin IS NULL
                   OR workspace_layout_variant_origin IN ('chief', 'user_override'));
    END IF;
END $$;

COMMIT;
