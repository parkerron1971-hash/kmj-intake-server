-- ══════════════════════════════════════════════════════════════════
-- APPLY 2026-09-04 — chief_jobs.heartbeat_at
--
-- Jobs run inside the web process (asyncio task + worker thread). A
-- deploy mid-build left the row at `running` forever, and the only
-- recovery was lazy: the next enqueue of the SAME kind for the SAME
-- business swept it. Until then the practitioner's "Chief is working
-- on…" chip spun on a corpse.
--
-- Age alone cannot tell a slow build from a dead one (a full Opus build
-- approaches ten minutes), and process identity (`_INFLIGHT`) only
-- works inside one process. A heartbeat can tell across replicas: the
-- progress callback already PATCHes the row every ~1.5s while the
-- build is alive; it now stamps this column too. A `running` row whose
-- heartbeat is minutes old belongs to a process that is gone.
--
-- The code is fail-soft without this column: heartbeat stamping
-- disables itself after one refused PATCH, and the recovery sweep
-- falls back to started_at with the older, longer threshold. So this
-- can be applied before or after the deploy.
--
-- Additive + idempotent.
-- ══════════════════════════════════════════════════════════════════

ALTER TABLE public.chief_jobs
  ADD COLUMN IF NOT EXISTS heartbeat_at timestamptz;

-- The recovery sweep's read: live rows, oldest heartbeat first.
CREATE INDEX IF NOT EXISTS idx_chief_jobs_live_heartbeat
  ON public.chief_jobs (heartbeat_at)
  WHERE status IN ('queued', 'running');

COMMENT ON COLUMN public.chief_jobs.heartbeat_at IS
  'Last progress ping from the running worker. Stale (>5 min) on a running row = orphaned by a restart; the recovery sweep marks it failed with a retryable reason.';

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP INDEX IF EXISTS public.idx_chief_jobs_live_heartbeat;
--   ALTER TABLE public.chief_jobs DROP COLUMN IF EXISTS heartbeat_at;
