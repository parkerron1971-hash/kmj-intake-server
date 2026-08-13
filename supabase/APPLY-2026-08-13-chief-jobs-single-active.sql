-- Site-builder audit (2026-08-13) — one active job per business+kind.
--
-- chief_jobs.enqueue deduped with a READ followed by an INSERT and no
-- constraint between them. Two clicks landing inside one Supabase
-- round-trip both read "nothing fresh" and both insert, so a site build
-- could run twice concurrently — two threads racing to PATCH the same
-- business_sites row, and two site_build_marker rows at 600 credits
-- each. A check that spans two round-trips is not a guarantee; the
-- database has to hold it.
--
-- Partial unique index: at most one queued-or-running row per
-- (business_id, kind). Finished rows (done/failed/cancelled) are
-- unconstrained, so history is untouched and retries still work.
--
-- Verified before applying: zero (business_id, kind) pairs currently
-- have more than one queued/running row, so this creates cleanly.

CREATE UNIQUE INDEX IF NOT EXISTS chief_jobs_one_active_per_business_kind
    ON public.chief_jobs (business_id, kind)
    WHERE status IN ('queued', 'running');

COMMENT ON INDEX public.chief_jobs_one_active_per_business_kind IS
    'Site-builder audit 2026-08-13: makes enqueue dedupe atomic. Without '
    'it the read-then-insert races and a paid site build can run twice.';
