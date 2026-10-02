-- ══════════════════════════════════════════════════════════════════
-- APPLY 2026-09-04 — rate_windows + rate_take(): a limiter that holds
-- across replicas
--
-- Every rate limiter in this service is a dict in one process. The
-- platform is designed for N web replicas (scheduler_lock exists for
-- exactly that), so every anonymous budget is really N times what the
-- code says: at three replicas, "10 bookings an hour per IP" is 30.
--
-- This is the shared substrate, in the same shape as
-- decrement_offering_stock and next_po_number: one atomic upsert per
-- check, fixed-window semantics identical to rate_limit._check() so the
-- numbers in _LIMITS mean the same thing whichever path decides.
--
-- rate_take(bucket, key, max, window_sec) → true when this call is
-- within budget for the current window (and counts it), false when the
-- window is full. One row per (bucket, key); a stale window resets on
-- the next call rather than needing a sweeper. rate_purge() deletes
-- rows nobody has touched in a day — the scheduler calls it hourly.
--
-- SECURITY DEFINER + EXECUTE revoked from anon/authenticated/public:
-- only the service role (the backend) can take from a bucket. The
-- table has RLS on and no policies, grants revoked — backend-mediated
-- only, like agent_runs.
--
-- The code is fail-soft without this: rate_limit.allow_strict() checks
-- its in-process window first, and if the RPC is missing or the
-- database blips it falls back to that in-process answer with a
-- warning — a limiter still, just per process again. Apply before or
-- after the deploy.
--
-- Additive + idempotent.
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.rate_windows (
  bucket        text        NOT NULL,
  key           text        NOT NULL,
  window_start  timestamptz NOT NULL DEFAULT now(),
  count         integer     NOT NULL DEFAULT 0,
  touched_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (bucket, key)
);

-- The purge's read: rows nobody has touched lately.
CREATE INDEX IF NOT EXISTS idx_rate_windows_touched
  ON public.rate_windows (touched_at);

ALTER TABLE public.rate_windows ENABLE ROW LEVEL SECURITY;
-- No policies. Backend-mediated only.
REVOKE ALL ON public.rate_windows FROM anon, authenticated;

CREATE OR REPLACE FUNCTION public.rate_take(
  p_bucket text, p_key text, p_max integer, p_window_sec integer)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_count integer;
BEGIN
  INSERT INTO public.rate_windows (bucket, key, window_start, count, touched_at)
  VALUES (p_bucket, p_key, now(), 1, now())
  ON CONFLICT (bucket, key) DO UPDATE SET
    count = CASE
      WHEN public.rate_windows.window_start < now() - make_interval(secs => p_window_sec)
        THEN 1
      ELSE public.rate_windows.count + 1
    END,
    window_start = CASE
      WHEN public.rate_windows.window_start < now() - make_interval(secs => p_window_sec)
        THEN now()
      ELSE public.rate_windows.window_start
    END,
    touched_at = now()
  RETURNING count INTO v_count;
  RETURN v_count <= p_max;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.rate_take(text, text, integer, integer)
  FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION public.rate_purge(p_older_than_sec integer DEFAULT 86400)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_deleted integer;
BEGIN
  DELETE FROM public.rate_windows
   WHERE touched_at < now() - make_interval(secs => p_older_than_sec);
  GET DIAGNOSTICS v_deleted = ROW_COUNT;
  RETURN v_deleted;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.rate_purge(integer)
  FROM PUBLIC, anon, authenticated;

COMMENT ON TABLE public.rate_windows IS
  'Fixed-window rate limiter shared across web replicas. One row per (bucket, key). Service role only; rate_take() is the only writer.';

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP FUNCTION IF EXISTS public.rate_purge(integer);
--   DROP FUNCTION IF EXISTS public.rate_take(text, text, integer, integer);
--   DROP TABLE IF EXISTS public.rate_windows;
