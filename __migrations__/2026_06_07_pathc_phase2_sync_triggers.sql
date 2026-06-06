-- ─────────────────────────────────────────────────────────────────
-- Path C Phase 2 — 2b DB triggers for businesses.type ↔
-- business_profiles.business_type sync
-- ─────────────────────────────────────────────────────────────────
-- Replaces the Phase 1d app-level mirror with database-level enforcement.
-- Once these triggers are in place, ANY writer of either column
-- (frontend, backend, Chief CRUD, future code paths, raw SQL) keeps
-- both columns aligned automatically.
--
-- RECURSION GUARD: Both triggers fire AFTER UPDATE. The trigger body
-- compares NEW vs OLD using IS DISTINCT FROM (null-safe), and the UPDATE
-- it issues includes a `business_type IS DISTINCT FROM NEW.value` (or
-- `type IS DISTINCT FROM NEW.business_type`) WHERE clause so a same-
-- value write is a no-op AT POSTGRES LEVEL — the row's xmin doesn't
-- bump, no row-level UPDATE fires, no second trigger invocation. So
-- the mutual triggers terminate after at most one bounce.
--
-- (Defensive backup: even without the IS DISTINCT FROM guard, Postgres
-- only fires AFTER UPDATE triggers on rows where the UPDATE actually
-- changed data; UPDATE ... SET col = col on equal values is a no-op.)
--
-- CONCURRENCY: AFTER UPDATE runs inside the original transaction. If
-- two clients race-update both rows, MVCC + the IS DISTINCT FROM
-- guard ensure final consistency — last writer wins, both columns
-- end up aligned.
--
-- IDEMPOTENT, FORWARD-ONLY, NON-DESTRUCTIVE.
-- Apply AFTER pathc_phase1_fk_constraint.sql (so businesses.type
-- writes are FK-validated before the trigger propagates them).
-- ─────────────────────────────────────────────────────────────────

-- ─── Trigger 1: businesses.type → business_profiles.business_type ─

CREATE OR REPLACE FUNCTION public.sync_business_type_to_profile()
RETURNS TRIGGER AS $$
BEGIN
    -- Only act when type actually changed.
    IF NEW.type IS DISTINCT FROM OLD.type THEN
        UPDATE public.business_profiles
        SET business_type = NEW.type,
            updated_at    = now()
        WHERE business_id = NEW.id
          AND business_type IS DISTINCT FROM NEW.type;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS sync_business_type_trigger ON public.businesses;
CREATE TRIGGER sync_business_type_trigger
AFTER UPDATE OF type ON public.businesses
FOR EACH ROW EXECUTE FUNCTION public.sync_business_type_to_profile();

-- ─── Trigger 2: business_profiles.business_type → businesses.type ─

CREATE OR REPLACE FUNCTION public.sync_profile_type_to_business()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.business_type IS DISTINCT FROM OLD.business_type
       AND NEW.business_type IS NOT NULL THEN
        UPDATE public.businesses
        SET type       = NEW.business_type,
            updated_at = now()
        WHERE id = NEW.business_id
          AND type IS DISTINCT FROM NEW.business_type;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS sync_profile_type_trigger ON public.business_profiles;
CREATE TRIGGER sync_profile_type_trigger
AFTER UPDATE OF business_type ON public.business_profiles
FOR EACH ROW EXECUTE FUNCTION public.sync_profile_type_to_business();

-- ─── Verify ─────────────────────────────────────────────────────
-- 1. Confirm trigger definitions exist.
SELECT
    n.nspname    AS schema_name,
    c.relname    AS table_name,
    t.tgname     AS trigger_name,
    pg_get_triggerdef(t.oid) AS definition
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE t.tgname IN ('sync_business_type_trigger', 'sync_profile_type_trigger')
ORDER BY c.relname;

-- 2. Smoke test (RUN MANUALLY against a non-prod test row first):
--    Pick a business id, snapshot both columns, update one,
--    confirm the other follows.
--
-- DO $smoke$
-- DECLARE
--   _id uuid := '<some business id>';
--   _t1 text;
--   _t2 text;
-- BEGIN
--   UPDATE public.businesses SET type = 'coach' WHERE id = _id;
--   SELECT type FROM public.businesses        WHERE id = _id        INTO _t1;
--   SELECT business_type FROM public.business_profiles WHERE business_id = _id INTO _t2;
--   RAISE NOTICE 'after biz update: businesses.type=%, profile.business_type=%', _t1, _t2;
--   ASSERT _t1 = _t2, 'mirror failed';
-- END $smoke$;
